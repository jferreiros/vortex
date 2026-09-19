"""Per-call JSONL log. One line per event, every line tagged with ``call_id``.

The file is append-only and shared by all calls in the process. A reader that
groups lines by ``call_id`` gets the whole story of a call: the handshake, each
turn, each tool call with its typed result, each submission, and a final
``call.summary`` line that rolls it all up. This is what the live view reads.

Event kinds written by the base:

- ``call.started``     stream_sid, from_number, voice mode, clinic mode
- ``turn.user``        text
- ``turn.assistant``   text
- ``tool.called``      tool, args
- ``tool.returned``    tool, result, ms
- ``tool.failed``      tool, error
- ``submit.sent``      route, payload
- ``submit.result``    status, http_status, detail
- ``submit.fallback``  branch, why, route, skipped (the end-of-call fallback)
- ``call.ended``       reason, media_frames_in, media_frames_out
- ``call.summary``     turns, tools, actions, duration_ms

Lanes may add their own kinds. Keep the payload JSON-safe and small.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()

#: How many of the caller's own turns ``CallLog.said`` keeps. A three-minute
#: call runs to about twenty of them, and what a tool needs from the transcript
#: is what was asked for, which is said early and repeated when it is not heard.
CALLER_WORDS_KEPT = 24


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class CallLog:
    """Writer bound to one ``call_id``. Cheap to create; never shared across calls."""

    def __init__(self, call_id: str, path: Path):
        self.call_id = call_id
        self.path = path
        self._started = time.monotonic()
        self.turns = 0
        # Turns the caller took. The end-of-call fallback reads it to tell a
        # call that said nothing from one that talked and resolved nothing.
        self.user_turns = 0
        # What the caller themselves said, most recent last, capped at
        # ``CALLER_WORDS_KEPT``. A tool that must not depend on the model's
        # summary of a turn reads this instead: ``triage`` takes the specialty
        # out of it when the model paraphrased it away. Per call, never shared.
        self.said: deque[str] = deque(maxlen=CALLER_WORDS_KEPT)
        self.tool_calls = 0
        self.actions: list[dict[str, Any]] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **data: Any) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "call_id": self.call_id,
            "kind": kind,
            **data,
        }
        text = json.dumps(line, default=_json_default, ensure_ascii=False)
        with _WRITE_LOCK, self.path.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    # Convenience wrappers so lanes log the same shape.

    def user_turn(self, text: str) -> None:
        self.turns += 1
        self.user_turns += 1
        self.said.append(text)
        self.event("turn.user", text=text)

    def caller_words(self) -> str:
        """The caller's own recent turns, oldest first, as one string to match on."""
        return " ".join(self.said)

    def assistant_turn(self, text: str) -> None:
        self.turns += 1
        self.event("turn.assistant", text=text)

    def tool_called(self, tool: str, args: Any) -> None:
        self.tool_calls += 1
        self.event("tool.called", tool=tool, args=args)

    def tool_returned(self, tool: str, result: Any, ms: float) -> None:
        self.event("tool.returned", tool=tool, result=result, ms=round(ms, 1))

    def tool_failed(self, tool: str, error: str) -> None:
        self.event("tool.failed", tool=tool, error=error)

    def action_submitted(self, route: str, payload: dict[str, Any], result: Any) -> None:
        self.actions.append({"route": route, "payload": payload, "result": result})
        self.event("submit.result", route=route, payload=payload, result=result)

    def summary(self, **extra: Any) -> None:
        self.event(
            "call.summary",
            turns=self.turns,
            tools=self.tool_calls,
            actions=self.actions,
            duration_ms=round((time.monotonic() - self._started) * 1000),
            **extra,
        )


def read_recent(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    """The last ``limit`` events, oldest first. For /calls and the live view."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()[-limit:]
    out: list[dict[str, Any]] = []
    for raw in lines:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def group_by_call(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        grouped.setdefault(ev.get("call_id", "?"), []).append(ev)
    return grouped
