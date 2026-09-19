from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

ToolStatus = Literal["running", "ok", "fail"]
CallStatus = Literal[
    "live",
    "booked",
    "registered",
    "rescheduled",
    "cancelled",
    "refused",
    "escalated",
    "ended",
]


@dataclass
class ToolStep:
    name: str
    args: Any = None
    result: Any = None
    error: str | None = None
    ms: float | None = None
    status: ToolStatus = "running"


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str
    ts: str | None = None


@dataclass
class CallCard:
    call_id: str
    started_at: str | None = None
    from_number: str | None = None
    voice: str | None = None
    clinic: str | None = None
    turns: list[Turn] = field(default_factory=list)
    tools: list[ToolStep] = field(default_factory=list)
    action_kind: str | None = None
    action_payload: dict[str, Any] | None = None
    submit_status: str | None = None
    submit_route: str | None = None
    ended: bool = False
    reason: str | None = None
    duration_ms: float | None = None
    patient_name: str | None = None
    patient_id: str | None = None
    provider_name: str | None = None
    slot: str | None = None
    decline_reason: str | None = None
    last_ts: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> CallStatus:
        if not self.ended:
            return "live"
        kind = self.action_kind or ""
        if kind == "book":
            return "booked"
        if kind == "register":
            return "registered"
        if kind == "reschedule":
            return "rescheduled"
        if kind == "cancel":
            return "cancelled"
        if kind == "escalate":
            return "escalated"
        if kind == "no-action":
            return "refused"
        return "ended"

    @property
    def live(self) -> bool:
        return self.status == "live"


def _norm_text(text: str) -> str:
    return " ".join(text.split())


def _extends(short: str, long: str) -> bool:
    if not long.startswith(short):
        return False
    if len(long) == len(short):
        return True
    return long[len(short)] in " \t.,;:!?…"


def fold_turns(turns: list[Turn]) -> list[Turn]:
    out: list[Turn] = []
    for turn in turns:
        text = _norm_text(turn.text)
        if not text:
            continue
        if out:
            last = out[-1]
            last_text = _norm_text(last.text)
            if last.role == turn.role:
                if text == last_text:
                    continue
                if _extends(last_text, text):
                    out[-1] = Turn(turn.role, text, turn.ts)
                    continue
                if _extends(text, last_text):
                    continue
            if any(
                item.role == turn.role and _norm_text(item.text) == text for item in out[-8:]
            ):
                continue
        out.append(Turn(turn.role, text, turn.ts))
    return out


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {}


def _patient_name(result: Any) -> str | None:
    data = _as_dict(result)
    patient = data.get("patient")
    if isinstance(patient, dict):
        parts = [
            patient.get("given_name") or "",
            patient.get("first_surname") or "",
            patient.get("second_surname") or "",
        ]
        name = " ".join(p for p in parts if p).strip()
        return name or None
    return None


def _patient_id(result: Any) -> str | None:
    data = _as_dict(result)
    patient = data.get("patient")
    if isinstance(patient, dict) and patient.get("patient_id"):
        return str(patient["patient_id"])
    return None


def _provider_name(result: Any) -> str | None:
    data = _as_dict(result)
    provider = data.get("provider")
    if isinstance(provider, dict):
        return provider.get("name")
    return None


def _slot_label(result: Any) -> str | None:
    data = _as_dict(result)
    slots = data.get("slots")
    start = None
    if isinstance(slots, list) and slots and isinstance(slots[0], dict):
        start = slots[0].get("start")
    action = data.get("action")
    if start is None and isinstance(action, dict):
        start = action.get("slot")
    if not start:
        return None
    text = str(start)
    try:
        stamp = datetime.fromisoformat(text)
        return stamp.strftime("%d/%m %H:%M")
    except ValueError:
        return text


def _decline(result: Any) -> str | None:
    data = _as_dict(result)
    rejection = data.get("rejection")
    if isinstance(rejection, dict):
        return rejection.get("reason")
    if data.get("reason") and data.get("kind") in {"no-action", "escalate"}:
        return data.get("reason")
    return None


def _action_from_result(result: Any) -> tuple[str | None, dict[str, Any] | None]:
    data = _as_dict(result)
    action = data.get("action")
    if isinstance(action, dict) and action.get("kind"):
        return str(action["kind"]), action
    if data.get("kind"):
        return str(data["kind"]), data
    return None, None


def build_call(call_id: str, events: list[dict[str, Any]]) -> CallCard:
    card = CallCard(call_id=call_id, events=events)
    open_tools: list[ToolStep] = []
    for event in events:
        kind = event.get("kind")
        if event.get("ts"):
            card.last_ts = str(event["ts"])
        if kind == "call.started":
            card.started_at = event.get("ts") or event.get("connected_at")
            card.from_number = event.get("from_number")
            card.voice = event.get("voice")
            card.clinic = event.get("clinic")
        elif kind == "turn.user":
            card.turns.append(Turn("user", str(event.get("text") or ""), event.get("ts")))
        elif kind == "turn.assistant":
            card.turns.append(Turn("assistant", str(event.get("text") or ""), event.get("ts")))
        elif kind == "tool.called":
            step = ToolStep(name=str(event.get("tool") or "?"), args=event.get("args"))
            card.tools.append(step)
            open_tools.append(step)
        elif kind in {"tool.returned", "tool.failed"}:
            name = str(event.get("tool") or "")
            match = next((s for s in reversed(open_tools) if s.name == name), None)
            if match is None:
                match = ToolStep(name=name or "?")
                card.tools.append(match)
            else:
                open_tools.remove(match)
            if kind == "tool.failed":
                match.status = "fail"
                match.error = str(event.get("error") or "")
            else:
                match.status = "ok"
                match.result = event.get("result")
                ms = event.get("ms")
                match.ms = float(ms) if ms is not None else None
                name_guess = _patient_name(match.result)
                if name_guess:
                    card.patient_name = name_guess
                id_guess = _patient_id(match.result)
                if id_guess:
                    card.patient_id = id_guess
                provider_guess = _provider_name(match.result)
                if not provider_guess:
                    data = _as_dict(match.result)
                    slots = data.get("slots")
                    if isinstance(slots, list) and slots and isinstance(slots[0], dict):
                        nested = slots[0].get("provider")
                        if isinstance(nested, dict):
                            provider_guess = nested.get("name")
                if provider_guess:
                    card.provider_name = provider_guess
                slot_guess = _slot_label(match.result)
                if slot_guess:
                    card.slot = slot_guess
                decline_guess = _decline(match.result)
                if decline_guess:
                    card.decline_reason = decline_guess
                action_kind, action_payload = _action_from_result(match.result)
                if action_kind:
                    card.action_kind = action_kind
                    card.action_payload = action_payload
        elif kind in {"submit.result", "submit.sent"}:
            payload = event.get("payload")
            if isinstance(payload, dict):
                card.action_payload = payload
            route = event.get("route")
            if isinstance(route, str) and route:
                card.submit_route = route
                tail = route.rstrip("/").rsplit("/", 1)[-1]
                if tail:
                    card.action_kind = tail
            result = event.get("result")
            result_data = _as_dict(result)
            if result_data.get("status"):
                card.submit_status = str(result_data["status"])
            elif isinstance(result, str):
                card.submit_status = result
            if isinstance(payload, dict) and payload.get("reason"):
                card.decline_reason = str(payload["reason"])
        elif kind == "call.ended":
            card.ended = True
            card.reason = event.get("reason")
        elif kind == "call.summary":
            card.ended = True
            duration = event.get("duration_ms")
            card.duration_ms = float(duration) if duration is not None else card.duration_ms
            if event.get("reason"):
                card.reason = str(event["reason"])
            actions = event.get("actions")
            if isinstance(actions, list) and actions:
                last = actions[-1]
                if isinstance(last, dict):
                    route = last.get("route")
                    if isinstance(route, str) and route:
                        card.submit_route = route
                        card.action_kind = route.rstrip("/").rsplit("/", 1)[-1]
                    payload = last.get("payload")
                    if isinstance(payload, dict):
                        card.action_payload = payload
                        if payload.get("reason"):
                            card.decline_reason = str(payload["reason"])
    card.turns = fold_turns(card.turns)
    if card.action_kind in {"book", "register", "reschedule", "cancel"}:
        payload_reason = None
        if isinstance(card.action_payload, dict) and card.action_payload.get("reason"):
            payload_reason = str(card.action_payload["reason"])
        card.decline_reason = payload_reason
    return card


def build_calls(events: list[dict[str, Any]]) -> list[CallCard]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for event in events:
        call_id = str(event.get("call_id") or "?")
        if call_id not in grouped:
            grouped[call_id] = []
            order.append(call_id)
        grouped[call_id].append(event)
    cards = [build_call(call_id, grouped[call_id]) for call_id in order]
    cards.reverse()
    return cards


def flatten_grouped(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call_events in grouped.values():
        events.extend(call_events)
    events.sort(key=lambda event: str(event.get("ts") or ""))
    return events
