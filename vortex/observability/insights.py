"""Numbers for the Insights and Patients pages, computed from call cards.

Everything here comes from the call log. No storage, no sampling. When the
log is empty the page shows an honest empty state, never a sample chart.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

from vortex.observability.view import CallCard

MADRID = ZoneInfo("Europe/Madrid")


@dataclass
class Bar:
    key: str
    label: str
    value: int
    share: float  # 0..1 of the largest bar, for the width


def _bars(
    counter: Counter[str], labels: dict[str, str] | None = None, limit: int = 10
) -> list[Bar]:
    if not counter:
        return []
    top = counter.most_common(limit)
    biggest = top[0][1] or 1
    labels = labels or {}
    return [Bar(k, labels.get(k, k), v, v / biggest) for k, v in top]


def reasons(cards: list[CallCard], labels: dict[str, str] | None = None) -> list[Bar]:
    """Why calls did not book, most frequent first."""
    counter: Counter[str] = Counter(c.decline_reason for c in cards if c.decline_reason)
    return _bars(counter, labels)


def outcomes(cards: list[CallCard], labels: dict[str, str] | None = None) -> list[Bar]:
    counter: Counter[str] = Counter(
        "ended" if c.action_kind and not (c.submit_status or c.submit_route) else c.status
        for c in cards
        if not c.live
    )
    return _bars(counter, labels)


def tool_latency(cards: list[CallCard]) -> list[tuple[str, float, int]]:
    """(tool, median ms, samples), slowest first."""
    samples: dict[str, list[float]] = defaultdict(list)
    for card in cards:
        for step in card.tools:
            if step.ms is not None:
                samples[step.name].append(step.ms)
    rows = [(name, median(values), len(values)) for name, values in samples.items()]
    rows.sort(key=lambda r: -r[1])
    return rows


def tool_failures(cards: list[CallCard]) -> Counter[str]:
    return Counter(step.name for c in cards for step in c.tools if step.status == "fail")


def calls_by_hour(cards: list[CallCard]) -> list[Bar]:
    """Calls per hour of the day, Madrid time, 00..23. Empty hours are kept."""
    counter: Counter[int] = Counter()
    for card in cards:
        if not card.started_at:
            continue
        try:
            stamp = datetime.fromisoformat(card.started_at)
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo("UTC"))
        counter[stamp.astimezone(MADRID).hour] += 1
    if not counter:
        return []
    biggest = max(counter.values()) or 1
    return [
        Bar(str(h), f"{h:02d}", counter.get(h, 0), counter.get(h, 0) / biggest) for h in range(24)
    ]


def handle_times(cards: list[CallCard]) -> tuple[float | None, float | None, float | None]:
    """(median, p90, max) seconds for ended calls with a duration."""
    values = sorted(c.duration_ms / 1000 for c in cards if not c.live and c.duration_ms)
    if not values:
        return None, None, None
    p90 = values[min(len(values) - 1, int(round(0.9 * (len(values) - 1))))]
    return median(values), p90, values[-1]


@dataclass
class PatientRow:
    key: str
    name: str
    phone: str | None
    insurer: str | None
    calls: int = 0
    last_status: str = "ended"
    last_reason: str | None = None
    last_call_id: str = ""
    last_started: str | None = None
    call_ids: list[str] = field(default_factory=list)


def _insurer(card: CallCard) -> str | None:
    for step in card.tools:
        if step.name == "find_patient" and isinstance(step.result, dict):
            patient = step.result.get("patient")
            if isinstance(patient, dict) and patient.get("insurer"):
                return str(patient["insurer"])
    return None


def patients(cards: list[CallCard]) -> list[PatientRow]:
    """One row per patient seen on the line, most recent first.

    A patient is keyed by the directory patient_id when found, else by phone
    for unmatched callers. Calls with neither stay out: there is no patient
    to show.
    """
    rows: dict[str, PatientRow] = {}
    order: list[str] = []
    for card in cards:  # cards arrive newest first
        key = card.patient_id or card.from_number
        if not key:
            continue
        row = rows.get(key)
        if row is None:
            row = PatientRow(
                key=key,
                name=card.patient_name or "Unidentified patient",
                phone=card.from_number,
                insurer=_insurer(card),
                last_status=card.status,
                last_reason=card.decline_reason,
                last_call_id=card.call_id,
                last_started=card.started_at,
            )
            rows[key] = row
            order.append(key)
        row.calls += 1
        row.call_ids.append(card.call_id)
        if row.insurer is None:
            row.insurer = _insurer(card)
        if row.phone is None:
            row.phone = card.from_number
    return [rows[k] for k in order]


def mask_phone(value: str | None) -> str:
    """+34 612 345 678 -> +34 6•• ••• 678. Public pages never show a full number."""
    if not value:
        return "—"
    digits = [ch for ch in value if ch.isdigit()]
    if len(digits) < 6:
        return "•" * len(value)
    keep_head = 3 if value.startswith("+") else 1
    head = value[: keep_head + 1] if value.startswith("+") else value[:keep_head]
    tail = "".join(digits[-3:])
    hidden = max(len(digits) - len(head.strip("+")) - 3, 3)
    return f"{head}{'•' * hidden}{tail}"
