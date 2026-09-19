"""Business-facing insights for the Clinic View's Insights page.

Four questions a clinic manager actually asks, all answered from
``calls.jsonl`` through ``view.build_calls`` — no synthetic numbers, same
rule as ``insights.py`` next to this file (read that one first; ``Bar`` and
``mask_phone`` live there and this module follows the same shape):

1. ``unavailability_reasons`` — of the calls that tried to schedule and did
   not end up booked, why not: no slot in the window asked, a specific
   doctor unavailable, a specialty with no agenda here, an insurance/referral
   rule, outside opening hours, or something else.
2. ``provider_ranking`` — which doctors get asked for by name, how often
   that turns into a kept appointment, and the median wait to their next
   slot when it does.
3. ``demand_supply_heatmap`` — weekday x time-band grid of appointments
   *requested* against slots *actually offered*, to spot where demand has
   nowhere to land.
4. ``cancellation_slots`` — every slot a cancellation freed this period:
   picked up by another caller before the day arrived, or left empty. The
   platform only ever books for the day after the call, so a freed slot has
   one short window to be reused, never more.

Every function takes the same ``list[CallCard]`` the rest of observability
already builds from the log — plug this into any of them, including a
date-filtered subset for the "7 / 30 / 90 days" pills the console shows.

The reason and doctor classification below is a deterministic, offline
keyword read of the caller's own turns (``card.turns``), not a call to an
LLM: it never needs a key or the network, matching ``make test``'s "no key,
no network" rule. See ``REASON_CLASSIFIER_PROMPT`` for the prompt a real
NLP pass would use instead, and ``DATA_GAPS`` for what the log should start
capturing so this stops being a heuristic.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from datetime import date as date_cls
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from vortex.clinic.fixtures import PROVIDERS, SPECIALTIES
from vortex.observability.view import CallCard

MADRID = ZoneInfo("Europe/Madrid")

# ---------------------------------------------------------------------------
# Provider & specialty directory
#
# Read from the clinic fixtures, the same names/ids every lane's tests use.
# In fake-clinic mode (the default with no PLATFORM_API_KEY) this *is* the
# directory. In live mode it is a stand-in for one — see DATA_GAPS.
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """Lower-cased, accent-stripped. "Sáez" and "café" fold the same as
    "saez" and "cafe" so a mis-transcribed accent never breaks a match."""
    folded = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()


_TITLES = {"dr", "dra", "d", "sr", "sra", "don", "dona"}


def _name_tokens(name: str) -> frozenset[str]:
    tokens = {t.strip(".,").lower() for t in _fold(name).split()}
    return frozenset(t for t in tokens if t not in _TITLES)


class _Provider:
    __slots__ = ("id", "name", "specialty_id", "specialty_name", "tokens")

    def __init__(self, raw: dict[str, Any]) -> None:
        self.id = raw["id"]
        self.name = raw["name"]
        self.specialty_id = raw["specialty_id"]
        self.specialty_name = raw["specialty_name"]
        self.tokens = _name_tokens(self.name)


PROVIDER_DIRECTORY: list[_Provider] = [_Provider(p) for p in PROVIDERS]
PROVIDER_BY_ID: dict[str, _Provider] = {p.id: p for p in PROVIDER_DIRECTORY}
PROVIDER_BY_FOLDED_NAME: dict[str, _Provider] = {_fold(p.name): p for p in PROVIDER_DIRECTORY}
PROVIDERS_BY_SPECIALTY: dict[str, list[_Provider]] = defaultdict(list)
for _p in PROVIDER_DIRECTORY:
    PROVIDERS_BY_SPECIALTY[_p.specialty_id].append(_p)

SPECIALTY_NAME_BY_ID: dict[str, str] = {s["id"]: s["name"] for s in SPECIALTIES}

#: Spanish spoken forms for each specialty — the caller never says
#: "general_practice". Substring match on folded text, deliberately loose
#: (e.g. "fisio" also catches "fisioterapeuta").
SPECIALTY_ES_ALIASES: dict[str, tuple[str, ...]] = {
    "general_practice": ("medicina general", "medico de cabecera", "generalista"),
    "paediatrics": ("pediatr",),
    "dermatology": ("dermatolog",),
    "orthopaedics": ("traumatolog", "ortoped"),
    "gynaecology": ("ginecolog",),
    "physiotherapy": ("fisioterap", "fisio"),
}

# ---------------------------------------------------------------------------
# Reading a call's own words
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _user_text(card: CallCard) -> str:
    """Every turn the caller said in this call, folded and joined — what a
    keyword or LLM pass over the transcript reads."""
    return _fold(" ".join(t.text for t in card.turns if t.role == "user"))


def mention_provider_ids(card: CallCard) -> set[str]:
    """Doctors the caller named by surname, however the model paraphrased
    the rest of the sentence. A provider's surname tokens must *all* appear
    among the caller's words — "Sáez" and "Sáenz" are one token apart and
    never collide, same rule the identity lane's own matcher uses."""
    text = _user_text(card)
    if not text:
        return set()
    words = set(text.split())
    return {p.id for p in PROVIDER_DIRECTORY if p.tokens and p.tokens <= words}


def mention_specialty_ids(card: CallCard) -> set[str]:
    text = _user_text(card)
    if not text:
        return set()
    return {sid for sid, aliases in SPECIALTY_ES_ALIASES.items() if any(a in text for a in aliases)}


def _resolved_provider_id(card: CallCard) -> str | None:
    """The provider a tool actually resolved for this call, from the name
    ``view.build_call`` already pulled out of a tool result."""
    if not card.provider_name:
        return None
    info = PROVIDER_BY_FOLDED_NAME.get(_fold(card.provider_name))
    return info.id if info else None


def requested_provider_ids(card: CallCard) -> set[str]:
    """Every doctor this call was, in some way, about: named by the caller
    or matched by a tool."""
    ids = mention_provider_ids(card)
    resolved = _resolved_provider_id(card)
    if resolved:
        ids.add(resolved)
    return ids


# ---------------------------------------------------------------------------
# Unmet demand: which calls, and why
# ---------------------------------------------------------------------------

BOOKED_KINDS = frozenset({"book", "reschedule"})
#: Tools that mean the call was genuinely trying to land an appointment,
#: not just look someone up.
_SCHEDULING_TOOLS = frozenset(
    {
        "check_eligibility",
        "find_slots",
        "list_appointments",
        "find_provider",
        "prepare_booking",
        "prepare_reschedule",
        "triage",
        "nearest_location",
    }
)


def is_unmet_demand(card: CallCard) -> bool:
    """A call that tried to schedule and did not end up booked or moved.

    A successful ``register`` or ``cancel`` is not unmet demand for a new
    slot, so both are excluded even though they are not in ``BOOKED_KINDS``.
    """
    if card.action_kind in BOOKED_KINDS or card.action_kind in {"register", "cancel"}:
        return False
    if card.decline_reason:
        return True
    return any(t.name in _SCHEDULING_TOOLS for t in card.tools)


#: The eighteen ``reason`` values ``explain.REASON_TEXT`` documents, folded
#: into the six buckets a clinic manager reads at a glance. Kept local
#: (rather than re-exported from ``explain``) since the grouping is a
#: judgement call specific to this page, not part of that module's
#: platform-facing vocabulary.
REASON_BUCKET: dict[str, str] = {
    "no_availability": "no_slot_in_window",
    "provider_on_leave": "provider_unavailable",
    "provider_not_in_network": "provider_unavailable",
    "provider_not_found": "provider_unavailable",
    "specialty_not_covered": "specialty_no_agenda",
    "type_not_offered": "specialty_no_agenda",
    "referral_required": "policy_not_covered",
    "insurer_referral_required": "policy_not_covered",
    "allowance_exhausted": "policy_not_covered",
    "not_eligible_age": "policy_not_covered",
    "location_not_covered": "policy_not_covered",
    "patient_history": "policy_not_covered",
    "caller_not_authorised": "policy_not_covered",
    "location_hours": "out_of_hours",
    "clinic_closed": "out_of_hours",
    "out_of_scope": "other",
    "medical_emergency": "other",
    "patient_not_found": "other",
}

BUCKET_LABELS: dict[str, str] = {
    "no_slot_in_window": "Sin hueco en la franja pedida",
    "provider_unavailable": "Médico concreto no disponible",
    "specialty_no_agenda": "Especialidad sin agenda",
    "policy_not_covered": "Policy no cubierta",
    "out_of_hours": "Fuera de horario",
    "other": "Otro",
}

#: Offline keyword read of the caller's turns, for the (rare) unmet call
#: with no structured ``decline_reason`` — the agent found nothing to
#: submit, or offered a slot the caller turned down out loud. Order matters:
#: first bucket with any hit wins, checked in this order because a mention
#: of "cerrado" alongside a doctor's name is more often about hours than
#: about that doctor.
_KEYWORD_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("out_of_hours", ("cerrad", "fuera de horario", "no abrimos", "no abris")),
    (
        "no_slot_in_window",
        (
            "no hay hueco",
            "no tenemos nada",
            "no tienen nada",
            "no me viene bien",
            "no me va bien",
            "otro dia",
            "mas adelante",
            "no hay disponibilidad",
            "no hay nada esa",
        ),
    ),
    (
        "policy_not_covered",
        (
            "no lo cubre",
            "no cubre mi seguro",
            "no admite mi seguro",
            "derivacion",
            "volante",
        ),
    ),
)

#: The system/user prompt a real LLM pass would use to replace
#: ``_keyword_bucket`` below, once a model client is wired in with a key.
#: Kept here as documentation, not called: the default path must run with
#: no key and no network, same rule ``make test`` and ``make smoke`` hold
#: everywhere else in the project.
REASON_CLASSIFIER_PROMPT = """\
You classify why a clinic phone call did not end in a kept appointment.
Read only the caller's own turns (never the assistant's). Answer with
exactly one of these six labels, nothing else:

  no_slot_in_window    - no opening in the day/time they asked for
  provider_unavailable  - they wanted a specific doctor who could not see them
  specialty_no_agenda   - the specialty they need has no agenda at this site
  policy_not_covered    - insurance, referral, age or history rule blocked it
  out_of_hours          - the request fell outside the clinic's opening hours
  other                 - none of the above, or not enough said to tell

Caller's turns:
{turns}
"""


def _keyword_bucket(text: str) -> str | None:
    for bucket, keywords in _KEYWORD_BUCKETS:
        if any(kw in text for kw in keywords):
            return bucket
    return None


def _provider_unavailable_by_text(card: CallCard) -> bool:
    if not mention_provider_ids(card):
        return False
    text = _user_text(card)
    negations = ("no esta", "no trabaja", "vacaciones", "de baja", "no atiende")
    return any(neg in text for neg in negations)


def classify_unmet(card: CallCard) -> str:
    """One of ``BUCKET_LABELS``' keys for an unmet-demand call."""
    if card.decline_reason:
        return REASON_BUCKET.get(card.decline_reason, "other")
    if _provider_unavailable_by_text(card):
        return "provider_unavailable"
    return _keyword_bucket(_user_text(card)) or "other"


# ---------------------------------------------------------------------------
# Weekday x time-band grid, shared by the reason drill-down and the heatmap
# ---------------------------------------------------------------------------

WEEKDAYS_ES: tuple[str, ...] = (
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
)
#: (label, hour start inclusive, hour end exclusive). A request or a slot
#: outside 08:00-21:00 falls in no band — the clinic does not run then.
BANDS: tuple[tuple[str, int, int], ...] = (
    ("Mañana", 8, 12),
    ("Mediodía", 12, 15),
    ("Tarde", 15, 18),
    ("Tarde-noche", 18, 21),
)
BAND_LABELS: tuple[str, ...] = tuple(b[0] for b in BANDS)


def _band_for_hour(hour: int) -> str | None:
    for label, start, end in BANDS:
        if start <= hour < end:
            return label
    return None


def _requested_bands(card: CallCard) -> list[tuple[int, str | None]]:
    """(weekday 0=Monday, band or None for "no hour given") for every
    ``find_slots`` call this card made — the window the caller actually
    asked for, read straight off ``FindSlotsInput.date_from``/``time_from``."""
    out: list[tuple[int, str | None]] = []
    for step in card.tools:
        if step.name != "find_slots":
            continue
        args = _as_dict(step.args)
        date_from = args.get("date_from")
        if not date_from:
            continue
        try:
            day = date_cls.fromisoformat(str(date_from))
        except ValueError:
            continue
        band = None
        time_from = args.get("time_from")
        if time_from:
            try:
                band = _band_for_hour(int(str(time_from).split(":")[0]))
            except (ValueError, IndexError):
                band = None
        out.append((day.weekday(), band))
    return out


def _dominant_band(cards: list[CallCard]) -> tuple[str, str] | None:
    counter: Counter[tuple[int, str]] = Counter()
    for card in cards:
        for weekday, band in _requested_bands(card):
            if band:
                counter[(weekday, band)] += 1
    if not counter:
        return None
    (weekday, band), _count = counter.most_common(1)[0]
    return WEEKDAYS_ES[weekday], band


# ---------------------------------------------------------------------------
# 1. Unavailability reasons
# ---------------------------------------------------------------------------


def _unavailability_suggestion(unmet: list[CallCard], ranked: list[dict[str, Any]]) -> str | None:
    if not ranked:
        return None
    top = ranked[0]
    subset = [c for c in unmet if classify_unmet(c) == top["key"]]
    total = len(unmet)
    pct = top["pct"]
    count = top["count"]
    base = f"El {pct:.0f}% de la demanda no cubierta ({count} de {total} llamadas)"

    if top["key"] == "provider_unavailable":
        counts: Counter[str] = Counter()
        for c in subset:
            counts.update(requested_provider_ids(c))
        if counts:
            pid, n = counts.most_common(1)[0]
            info = PROVIDER_BY_ID.get(pid)
            name = info.name if info else pid
            return (
                f"{base} es por médico no disponible; {name} concentra {n} de esas peticiones. "
                "Ofrecer automáticamente otro médico de su especialidad cuando no tenga hueco."
            )
    if top["key"] == "no_slot_in_window":
        band = _dominant_band(subset)
        if band:
            weekday, label = band
            return (
                f"{base} es por falta de hueco en la franja pedida, concentrado los "
                f"{weekday.lower()} en la {label.lower()}: ampliar agenda ese tramo capturaría la "
                "mayor parte de esos rechazos."
            )
    if top["key"] == "out_of_hours":
        return (
            f"{base} llega fuera del horario del centro: revisar si compensa abrir antes o "
            "cerrar más tarde esos días."
        )
    if top["key"] == "specialty_no_agenda":
        return f"{base} pide una especialidad sin agenda propia en el centro solicitado."
    if top["key"] == "policy_not_covered":
        return (
            f"{base} se pierde por reglas de seguro o derivación, no por falta de hueco: conviene "
            "explicar el requisito antes de colgar."
        )
    return f"{base} cae en «{top['label']}»: no sigue un patrón de agenda, revisar caso a caso."


def unavailability_reasons(cards: list[CallCard]) -> dict[str, Any]:
    """Ranking with count and % of unmet demand, most frequent first."""
    unmet = [c for c in cards if is_unmet_demand(c)]
    counter: Counter[str] = Counter(classify_unmet(c) for c in unmet)
    total = sum(counter.values())
    ranked: list[dict[str, Any]] = []
    if total:
        top_count = counter.most_common(1)[0][1]
        for key, count in sorted(counter.items(), key=lambda kv: -kv[1]):
            ranked.append(
                {
                    "key": key,
                    "label": BUCKET_LABELS[key],
                    "count": count,
                    "share": round(count / top_count, 3),
                    "pct": round(100 * count / total, 1),
                }
            )
    return {
        "unmet_total": total,
        "buckets": ranked,
        "suggested_action": _unavailability_suggestion(unmet, ranked),
    }


# ---------------------------------------------------------------------------
# 2. Provider ranking
# ---------------------------------------------------------------------------


def _booked_provider_id(card: CallCard) -> str | None:
    if card.action_kind not in BOOKED_KINDS:
        return None
    payload = card.action_payload or {}
    pid = payload.get("provider_id")
    return str(pid) if pid else _resolved_provider_id(card)


def _wait_days(card: CallCard) -> float | None:
    if card.action_kind not in BOOKED_KINDS or not card.started_at:
        return None
    payload = card.action_payload or {}
    slot = payload.get("slot")
    if not slot:
        return None
    try:
        start = datetime.fromisoformat(str(card.started_at))
        slot_dt = datetime.fromisoformat(str(slot))
    except ValueError:
        return None
    if start.tzinfo is None or slot_dt.tzinfo is None:
        return None
    return (slot_dt - start).total_seconds() / 86400


def _provider_suggestion(rows: list[dict[str, Any]]) -> str | None:
    flagged = sorted((r for r in rows if r["flagged"]), key=lambda r: -r["requests"])
    if not flagged:
        return None
    top = flagged[0]
    peers = [p for p in PROVIDERS_BY_SPECIALTY.get(top["specialty_id"], []) if p.id != top["id"]]
    failed = top["requests"] - top["booked"]
    name = top["name"]
    rate = top["success_rate"]
    specialty = top["specialty_name"]
    if not peers or failed <= 0:
        return (
            f"{name} recibe {top['requests']} peticiones explícitas con solo un {rate:.0f}% de "
            f"éxito, y no hay otro médico de {specialty} en plantilla al que redirigir la demanda."
        )
    return (
        f"{name} recibe {top['requests']} peticiones explícitas pero solo termina en cita el "
        f"{rate:.0f}% ({top['booked']} de {top['requests']}); hay {len(peers)} médico(s) más de "
        f"{specialty} en plantilla. Ofrecer automáticamente uno de ellos cuando {name} no tenga "
        f"hueco podría haber salvado hasta {failed} de esas citas."
    )


def provider_ranking(
    cards: list[CallCard], *, min_requests: int = 2, low_success_pct: float = 50.0
) -> dict[str, Any]:
    """Doctors asked for by name: volume, success rate, median wait."""
    requests: Counter[str] = Counter()
    booked: Counter[str] = Counter()
    waits: dict[str, list[float]] = defaultdict(list)
    for card in cards:
        wanted = requested_provider_ids(card)
        requests.update(wanted)
        booked_pid = _booked_provider_id(card)
        if booked_pid and booked_pid in wanted:
            booked[booked_pid] += 1
        if booked_pid:
            wait = _wait_days(card)
            if wait is not None:
                waits[booked_pid].append(wait)

    rows: list[dict[str, Any]] = []
    for pid, n in requests.items():
        info = PROVIDER_BY_ID.get(pid)
        if info is None:
            continue
        b = booked.get(pid, 0)
        rate = round(100 * b / n, 1) if n else 0.0
        rows.append(
            {
                "id": pid,
                "name": info.name,
                "specialty_id": info.specialty_id,
                "specialty_name": info.specialty_name,
                "requests": n,
                "booked": b,
                "success_rate": rate,
                "median_wait_days": round(median(waits[pid]), 1) if waits.get(pid) else None,
                "flagged": n >= min_requests and rate < low_success_pct,
            }
        )
    rows.sort(key=lambda r: (-r["requests"], r["name"]))
    return {"providers": rows, "suggested_action": _provider_suggestion(rows)}


# ---------------------------------------------------------------------------
# 3. Demand vs. supply heatmap
# ---------------------------------------------------------------------------


def _offered_bands(card: CallCard) -> list[tuple[int, str]]:
    """(weekday, band) for every slot a ``find_slots`` call actually
    returned — the availability really on offer, independent of what was
    asked, read straight off ``AvailabilityResult.slots[].start``."""
    out: list[tuple[int, str]] = []
    for step in card.tools:
        if step.name != "find_slots":
            continue
        result = _as_dict(step.result)
        for slot in result.get("slots") or []:
            slot_d = slot if isinstance(slot, dict) else _as_dict(slot)
            start = slot_d.get("start")
            if not start:
                continue
            try:
                dt = datetime.fromisoformat(str(start))
            except ValueError:
                continue
            local = dt.astimezone(MADRID) if dt.tzinfo else dt
            band = _band_for_hour(local.hour)
            if band:
                out.append((local.weekday(), band))
    return out


def _hottest_gap(
    demand: Counter[tuple[int, str]], supply: Counter[tuple[int, str]]
) -> tuple[tuple[int, str], int] | None:
    candidates = [(key, d) for key, d in demand.items() if d > 0 and supply.get(key, 0) < d]
    if not candidates:
        return None
    return max(candidates, key=lambda kv: kv[1] - supply.get(kv[0], 0))


def demand_supply_heatmap(cards: list[CallCard]) -> dict[str, Any]:
    """Weekday x band grid: appointments requested vs. slots offered."""
    demand: Counter[tuple[int, str]] = Counter()
    demand_all_day: Counter[int] = Counter()
    supply: Counter[tuple[int, str]] = Counter()

    for card in cards:
        for weekday, band in _requested_bands(card):
            if band:
                demand[(weekday, band)] += 1
            else:
                demand_all_day[weekday] += 1
        for weekday, band in _offered_bands(card):
            supply[(weekday, band)] += 1

    rows = [
        {
            "weekday": WEEKDAYS_ES[wd],
            "all_day_demand": demand_all_day.get(wd, 0),
            "cells": [
                {
                    "band": label,
                    "demand": demand.get((wd, label), 0),
                    "availability": supply.get((wd, label), 0),
                }
                for label in BAND_LABELS
            ],
        }
        for wd in range(7)
    ]

    suggestion = None
    hot = _hottest_gap(demand, supply)
    if hot:
        (weekday, band), requested = hot
        offered = supply.get((weekday, band), 0)
        day_label = WEEKDAYS_ES[weekday].lower()
        suggestion = (
            f"Los {day_label} en la franja de {band.lower()} concentran {requested} peticiones de "
            f"cita con solo {offered} huecos ofrecidos ese tramo: abrir agenda ahí capturaría la "
            "mayor bolsa de demanda sin horario."
        )

    return {"rows": rows, "bands": list(BAND_LABELS), "suggested_action": suggestion}


# ---------------------------------------------------------------------------
# 4. Cancellations: slots reused vs. slots lost
# ---------------------------------------------------------------------------


def _appointment_lookup(cards: list[CallCard]) -> dict[str, dict[str, Any]]:
    """``appointment_id`` -> ``{"provider_id", "start"}`` from every
    ``list_appointments`` result across these calls — a cancel's own payload
    only carries the ``appointment_id``, never the slot it freed, so the
    slot has to be recovered from the lookup that came before it."""
    out: dict[str, dict[str, Any]] = {}
    for card in cards:
        for step in card.tools:
            if step.name != "list_appointments":
                continue
            result = _as_dict(step.result)
            for appt in result.get("appointments") or []:
                appt_d = appt if isinstance(appt, dict) else _as_dict(appt)
                aid, start, provider_id = (
                    appt_d.get("appointment_id"),
                    appt_d.get("start"),
                    appt_d.get("provider_id"),
                )
                if not (aid and start and provider_id):
                    continue
                try:
                    start_dt = datetime.fromisoformat(str(start))
                except ValueError:
                    continue
                out[str(aid)] = {"provider_id": str(provider_id), "start": start_dt}
    return out


def _cancel_event_ts(card: CallCard) -> datetime | None:
    """When the cancellation actually reached the platform — the
    ``submit.result``/``submit.sent`` event on the ``/cancel`` route, not
    the call's start."""
    for event in card.events:
        if event.get("kind") not in {"submit.result", "submit.sent"}:
            continue
        route = str(event.get("route") or "")
        if route.rstrip("/").endswith("/cancel") and event.get("ts"):
            try:
                return datetime.fromisoformat(str(event["ts"]))
            except ValueError:
                return None
    return None


def _booked_slot(card: CallCard) -> tuple[str, datetime] | None:
    """(provider_id, slot start) this call actually booked or moved into —
    read straight off the submitted ``BookAction``/``RescheduleAction``."""
    if card.action_kind not in BOOKED_KINDS:
        return None
    payload = card.action_payload or {}
    provider_id, slot = payload.get("provider_id"), payload.get("slot")
    if not (provider_id and slot):
        return None
    try:
        slot_dt = datetime.fromisoformat(str(slot))
    except ValueError:
        return None
    return str(provider_id), slot_dt


def _cancellation_suggestion(
    freed: list[dict[str, Any]], relocated_n: int, lost_n: int
) -> str | None:
    decided = relocated_n + lost_n
    if not decided:
        return None
    rate = 100 * relocated_n / decided
    if lost_n > 0:
        return (
            f"De los {len(freed)} huecos liberados por cancelación, {relocated_n} se reubicaron "
            f"({rate:.0f}%) pero {lost_n} llegaron vacíos el día de la cita: avisar a la lista de "
            "espera en el instante de la cancelación recuperaría parte de esos huecos."
        )
    return (
        f"Los {len(freed)} huecos liberados por cancelación en el período se reubicaron todos "
        f"({rate:.0f}%): la ventana de un día no está siendo un problema hoy."
    )


def cancellation_slots(cards: list[CallCard], *, now: datetime | None = None) -> dict[str, Any]:
    """Every slot a cancellation freed this period: reused by another
    caller, or still empty once the appointment day arrived.

    A cancellation only frees the exact (provider, minute) an earlier
    ``list_appointments`` call showed for that ``appointment_id``; without
    that lookup in the log a freed slot cannot be placed and is skipped
    (see ``DATA_GAPS``). "Reused" means a *different* call booked into that
    same (provider, minute) — the original booking that got cancelled does
    not count against itself.
    """
    now = now or datetime.now(UTC)
    lookup = _appointment_lookup(cards)
    bookings = [(*slot, card.call_id) for card in cards if (slot := _booked_slot(card))]

    freed: list[dict[str, Any]] = []
    for card in cards:
        if card.action_kind != "cancel":
            continue
        appointment_id = (card.action_payload or {}).get("appointment_id")
        info = lookup.get(str(appointment_id)) if appointment_id else None
        if not info:
            continue
        relocated = any(
            pid == info["provider_id"] and start == info["start"] and cid != card.call_id
            for pid, start, cid in bookings
        )
        if relocated:
            status = "relocated"
        elif info["start"] < now:
            status = "lost"
        else:
            status = "pending"
        freed.append(
            {
                "call_id": card.call_id,
                "provider_id": info["provider_id"],
                "start": info["start"].isoformat(),
                "freed_at": (_cancel_event_ts(card) or now).isoformat(),
                "status": status,
            }
        )

    relocated_n = sum(1 for f in freed if f["status"] == "relocated")
    lost_n = sum(1 for f in freed if f["status"] == "lost")
    pending_n = sum(1 for f in freed if f["status"] == "pending")
    decided = relocated_n + lost_n

    daily: list[dict[str, Any]] | None = None
    if len(freed) >= 5:
        by_day: dict[str, dict[str, int]] = defaultdict(
            lambda: {"freed": 0, "relocated": 0, "lost": 0}
        )
        for f in freed:
            day = f["start"][:10]
            by_day[day]["freed"] += 1
            if f["status"] in ("relocated", "lost"):
                by_day[day][f["status"]] += 1
        daily = [{"date": d, **counts} for d, counts in sorted(by_day.items())]

    return {
        "freed_total": len(freed),
        "relocated": relocated_n,
        "lost": lost_n,
        "pending": pending_n,
        "recovery_rate_pct": round(100 * relocated_n / decided, 1) if decided else None,
        "daily": daily,
        "suggested_action": _cancellation_suggestion(freed, relocated_n, lost_n),
    }


# ---------------------------------------------------------------------------
# Everything together
# ---------------------------------------------------------------------------

#: What this page would do better with data the log does not capture today.
#: Surfaced by the API too (``data_gaps``), not just this docstring, so the
#: console can show it next to the numbers it actually has.
DATA_GAPS: list[str] = [
    'The caller\'s verbal rejection of an offered slot ("esa hora no me viene bien") is not a '
    "structured event — only inferable from turn.user keywords. An explicit "
    "`slot.declined_by_caller` event carrying the offered slot would replace the NLP fallback "
    "in classify_unmet with a real signal.",
    "The provider/specialty directory this page matches mentions against comes from the local "
    "clinic fixtures, not a cached snapshot of the real /providers and /specialties responses "
    "for this call — in live mode the roster can drift from what the API actually returned.",
    "A booked action's payload does not always carry provider_id (it depends on which tool built "
    "it); the ranking falls back to the provider name view.py already extracted, which can be "
    "missing if find_slots was not the last tool to touch that call's provider data.",
    'find_slots calls with no time_from ("cualquier hora") and calls where the caller genuinely '
    "never said a time both land in the heatmap's all_day_demand bucket — there is no field that "
    "tells the two apart.",
    "A `cancel` submission carries only the appointment_id, never the provider/slot it freed — "
    "cancellation_slots recovers it from a `list_appointments` call earlier in the same call and "
    "drops the cancellation from the count when that lookup is missing from the log. A "
    "`reschedule` frees its old slot the same way but is not counted here: only cancellations are.",
]


def business_insights(cards: list[CallCard], *, now: datetime | None = None) -> dict[str, Any]:
    """The full payload the Insights page's business-insights endpoint returns."""
    return {
        "calls_considered": len(cards),
        "unavailability": unavailability_reasons(cards),
        "providers": provider_ranking(cards),
        "heatmap": demand_supply_heatmap(cards),
        "cancellations": cancellation_slots(cards, now=now),
        "data_gaps": DATA_GAPS,
    }
