"""Ping Supabase to confirm connectivity before seeding or upserting.

    uv run python database/scripts/ping.py

Checks both ways the project reaches the hosted Postgres:

* PostgREST — ``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY`` /
  ``SUPABASE_SECRET_KEY``. This is what the board and line use at runtime
  (``database/remote.py``). A live GET against ``wall_documents`` proves the
  key works and the table is there.
* Direct Postgres — ``SUPABASE_DB_URL``. This is what raw-SQL seeds and the
  wall-document upsert need (``database/scripts/load_seed.py``). Optional: it
  is fine for this to be missing if you only run the app.

Exit code is 0 when at least the PostgREST path is up, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv() -> None:
    """Populate os.environ from .env for values not already set, so the ping
    works when run directly (not just under `make`, which exports it)."""
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ping_postgrest() -> bool:
    from database import remote

    if not remote.enabled():
        print("PostgREST : NOT configured (need SUPABASE_URL + SUPABASE_SECRET_KEY)")
        return False
    try:
        import httpx

        response = httpx.get(
            remote._rest("/rest/v1/wall_documents"),
            params={"select": "kind"},
            headers=remote._headers(),
            timeout=remote.TIMEOUT_S,
        )
        response.raise_for_status()
        kinds = [r.get("kind") for r in response.json() if isinstance(r, dict)]
        host = os.environ["SUPABASE_URL"].strip()
        print(f"PostgREST : OK  ({host})  wall_documents kinds -> {kinds or '[]'}")
        return True
    except Exception as exc:
        print(f"PostgREST : FAILED  {exc!r}")
        return False


def ping_direct_pg() -> bool:
    try:
        from database.supabase.migrate import database_url

        url = database_url()
    except SystemExit:
        print("Direct PG : SUPABASE_DB_URL not set (only needed for SQL seeds/upsert)")
        return False
    except Exception as exc:
        print(f"Direct PG : could not resolve URL  {exc!r}")
        return False
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
        print("Direct PG : OK  (select 1 succeeded)")
        return True
    except Exception as exc:
        print(f"Direct PG : FAILED  {exc!r}")
        return False


def main() -> int:
    _load_dotenv()
    print("=== Supabase connectivity ping ===")
    rest_ok = ping_postgrest()
    ping_direct_pg()
    print("==================================")
    if rest_ok:
        print("Connection to Supabase is working (PostgREST path).")
        return 0
    print("Cannot reach Supabase. Check SUPABASE_URL / SUPABASE_SECRET_KEY in .env.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
