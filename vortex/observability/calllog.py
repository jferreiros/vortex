"""Per-call JSONL log. One line per event, every line tagged with ``call_id``.

The file is append-only and shared by all calls in the process. A reader that
groups lines by ``call_id`` gets the whole story of a call: the handshake, each
turn, each tool call with its typed result, each submission, and a final
``call.summary`` line that rolls it all up. This is what the live view reads.

Event kinds written by the base:

- ``call.started``     stream_sid, from_number, voice mode, clinic mode
- ``turn.user``        text
- ``turn.assistant``   text
- ``turn.metrics``     speaker, started_ts, ended_ts, words, ttfb_ms (agent only)
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
from collections.abc import Iterator
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
        # Turn-metric state: the ts of the last caller turn, and whether the
        # next agent turn is its reply. ``turn.metrics`` reads both so the
        # first answer after a caller turn carries a TTFB even when the
        # pipeline passes no timing of its own.
        self._last_user_ts: str | None = None
        self._awaiting_reply = False
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **data: Any) -> str:
        """Append one line. Returns the ``ts`` it was written with."""
        ts = datetime.now(UTC).isoformat(timespec="milliseconds")
        line = {
            "ts": ts,
            "call_id": self.call_id,
            "kind": kind,
            **data,
        }
        text = json.dumps(line, default=_json_default, ensure_ascii=False)
        with _WRITE_LOCK, self.path.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")
        return ts

    # Convenience wrappers so lanes log the same shape.

    def user_turn(
        self, text: str, *, started_ts: str | None = None, ended_ts: str | None = None
    ) -> None:
        self.turns += 1
        self.user_turns += 1
        self.said.append(text)
        ts = self.event("turn.user", text=text)
        self._last_user_ts = ts
        self._awaiting_reply = True
        self._turn_metrics("user", text, ts, started_ts=started_ts, ended_ts=ended_ts)

    def caller_words(self) -> str:
        """The caller's own recent turns, oldest first, as one string to match on."""
        return " ".join(self.said)

    def assistant_turn(
        self,
        text: str,
        *,
        started_ts: str | None = None,
        ended_ts: str | None = None,
        ttfb_ms: float | None = None,
    ) -> None:
        self.turns += 1
        ts = self.event("turn.assistant", text=text)
        if ttfb_ms is None and self._awaiting_reply and self._last_user_ts is not None:
            # First agent turn after a caller turn: the gap between the
            # transcript landing and the first spoken line is the best TTFB a
            # pipeline with no frame timing can report.
            ttfb_ms = round(
                (
                    datetime.fromisoformat(ts) - datetime.fromisoformat(self._last_user_ts)
                ).total_seconds()
                * 1000,
                1,
            )
        self._awaiting_reply = False
        self._turn_metrics(
            "assistant", text, ts, started_ts=started_ts, ended_ts=ended_ts, ttfb_ms=ttfb_ms
        )

    def _turn_metrics(
        self,
        speaker: str,
        text: str,
        ts: str,
        *,
        started_ts: str | None,
        ended_ts: str | None,
        ttfb_ms: float | None = None,
    ) -> None:
        """The per-turn analytics row, written right after its ``turn.*`` line.

        ``started_ts``/``ended_ts`` bound the turn in wall clock when the
        pipeline knows it (pipecat reads them off the frame stream); a lane
        that cannot time a turn leaves both at the turn's own ts. ``ttfb_ms``
        exists on agent turns only - it is None where no latency was seen.
        """
        payload: dict[str, Any] = {
            "speaker": speaker,
            "started_ts": started_ts or ts,
            "ended_ts": ended_ts or ts,
            "words": len(text.split()),
        }
        if speaker == "assistant":
            payload["ttfb_ms"] = ttfb_ms
        self.event("turn.metrics", **payload)

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


def _iter_lines_backwards(path: Path, chunk_size: int = 1 << 19) -> Iterator[str]:
    """Yield the file's lines newest-first without holding it all in memory.

    The log is append-only and chronological, so a reader that wants "the last
    N" or "everything since Tuesday" can stop as soon as it has enough instead
    of reading the whole file the way ``readlines()`` does.
    """
    with path.open("rb") as fh:
        fh.seek(0, 2)
        pos = fh.tell()
        tail = b""
        while pos > 0:
            step = min(chunk_size, pos)
            pos -= step
            fh.seek(pos)
            lines = (fh.read(step) + tail).split(b"\n")
            tail = lines[0]
            for raw in reversed(lines[1:]):
                if raw.strip():
                    yield raw.decode("utf-8", "replace")
        if tail.strip():
            yield tail.decode("utf-8", "replace")


def read_recent(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    """The last ``limit`` events, oldest first. For /calls and the live view."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in _iter_lines_backwards(path):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    out.reverse()
    return out


#: Bound on how far ``read_calls`` may scan before it has to stop anyway. The
#: log grows without rotation during a run; this keeps a degenerate request
#: (e.g. a ``since`` in the far past on a huge log) from parsing forever.
READ_CALLS_MAX_EVENTS = 100_000


def _since_str(since: datetime | str) -> str:
    """Normalise to the exact format ``CallLog.event`` writes so a plain string
    compare orders timestamps correctly: UTC ISO-8601, millisecond precision."""
    stamp = datetime.fromisoformat(str(since)) if isinstance(since, str) else since
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).isoformat(timespec="milliseconds")


def read_calls(
    path: Path,
    *,
    max_calls: int | None = None,
    since: datetime | str | None = None,
    max_events: int = READ_CALLS_MAX_EVENTS,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Complete calls from the log, grouped by ``call_id``, oldest call first.

    "Complete" means the ``call.started`` line was found: an event-tail read
    can cut a call mid-flight, and a card without ``started_at`` is silently
    dropped by the board's date filter — the exact failure that emptied
    Insights on the live deployment. Scanning backwards past the requested
    window until every call in it has its start is what fixes that.

    - ``max_calls`` caps the result to the most recent N complete calls.
    - ``since`` keeps only calls that started at or after that timestamp; the
      scan continues a little past the horizon so calls straddling it are
      still returned whole.
    - ``max_events`` is the safety bound; ``meta["truncated"]`` reports it.

    Returns ``(grouped, meta)`` where each group is chronological and meta
    carries event/call counts and the truncation flag.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    meta: dict[str, Any] = {"calls": 0, "events": 0, "truncated": False}
    if not path.exists():
        return grouped, meta

    since_ts = _since_str(since) if since is not None else None
    started: dict[str, str] = {}
    # No `since` means no horizon at all: the scan only stops at max_calls or
    # EOF, so an unbounded read returns every call in the file.
    past_horizon = False
    scanned = 0

    def _done() -> bool:
        # A group still missing its start blocks the stop only if it could be
        # in-window. The first event a backwards scan meets is a call's latest,
        # so a group seen solely through events older than `since` started
        # before `since` too — it will be filtered out, no need to trace it
        # back to its start.
        for cid, events in grouped.items():
            if cid in started:
                continue
            if since_ts is None:
                return False
            if any(str(e.get("ts") or "") >= since_ts for e in events):
                return False
        if max_calls is not None:
            in_window = (
                len(grouped)
                if since_ts is None
                else sum(1 for cid in grouped if started.get(cid, "") >= since_ts)
            )
            if in_window >= max_calls:
                return True
        return past_horizon

    for raw in _iter_lines_backwards(path):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        cid = str(event.get("call_id") or "?")
        grouped.setdefault(cid, []).append(event)
        if event.get("kind") == "call.started" and event.get("ts"):
            started[cid] = str(event["ts"])
        scanned += 1
        if scanned >= max_events:
            meta["truncated"] = True
            break
        ts = event.get("ts")
        if since_ts is not None and ts and str(ts) < since_ts:
            past_horizon = True
        if scanned % 64 == 0 and _done():
            break

    # Only calls with a known start leave this function. Newest first, capped.
    complete = [(cid, events) for cid, events in grouped.items() if cid in started]
    if since_ts is not None:
        complete = [(cid, evs) for cid, evs in complete if started[cid] >= since_ts]
    complete.sort(key=lambda item: started[item[0]], reverse=True)
    if max_calls is not None:
        complete = complete[:max_calls]

    out: dict[str, list[dict[str, Any]]] = {}
    for cid, events in reversed(complete):
        out[cid] = list(reversed(events))
        meta["events"] += len(events)
    meta["calls"] = len(out)
    return out, meta


def group_by_call(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        grouped.setdefault(ev.get("call_id", "?"), []).append(ev)
    return grouped
