"""Per-call event log. One row per event, every row tagged with ``call_id``.

Every event goes to Postgres (``public.call_events`` via PostgREST). There is
no file: a reader that groups rows by ``call_id`` gets the whole story of a
call — the handshake, each turn, each tool call with its typed result, each
submission, and a final ``call.summary`` row that rolls it all up. That is
what the live view reads.

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

Writes are batched by ``supabase_log``'s background worker. ``flush()`` runs
at hangup and blocks briefly so the last events of a call land before the
process forgets them.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("vortex.observability.calllog")

#: How many of the caller's own turns ``CallLog.said`` keeps. A three-minute
#: call runs to about twenty of them, and what a tool needs from the transcript
#: is what was asked for, which is said early and repeated when it is not heard.
CALLER_WORDS_KEPT = 24

#: Upper bound on how long a hangup may wait for the store. A call's last
#: events matter, but not more than answering the next socket.
FLUSH_TIMEOUT_S = 5.0


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_safe(line: dict[str, Any]) -> dict[str, Any]:
    """The row as Postgres will store it, so ``event_hash`` is stable."""
    return json.loads(json.dumps(line, default=_json_default, ensure_ascii=False))


class CallLog:
    """Writer bound to one ``call_id``. Cheap to create; never shared across calls."""

    def __init__(self, call_id: str, path: Any = None):
        # ``path`` is accepted and ignored: the JSONL file is gone and every
        # event goes to Postgres. The argument stays for one release so a
        # caller still passing a path keeps working.
        self.call_id = call_id
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
        #: This call's own events, in write order — so the product-database
        #: hook at hangup can persist the row without re-reading the store,
        #: and so ``flush`` can re-post the whole call idempotently.
        self.events: list[dict[str, Any]] = []

    def event(self, kind: str, **data: Any) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "call_id": self.call_id,
            "kind": kind,
            **data,
        }
        self.events.append(line)
        try:
            from vortex.observability.supabase_log import enqueue

            enqueue(_json_safe(line))
        except Exception:
            log.error("call %s: %s event not queued", self.call_id, kind, exc_info=True)

    def flush(self, timeout: float = FLUSH_TIMEOUT_S) -> None:
        """Land this call's events before the process forgets them.

        Called on hangup, after ``call.ended`` and the summary. Drains the
        shared batch queue, then re-posts this call's own events: the upsert is
        keyed on ``event_hash``, so a duplicate is a no-op and a row the worker
        lost is recovered. Bounded by ``timeout`` — a slow store must never
        hold a socket open past the submission window.

        This blocks on HTTP. An async caller runs it in a worker thread
        (``asyncio.to_thread``): twenty sockets stream audio on the same loop.
        """
        from vortex.observability import supabase_log

        if not supabase_log.configured():
            return
        deadline = time.monotonic() + timeout
        try:
            supabase_log.flush(timeout=timeout)
            left = max(0.5, deadline - time.monotonic())
            supabase_log.upsert_events([_json_safe(e) for e in self.events], timeout=left)
        except Exception:
            log.error(
                "call %s: %s events did not reach supabase",
                self.call_id,
                len(self.events),
                exc_info=True,
            )

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


def since_str(since: datetime | str) -> str:
    """Normalise to the exact format ``CallLog.event`` writes so a plain string
    compare orders timestamps correctly: UTC ISO-8601, millisecond precision."""
    stamp = datetime.fromisoformat(str(since)) if isinstance(since, str) else since
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).isoformat(timespec="milliseconds")


#: Kept under the old private name: ``supabase_log`` imported it that way.
_since_str = since_str


def group_by_call(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        grouped.setdefault(ev.get("call_id", "?"), []).append(ev)
    return grouped
