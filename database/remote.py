"""The PostgREST client every other module in this package goes through.

Reads ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` from the
environment — this package does not import ``vortex``, so tests, the line and
the board can all use it. There is no second store behind it and no local
fallback: when ``enabled()`` is false there is simply nowhere to read or
write, and ``database/db.py`` turns that into empty reads and a loud
``RuntimeError`` on a write.

The service-role key is server-side only. It is never handed to a browser:
the wall reaches these tables through the board's own ``/api/wall`` routes.

Reads (``select``, ``count``) swallow failures and return ``None`` — a
missing panel is better than a crashed board. Writes (``upsert``, ``update``,
``delete``) raise; ``safe_upsert`` is the one that does not, for call
telemetry that must never take a call down with it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("database.remote")

TIMEOUT_S = 20.0


def _secret_key() -> str:
    return (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    )


def enabled() -> bool:
    """Whether there is a store to talk to at all. Every public function
    here is a no-op when this is false."""
    return bool(os.environ.get("SUPABASE_URL", "").strip() and _secret_key())


def _headers(**extra: str) -> dict[str, str]:
    key = _secret_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        **extra,
    }


def _rest(path: str) -> str:
    return f"{os.environ['SUPABASE_URL'].strip().rstrip('/')}{path}"


def _rows(response: httpx.Response) -> list[dict[str, Any]]:
    if not response.content:
        return []
    body = response.json()
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    return [body] if isinstance(body, dict) else []


def select(table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]] | None:
    """A GET. ``None`` when Supabase is off or the request failed — never an
    exception, so a read can never be what ends a call or a page render."""
    if not enabled():
        return None
    try:
        response = httpx.get(
            _rest(f"/rest/v1/{table}"),
            params=params or {},
            headers=_headers(),
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        rows = response.json()
        return rows if isinstance(rows, list) else None
    except Exception:
        log.exception("supabase select %s failed", table)
        return None


def upsert(
    table: str, rows: list[dict[str, Any]], on_conflict: str | None = None
) -> list[dict[str, Any]]:
    """A POST. With ``on_conflict`` it merges duplicates on that key (or key
    tuple, comma-separated); without one it is a plain insert, which is what
    an identity primary key wants — you cannot name a column you are not
    sending. Returns the rows as the database now holds them, so a caller
    can read back a generated ``id`` or a defaulted column."""
    if not rows or not enabled():
        return []
    params = {"on_conflict": on_conflict} if on_conflict else {}
    prefer = "return=representation"
    if on_conflict:
        prefer = f"resolution=merge-duplicates,{prefer}"
    response = httpx.post(
        _rest(f"/rest/v1/{table}"),
        params=params,
        headers=_headers(Prefer=prefer),
        json=[dict(row) for row in rows],
        timeout=TIMEOUT_S,
    )
    if response.status_code not in {200, 201, 204}:
        raise RuntimeError(f"{table} upsert {response.status_code}: {response.text[:240]}")
    return _rows(response)


def safe_upsert(table: str, rows: list[dict[str, Any]], on_conflict: str | None = None) -> None:
    """``upsert`` that logs instead of raising — for telemetry writes where a
    missing remote row is a smaller problem than a failed call."""
    try:
        upsert(table, rows, on_conflict)
    except Exception:
        log.exception("supabase upsert %s failed", table)


def update(table: str, params: dict[str, str], values: dict[str, Any]) -> list[dict[str, Any]]:
    """A PATCH over every row ``params`` selects. Returns what was changed —
    an empty list means nothing matched, which is how the callers tell
    "already cancelled" from "cancelled just now"."""
    if not enabled():
        return []
    response = httpx.patch(
        _rest(f"/rest/v1/{table}"),
        params=params,
        headers=_headers(Prefer="return=representation"),
        json=dict(values),
        timeout=TIMEOUT_S,
    )
    if response.status_code not in {200, 204}:
        raise RuntimeError(f"{table} update {response.status_code}: {response.text[:240]}")
    return _rows(response)


def delete(table: str, params: dict[str, str]) -> int:
    """A DELETE over every row ``params`` selects. Returns how many went.

    PostgREST refuses an unfiltered DELETE, and so does this: an empty
    ``params`` would mean "the whole table", which is never what a caller in
    this codebase means.
    """
    if not enabled():
        return 0
    if not params:
        raise ValueError(f"refusing to delete every row of {table}: pass a filter")
    response = httpx.delete(
        _rest(f"/rest/v1/{table}"),
        params=params,
        headers=_headers(Prefer="return=representation"),
        timeout=TIMEOUT_S,
    )
    if response.status_code not in {200, 204}:
        raise RuntimeError(f"{table} delete {response.status_code}: {response.text[:240]}")
    return len(_rows(response))


def count(table: str) -> int | None:
    """Exact row count via ``Prefer: count=exact``, or ``None`` on failure."""
    if not enabled():
        return None
    try:
        response = httpx.get(
            _rest(f"/rest/v1/{table}"),
            params={"select": "*", "limit": "1"},
            headers=_headers(Prefer="count=exact"),
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        cr = response.headers.get("content-range") or ""
        if "/" in cr:
            return int(cr.rsplit("/", 1)[1])
        body = response.json()
        return len(body) if isinstance(body, list) else None
    except Exception:
        log.exception("supabase count %s failed", table)
        return None
