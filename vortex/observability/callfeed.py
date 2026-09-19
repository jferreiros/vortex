"""How the board reads call events — the single source of truth for
observability, kept in a leaf module so it can be imported without pulling in
NiceGUI pages.

Order of sources:

1. ``GET {VORTEX_LINE_URL}/calls`` — the line's own API. Bounded by *calls*
   (``calls=60`` for the wall) or by start date (``since=<ISO>`` for the
   Insights window), never by an arbitrary event tail: a tail cut can split a
   call and drop its ``call.started``, which is what emptied Insights on the
   live deployment while the log itself was healthy.
2. The last good fetch for that scope — one slow or dropped request degrades
   to slightly-stale real data instead of an empty board.
3. The local JSONL at ``calls_log_path``. In production that path is the
   line's own volume mounted into the board (see deploy/compose.yml); locally
   it is the file ``make run`` writes. Either way the fallback reads real
   events, and the returned ``source`` block says which kind served.

Every result carries a ``source`` dict (``line_api`` | ``cache`` |
``jsonl_fallback``, plus the error that degraded it) so a screen can say
"degraded" instead of silently showing zeros.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from vortex.observability.calllog import read_calls
from vortex.observability.view import flatten_grouped

log = logging.getLogger("vortex.observability")

LINE_URL = os.environ.get("VORTEX_LINE_URL", "http://127.0.0.1:7860").rstrip("/")

#: Deliberately generous. The line server answers /health and /calls from the
#: same event loop that streams live call audio, so under real load (a "Run
#: All" holding ten to twenty sockets open) a fetch that used to time out at
#: 0.35 s / 0.5 s failed constantly and silently fell back to the board's own,
#: always-empty log — every Insights panel read as "no data" during exactly
#: the calls that mattered. The insights timeout is longer still: a 90-day
#: window can be a few MB of events, and a slow-but-correct answer beats an
#: empty one. All three are configurable so a deploy can tune them without a
#: rebuild.
LINE_HEALTH_TIMEOUT_S = float(os.environ.get("VORTEX_LINE_HEALTH_TIMEOUT_S", "3"))
LINE_CALLS_TIMEOUT_S = float(os.environ.get("VORTEX_LINE_CALLS_TIMEOUT_S", "6"))
LINE_INSIGHTS_TIMEOUT_S = float(os.environ.get("VORTEX_LINE_INSIGHTS_TIMEOUT_S", "25"))

#: How many complete calls the wall and the per-call pages ask the line for.
#: Counted in calls, not events: the old ``limit=800`` tail was about ten
#: calls on the real log and could cut the oldest one's ``call.started``.
WALL_CALLS = 60

#: One Insights fetch per this many seconds, no matter how many tabs poll.
#: The page itself only asks every 6 s.
INSIGHTS_CACHE_TTL_S = 4.0

#: Last events successfully fetched from the line per scope. Cleared only by
#: a fresh success; never written to disk.
_last_good: dict[str, tuple[list[dict[str, Any]], dict[str, Any] | None]] = {}
_scope_cache: dict[str, tuple[float, list[dict[str, Any]], dict[str, Any] | None, dict]] = {}


def _source(scope: str, kind: str, events: list[dict[str, Any]], detail: str | None) -> dict:
    return {
        "kind": kind,
        "scope": scope,
        "detail": detail,
        "events": len(events),
        "calls": len({str(e.get("call_id") or "?") for e in events}),
    }


def load_events(
    scope: str = "recent",
    log_path: Path | None = None,
    *,
    since: datetime | None = None,
    cache_ttl: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict]:
    """The events a screen draws, and where they came from.

    ``scope`` names the reader ("recent" for the wall, "insights:<days>" for
    the range pills) so the last-good and TTL caches never mix windows.
    """
    if cache_ttl:
        cached = _scope_cache.get(scope)
        if cached and time.monotonic() - cached[0] < cache_ttl:
            return cached[1], cached[2], cached[3]

    params: dict[str, Any] = {"calls": WALL_CALLS}
    timeout = LINE_CALLS_TIMEOUT_S
    if since is not None:
        params = {"since": since.isoformat()}
        timeout = LINE_INSIGHTS_TIMEOUT_S

    result: tuple[list[dict[str, Any]], dict[str, Any] | None, dict]
    try:
        health = httpx.get(f"{LINE_URL}/health", timeout=LINE_HEALTH_TIMEOUT_S).json()
        grouped = (
            httpx.get(f"{LINE_URL}/calls", params=params, timeout=timeout).json().get("calls", {})
        )
        if not isinstance(grouped, dict):
            raise ValueError("/calls answered with no 'calls' object")
        events = flatten_grouped(grouped)
        _last_good[scope] = (events, health)
        result = (events, health, _source(scope, "line_api", events, None))
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:200]
        log.warning("line %s fetch failed (%s); degrading", scope, detail)
        if scope in _last_good:
            events, health = _last_good[scope]
            result = (events, health, _source(scope, "cache", events, detail))
        else:
            grouped = {}
            if log_path is not None:
                grouped, _meta = (
                    read_calls(log_path, since=since)
                    if since is not None
                    else read_calls(log_path, max_calls=WALL_CALLS)
                )
            events = flatten_grouped(grouped)
            result = (events, None, _source(scope, "jsonl_fallback", events, detail))

    if cache_ttl:
        _scope_cache[scope] = (time.monotonic(), *result)
    return result
