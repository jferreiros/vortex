"""``/api/wall`` aggregate routes: Insights, Analytics, Home and occupancy.

All four read the same date-bounded call feed and differ only in what they
fold it into. The Analytics pack is the most expensive read on the board, so
it keeps a stale-while-revalidate cache per window and a start-up warm-up
(``start_analytics_warmup``, registered by the board's ``main``).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from vortex.api import _shared
from vortex.observability import analytics as analytics_pack_module
from vortex.observability import callfeed, langfuse_metrics
from vortex.observability.business_insights import business_insights, is_real_call
from vortex.observability.home_overview import WINDOW_DAYS as HOME_WINDOW_DAYS
from vortex.observability.home_overview import home_overview
from vortex.observability.home_pack import occupancy
from vortex.observability.view import CallCard, build_calls

log = logging.getLogger("vortex.api")
router = APIRouter()


@router.get("/business-insights")
def wall_business_insights_api(days: int = 30) -> JSONResponse:
    """Unavailability reasons, doctor ranking, the demand/supply heatmap and
    cancellation recovery for the Insights page's "7 / 30 / 90 días" pills.
    ``days`` is one of those three; anything else is clamped to the nearest.
    """
    days = min((7, 30, 90), key=lambda d: abs(d - days))
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    # Every call started inside the window — a fetch bounded by date, so a
    # busy day's worth of events can never push an in-range call out of the
    # read the way an event tail would.
    events, _health, source = _shared.load_events(
        f"insights:{days}", since=cutoff, cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S
    )
    cards = build_calls(events)
    in_range = [c for c in cards if (started := _shared.card_started(c)) and started >= cutoff]
    # Same roster the Agenda page shows, not one rebuilt per window: a
    # provider is a lasting fact about the clinic, so a doctor the log saw
    # outside this "days" cut still belongs on it. Without this, a specialty
    # the offline fixtures never modelled at all (there is no gynaecologist
    # in vortex/clinic/fixtures.py) reads as "0 médicos" while its real,
    # log-sourced demand still shows a non-zero occupancy.
    payload = business_insights(in_range, now=now, catalogue=_shared.agenda_catalogue())
    payload["range_days"] = days
    payload["source"] = source
    return JSONResponse(payload)


#: The Analytics pack needs every event in the window, and the hosted log
#: serves those in pages of a thousand. callfeed's own 4-second TTL is tuned
#: for the live cards, where a read is one request — here it expires before
#: the read finishes, so every poll starts another full fetch and they queue.
#: Two minutes is well inside how fast these aggregates move.
ANALYTICS_CACHE_TTL_S = 120.0
ANALYTICS_WINDOWS = (7, 30, 90)
#: How many calls one build reads. Bounded on purpose: the whole log is
#: ~32k events and 13 MB, which the hosted project cannot aggregate inside
#: its statement timeout. 250 calls is one request, a few seconds, and far
#: more than any percentile on this page needs. The page says the number
#: out loud.
ANALYTICS_MAX_CALLS = 250
_analytics_cache: dict[int, tuple[float, dict[str, Any]]] = {}
#: One lock per window rather than one lock for all of them — a slow 90-day
#: build must not stall a 7-day request. Also what a cold-path request and
#: the start-up warm-up serialize on, so the two never both pay for the same
#: window's read at once.
_analytics_locks: dict[int, threading.Lock] = {days: threading.Lock() for days in ANALYTICS_WINDOWS}
#: Windows with a background refresh already in flight, so five tabs polling
#: a stale window kick off one rebuild, not five.
_analytics_refreshing: set[int] = set()
_analytics_refreshing_lock = threading.Lock()


@router.get("/analytics")
def wall_analytics_api(days: int = 30) -> JSONResponse:
    """The Analytics page: the call funnel, latency, conversation shape,
    tool and model usage, and the call table under them.

    Same window pills and the same date-bounded read as
    ``/api/wall/business-insights``, so both pages describe the same calls.
    Langfuse is asked separately and is allowed to be absent — it is the
    only source here we do not own, and the page drops its two panels
    rather than block on it.

    Stale-while-revalidate past the cache's TTL: an old payload still
    answers instantly while a background thread rebuilds it, so only the
    very first request for a window (before start-up warm-up lands) ever
    waits on the full read.
    """
    days = min(ANALYTICS_WINDOWS, key=lambda d: abs(d - days))
    hit = _analytics_cache.get(days)
    if hit and time.monotonic() - hit[0] < ANALYTICS_CACHE_TTL_S:
        return JSONResponse(hit[1])
    if hit:
        _start_analytics_refresh(days)
        return JSONResponse(hit[1])
    # No payload at all yet for this window. The per-window lock means three
    # tabs opened at once start one full read, not three — and a request that
    # lands mid-warm-up just waits for that build instead of starting another.
    with _analytics_locks[days]:
        hit = _analytics_cache.get(days)
        if hit is None:
            payload = _build_analytics(days)
            _analytics_cache[days] = (time.monotonic(), payload)
            hit = _analytics_cache[days]
    return JSONResponse(hit[1])


def _start_analytics_refresh(days: int) -> None:
    with _analytics_refreshing_lock:
        if days in _analytics_refreshing:
            return
        _analytics_refreshing.add(days)
    threading.Thread(
        target=_refresh_analytics_cache, args=(days,), name=f"analytics-refresh-{days}", daemon=True
    ).start()


def _refresh_analytics_cache(days: int) -> None:
    try:
        with _analytics_locks[days]:
            payload = _build_analytics(days)
            _analytics_cache[days] = (time.monotonic(), payload)
    except Exception:
        log.exception("background analytics refresh failed for days=%s", days)
    finally:
        with _analytics_refreshing_lock:
            _analytics_refreshing.discard(days)


def _warm_analytics_cache() -> None:
    """Pay the cold-cache read once, at start-up, off the request path.

    Runs after the board starts serving (registered via ``app.on_startup``),
    so a slow Supabase read never delays start-up itself — the first visitor
    before it finishes just pays the cold read once.
    """
    for days in (30, 7, 90):  # 30 first: the page's default range.
        try:
            with _analytics_locks[days]:
                if days not in _analytics_cache:
                    payload = _build_analytics(days)
                    _analytics_cache[days] = (time.monotonic(), payload)
        except Exception:
            log.exception("analytics warm-up failed for days=%s", days)


def start_analytics_warmup() -> None:
    threading.Thread(target=_warm_analytics_cache, name="analytics-warmup", daemon=True).start()


def _build_analytics(days: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    events, _health, source = _shared.load_events(
        f"analytics:{days}",
        since=cutoff,
        cache_ttl=ANALYTICS_CACHE_TTL_S,
        max_calls=ANALYTICS_MAX_CALLS,
    )
    cards = build_calls(events)
    in_range = [c for c in cards if (started := _shared.card_started(c)) and started >= cutoff]
    payload = analytics_pack_module.analytics_pack(
        in_range,
        days=days,
        now=now,
        langfuse=langfuse_metrics.metrics(days),
    )
    payload["source"] = source
    return payload


def _home_cards() -> tuple[list[CallCard], dict]:
    """The real calls of the last ``HOME_WINDOW_DAYS`` days, and their source.

    Bounded by start date rather than by an event tail for the same reason
    the Insights fetch is: a tail cut can split a call and drop its
    ``call.started``. ``is_real_call`` then removes the eval probes and
    scripted demo calls that share this feed.

    Not cached for the life of the process: ``home_overview`` buckets against
    a live clock, so cards fixed at start-up would report a stale "today"
    from the moment the day rolled over.
    """
    cutoff = datetime.now(UTC) - timedelta(days=HOME_WINDOW_DAYS)
    events, _health, source = _shared.load_events(
        f"home:{HOME_WINDOW_DAYS}", since=cutoff, cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S
    )
    return [c for c in build_calls(events) if is_real_call(c)], source


@router.get("/home-overview")
def wall_home_overview_api() -> JSONResponse:
    """Today's diary activity for the Home page, off the call feed.

    ``source`` rides along so a page of zeros can be told apart from a feed
    that degraded to stale or empty data.
    """
    cards, source = _home_cards()
    payload = home_overview(cards, now=datetime.now(UTC))
    payload["source"] = source
    return JSONResponse(payload)


@router.get("/occupancy")
def wall_occupancy_api(site: str = "", specialty: str = "") -> JSONResponse:
    """Occupancy calendar for the Home page's site/specialty filters — read
    straight off ``wall-cache/occupancy.json``, precomputed at start-up."""
    return JSONResponse(occupancy(site=site, specialty=specialty))
