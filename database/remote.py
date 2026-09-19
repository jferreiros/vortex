"""PostgREST client for the product tables on Supabase.

Reads ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` from the
environment — this package does not import ``vortex``, so tests and the
line can both use it. A missing key is a no-op: SQLite stays the store.

Never raises into a caller. A failed upsert is a missing remote row, not a
failed booking.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
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
    return bool(os.environ.get("SUPABASE_URL", "").strip() and _secret_key())


# Same default as vortex.settings.product_db_path — cwd would miss the
# live file when the board is launched from anywhere other than the repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def product_db_path() -> Path:
    raw = os.environ.get("VORTEX_PRODUCT_DB", "").strip()
    if raw:
        return Path(raw).resolve()
    return (_REPO_ROOT / "logs" / "vortex_product.db").resolve()


def mirrors_product(conn: sqlite3.Connection) -> bool:
    """Whether this connection is the live product file — never a test tmp."""
    if not enabled():
        return False
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
    except sqlite3.Error:
        return False
    file = ""
    if row is not None:
        file = row["file"] if isinstance(row, sqlite3.Row) else row[2]
    if not file:
        return False
    try:
        return Path(file).resolve() == product_db_path()
    except OSError:
        return False


def mirrors_file(path: Path | str) -> bool:
    """True when ``path`` is a live on-disk store (rebooking next to the
    product db, voiceconfig next to the call log) and Supabase is on."""
    if not enabled():
        return False
    try:
        return Path(path).resolve().parent == product_db_path().parent
    except OSError:
        return False


def _headers() -> dict[str, str]:
    key = _secret_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _rest(path: str) -> str:
    return f"{os.environ['SUPABASE_URL'].strip().rstrip('/')}{path}"


def upsert(table: str, rows: list[dict[str, Any]], on_conflict: str) -> int:
    if not rows or not enabled():
        return 0
    payload = [{k: v for k, v in row.items()} for row in rows]
    response = httpx.post(
        _rest(f"/rest/v1/{table}"),
        params={"on_conflict": on_conflict},
        headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
        json=payload,
        timeout=TIMEOUT_S,
    )
    if response.status_code not in {200, 201, 204}:
        raise RuntimeError(f"{table} upsert {response.status_code}: {response.text[:240]}")
    return len(payload)


def safe_upsert(table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
    try:
        upsert(table, rows, on_conflict)
    except Exception:
        log.exception("supabase upsert %s failed", table)


def after_write(
    conn: sqlite3.Connection, table: str, row: sqlite3.Row | dict[str, Any], on_conflict: str
) -> None:
    if not mirrors_product(conn):
        return
    payload = dict(row)
    safe_upsert(table, [payload], on_conflict)


def count(table: str) -> int | None:
    """Exact row count via ``Prefer: count=exact``, or ``None`` on failure."""
    if not enabled():
        return None
    try:
        response = httpx.get(
            _rest(f"/rest/v1/{table}"),
            params={"select": "*", "limit": "1"},
            headers={**_headers(), "Prefer": "count=exact"},
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


def select(table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]] | None:
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
