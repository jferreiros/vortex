"""Aggregate latency read back from Langfuse, for the Analytics page.

``tracing.py`` writes traces; this module is the only thing that reads them.
It asks the public Metrics API for percentiles grouped by observation name,
which answers the two questions our own log cannot:

- how long the model itself takes to answer (``generate-response``), apart
  from the speech in front of it and the network behind it;
- how long each tool takes inside the clinic API (``find-slots``,
  ``check-eligibility``, ...), measured at the call site rather than guessed
  from the event log's own timestamps.

**No per-call join.** The ``call_id`` that reaches Langfuse is pseudonymised
with an HMAC key generated in memory at import and never written down (see
``tracing.py``), and the log keeps no ``trace_id``. So one Langfuse row can
never be tied back to one row of ours. Everything here is therefore an
aggregate over the window, presented as its own panel, and never mixed into
a per-call number the page would otherwise imply is exact.

Missing keys, a slow endpoint or a changed payload all return ``None``: the
page drops the Langfuse panels and keeps every number it owns.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

log = logging.getLogger("vortex.observability.langfuse_metrics")

HTTP_TIMEOUT_S = 12.0
CACHE_TTL_S = 120.0
ROW_LIMIT = 100

#: The trace that wraps one whole call — see ``tracing.trace_call``.
CALL_OBSERVATION = "handle-inbound-call"
#: One LLM answer — see ``tracing.GENERATION_NAME``.
GENERATION_OBSERVATION = "generate-response"
#: Named here so the page can keep them out of the "tools" table: they are
#: our own plumbing, not a clinic API call.
NON_TOOL_OBSERVATIONS = frozenset(
    {CALL_OBSERVATION, GENERATION_OBSERVATION, "submit-fallback", "submit-action"}
)

_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_lock = threading.Lock()


def _settings() -> Any:
    from vortex.settings import get_settings

    return get_settings()


def configured() -> bool:
    settings = _settings()
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def _auth_header() -> str:
    settings = _settings()
    pair = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}"
    return "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii")


def _query(since: datetime, until: datetime) -> str:
    """Percentiles and a count per observation name, over the window.

    ``latency`` comes back in milliseconds for every observation type.
    """
    return json.dumps(
        {
            "view": "observations",
            "metrics": [
                {"measure": "latency", "aggregation": "p50"},
                {"measure": "latency", "aggregation": "p95"},
                {"measure": "count", "aggregation": "count"},
            ],
            "dimensions": [{"field": "name"}],
            "filters": [],
            "fromTimestamp": since.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "toTimestamp": until.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "config": {"row_limit": ROW_LIMIT},
        }
    )


def _number(value: Any) -> float | None:
    """Langfuse returns counts as strings and a missing percentile as null."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    rows = []
    for row in data:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        count = _number(row.get("count_count"))
        if not name or not count:
            continue
        rows.append(
            {
                "name": name,
                "count": int(count),
                "p50_ms": _number(row.get("p50_latency")),
                "p95_ms": _number(row.get("p95_latency")),
            }
        )
    return rows


def _fetch(days: int) -> dict[str, Any] | None:
    if not configured():
        return None
    settings = _settings()
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    try:
        response = httpx.get(
            f"{settings.langfuse_base_url.rstrip('/')}/api/public/v2/metrics",
            params={"query": _query(since, until)},
            headers={"Authorization": _auth_header()},
            timeout=HTTP_TIMEOUT_S,
        )
        response.raise_for_status()
        rows = _rows(response.json())
    except Exception as exc:  # network, auth, shape — all the same to the page
        log.warning("langfuse metrics unavailable: %s", exc)
        return None
    if not rows:
        return None

    by_name = {row["name"]: row for row in rows}
    tools = sorted(
        (row for row in rows if row["name"] not in NON_TOOL_OBSERVATIONS),
        key=lambda row: row["count"],
        reverse=True,
    )
    return {
        "generation": by_name.get(GENERATION_OBSERVATION),
        "call": by_name.get(CALL_OBSERVATION),
        "tools": tools,
        "observations": sum(row["count"] for row in rows),
        # Not a Settings field: the project URL is a deep link for the
        # page's footer, read straight from the environment the same way
        # langfuse_status.py's constant does.
        "project_url": os.environ.get("LANGFUSE_PROJECT_URL", "").strip(),
        "environment": settings.langfuse_environment or "",
    }


def metrics(days: int) -> dict[str, Any] | None:
    """Cached for ``CACHE_TTL_S``: the page polls, Langfuse is rate limited
    and these percentiles move slowly. A failed fetch is cached too, so a
    dead endpoint costs one request every two minutes, not one per render."""
    key = f"days:{days}"
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    try:
        value = _fetch(days)
    except Exception:  # a shape or config surprise must cost two panels, not the page
        log.exception("langfuse metrics failed")
        value = None
    with _lock:
        _cache[key] = (now, value)
    return value
