"""Check the hosted store from the terminal.

    uv run python scripts/supabase_logs.py ping     # can we reach call_events?
    uv run python scripts/supabase_logs.py count    # remote row counts

Needs ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` (or
``SUPABASE_SECRET_KEY``) in ``.env``. Both go through PostgREST; neither
command writes anything.

Schema is not this script's job. The only source of DDL is
``database/supabase/migrations/``, applied with ``make supabase-migrate``,
which reads ``SUPABASE_DB_URL`` (the direct Postgres URI) instead.
"""

from __future__ import annotations

import argparse
import sys

from database.remote import count as remote_count
from vortex.observability.supabase_log import configured, ping
from vortex.settings import reset_settings

REMOTE_TABLES = (
    "call_events",
    "calls",
    "appointments",
    "wall_cancellations",
    "rebooking_requests",
    "voiceconfig",
    "personalities",
)

_MISSING = "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are empty — add them to .env"


def cmd_ping() -> int:
    reset_settings()
    if not configured():
        print(_MISSING)
        return 2
    result = ping()
    print(f"{'ok' if result['ok'] else 'fail'}: {result['detail']}")
    return 0 if result["ok"] else 1


def cmd_count() -> int:
    reset_settings()
    if not configured():
        print(_MISSING)
        return 2
    failed = 0
    for table in REMOTE_TABLES:
        n = remote_count(table)
        if n is None:
            failed += 1
            print(f"{table}: FAIL")
        else:
            print(f"{table}: {n}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hosted store (Supabase).")
    parser.add_argument("command", choices=("ping", "count"))
    args = parser.parse_args()
    return cmd_ping() if args.command == "ping" else cmd_count()


if __name__ == "__main__":
    sys.exit(main())
