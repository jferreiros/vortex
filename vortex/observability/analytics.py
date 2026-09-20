"""The Analytics page's numbers: where calls end, and what they cost us.

``business_insights.py`` answers the clinic's questions — which demand the
line could not honour, which doctor is the bottleneck. This module answers
the engineering ones: how fast the line replies, how many turns it takes,
how much of the conversation the agent holds, what the models metered, and
how every call in the window fanned out from one number into its ending.

Everything here is derived from ``CallCard``s, so it reads whatever
``supabase_log.fetch_calls`` read of ``public.call_events`` — the one
store. Nothing is computed twice: the outcome taxonomy
is ``CallCard.status``, the refusal buckets are ``business_insights``'s, the
euros are ``pricing.price_call``'s.

**Honesty rules, because a dense page invites belief:**

- Every metric carries the number of calls it could be measured on.
  ``voice.reply_latency`` exists only on the pipecat lane and ``call.usage``
  only on metered calls, so both are minorities of the window and say so.
- The agent/caller split is counted in **words**, from the turn texts. No
  event carries speech seconds per side, so the page never claims them.
- Reply time from the log is the gap between a caller turn being written and
  the next agent turn being written. It covers every call, and it is a log
  measurement, not the microphone one. Where the real VAD measurement exists
  it is shown beside it, never averaged into it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any

from vortex.observability.business_insights import (
    BUCKET_LABELS,
    classify_unmet,
    is_real_call,
)
from vortex.observability.pricing import price_call
from vortex.observability.view import CallCard

#: Column 1 of the funnel: what the line did with the call.
OUTCOME_LABELS: dict[str, str] = {
    "booked": "Cita reservada",
    "registered": "Paciente registrado",
    "rescheduled": "Cita reprogramada",
    "cancelled": "Cita cancelada",
    "refused": "Sin acción",
    "escalated": "Escalada a persona",
    "ended": "Sin desenlace",
    "live": "En curso",
}

#: The four endings that changed the diary. Grouped in column 1 so the split
#: the clinic cares about — handled or not — is one read, and the detail is
#: one column further right.
RESOLVED = ("booked", "registered", "rescheduled", "cancelled")

GROUP_LABELS: dict[str, str] = {
    "resolved": "Gestión completada",
    "refused": "Sin acción",
    "escalated": "Escalada a persona",
    "dropped": "Sin desenlace",
}

#: ``business_insights``' "other" bucket holds three findings that have
#: nothing to do with each other — a caller the line was never meant to
#: serve, a patient the directory could not match, and an emergency. Rolled
#: up they read as one shrug; split they are three different jobs. The page
#: splits them, and keeps the bucket name for everything else.
OTHER_REASON_LABELS: dict[str, str] = {
    "out_of_scope": "Fuera de alcance de la línea",
    "patient_not_found": "Paciente no encontrado",
    "medical_emergency": "Urgencia médica",
}

#: Tone keys the page maps to design tokens. Never a colour here.
GROUP_TONE: dict[str, str] = {
    "resolved": "primary",
    "refused": "warn",
    "escalated": "urgent",
    "dropped": "faint",
}

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str | None) -> int:
    return len(_WORD.findall(text or ""))


def _stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _pct(part: float, whole: float) -> float:
    return round(part * 100.0 / whole, 1) if whole else 0.0


def _percentiles(values: list[float]) -> dict[str, float | int | None]:
    """p50/p90 plus the count they were measured on — the count is part of
    the number, not a footnote: a p90 over four calls is not a p90."""
    if not values:
        return {"p50": None, "p90": None, "n": 0}
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * 0.9))
    return {
        "p50": round(median(ordered), 1),
        "p90": round(ordered[index], 1),
        "n": len(ordered),
    }


def _group_of(status: str) -> str:
    if status in RESOLVED:
        return "resolved"
    if status == "refused":
        return "refused"
    if status == "escalated":
        return "escalated"
    return "dropped"


@dataclass
class CallRow:
    """One call, flattened for the table and for every aggregate above it."""

    card: CallCard
    started: datetime | None
    status: str
    group: str
    turns_user: int
    turns_agent: int
    words_user: int
    words_agent: int
    reply_gaps_ms: list[float]
    voice_latency_s: list[float]
    tool_calls: list[tuple[str, float | None, bool]]
    duration_s: float | None
    language: str | None

    @property
    def words_total(self) -> int:
        return self.words_user + self.words_agent


def _events_of(card: CallCard, kind: str) -> list[dict[str, Any]]:
    return [e for e in card.events if isinstance(e, dict) and e.get("kind") == kind]


def _language(card: CallCard) -> str | None:
    """The language this call ran in.

    ``call.started`` does not carry one — it is settled during the call, not
    at connect — so this reads the same three signals the database write
    does, strongest first: an explicit switch, the filler line's own tag,
    and failing both, ``detect_language`` over the caller's words. That last
    one is exactly what ``database/hooks.py`` stores in ``calls.language``,
    so the page and the table never disagree.
    """
    for event in reversed(card.events):
        if not isinstance(event, dict):
            continue
        if event.get("kind") == "voice.language_switch" and event.get("now"):
            return str(event["now"])
    for event in reversed(card.events):
        if isinstance(event, dict) and event.get("kind") == "voice.tool_filler":
            if event.get("language"):
                return str(event["language"])
    words = " ".join(t.text for t in card.turns if t.role == "user" and t.text)
    if not words.strip():
        return None
    try:
        from vortex.conversation.language import detect_language

        return detect_language(words) or None
    except Exception:
        return None


def _reply_gaps(card: CallCard) -> list[float]:
    """Milliseconds from a caller turn reaching the log to the next agent
    turn reaching it. A log measurement — see the module docstring."""
    gaps: list[float] = []
    pending: datetime | None = None
    for event in card.events:
        if not isinstance(event, dict):
            continue
        kind = event.get("kind")
        if kind == "turn.user":
            pending = _stamp(event.get("ts"))
        elif kind == "turn.assistant" and pending is not None:
            landed = _stamp(event.get("ts"))
            if landed is not None:
                delta = (landed - pending).total_seconds() * 1000.0
                # A negative or absurd gap means the two lines were written
                # out of order (a batched flush), not a 40-second silence.
                if 0 <= delta <= 60_000:
                    gaps.append(delta)
            pending = None
    return gaps


def _row(card: CallCard) -> CallRow:
    turns_user = sum(1 for t in card.turns if t.role == "user")
    turns_agent = sum(1 for t in card.turns if t.role == "assistant")
    words_user = sum(_words(t.text) for t in card.turns if t.role == "user")
    words_agent = sum(_words(t.text) for t in card.turns if t.role == "assistant")
    voice = [
        float(e["total_secs"])
        for e in _events_of(card, "voice.reply_latency")
        if isinstance(e.get("total_secs"), int | float)
    ]
    tools = [(step.name, step.ms, step.status == "failed") for step in card.tools if step.name]
    return CallRow(
        card=card,
        started=_stamp(card.started_at),
        status=card.status,
        group=_group_of(card.status),
        turns_user=turns_user,
        turns_agent=turns_agent,
        words_user=words_user,
        words_agent=words_agent,
        reply_gaps_ms=_reply_gaps(card),
        voice_latency_s=voice,
        tool_calls=tools,
        duration_s=(card.duration_ms / 1000.0) if card.duration_ms else None,
        language=_language(card),
    )


# ---------------------------------------------------------------------------
# 1. The funnel — one number fanning out into its endings
# ---------------------------------------------------------------------------


def _refusal_label(bucket: str) -> str:
    if bucket == "unrecorded":
        return "Sin motivo registrado"
    if bucket.startswith("reason:"):
        reason = bucket.split(":", 1)[1]
        return OTHER_REASON_LABELS.get(reason, reason.replace("_", " ").capitalize())
    return BUCKET_LABELS.get(bucket, bucket)


def funnel(rows: list[CallRow]) -> dict[str, Any]:
    """Nodes and links for the Sankey: total → what the line did → how it
    ended. Column 2 splits the refusals by the same buckets the Statistics
    page names, so the two pages never disagree about why a call failed."""
    total = len(rows)
    nodes: list[dict[str, Any]] = [
        {"id": "all", "label": "Llamadas", "value": total, "column": 0, "tone": "ink"}
    ]
    links: list[dict[str, Any]] = []

    groups = Counter(row.group for row in rows)
    for key in ("resolved", "refused", "escalated", "dropped"):
        value = groups.get(key, 0)
        if not value:
            continue
        nodes.append(
            {
                "id": f"g:{key}",
                "label": GROUP_LABELS[key],
                "value": value,
                "column": 1,
                "tone": GROUP_TONE[key],
            }
        )
        links.append({"source": "all", "target": f"g:{key}", "value": value})

    # Column 2, branch by branch.
    resolved = Counter(row.status for row in rows if row.group == "resolved")
    for status, value in resolved.most_common():
        nodes.append(
            {
                "id": f"o:{status}",
                "label": OUTCOME_LABELS.get(status, status),
                "value": value,
                "column": 2,
                "tone": "primary",
            }
        )
        links.append({"source": "g:resolved", "target": f"o:{status}", "value": value})

    refused: Counter[str] = Counter()
    for row in rows:
        if row.group != "refused":
            continue
        bucket = classify_unmet(row.card)
        if bucket == "other":
            # A call refused with no typed reason is not "other" either: it
            # is a gap in our own instrumentation, and naming it apart is
            # what makes it fixable.
            reason = row.card.decline_reason
            bucket = f"reason:{reason}" if reason else "unrecorded"
        refused[bucket] += 1
    for bucket, value in refused.most_common():
        nodes.append(
            {
                "id": f"r:{bucket}",
                "label": _refusal_label(bucket),
                "value": value,
                "column": 2,
                "tone": "faint" if bucket == "unrecorded" else "warn",
            }
        )
        links.append({"source": "g:refused", "target": f"r:{bucket}", "value": value})

    escalated = Counter(
        row.card.decline_reason or "sin_motivo" for row in rows if row.group == "escalated"
    )
    for reason, value in escalated.most_common():
        label = "Urgencia médica" if reason == "medical_emergency" else "Fuera de alcance"
        nodes.append(
            {
                "id": f"e:{reason}",
                "label": label,
                "value": value,
                "column": 2,
                "tone": "urgent",
            }
        )
        links.append({"source": "g:escalated", "target": f"e:{reason}", "value": value})

    dropped = Counter(row.status for row in rows if row.group == "dropped")
    for status, value in dropped.most_common():
        nodes.append(
            {
                "id": f"d:{status}",
                "label": OUTCOME_LABELS.get(status, status),
                "value": value,
                "column": 2,
                "tone": "faint",
            }
        )
        links.append({"source": "g:dropped", "target": f"d:{status}", "value": value})

    return {
        "total": total,
        "nodes": nodes,
        "links": links,
        "columns": ["Todas las llamadas", "Qué hizo la línea", "Cómo terminó"],
    }


# ---------------------------------------------------------------------------
# 2. Latency and conversation shape
# ---------------------------------------------------------------------------


def _histogram(values: list[float], edges: list[float], labels: list[str]) -> list[dict[str, Any]]:
    buckets = [0] * len(labels)
    for value in values:
        slot = len(edges)
        for index, edge in enumerate(edges):
            if value < edge:
                slot = index
                break
        buckets[slot] += 1
    total = sum(buckets) or 1
    return [
        {"label": label, "count": count, "pct": _pct(count, total)}
        for label, count in zip(labels, buckets, strict=True)
    ]


def latency(rows: list[CallRow], langfuse: dict[str, Any] | None) -> dict[str, Any]:
    gaps = [gap for row in rows for gap in row.reply_gaps_ms]
    voice = [value for row in rows for value in row.voice_latency_s]
    generation = (langfuse or {}).get("generation") or {}
    return {
        # Every call in the window has this one.
        "log_reply_ms": _percentiles(gaps),
        "log_reply_calls": sum(1 for row in rows if row.reply_gaps_ms),
        # The microphone measurement: pipecat lane only.
        "voice_reply_s": _percentiles(voice),
        "voice_reply_calls": sum(1 for row in rows if row.voice_latency_s),
        # The model alone, from Langfuse. None when it is not configured.
        "llm_ms": (
            {
                "p50": generation.get("p50_ms"),
                "p90": generation.get("p95_ms"),
                "n": generation.get("count"),
                "percentile_label": "p95",
            }
            if generation
            else None
        ),
        "histogram": _histogram(
            gaps,
            [500, 1000, 2000, 4000],
            ["< 0,5 s", "0,5 – 1 s", "1 – 2 s", "2 – 4 s", "> 4 s"],
        ),
    }


def conversation(rows: list[CallRow]) -> dict[str, Any]:
    with_turns = [row for row in rows if row.turns_user or row.turns_agent]
    words_agent = sum(row.words_agent for row in with_turns)
    words_user = sum(row.words_user for row in with_turns)
    total_words = words_agent + words_user
    turns = [float(row.turns_user + row.turns_agent) for row in with_turns]
    durations = [row.duration_s for row in rows if row.duration_s]
    return {
        "calls": len(with_turns),
        "turns": _percentiles(turns),
        "turns_user": sum(row.turns_user for row in with_turns),
        "turns_agent": sum(row.turns_agent for row in with_turns),
        "words_user": words_user,
        "words_agent": words_agent,
        "agent_share_pct": _pct(words_agent, total_words),
        "duration_s": _percentiles([float(value) for value in durations]),
        "histogram": _histogram(
            turns,
            [6, 12, 20, 30],
            ["< 6 turnos", "6 – 12", "12 – 20", "20 – 30", "> 30"],
        ),
    }


# ---------------------------------------------------------------------------
# 3. Tools and models
# ---------------------------------------------------------------------------


def tools(rows: list[CallRow], langfuse: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per tool: how often the line reached for it, how long it took here,
    and what Langfuse measured at the call site. The two clocks differ on
    purpose — ours includes our own dispatch, theirs does not."""
    calls: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    durations: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for name, ms, failed in row.tool_calls:
            calls[name] += 1
            if failed:
                failures[name] += 1
            if isinstance(ms, int | float):
                durations[name].append(float(ms))

    remote = {
        str(row.get("name", "")).replace("-", "_"): row for row in (langfuse or {}).get("tools", [])
    }
    out = []
    for name, count in calls.most_common(14):
        stats = _percentiles(durations.get(name, []))
        far = remote.get(name.replace("-", "_"))
        out.append(
            {
                "name": name,
                "calls": count,
                "failures": failures.get(name, 0),
                "p50_ms": stats["p50"],
                "p90_ms": stats["p90"],
                "langfuse_p50_ms": (far or {}).get("p50_ms"),
                "langfuse_p95_ms": (far or {}).get("p95_ms"),
            }
        )
    return out


def models(rows: list[CallRow]) -> dict[str, Any]:
    """What the providers metered, and what it cost. Only calls carrying a
    ``call.usage`` event count: a stub-lane call has no meter, and averaging
    it in would quietly halve the price per call."""
    metered = []
    llm_models: Counter[str] = Counter()
    stt_models: Counter[str] = Counter()
    tts_models: Counter[str] = Counter()
    tokens_in = tokens_out = 0
    stt_seconds = 0.0
    tts_characters = 0
    total_eur = 0.0
    priced = 0

    for row in rows:
        usage = row.card.usage
        if not isinstance(usage, dict):
            continue
        metered.append(row)
        llm = usage.get("llm") if isinstance(usage.get("llm"), dict) else {}
        stt = usage.get("stt") if isinstance(usage.get("stt"), dict) else {}
        if llm.get("model"):
            llm_models[str(llm["model"])] += 1
        if stt.get("model"):
            stt_models[str(stt["model"])] += 1
        for leg in usage.get("tts") or []:
            if isinstance(leg, dict) and leg.get("model"):
                tts_models[str(leg["model"])] += 1
        try:
            cost = price_call(usage)
        except Exception:  # one malformed meter must not empty the panel
            continue
        tokens_in += cost.llm_tokens_in
        tokens_out += cost.llm_tokens_out
        stt_seconds += cost.stt_seconds
        tts_characters += cost.tts_characters
        if cost.metered:
            total_eur += cost.total_eur
            priced += 1

    def _top(counter: Counter[str]) -> list[dict[str, Any]]:
        return [{"name": name, "calls": value} for name, value in counter.most_common(4)]

    return {
        "metered_calls": len(metered),
        "llm": _top(llm_models),
        "stt": _top(stt_models),
        "tts": _top(tts_models),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "stt_seconds": round(stt_seconds, 1),
        "tts_characters": tts_characters,
        "total_eur": round(total_eur, 4),
        "eur_per_call": round(total_eur / priced, 4) if priced else None,
        "priced_calls": priced,
    }


# ---------------------------------------------------------------------------
# 4. The table
# ---------------------------------------------------------------------------


def call_table(rows: list[CallRow], limit: int = 120) -> list[dict[str, Any]]:
    """Newest first. One row per call, every column a measurement — this is
    the page's receipt: every aggregate above it can be found here."""
    ordered = sorted(
        rows,
        key=lambda row: row.started or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    out = []
    for row in ordered[:limit]:
        gaps = row.reply_gaps_ms
        out.append(
            {
                "call_id": row.card.call_id,
                "started_at": row.card.started_at,
                "status": row.status,
                "status_label": OUTCOME_LABELS.get(row.status, row.status),
                "group": row.group,
                "language": row.language,
                "duration_s": round(row.duration_s, 1) if row.duration_s else None,
                "turns": row.turns_user + row.turns_agent,
                "turns_user": row.turns_user,
                "turns_agent": row.turns_agent,
                "words_user": row.words_user,
                "words_agent": row.words_agent,
                "agent_share_pct": _pct(row.words_agent, row.words_total),
                "reply_ms": round(median(gaps), 0) if gaps else None,
                "voice_reply_s": (
                    round(median(row.voice_latency_s), 2) if row.voice_latency_s else None
                ),
                "tools": len(row.tool_calls),
                "tool_failures": sum(1 for _, _, failed in row.tool_calls if failed),
                "reason": row.card.decline_reason,
                "patient": row.card.patient_name,
                "provider": row.card.provider_name,
            }
        )
    return out


# ---------------------------------------------------------------------------
# 5. The pack
# ---------------------------------------------------------------------------


def _kpis(
    rows: list[CallRow],
    lat: dict[str, Any],
    convo: dict[str, Any],
    cost: dict[str, Any],
) -> list[dict[str, Any]]:
    total = len(rows)
    handled = sum(1 for row in rows if row.group == "resolved")
    llm = lat.get("llm_ms") or {}
    return [
        {
            "key": "calls",
            "label": "Llamadas analizadas",
            "value": total,
            "caption": f"{sum(1 for r in rows if r.group == 'dropped')} sin desenlace",
        },
        {
            "key": "handled",
            "label": "Gestión completada",
            "value": f"{_pct(handled, total)}%",
            "caption": f"{handled} de {total} tocaron la agenda",
        },
        {
            "key": "reply",
            "label": "Respuesta mediana",
            "value": (
                f"{lat['log_reply_ms']['p50'] / 1000:.2f} s"
                if lat["log_reply_ms"]["p50"] is not None
                else "—"
            ),
            "caption": f"p90 {lat['log_reply_ms']['p90'] / 1000:.2f} s"
            if lat["log_reply_ms"]["p90"] is not None
            else "sin muestras",
        },
        {
            "key": "llm",
            "label": "Latencia del modelo",
            "value": f"{llm['p50']:.0f} ms" if llm.get("p50") is not None else "—",
            "caption": (
                f"p95 {llm['p90']:.0f} ms · {llm.get('n', 0)} respuestas"
                if llm.get("p90") is not None
                else "Langfuse no conectado"
            ),
        },
        {
            "key": "turns",
            "label": "Turnos por llamada",
            "value": convo["turns"]["p50"] or "—",
            "caption": f"p90 {convo['turns']['p90'] or '—'} · {convo['calls']} llamadas",
        },
        {
            "key": "share",
            "label": "Habla el agente",
            "value": f"{convo['agent_share_pct']}%",
            "caption": f"{convo['words_agent']:,} palabras frente a "
            f"{convo['words_user']:,}".replace(",", "."),
        },
        {
            "key": "duration",
            "label": "Duración mediana",
            "value": (
                f"{convo['duration_s']['p50']:.0f} s"
                if convo["duration_s"]["p50"] is not None
                else "—"
            ),
            "caption": f"p90 {convo['duration_s']['p90']:.0f} s"
            if convo["duration_s"]["p90"] is not None
            else "sin muestras",
        },
        {
            "key": "cost",
            "label": "Coste por llamada",
            "value": (
                f"{cost['eur_per_call']:.4f} €".replace(".", ",")
                if cost.get("eur_per_call")
                else "—"
            ),
            "caption": f"{cost['metered_calls']} llamadas con contador",
        },
    ]


def analytics_pack(
    cards: list[CallCard],
    *,
    days: int,
    now: datetime | None = None,
    langfuse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything the Analytics page renders, from one pass over the window.

    ``cards`` is already date-filtered by the caller. Calls that never dialled
    the line — eval probes, the synthetic corpus — are dropped here the same
    way the Statistics page drops them, and counted in ``coverage`` so the
    page can say so out loud.
    """
    now = now or datetime.now(UTC)
    real = [card for card in cards if is_real_call(card)]
    rows = [_row(card) for card in real]

    lat = latency(rows, langfuse)
    convo = conversation(rows)
    cost = models(rows)
    return {
        "range_days": days,
        "generated_at": now.isoformat(),
        "coverage": {
            "calls": len(rows),
            "excluded": len(cards) - len(real),
            "with_turns": convo["calls"],
            "with_log_reply": lat["log_reply_calls"],
            "with_voice_latency": lat["voice_reply_calls"],
            "metered": cost["metered_calls"],
            "langfuse": bool(langfuse),
        },
        "kpis": _kpis(rows, lat, convo, cost),
        "funnel": funnel(rows),
        "latency": lat,
        "conversation": convo,
        "tools": tools(rows, langfuse),
        "models": cost,
        "calls": call_table(rows),
        "langfuse": (
            {
                "observations": langfuse.get("observations"),
                "environment": langfuse.get("environment"),
                "project_url": langfuse.get("project_url"),
                "call_p50_ms": (langfuse.get("call") or {}).get("p50_ms"),
                "call_p95_ms": (langfuse.get("call") or {}).get("p95_ms"),
            }
            if langfuse
            else None
        ),
        "languages": [
            {"code": code or "—", "calls": value}
            for code, value in Counter(row.language for row in rows).most_common(6)
        ],
    }
