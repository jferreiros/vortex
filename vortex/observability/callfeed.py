"""How the board reads call events — the single source of truth for
observability, kept in a leaf module so it can be imported without pulling in
NiceGUI pages.

There is one store: Postgres (``public.call_events``, read through PostgREST
by ``supabase_log``). Every screen reads it, so a board container that has
never served a call paints the same cards as the line that did. Windows are
bounded by *calls*, never by an arbitrary event tail: a tail cut can split a
call and drop its ``call.started``, and a card without ``started_at`` is
dropped by the board's date filter.

One degradation is kept: the last good fetch for a scope. A slow or dropped
request then shows slightly-stale real data instead of an empty board.

Every result carries a ``source`` dict (``store: "supabase"``, ``kind``:
``supabase`` | ``cache`` | ``empty``, plus the error that degraded it) so a
screen can say "degraded" instead of silently showing zeros.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

from vortex.observability.view import flatten_grouped

log = logging.getLogger("vortex.observability")

LINE_URL = os.environ.get("VORTEX_LINE_URL", "http://127.0.0.1:7860").rstrip("/")


def ttl_env(name: str, default: float) -> float:
    """A cache lifetime, overridable from the environment.

    Every read behind these caches is one hop to a hosted project that has
    spent this weekend stalling for tens of seconds at a time. The defaults
    are generous on purpose; raise them further for a demo, or drop them to
    0 to watch a change land immediately.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default


#: How many complete calls the wall and the per-call pages ask for. Counted
#: in calls, not events: the old ``limit=800`` tail was about ten calls on a
#: real log and could cut the oldest one's ``call.started``. Sized to hold a
#: whole busy day, since the Live list now shows every call that ended today.
WALL_CALLS = 160

#: One Insights fetch per this many seconds, no matter how many tabs poll.
#: The page itself only asks every 6 s. Aggregates over a 7-to-90-day window
#: do not move in a minute, and the read behind them is the expensive one.
INSIGHTS_CACHE_TTL_S = ttl_env("VORTEX_INSIGHTS_TTL_S", 60.0)

#: Last events successfully fetched per scope. Cleared only by a fresh
#: success; never written to disk.
_last_good: dict[str, list[dict[str, Any]]] = {}
_scope_cache: dict[str, tuple[float, list[dict[str, Any]], dict[str, Any] | None, dict]] = {}


def _source(scope: str, kind: str, events: list[dict[str, Any]], detail: str | None) -> dict:
    return {
        "kind": kind,
        "store": "supabase",
        "scope": scope,
        "detail": detail,
        "events": len(events),
        "calls": len({str(e.get("call_id") or "?") for e in events}),
    }


def load_events(
    scope: str = "recent",
    *,
    since: datetime | None = None,
    cache_ttl: float = 0.0,
    max_calls: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict]:
    """The events a screen draws, and where they came from.

    ``scope`` names the reader ("recent" for the wall, "insights:<days>" for
    the range pills) so the last-good and TTL caches never mix windows.

    ``max_calls`` caps a date-bounded read at the most recent N calls. The
    whole table is far more than any aggregate needs, and asking the hosted
    project for all of it exceeds its statement timeout.

    The middle element of the triple used to be the line's ``/health``. There
    is no line fetch left, so it is always ``None`` — callers already had to
    handle that, since every degraded path returned it.
    """
    if cache_ttl:
        cached = _scope_cache.get(scope)
        if cached and time.monotonic() - cached[0] < cache_ttl:
            return cached[1], cached[2], cached[3]

    bound = max_calls if since is not None else WALL_CALLS
    result: tuple[list[dict[str, Any]], dict[str, Any] | None, dict]
    try:
        from vortex.observability import supabase_log

        grouped, meta = supabase_log.fetch_calls(bound, since)
        events = flatten_grouped(grouped)
        unreachable = meta.get("unreachable")
        if events:
            _last_good[scope] = events
            result = (events, None, _source(scope, "supabase", events, None))
        elif unreachable:
            # The store never answered. Say so: "error" and "empty" look the
            # same on a page of zeros, and only one of them means the clinic
            # was quiet.
            stale = _last_good.get(scope, [])
            kind = "cache" if stale else "error"
            result = (stale, None, _source(scope, kind, stale, unreachable))
        elif scope in _last_good:
            stale = _last_good[scope]
            result = (stale, None, _source(scope, "cache", stale, "store returned no calls"))
        else:
            result = (events, None, _source(scope, "empty", events, None))
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:200]
        log.warning("supabase %s fetch failed (%s); degrading", scope, detail)
        stale = _last_good.get(scope, [])
        result = (stale, None, _source(scope, "cache" if stale else "error", stale, detail))

    # Never cache a read that failed. A TTL is a promise that the answer is
    # good for that long; caching an outage makes one bad second last the
    # whole window, and the next caller — who might have got through — is
    # handed the failure instead of trying.
    if cache_ttl and result[2].get("kind") != "error":
        _scope_cache[scope] = (time.monotonic(), *result)
    return result
