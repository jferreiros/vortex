"""A chat+tool timeline for one call, for the react-spring zoom page.

``build_timeline`` replays a call's raw JSONL events into the shape
``wall-app/src`` expects: an ordered list of ``turn`` and ``tool`` items.
A ``tool`` item is created on ``tool.called`` and mutated in place on
``tool.returned``/``tool.failed`` (same ``id``, ``status`` flips from
``"running"`` to ``"ok"``/``"fail"``) — the client tells the two apart by
watching that one field, never by re-fetching a different item.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from vortex.observability.view import build_call


def build_timeline(events: list[dict[str, Any]], call_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    open_tools: list[dict[str, Any]] = []
    next_id = 0

    def new_id() -> int:
        nonlocal next_id
        next_id += 1
        return next_id

    for event in events:
        if str(event.get("call_id") or "") != call_id:
            continue
        kind = event.get("kind")

        if kind == "turn.user":
            items.append(
                {
                    "id": new_id(),
                    "type": "turn",
                    "role": "user",
                    "text": str(event.get("text") or ""),
                    "ts": event.get("ts"),
                }
            )
        elif kind == "turn.assistant":
            items.append(
                {
                    "id": new_id(),
                    "type": "turn",
                    "role": "assistant",
                    "text": str(event.get("text") or ""),
                    "ts": event.get("ts"),
                }
            )
        elif kind == "tool.called":
            item = {
                "id": new_id(),
                "type": "tool",
                "tool": str(event.get("tool") or "?"),
                "status": "running",
                "args": event.get("args"),
                "result": None,
                "error": None,
                "ts": event.get("ts"),
            }
            items.append(item)
            open_tools.append(item)
        elif kind in {"tool.returned", "tool.failed"}:
            name = str(event.get("tool") or "")
            match = next((it for it in reversed(open_tools) if it["tool"] == name), None)
            if match is None:
                match = {
                    "id": new_id(),
                    "type": "tool",
                    "tool": name or "?",
                    "status": "running",
                    "args": None,
                    "result": None,
                    "error": None,
                    "ts": event.get("ts"),
                }
                items.append(match)
            else:
                open_tools.remove(match)
            if kind == "tool.failed":
                match["status"] = "fail"
                match["error"] = str(event.get("error") or "")
            else:
                match["status"] = "ok"
                match["result"] = event.get("result")
            ms = event.get("ms")
            match["ms"] = float(ms) if ms is not None else None
            match["finished_ts"] = event.get("ts")

    return items


def latest_intent(events: list[dict[str, Any]], call_id: str) -> str | None:
    """The most recent ``call.intent`` value for this call, or ``None``.

    No lane emits ``call.intent`` yet — this is the shape the conversation
    lane should log the moment it classifies what the caller wants:
    ``ctx.log.event("call.intent", intent="book")``. It is a running best
    guess, not final: a later event with a different value simply replaces it,
    same as any other call state that can change mid-conversation.
    """
    intent: str | None = None
    for event in events:
        if str(event.get("call_id") or "") != call_id:
            continue
        if event.get("kind") == "call.intent":
            value = str(event.get("intent") or "").strip()
            if value:
                intent = value
    return intent


def _call_events(events: list[dict[str, Any]], call_id: str) -> list[dict[str, Any]]:
    return [e for e in events if str(e.get("call_id") or "") == call_id]


def _actions(call_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every submit attempt this call made, in order — not just the last one.

    A single call can send two actions ("cancel mine and my son's"); a retry
    after a 409/422 also shows up here, so a jury can see the guard worked.
    """
    actions = []
    for event in call_events:
        if event.get("kind") == "submit.result":
            actions.append(
                {
                    "route": event.get("route"),
                    "payload": event.get("payload"),
                    "result": event.get("result"),
                    "ts": event.get("ts"),
                }
            )
    return actions


def _language_switches(call_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"was": event.get("was"), "now": event.get("now"), "ts": event.get("ts")}
        for event in call_events
        if event.get("kind") == "voice.language_switch"
    ]


def _ended_at(call_events: list[dict[str, Any]]) -> str | None:
    for event in reversed(call_events):
        if event.get("kind") in {"call.ended", "call.summary"}:
            return event.get("ts")
    return None


def call_summary(events: list[dict[str, Any]], call_id: str) -> dict[str, Any]:
    """Everything about the call itself, not the turn-by-turn feed.

    Built on top of ``view.build_call`` (the same source the NiceGUI ``/wall``
    and ``/ops`` pages use) so the two never disagree, plus the fields that
    dataclass never tracked: every submit attempt (not just the last),
    language switches, and how many times the caller went quiet.
    """
    call_events = _call_events(events, call_id)
    card = build_call(call_id, call_events)
    data = asdict(card)
    data.pop("turns", None)
    data.pop("tools", None)
    data["status"] = card.status
    data["live"] = card.live
    data["ended_at"] = _ended_at(call_events)
    data["actions"] = _actions(call_events)
    languages = _language_switches(call_events)
    data["language_history"] = languages
    data["language"] = languages[-1]["now"] if languages else None
    data["idle_count"] = sum(1 for e in call_events if e.get("kind") == "voice.user_idle")
    return data
