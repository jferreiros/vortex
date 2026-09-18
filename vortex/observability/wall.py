"""Public board projections. Explicit states win over tool-based estimates.

These are display states, not a second conversation controller. See README.md
in this directory for the optional state, language and evaluation event shapes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from vortex.observability.view import CallCard, build_call


class Phase(StrEnum):
    CONNECTED = "CONNECTED"
    IDENTIFYING = "IDENTIFYING"
    REGISTERING = "REGISTERING"
    ROUTING = "ROUTING"
    SEARCHING = "SEARCHING"
    OFFERING = "OFFERING"
    MODIFYING = "MODIFYING"
    EMERGENCY = "EMERGENCY"
    SUBMITTING = "SUBMITTING"
    FINISHED = "FINISHED"


PHASE_DESCRIPTIONS = {
    Phase.CONNECTED: "Socket abierto · datos de la llamada recibidos",
    Phase.IDENTIFYING: "Buscando al paciente y resolviendo coincidencias",
    Phase.REGISTERING: "Paciente nuevo · recogiendo datos demográficos",
    Phase.ROUTING: "Detectando la intención de la llamada",
    Phase.SEARCHING: "Consultando disponibilidad y preferencias",
    Phase.OFFERING: "Proponiendo un hueco · esperando confirmación",
    Phase.MODIFYING: "Buscando una cita para cambiarla o cancelarla",
    Phase.EMERGENCY: "Síntomas graves · derivando a urgencias",
    Phase.SUBMITTING: "Enviando el resultado a Prosper",
    Phase.FINISHED: "Llamada cerrada · resultado final",
}

_TOOL_PHASES = {
    "find_patient": Phase.IDENTIFYING,
    "validate_national_id": Phase.IDENTIFYING,
    "build_registration": Phase.REGISTERING,
    "triage": Phase.ROUTING,
    "find_provider": Phase.SEARCHING,
    "nearest_location": Phase.SEARCHING,
    "resolve_date": Phase.SEARCHING,
    "check_eligibility": Phase.SEARCHING,
    "find_slots": Phase.SEARCHING,
    "prepare_booking": Phase.OFFERING,
    "list_appointments": Phase.MODIFYING,
    "prepare_cancel": Phase.MODIFYING,
    "prepare_reschedule": Phase.MODIFYING,
    "submit_action": Phase.SUBMITTING,
}
OUTCOMES = ("BOOK", "REGISTER", "CANCEL", "RESCHEDULE", "NO_ACTION", "ESCALATE")


@dataclass
class WallCall:
    card: CallCard
    phase: Phase = Phase.CONNECTED
    explicit_state: bool = False
    has_start: bool = False
    language: str | None = None
    passed: bool | None = None
    ended_at: str | None = None
    # Multiple submissions per call are valid. Store only distinct outcomes;
    # retries and call.summary must not inflate the historical distribution.
    outcomes: set[str] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return self.has_start and not self.card.ended

    @property
    def result_label(self) -> str:
        return " + ".join(sorted(self.outcomes)) or "SIN RESULTADO"

    def duration_seconds(self, now: datetime | None = None) -> float | None:
        if self.card.ended and self.card.duration_ms is not None:
            return max(0, self.card.duration_ms / 1000)
        try:
            start = datetime.fromisoformat(self.card.started_at or "")
            end = datetime.fromisoformat(self.ended_at or "") if self.card.ended else now
            end = end or datetime.now(UTC)
            if start.tzinfo is None or end.tzinfo is None:
                return None
            return max(0, (end - start).total_seconds())
        except (ValueError, TypeError):
            return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _submission(call: WallCall, event: dict[str, Any]) -> None:
    result = _dict(event.get("result"))
    status = result.get("status")
    if isinstance(status, str):
        call.card.submit_status = status
    route = event.get("route")
    if isinstance(route, str):
        outcome = route.rstrip("/").rsplit("/", 1)[-1].upper().replace("-", "_")
        # A prepared/rejected action is not a completed booking. Dry runs are
        # displayed as simulated outcomes, and never count as a passed case.
        if outcome in OUTCOMES and status in {"accepted", "duplicate", "dry_run"}:
            call.outcomes.add(outcome)


def _infer_phase(call: WallCall, event: dict[str, Any]) -> None:
    kind = event.get("kind")
    tool = event.get("tool")
    if kind == "tool.called" and tool in _TOOL_PHASES:
        call.phase = _TOOL_PHASES[tool]
    elif kind == "tool.returned":
        result = _dict(event.get("result"))
        if result.get("emergency") or _dict(result.get("rejection")).get("reason") == (
            "medical_emergency"
        ):
            call.phase = Phase.EMERGENCY
        elif tool == "find_patient":
            call.phase = {
                "found": Phase.ROUTING,
                "not_found": Phase.REGISTERING,
            }.get(result.get("status"), Phase.IDENTIFYING)
        elif tool == "find_slots":
            call.phase = Phase.OFFERING if result.get("slots") else Phase.SEARCHING
        elif tool in _TOOL_PHASES:
            call.phase = _TOOL_PHASES[tool]
    elif kind in {"submit.sent", "submit.result"}:
        call.phase = Phase.SUBMITTING


def build_wall_calls(events: list[dict[str, Any]]) -> list[WallCall]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("call_id"):
            grouped.setdefault(str(event["call_id"]), []).append(event)
    calls = []
    for call_id, items in reversed(list(grouped.items())):
        call = WallCall(card=build_call(call_id, items))
        for event in items:
            kind = event.get("kind")
            if kind == "call.started":
                call.has_start = True
            if kind in {"call.started", "turn.user", "language.detected", "call.summary"}:
                language = event.get("language")
                if isinstance(language, str) and language.strip():
                    call.language = language.strip().lower().replace("_", "-").split("-")[0]
            if kind == "call.verdict" and isinstance(event.get("passed"), bool):
                call.passed = event["passed"]
            if kind == "call.state":
                try:
                    call.phase = Phase(event.get("state"))
                    call.explicit_state = True
                    if call.phase == Phase.FINISHED:
                        call.card.ended = True
                        call.ended_at = event.get("ts")
                except ValueError:
                    pass
            elif not call.explicit_state:
                _infer_phase(call, event)
            if kind == "submit.result":
                _submission(call, event)
            if kind in {"call.ended", "call.summary"}:
                call.ended_at = event.get("ts") or call.ended_at
            if kind == "call.summary":
                for action in event.get("actions") or []:
                    if isinstance(action, dict):
                        _submission(call, action)
        if call.card.ended:
            call.phase = Phase.FINISHED
        calls.append(call)
    return calls


def group_by_phase(calls: list[WallCall]) -> dict[Phase, list[WallCall]]:
    groups: dict[Phase, list[WallCall]] = {phase: [] for phase in Phase}
    for call in calls:
        # A truncated remote log can contain tools without an opening event.
        # Do not claim those records are currently connected sockets.
        if call.active or call.card.ended:
            groups[call.phase].append(call)
    return groups


@dataclass
class WallStats:
    active: int
    completed: int
    evaluated: int
    passed: int
    accepted: int
    simulated: int
    average_seconds: float | None
    outcomes: Counter[str]
    languages: Counter[str]
    reasons: Counter[str]

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.evaluated if self.evaluated else None


def historical_stats(calls: list[WallCall]) -> WallStats:
    completed = [call for call in calls if call.card.ended]
    durations = [call.duration_seconds() for call in completed]
    known_durations = [duration for duration in durations if duration is not None]
    outcomes: Counter[str] = Counter(dict.fromkeys(OUTCOMES, 0))
    for call in completed:
        outcomes.update(call.outcomes or {"SIN RESULTADO"})
    return WallStats(
        active=sum(call.active for call in calls),
        completed=len(completed),
        evaluated=sum(call.passed is not None for call in completed),
        passed=sum(call.passed is True for call in completed),
        accepted=sum(call.card.submit_status in {"accepted", "duplicate"} for call in completed),
        simulated=sum(call.card.submit_status == "dry_run" for call in completed),
        average_seconds=(sum(known_durations) / len(known_durations)) if known_durations else None,
        outcomes=outcomes,
        languages=Counter(call.language or "Sin detectar" for call in completed),
        reasons=Counter(call.card.decline_reason for call in completed if call.card.decline_reason),
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"
