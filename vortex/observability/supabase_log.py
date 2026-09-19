"""Supabase store for the call event log.

The JSONL file stays the local fallback. When ``SUPABASE_URL`` and
``SUPABASE_SERVICE_ROLE_KEY`` are set, every ``CallLog.event`` is also
queued here, and ``read_calls`` / ``read_recent`` prefer this table so the
board keeps working on a machine that has never served a call.

Never raises into a call: a dropped insert is a missing row, not a hung
socket. The service-role key is server-only — it is never sent to the
browser and never appears in ``/health``.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import queue
import threading
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger("vortex.observability.supabase")

FLUSH_EVERY = 50
FLUSH_TIMEOUT_S = 0.4
HTTP_TIMEOUT_S = 30.0
PAGE_SIZE = 1000

_queue: queue.Queue[dict[str, Any]] = queue.Queue()
_worker_started = False
_lock = threading.Lock()


def configured() -> bool:
    settings = _settings()
    return bool(settings.supabase_url and settings.supabase_service_role_key)


def event_hash(event: dict[str, Any]) -> str:
    """Stable identity for one log line, whatever key order it was written in."""
    return hashlib.sha256(
        json.dumps(event, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _settings() -> Any:
    from vortex.settings import get_settings

    return get_settings()


def _headers() -> dict[str, str]:
    settings = _settings()
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }


def _rest(path: str) -> str:
    return f"{_settings().supabase_url.rstrip('/')}{path}"


def _row(event: dict[str, Any]) -> dict[str, Any] | None:
    ts = event.get("ts")
    if not ts:
        return None
    return {
        "event_hash": event_hash(event),
        "ts": str(ts),
        "call_id": str(event.get("call_id") or ""),
        "kind": str(event.get("kind") or ""),
        "event": event,
    }


def ping() -> dict[str, Any]:
    """Reachability check used by ``/health`` and ``make supabase-ping``."""
    if not configured():
        return {"ok": False, "detail": "not configured"}
    try:
        response = httpx.get(
            _rest("/rest/v1/call_events"),
            params={"select": "id", "limit": "1"},
            headers=_headers(),
            timeout=8.0,
        )
        if response.status_code == 200:
            return {"ok": True, "detail": "reachable"}
        return {"ok": False, "detail": f"HTTP {response.status_code}: {response.text[:160]}"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}


def upsert_events(events: list[dict[str, Any]]) -> int:
    """Insert ``events``, skipping hashes already stored. Returns how many
    rows the request accepted (including ignored duplicates as 0 extra)."""
    rows = [row for event in events if (row := _row(event)) is not None]
    if not rows or not configured():
        return 0
    response = httpx.post(
        _rest("/rest/v1/call_events"),
        params={"on_conflict": "event_hash"},
        headers={
            **_headers(),
            "Prefer": "resolution=ignore-duplicates,return=minimal",
        },
        json=rows,
        timeout=HTTP_TIMEOUT_S,
    )
    if response.status_code not in {200, 201, 204}:
        raise RuntimeError(f"upsert {response.status_code}: {response.text[:240]}")
    return len(rows)


def fetch_recent(limit: int) -> list[dict[str, Any]] | None:
    """The last ``limit`` events, oldest first, or ``None`` if unused/failed."""
    if not configured() or limit <= 0:
        return None
    try:
        response = httpx.get(
            _rest("/rest/v1/call_events"),
            params={
                "select": "event",
                "order": "ts.desc,id.desc",
                "limit": str(limit),
            },
            headers=_headers(),
            timeout=HTTP_TIMEOUT_S,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            return None
        events = [row["event"] for row in reversed(rows) if isinstance(row.get("event"), dict)]
        return events or None
    except Exception:
        log.exception("supabase fetch_recent failed")
        return None


def fetch_window(
    *,
    max_calls: int | None = None,
    since: datetime | str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Events for the newest ``max_calls`` (or every call since ``since``)."""
    if not configured():
        return None
    payload: dict[str, Any] = {
        "p_max_calls": max_calls,
        "p_since": None,
    }
    if since is not None:
        stamp = datetime.fromisoformat(str(since)) if isinstance(since, str) else since
        if stamp.tzinfo is None:
            from datetime import UTC

            stamp = stamp.replace(tzinfo=UTC)
        payload["p_since"] = stamp.isoformat()
    try:
        response = httpx.post(
            _rest("/rest/v1/rpc/call_events_for_window"),
            headers=_headers(),
            json=payload,
            timeout=HTTP_TIMEOUT_S,
        )
        if response.status_code == 404:
            events = _fetch_all_paginated()
        else:
            response.raise_for_status()
            body = response.json()
            events = body if isinstance(body, list) else []
        if not events:
            return None
        from vortex.observability.calllog import group_by_call

        grouped = group_by_call([e for e in events if isinstance(e, dict)])
        return _complete_calls(grouped, max_calls=max_calls, since=since)
    except Exception:
        log.exception("supabase fetch_window failed")
        return None


def _complete_calls(
    grouped: dict[str, list[dict[str, Any]]],
    *,
    max_calls: int | None,
    since: datetime | str | None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Same completeness rule as ``calllog.read_calls``: keep only groups
    that have ``call.started``, honour ``since`` on that start, newest first."""
    from vortex.observability.calllog import _since_str

    started: dict[str, str] = {}
    for cid, events in grouped.items():
        for event in events:
            if event.get("kind") == "call.started" and event.get("ts"):
                started[cid] = str(event["ts"])
                break
    complete = [(cid, events) for cid, events in grouped.items() if cid in started]
    since_ts = _since_str(since) if since is not None else None
    if since_ts is not None:
        complete = [(cid, evs) for cid, evs in complete if started[cid] >= since_ts]
    complete.sort(key=lambda item: started[item[0]], reverse=True)
    if max_calls is not None:
        complete = complete[:max_calls]
    out: dict[str, list[dict[str, Any]]] = {}
    events_n = 0
    for cid, events in reversed(complete):
        out[cid] = sorted(events, key=lambda event: str(event.get("ts") or ""))
        events_n += len(events)
    return out, {"calls": len(out), "events": events_n, "truncated": False}


def _fetch_all_paginated() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = httpx.get(
            _rest("/rest/v1/call_events"),
            params={
                "select": "event",
                "order": "ts.asc,id.asc",
                "limit": str(PAGE_SIZE),
                "offset": str(offset),
            },
            headers=_headers(),
            timeout=HTTP_TIMEOUT_S,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            break
        events.extend(row["event"] for row in rows if isinstance(row.get("event"), dict))
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return events


def enqueue(event: dict[str, Any]) -> None:
    """Queue one event for a background upsert. No-op when unconfigured."""
    if not configured():
        return
    _ensure_worker()
    try:
        _queue.put_nowait(event)
    except Exception:
        log.exception("supabase enqueue failed")


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_run_worker, name="supabase-call-log", daemon=True)
        thread.start()
        atexit.register(flush)
        _worker_started = True


def _run_worker() -> None:
    batch: list[dict[str, Any]] = []
    while True:
        try:
            batch.append(_queue.get(timeout=FLUSH_TIMEOUT_S))
        except queue.Empty:
            if batch:
                _flush(batch)
                batch = []
            continue
        if len(batch) >= FLUSH_EVERY:
            _flush(batch)
            batch = []


def _flush(events: list[dict[str, Any]]) -> None:
    try:
        upsert_events(events)
    except Exception:
        log.exception("supabase flush of %s events failed", len(events))


def flush() -> None:
    """Drain the queue. Called at process exit and by the push script."""
    leftover: list[dict[str, Any]] = []
    while True:
        try:
            leftover.append(_queue.get_nowait())
        except queue.Empty:
            break
    if leftover:
        _flush(leftover)


def apply_schema() -> None:
    """Apply ``database/supabase/schema.sql`` via the SQL HTTP API.

    The Management SQL endpoint is not on every project; when it is missing
    the caller prints the file path so the statement can be pasted once.
    """
    sql = _schema_path().read_text(encoding="utf-8")
    settings = _settings()
    # PostgREST cannot run DDL. The pg endpoint on hosted Supabase:
    # POST https://<ref>.supabase.co/pg/query is not public. We try the
    # database REST anyway and treat anything other than 2xx as "paste it".
    response = httpx.post(
        f"{settings.supabase_url.rstrip('/')}/pg/query",
        headers=_headers(),
        json={"query": sql},
        timeout=HTTP_TIMEOUT_S,
    )
    if response.status_code not in {200, 201, 204}:
        raise RuntimeError(
            f"cannot apply schema automatically (HTTP {response.status_code}). "
            f"Paste database/supabase/schema.sql in the Supabase SQL editor."
        )


def _schema_path():
    from vortex.settings import REPO_ROOT

    return REPO_ROOT / "database" / "supabase" / "schema.sql"


def uses_this_log(path: Any) -> bool:
    """Whether ``path`` is the process's real call log, so a test tmp file
    never silently starts hitting the network."""
    if not configured():
        return False
    try:
        from pathlib import Path

        return Path(path).resolve() == _settings().calls_log_path.resolve()
    except Exception:
        return False
