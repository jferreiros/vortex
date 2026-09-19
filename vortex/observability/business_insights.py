"""Business-facing insights for the Clinic View's Insights page.

Five questions a clinic manager actually asks, all answered from
``calls.jsonl`` through ``view.build_calls`` — no synthetic numbers, same
rule as ``insights.py`` next to this file (read that one first; ``Bar`` and
``mask_phone`` live there and this module follows the same shape):

1. ``unavailability_reasons`` — of the calls that tried to schedule and did
   not end up booked, why not: no slot in the window asked, a specific
   doctor unavailable, a specialty with no agenda here, an insurance/referral
   rule, or outside opening hours. Calls that fit none of those (``other``)
   name no rule to act on, so they are dropped from what the page shows and
   the remaining buckets renormalise to 100%.
2. ``provider_ranking`` — which doctors get asked for by name, how often
   that turns into a kept appointment, the median wait to their next slot
   when it does, and per doctor why the requests that failed did fail.
3. ``service_occupancy`` — per specialty, appointment requests against slots
   actually offered, whole-clinic or one site at a time. Over 100% means
   real callers were told there was nothing, and ``extra_providers_needed``
   turns that gap into a hiring number.
4. ``demand_supply_heatmap`` — weekday x time-band grid of appointments
   *requested* against slots *actually offered*, to spot where demand has
   nowhere to land.
5. ``cancellation_slots`` — every slot a cancellation freed this period:
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

import math
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from datetime import date as date_cls
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from vortex.clinic.client import fixtures_catalogue
from vortex.clinic.fixtures import PROVIDERS, SPECIALTIES
from vortex.contract import Catalogue, LocationRecord, ProviderRecord
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

_CATALOGUE: Catalogue | None = None


def site_catalogue() -> Catalogue:
    """The fixtures catalogue stands in for the live ``/clinic`` payload — its
    locations carry the per-site opening hours the heatmap paints as closed
    cells, in the same ``Catalogue`` shape a live fetch would give."""
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = fixtures_catalogue()
    return _CATALOGUE


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
    words = {w.strip(".,;:!?¿¡()\"'«»") for w in text.split()}
    words.discard("")
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


def _request_scope(catalogue: Catalogue, args: dict[str, Any]) -> frozenset[str]:
    """The sites one ``find_slots`` request could land in, mirroring the diary
    lane's ``_scope_sites``: the named site, else the sites of the provider or
    specialty asked for, else every site — a caller who names no site could
    have been served anywhere, so their demand counts against all of them."""
    if loc := args.get("location_id"):
        return frozenset({str(loc)})
    if pid := args.get("provider_id"):
        rec = next((p for p in catalogue.providers if p.provider_id == str(pid)), None)
        if rec and rec.location_ids:
            return frozenset(rec.location_ids)
    if sid := args.get("specialty_id"):
        sites = {
            loc for p in catalogue.providers if p.specialty_id == str(sid) for loc in p.location_ids
        }
        if sites:
            return frozenset(sites)
    return frozenset(loc.location_id for loc in catalogue.locations)


def _requested_bands(
    card: CallCard, catalogue: Catalogue
) -> list[tuple[int, str | None, frozenset[str]]]:
    """(weekday 0=Monday, band or None for "no hour given", site scope) for
    every ``find_slots`` call this card made — the window the caller actually
    asked for, read straight off ``FindSlotsInput.date_from``/``time_from``."""
    out: list[tuple[int, str | None, frozenset[str]]] = []
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
        out.append((day.weekday(), band, _request_scope(catalogue, args)))
    return out


def _dominant_band(cards: list[CallCard], catalogue: Catalogue) -> tuple[str, str] | None:
    counter: Counter[tuple[int, str]] = Counter()
    for card in cards:
        for weekday, band, _scope in _requested_bands(card, catalogue):
            if band:
                counter[(weekday, band)] += 1
    if not counter:
        return None
    (weekday, band), _count = counter.most_common(1)[0]
    return WEEKDAYS_ES[weekday], band


# ---------------------------------------------------------------------------
# 1. Unavailability reasons
# ---------------------------------------------------------------------------


def _unavailability_suggestion(
    unmet: list[CallCard], ranked: list[dict[str, Any]], catalogue: Catalogue
) -> str | None:
    if not ranked:
        return None
    top = ranked[0]
    subset = [c for c in unmet if classify_unmet(c) == top["key"]]
    # Matches the denominator ``pct`` was computed against: the shown
    # buckets, not every unmet call — "other" is excluded from both.
    total = sum(r["count"] for r in ranked)
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
        band = _dominant_band(subset, catalogue)
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


def unavailability_reasons(
    cards: list[CallCard], *, catalogue: Catalogue | None = None
) -> dict[str, Any]:
    """Ranking with count and % of unmet demand, most frequent first.

    "Otro" never appears: it names no clinic rule to act on, and because
    every decline that fits none of the other five buckets lands there, it
    would otherwise dominate the ranking with a bar that means nothing
    actionable. It is dropped from what is shown and the remaining buckets'
    percentages are renormalised over themselves, so they still sum to 100%.
    ``unmet_total`` keeps counting every unmet call, "otro" included — it
    answers "how many calls failed", not "how many the chart explains".
    """
    catalogue = catalogue or site_catalogue()
    unmet = [c for c in cards if is_unmet_demand(c)]
    counter: Counter[str] = Counter(classify_unmet(c) for c in unmet)
    total = sum(counter.values())
    shown = {key: count for key, count in counter.items() if key != "other"}
    shown_total = sum(shown.values())
    ranked: list[dict[str, Any]] = []
    if shown_total:
        top_count = max(shown.values())
        for key, count in sorted(shown.items(), key=lambda kv: -kv[1]):
            ranked.append(
                {
                    "key": key,
                    "label": BUCKET_LABELS[key],
                    "count": count,
                    "share": round(count / top_count, 3),
                    "pct": round(100 * count / shown_total, 1),
                }
            )
    return {
        "unmet_total": total,
        "buckets": ranked,
        "suggested_action": _unavailability_suggestion(unmet, ranked, catalogue),
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
    """Doctors asked for by name: volume, success rate, median wait — and,
    per doctor, why the requests that did not end in a kept appointment
    failed: ``unmet_reasons`` counts the same six buckets
    ``classify_unmet`` produces for the page's drill-down, while
    ``booked_elsewhere`` counts callers who asked for this doctor and were
    booked with a colleague instead."""
    requests: Counter[str] = Counter()
    booked: Counter[str] = Counter()
    booked_elsewhere: Counter[str] = Counter()
    unmet: dict[str, list[str]] = defaultdict(list)
    waits: dict[str, list[float]] = defaultdict(list)
    for card in cards:
        wanted = requested_provider_ids(card)
        requests.update(wanted)
        booked_pid = _booked_provider_id(card)
        if booked_pid and booked_pid in wanted:
            booked[booked_pid] += 1
        if booked_pid:
            booked_elsewhere.update(wanted - {booked_pid})
            wait = _wait_days(card)
            if wait is not None:
                waits[booked_pid].append(wait)
        if is_unmet_demand(card):
            bucket = classify_unmet(card)
            for pid in wanted:
                unmet[pid].append(bucket)

    rows: list[dict[str, Any]] = []
    for pid, n in requests.items():
        info = PROVIDER_BY_ID.get(pid)
        if info is None:
            continue
        b = booked.get(pid, 0)
        rate = round(100 * b / n, 1) if n else 0.0
        unmet_buckets = Counter(unmet.get(pid, []))
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
                "unmet": len(unmet.get(pid, [])),
                "unmet_reasons": [
                    {"key": k, "label": BUCKET_LABELS[k], "count": count}
                    for k, count in sorted(unmet_buckets.items(), key=lambda kv: (-kv[1], kv[0]))
                ],
                "booked_elsewhere": booked_elsewhere.get(pid, 0),
                #: The remainder — calls that named this doctor but ended in a
                #: register, a cancel, or no submission at all. Keeps
                #: booked + unmet + elsewhere + other == requests.
                "other_outcomes": n - b - len(unmet.get(pid, [])) - booked_elsewhere.get(pid, 0),
                "flagged": n >= min_requests and rate < low_success_pct,
            }
        )
    rows.sort(key=lambda r: (-r["requests"], r["name"]))
    return {"providers": rows, "suggested_action": _provider_suggestion(rows)}


# ---------------------------------------------------------------------------
# 3. Service occupancy: demand vs. capacity by specialty, and the providers
#    it would take to close the gap
# ---------------------------------------------------------------------------

#: Spanish display names for the specialty ids, mirroring
#: ``home_overview.SPECIALTY_ES``: the catalogue itself is in English (it
#: mirrors the platform's own field values).
SERVICE_LABEL_ES: dict[str, str] = {
    "general_practice": "Medicina general",
    "paediatrics": "Pediatría",
    "dermatology": "Dermatología",
    "orthopaedics": "Traumatología",
    "gynaecology": "Ginecología",
    "physiotherapy": "Fisioterapia",
}


def _request_specialty_id(catalogue: Catalogue, args: dict[str, Any]) -> str | None:
    """The specialty one ``find_slots`` request is actually about: the
    specialty asked for directly, or the one the named doctor practises. A
    request naming neither says nothing about which service was under
    pressure, so it counts toward no service's occupancy — the same rule
    the heatmap's ``all_day_demand`` bucket applies to an hour-less request."""
    if sid := args.get("specialty_id"):
        return str(sid)
    if pid := args.get("provider_id"):
        rec = next((p for p in catalogue.providers if p.provider_id == str(pid)), None)
        if rec:
            return rec.specialty_id
    return None


def _slot_specialty_id(catalogue: Catalogue, slot: dict[str, Any]) -> str | None:
    """The specialty an offered slot belongs to, resolved through the slot's
    own provider first — more reliable than trusting ``slot.specialty_id``
    made it through every layer of a real payload."""
    pid = slot.get("provider_id")
    rec = next((p for p in catalogue.providers if p.provider_id == str(pid)), None) if pid else None
    if rec:
        return rec.specialty_id
    sid = slot.get("specialty_id")
    return str(sid) if sid else None


def _extra_providers_needed(n_providers: int, occupancy_pct: float | None) -> int:
    """How many more providers of this specialty, at today's slots-per-doctor
    rate, would bring occupancy back to 100% — a straight-line estimate
    (capacity scales with headcount), not a schedule, but enough to turn a
    percentage into a hiring number."""
    if occupancy_pct is None or n_providers <= 0 or occupancy_pct <= 100:
        return 0
    needed = math.ceil(n_providers * occupancy_pct / 100)
    return needed - n_providers


def _providers_from_slots(cards: list[CallCard]) -> dict[str, ProviderRecord]:
    """Minimal provider records recovered straight from ``find_slots``
    results — id, name, specialty and the one site the slot was offered at.

    Thinner than a real ``/clinic`` ``find_provider`` record (no schedules,
    no insurers — not enough to draw the Agenda's grid, which is why
    ``calendar.provider_names_from_events`` only *corrects* an existing
    fixture provider instead of adding one), but enough to count a
    specialty's real doctors. It matters because ``occupancy_pct`` below is
    computed from these same ``find_slots`` results independently of the
    provider catalogue: a specialty the offline fixtures never modelled at
    all (there is no gynaecologist anywhere in ``vortex/clinic/fixtures.py``)
    can show real demand and a real offered slot yet count 0 providers,
    reading as "0 médicos, N% ocupación" on a service that plainly has at
    least one doctor — the exact doctor this recovers.
    """
    out: dict[str, ProviderRecord] = {}
    for card in cards:
        for step in card.tools:
            if step.name != "find_slots":
                continue
            result = _as_dict(step.result)
            for slot in result.get("slots") or []:
                slot_d = slot if isinstance(slot, dict) else _as_dict(slot)
                provider_id = str(slot_d.get("provider_id") or "")
                specialty_id = slot_d.get("specialty_id")
                if not provider_id or not specialty_id or provider_id in out:
                    continue
                location_id = slot_d.get("location_id")
                out[provider_id] = ProviderRecord(
                    provider_id=provider_id,
                    name=str(slot_d.get("provider_name") or provider_id),
                    specialty_id=str(specialty_id),
                    location_ids=[str(location_id)] if location_id else [],
                )
    return out


def _occupancy_providers(cards: list[CallCard], catalogue: Catalogue) -> list[ProviderRecord]:
    """``catalogue.providers`` plus any doctor ``find_slots`` named that the
    catalogue does not already know by id — see ``_providers_from_slots``."""
    known = {p.provider_id for p in catalogue.providers}
    extra = [p for pid, p in _providers_from_slots(cards).items() if pid not in known]
    return [*catalogue.providers, *extra]


def _service_occupancy_rows(
    cards: list[CallCard], catalogue: Catalogue, *, site_id: str | None = None
) -> list[dict[str, Any]]:
    """One row per specialty in the catalogue, scoped to one site when
    ``site_id`` is given. A request without a named site counts against
    every site it could have landed in (``_request_scope``), same as the
    heatmap; a slot only counts against the site it was actually offered at.
    """
    requested: Counter[str] = Counter()
    offered: Counter[str] = Counter()
    declined_full: Counter[str] = Counter()
    booked: Counter[str] = Counter()
    providers = _occupancy_providers(cards, catalogue)

    for card in cards:
        declined = is_unmet_demand(card) and classify_unmet(card) == "no_slot_in_window"
        for step in card.tools:
            if step.name != "find_slots":
                continue
            args = _as_dict(step.args)
            scope = _request_scope(catalogue, args)
            if site_id is not None and site_id not in scope:
                continue
            specialty_id = _request_specialty_id(catalogue, args)
            if not specialty_id:
                continue
            requested[specialty_id] += 1
            if declined:
                declined_full[specialty_id] += 1
            result = _as_dict(step.result)
            for slot in result.get("slots") or []:
                slot_d = slot if isinstance(slot, dict) else _as_dict(slot)
                if site_id is not None and str(slot_d.get("location_id")) != site_id:
                    continue
                slot_specialty = _slot_specialty_id(catalogue, slot_d) or specialty_id
                offered[slot_specialty] += 1
        pid = _booked_provider_id(card)
        info = PROVIDER_BY_ID.get(pid) if pid else None
        if info:
            loc_id = (card.action_payload or {}).get("location_id")
            if site_id is None or str(loc_id) == site_id:
                booked[info.specialty_id] += 1

    rows: list[dict[str, Any]] = []
    for specialty_id, specialty_name in SPECIALTY_NAME_BY_ID.items():
        n_providers = len(
            [
                p
                for p in providers
                if p.specialty_id == specialty_id and (site_id is None or site_id in p.location_ids)
            ]
        )
        req, off = requested.get(specialty_id, 0), offered.get(specialty_id, 0)
        if off > 0:
            occupancy_pct: float | None = round(100 * req / off, 1)
        elif req > 0:
            occupancy_pct = None  # asked for, nothing was ever on offer to divide by
        else:
            occupancy_pct = 0.0
        rows.append(
            {
                "id": specialty_id,
                "name": SERVICE_LABEL_ES.get(specialty_id, specialty_name),
                "requested": req,
                "offered": off,
                "booked": booked.get(specialty_id, 0),
                "declined_full": declined_full.get(specialty_id, 0),
                "providers": n_providers,
                "occupancy_pct": occupancy_pct,
                "extra_providers_needed": _extra_providers_needed(n_providers, occupancy_pct),
            }
        )
    rows.sort(key=lambda r: (-(r["occupancy_pct"] or -1), r["name"]))
    return rows


def service_occupancy(
    cards: list[CallCard], *, catalogue: Catalogue | None = None
) -> dict[str, Any]:
    """Occupancy per specialty, network-wide and per site: how many
    appointment requests landed against how many slots were actually
    offered. The platform only ever offers a slot that exists, so a request
    with nothing to match is exactly a rejection for being full — over 100%
    reads as "we turned real callers away here", not a rounding artefact.
    """
    catalogue = catalogue or site_catalogue()
    return {
        "all": _service_occupancy_rows(cards, catalogue),
        "sites": [
            {
                "id": loc.location_id,
                "name": loc.name,
                "services": _service_occupancy_rows(cards, catalogue, site_id=loc.location_id),
            }
            for loc in catalogue.locations
        ],
    }


# ---------------------------------------------------------------------------
# 4. Demand vs. supply heatmap
# ---------------------------------------------------------------------------


def _offered_bands(card: CallCard) -> list[tuple[int, str, str | None]]:
    """(weekday, band, location_id) for every slot a ``find_slots`` call
    actually returned — the availability really on offer, independent of what
    was asked, read straight off ``AvailabilityResult.slots[].start``."""
    out: list[tuple[int, str, str | None]] = []
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
                loc_id = slot_d.get("location_id")
                out.append((local.weekday(), band, str(loc_id) if loc_id else None))
    return out


def _hottest_gap(
    demand: Counter[tuple[int, str]], supply: Counter[tuple[int, str]]
) -> tuple[tuple[int, str], int] | None:
    candidates = [(key, d) for key, d in demand.items() if d > 0 and supply.get(key, 0) < d]
    if not candidates:
        return None
    return max(candidates, key=lambda kv: kv[1] - supply.get(kv[0], 0))


def _band_is_open(loc: LocationRecord, weekday: int, band_start: int, band_end: int) -> bool:
    """Whether the site's published hours cover any minute of the band. A
    band that only half overlaps (Sur's Friday 09:00–14:00 inside the 12–15
    "Mediodía" band) counts as open — it is closed cells that say "Cerrado"."""
    for h in loc.hours:
        if h.weekday != weekday:
            continue
        opens_m = h.opens.hour * 60 + h.opens.minute
        closes_m = h.closes.hour * 60 + h.closes.minute
        if opens_m < band_end * 60 and closes_m > band_start * 60:
            return True
    return False


def _open_matrix(loc: LocationRecord) -> list[list[bool]]:
    """7 weekdays x 4 bands, True where the site takes appointments."""
    return [[_band_is_open(loc, wd, start, end) for _label, start, end in BANDS] for wd in range(7)]


_DAY_SHORT = ("L", "M", "X", "J", "V", "S", "D")


def _hours_label(loc: LocationRecord) -> str:
    """The site's weekly pattern in one line: "L–V 09:00–20:00 · S 09:00–14:00"."""
    by_day: list[list[str]] = [[] for _ in range(7)]
    for h in loc.hours:
        by_day[h.weekday].append(f"{h.opens:%H:%M}–{h.closes:%H:%M}")
    parts: list[str] = []
    wd = 0
    while wd < 7:
        ivs = sorted(by_day[wd])
        if not ivs:
            wd += 1
            continue
        end = wd
        while end + 1 < 7 and sorted(by_day[end + 1]) == ivs:
            end += 1
        days_label = _DAY_SHORT[wd] if wd == end else f"{_DAY_SHORT[wd]}–{_DAY_SHORT[end]}"
        parts.append(f"{days_label} {' + '.join(ivs)}")
        wd = end + 1
    return " · ".join(parts)


def _heatmap_grid(
    demand: Counter[tuple[int, str]],
    all_day: Counter[int],
    supply: Counter[tuple[int, str]],
) -> list[dict[str, Any]]:
    return [
        {
            "weekday": WEEKDAYS_ES[wd],
            "all_day_demand": all_day.get(wd, 0),
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


def demand_supply_heatmap(
    cards: list[CallCard], *, catalogue: Catalogue | None = None
) -> dict[str, Any]:
    """Weekday x band grid: appointments requested vs. slots offered.

    ``rows`` is the whole network; ``sites`` repeats the same grid per
    location for the page's clinic picker. A request counts against every
    site it could have landed in (``_request_scope``), a slot only against
    its own site. ``open`` marks the (weekday, band) cells each site actually
    opens — the page paints the rest as "Cerrado".
    """
    catalogue = catalogue or site_catalogue()
    locations = list(catalogue.locations)
    site_ids = {loc.location_id for loc in locations}

    demand: Counter[tuple[int, str]] = Counter()
    demand_all_day: Counter[int] = Counter()
    supply: Counter[tuple[int, str]] = Counter()
    site_demand: dict[str, Counter[tuple[int, str]]] = defaultdict(Counter)
    site_all_day: dict[str, Counter[int]] = defaultdict(Counter)
    site_supply: dict[str, Counter[tuple[int, str]]] = defaultdict(Counter)

    for card in cards:
        for weekday, band, scope in _requested_bands(card, catalogue):
            if band:
                demand[(weekday, band)] += 1
            else:
                demand_all_day[weekday] += 1
            for site in scope & site_ids:
                if band:
                    site_demand[site][(weekday, band)] += 1
                else:
                    site_all_day[site][weekday] += 1
        for weekday, band, loc_id in _offered_bands(card):
            supply[(weekday, band)] += 1
            if loc_id in site_ids:
                site_supply[loc_id][(weekday, band)] += 1

    open_by_site = {loc.location_id: _open_matrix(loc) for loc in locations}
    combined_open = [
        [any(open_by_site[s][wd][bi] for s in site_ids) for bi in range(len(BANDS))]
        for wd in range(7)
    ]

    sites = [
        {
            "id": loc.location_id,
            "name": loc.name,
            "hours_label": _hours_label(loc),
            "open": open_by_site[loc.location_id],
            "rows": _heatmap_grid(
                site_demand[loc.location_id],
                site_all_day[loc.location_id],
                site_supply[loc.location_id],
            ),
        }
        for loc in locations
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

    return {
        "rows": _heatmap_grid(demand, demand_all_day, supply),
        "bands": list(BAND_LABELS),
        "open": combined_open,
        "sites": sites,
        "suggested_action": suggestion,
    }


# ---------------------------------------------------------------------------
# 5. Cancellations: slots reused vs. slots lost
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
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=UTC)
                out[str(aid)] = {"provider_id": str(provider_id), "start": start_dt}
    return out


def _started_dt(card: CallCard) -> datetime | None:
    """The call's start as an aware datetime (naive stamps read as UTC)."""
    if not card.started_at:
        return None
    try:
        stamp = datetime.fromisoformat(str(card.started_at))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


#: Lead-time buckets, by the edge a notice falls under. The story the panel
#: tells: last-minute cancellations are the ones that get lost — nobody has
#: the hours to take the freed slot.
LEAD_BUCKETS: tuple[tuple[str, str, float], ...] = (
    ("under_24h", "< 24 h", 24 * 3600),
    ("h24_48", "24–48 h", 48 * 3600),
    ("h48_7d", "48 h – 7 d", 7 * 86400),
    ("over_7d", "> 7 d", float("inf")),
)

CANCEL_REASON_LABELS: dict[str, str] = {
    "scheduling": "Horario o imprevisto",
    "no_longer_needed": "Ya no le hacía falta",
    "health": "Ya está mejor",
    "mistake": "Se equivocó",
    "other": "Otro motivo",
    "unknown": "Sin motivo dicho",
}

#: The two catch-all buckets. However many cancellations they carry, they
#: never outrank a specific reason in the list the clinic reads — a pile of
#: "no idea why" is a data-quality problem, not the clinic's top cancellation
#: driver. Order matters: "other" (a reason was given, just not one we know)
#: prints above "unknown" (no reason at all).
RESIDUAL_CANCEL_REASONS: tuple[str, ...] = ("other", "unknown")

#: Fixed print order for the specific (non-residual) buckets — the
#: declaration order of ``CANCEL_REASON_LABELS``, not a count. The count a
#: bucket happens to have this week is not a reason to reshuffle the list
#: every time someone reads it; only the two residual buckets are pinned
#: below these regardless of their own count (see ``_cancel_reason_sort_key``).
_CANCEL_REASON_ORDER: dict[str, int] = {
    key: i
    for i, key in enumerate(k for k in CANCEL_REASON_LABELS if k not in RESIDUAL_CANCEL_REASONS)
}


def _cancel_reason_sort_key(item: tuple[str, int]) -> tuple[int, int]:
    """Specific reasons in a fixed order, never by count; the residual
    buckets always last, in ``RESIDUAL_CANCEL_REASONS`` order, no matter
    their count."""
    key, _count = item
    if key in RESIDUAL_CANCEL_REASONS:
        return (1, RESIDUAL_CANCEL_REASONS.index(key))
    return (0, _CANCEL_REASON_ORDER.get(key, 0))


#: Folded keywords, same pattern as ``_KEYWORD_BUCKETS``: first bucket with
#: a hit wins. "me equivoqué" beats "no puedo" — a mistaken booking gets
#: cancelled however the caller frames the rest of the sentence.
#:
#: ``no_longer_needed`` was added by reading every call in ``logs/calls.jsonl``
#: that ``classify_cancel_reason`` put in "Otro motivo": "porque al final no
#: me hace falta" was the only real phrase there, appearing twice, so it
#: clears the "at least 2 real cases" bar this file's cancellation panel
#: applies before a bucket earns its own row. The seven other candidates a
#: clinic manager might expect — work/schedule (already covered by
#: ``scheduling``'s "trabajo"/"me ha surgido"/"imprevisto"), transport, family
#: care, another clinic, price/insurance, forgetting, and fear/nerves — have
#: zero occurrences anywhere in the log (checked with a plain substring
#: search over the whole file, not just unmet-demand or cancel calls), so
#: none of them get a bucket: a bucket with no real backing would just be an
#: empty row forever, which is worse than leaving that phrasing in "Otro
#: motivo" until a real case shows up.
_CANCEL_REASON_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "mistake",
        ("me equivoque", "me he equivocado", "no era asi", "me confundi", "era otro dia"),
    ),
    (
        "health",
        (
            "estoy mejor",
            "se me ha pasado",
            "ya no me duele",
            "me encuentro mejor",
            "me siento mejor",
            "me he curado",
        ),
    ),
    (
        "no_longer_needed",
        ("no me hace falta", "ya no me hace falta", "no lo necesito", "ya no lo necesito"),
    ),
    (
        "scheduling",
        (
            "no puedo",
            "me ha surgido",
            "me surge",
            "trabajo",
            "imprevisto",
            "me tengo que ir",
            "de viaje",
            "no me viene",
        ),
    ),
)

#: Cue words meaning the caller *did* give a reason, just none we know — the
#: difference between "other" and "unknown".
_REASON_CUES = ("porque", "es que", "ya que", "por culpa", "al final")


def classify_cancel_reason(card: CallCard) -> str:
    """Why the caller said they cancel — folded keyword match on their own
    turns, ``unknown`` when they never gave one. Same offline pattern as
    ``classify_unmet``."""
    text = _user_text(card)
    if not text:
        return "unknown"
    for bucket, keywords in _CANCEL_REASON_BUCKETS:
        if any(kw in text for kw in keywords):
            return bucket
    return "other" if any(cue in text for cue in _REASON_CUES) else "unknown"


def _lead_time_suggestion(leads: list[float]) -> str | None:
    if not leads:
        return None
    last_minute = sum(1 for s in leads if s < 24 * 3600)
    if last_minute * 2 >= len(leads):
        return (
            f"La mayoría de las cancelaciones ({last_minute} de {len(leads)}) llegan con "
            "menos de 24 h de antelación: ofrecer el hueco a la lista de espera en el "
            "instante de la cancelación es lo único que les da salida."
        )
    return (
        f"La cancelación mediana avisa con {median(leads) / 3600:.0f} h de antelación: hay "
        "margen para reofrecer el hueco si el aviso a la lista de espera es automático."
    )


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


def cancellation_slots(
    cards: list[CallCard],
    *,
    now: datetime | None = None,
    catalogue: Catalogue | None = None,
) -> dict[str, Any]:
    """Every slot a cancellation freed this period: reused by another
    caller, or still empty once the appointment day arrived — plus the
    detail around it: how far ahead the caller cancelled (``lead_time``),
    how fast a freed slot was taken again (``relocation_speed``), the
    cancellation rate over all appointment actions (``cancel_rate``), the
    doctors losing the most slots (``by_provider``), why callers said they
    cancelled (``reasons``), the unmet callers who had asked for the lost
    slots (``waitlist``) and repeat cancellers by number (``repeat_callers``).

    A cancellation only frees the exact (provider, minute) an earlier
    ``list_appointments`` call showed for that ``appointment_id``; without
    that lookup in the log a freed slot cannot be placed and is skipped
    (see ``DATA_GAPS``). "Reused" means a *different* call booked into that
    same (provider, minute) — the original booking that got cancelled does
    not count against itself.
    """
    now = now or datetime.now(UTC)
    catalogue = catalogue or site_catalogue()
    lookup = _appointment_lookup(cards)
    bookings: list[tuple[str, datetime, str, datetime | None]] = []
    for card in cards:
        if slot := _booked_slot(card):
            bookings.append((*slot, card.call_id, _started_dt(card)))

    freed: list[dict[str, Any]] = []
    for card in cards:
        if card.action_kind != "cancel":
            continue
        appointment_id = (card.action_payload or {}).get("appointment_id")
        info = lookup.get(str(appointment_id)) if appointment_id else None
        if not info:
            continue
        started = _started_dt(card)
        freed_at = _cancel_event_ts(card) or started
        rebookers = [
            booked_at
            for pid, start, cid, booked_at in bookings
            if pid == info["provider_id"] and start == info["start"] and cid != card.call_id
        ]
        relocated_at = min((b for b in rebookers if b is not None), default=None)
        if rebookers:
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
                "freed_at": (freed_at or now).isoformat(),
                "status": status,
                "start_dt": info["start"],
                "lead_s": (info["start"] - started).total_seconds() if started else None,
                "relocated_in_s": (
                    (relocated_at - freed_at).total_seconds()
                    if relocated_at is not None and freed_at is not None
                    else None
                ),
                "reason": classify_cancel_reason(card),
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

    # How far ahead of the slot the cancel call came in. A slot cancelled
    # after its own start lands in the <24 h bucket — retroactive, which in
    # practice is zero notice.
    leads = [f["lead_s"] for f in freed if f["lead_s"] is not None]
    lead_counts = {key: 0 for key, _label, _edge in LEAD_BUCKETS}
    for s in leads:
        for key, _label, edge in LEAD_BUCKETS:
            if s < edge:
                lead_counts[key] += 1
                break
    top_lead = max(lead_counts.values(), default=0) or 1
    lead_time = {
        "count": len(leads),
        "median_hours": round(median(leads) / 3600, 1) if leads else None,
        "buckets": [
            {
                "key": key,
                "label": label,
                "count": lead_counts[key],
                "share": round(lead_counts[key] / top_lead, 3),
            }
            for key, label, _edge in LEAD_BUCKETS
        ],
        "suggested_action": _lead_time_suggestion(leads),
    }

    # How fast a freed slot got taken again, from the cancel's submit event
    # to the rebooking call's start. A negative delta means the "rebooking"
    # call was already on the line when the cancel landed — real concurrency,
    # so it counts as relocated but says nothing about speed.
    reloc_deltas = [
        f["relocated_in_s"]
        for f in freed
        if f["relocated_in_s"] is not None and f["relocated_in_s"] >= 0
    ]
    relocation_speed = {
        "count": len(reloc_deltas),
        "median_minutes": round(median(reloc_deltas) / 60, 1) if reloc_deltas else None,
    }

    # Cancellations over every appointment action in the range — the
    # context the recovery rate needs.
    actions = Counter(c.action_kind for c in cards if c.action_kind)
    cancels = actions.get("cancel", 0)
    appointments = cancels + actions.get("book", 0) + actions.get("reschedule", 0)
    cancel_rate = {
        "cancels": cancels,
        "appointments": appointments,
        "pct": round(100 * cancels / appointments, 1) if appointments else None,
    }

    per_provider: dict[str, dict[str, int]] = {}
    for f in freed:
        row = per_provider.setdefault(f["provider_id"], {"freed": 0, "lost": 0})
        row["freed"] += 1
        row["lost"] += f["status"] == "lost"
    by_provider = sorted(
        (
            {
                "id": pid,
                "name": PROVIDER_BY_ID[pid].name if pid in PROVIDER_BY_ID else pid,
                **counts,
            }
            for pid, counts in per_provider.items()
        ),
        key=lambda r: (-r["freed"], r["name"]),
    )

    reason_counts = Counter(f["reason"] for f in freed)
    reasons = [
        {"key": k, "label": CANCEL_REASON_LABELS[k], "count": n}
        for k, n in sorted(reason_counts.items(), key=_cancel_reason_sort_key)
    ]

    # The implicit waiting list: unmet callers in the range who had asked
    # for the very doctor or the very (weekday, band) of a slot that ended
    # up lost — they are the patients the freed minute could have gone to.
    unmet_info = {
        c.call_id: {
            "providers": requested_provider_ids(c),
            "bands": {
                (weekday, band) for weekday, band, _scope in _requested_bands(c, catalogue) if band
            },
        }
        for c in cards
        if is_unmet_demand(c)
    }
    lost_with_demand = 0
    waitlist_callers: set[str] = set()
    for f in freed:
        if f["status"] != "lost":
            continue
        local = f["start_dt"].astimezone(MADRID)
        band = _band_for_hour(local.hour)
        matched = {
            cid
            for cid, info in unmet_info.items()
            if f["provider_id"] in info["providers"]
            or (band is not None and (local.weekday(), band) in info["bands"])
        }
        if matched:
            lost_with_demand += 1
            waitlist_callers |= matched
    waitlist_n = len(waitlist_callers)
    waitlist = {
        "lost_with_demand": lost_with_demand,
        "callers": waitlist_n,
        "suggested_action": (
            f"{lost_with_demand} de los huecos perdidos tenían {waitlist_n} "
            f"{'paciente' if waitlist_n == 1 else 'pacientes'} que los habían pedido: "
            "ofrecérselos al cancelar los habría recuperado."
            if waitlist_n
            else None
        ),
    }

    # Repeat cancellers by caller number — count only, the number itself
    # never leaves this function.
    cancel_by_number = Counter(
        c.from_number for c in cards if c.action_kind == "cancel" and c.from_number
    )
    repeat_callers = {
        "callers": sum(1 for n in cancel_by_number.values() if n > 1),
        "cancellations": sum(n for n in cancel_by_number.values() if n > 1),
    }

    return {
        "freed_total": len(freed),
        "relocated": relocated_n,
        "lost": lost_n,
        "pending": pending_n,
        "recovery_rate_pct": round(100 * relocated_n / decided, 1) if decided else None,
        "lead_time": lead_time,
        "relocation_speed": relocation_speed,
        "cancel_rate": cancel_rate,
        "by_provider": by_provider,
        "reasons": reasons,
        "waitlist": waitlist,
        "repeat_callers": repeat_callers,
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
    "The provider/specialty directory this page matches mentions against — and the per-site "
    "opening hours behind the heatmap's Cerrado cells — comes from the local clinic fixtures, "
    "not a cached snapshot of the real /providers, /specialties and /clinic responses for this "
    "call — in live mode the roster and the hours can drift from what the API actually returned.",
    "A booked action's payload does not always carry provider_id (it depends on which tool built "
    "it); the ranking falls back to the provider name view.py already extracted, which can be "
    "missing if find_slots was not the last tool to touch that call's provider data.",
    'find_slots calls with no time_from ("cualquier hora") and calls where the caller genuinely '
    "never said a time both land in the heatmap's all_day_demand bucket — there is no field that "
    "tells the two apart.",
    "A `cancel` submission carries only the appointment_id, never the provider/slot it freed — "
    "cancellation_slots recovers it from a `list_appointments` call earlier in the same call and "
    "drops the cancellation from the count when that lookup is missing from the log. The same gap "
    "covers lead_time: a cancellation whose lookup is absent contributes no notice to the median. "
    "A `reschedule` frees its old slot the same way but is not counted here: only cancellations.",
    "The cancellation reason is a keyword read of the caller's own turns — the submit payload "
    "carries no reason, so `unknown` covers both callers who never said why and reasons the "
    "word list does not know.",
    "Relocation speed measures submit-event to call-start — a rebooking call already on the "
    "line when the cancel landed produces a negative delta and is kept out of the median.",
    "The implicit waiting list matches unmet calls by named provider or requested "
    "(weekday, band), not by whether the exact freed minute would have suited them — it "
    "over-counts callers who wanted a different hour of the same band.",
    "Repeat cancellers are keyed by caller phone number: one patient on two phones reads as "
    "two callers, a shared phone as one.",
]


def is_real_call(card: CallCard) -> bool:
    """A call that actually dialled the line — a real caller or one of
    ``scripts/fake_caller.py``'s practice runs — never an offline artefact
    sharing the same log:

    - eval smoke tests carry ``call_id`` prefixed ``probe:``
      (``evals/corpus/hydrate.py``);
    - both eval families (probes and the named corpus cases such as
      ``adversarial-...`` or ``the_rules-...``) mark their own
      ``call.started`` with ``clinic="synthetic-data"``, a value
      ``Settings.describe()`` never produces (real calls get "live" or
      "fake" there, meaning only whether the *clinic* API is live — not
      whether the *call* is real);
    - the console's "replay demo" button (``observability/demo.py``) marks
      its scripted calls ``voice="demo"``, a value ``voice_label`` never
      returns (real calls get "gemini-live", "pipecat" or "stub").

    Any one of these three checks alone would catch most of the log; kept
    together because either offline family evolving its ``call_id`` shape
    must not let its calls sneak back into what the board counts.
    """
    if card.call_id.startswith("probe:"):
        return False
    if card.clinic == "synthetic-data":
        return False
    return card.voice != "demo"


def business_insights(
    cards: list[CallCard], *, now: datetime | None = None, catalogue: Catalogue | None = None
) -> dict[str, Any]:
    """The full payload the Insights page's business-insights endpoint
    returns. ``cards`` is filtered to ``is_real_call`` first: eval probes,
    synthetic corpus cases and scripted "replay demo" calls share this same
    log for visibility elsewhere in the console, but they are not a call a
    clinic manager should see counted as business volume.

    ``catalogue`` defaults to the offline fixtures (``site_catalogue()``),
    but the caller should pass one already widened with the real roster the
    call log has seen (``vortex.observability.calendar.catalogue_with_log_
    roster``, the same widening the Agenda page applies) whenever it has
    one: the fixtures model seven of the platform's providers and are
    missing a gynaecologist entirely, so a specialty with real demand in
    the log but no matching fixture provider reads as "0 médicos, N%
    ocupación" — a real service the fixtures never heard of, not a service
    with no doctors.
    """
    cards = [c for c in cards if is_real_call(c)]
    catalogue = catalogue or site_catalogue()
    return {
        "calls_considered": len(cards),
        "unavailability": unavailability_reasons(cards, catalogue=catalogue),
        "providers": provider_ranking(cards),
        "occupancy": service_occupancy(cards, catalogue=catalogue),
        "heatmap": demand_supply_heatmap(cards, catalogue=catalogue),
        "cancellations": cancellation_slots(cards, now=now, catalogue=catalogue),
        "data_gaps": DATA_GAPS,
    }
