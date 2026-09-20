"""Talk to the hosted call log and product tables.

    uv run python scripts/supabase_logs.py ping
    uv run python scripts/supabase_logs.py schema          # how to apply DDL
    uv run python scripts/supabase_logs.py push            # upload logs/calls.jsonl
    uv run python scripts/supabase_logs.py push --dry-run
    uv run python scripts/supabase_logs.py push-db         # sqlite product tables
    uv run python scripts/supabase_logs.py count           # remote row counts

Needs ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` (or
``SUPABASE_SECRET_KEY``) in ``.env``. There is no Alembic. Paste
``database/supabase/schema.sql`` in the SQL editor once (or run
``make supabase-schema``), then push.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from database.remote import count as remote_count
from database.remote import upsert as upsert_table
from vortex.observability.supabase_log import apply_schema, configured, ping, upsert_events
from vortex.settings import get_settings, reset_settings

BATCH = 200

# (sqlite table, on_conflict) inside logs/vortex_product.db
PRODUCT_TABLES = (
    ("calls", "call_id"),
    ("appointments", "id"),
    ("wall_cancellations", "id"),
)

REMOTE_TABLES = (
    "call_events",
    "calls",
    "appointments",
    "wall_cancellations",
    "rebooking_requests",
    "voiceconfig",
    "personalities",
)


def _iter_events(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _sqlite_rows(path: Path, table: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if table not in names:
            return []
        return [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"')]
    finally:
        conn.close()


def _upsert_batches(table: str, rows: list[dict], on_conflict: str, *, dry_run: bool) -> int:
    if dry_run:
        print(f"  {table}: {len(rows)} rows (dry run)")
        return 0
    sent = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        sent += upsert_table(table, chunk, on_conflict)
        print(f"  {table}: {min(i + BATCH, len(rows))}/{len(rows)}", flush=True)
    return sent


def cmd_schema() -> int:
    """There is no migration runner. DDL is one SQL file, pasted once."""
    from vortex.settings import REPO_ROOT

    path = REPO_ROOT / "database" / "supabase" / "schema.sql"
    print("No Alembic / supabase db push for this project.")
    print("1. Open the SQL editor for the project (Dashboard → SQL → New).")
    print(f"2. Paste and run: {path}")
    print("3. Then: make supabase-ping && make supabase-push")
    print("   Optional product rows: make supabase-push-db")
    reset_settings()
    if not configured():
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are empty — not trying HTTP apply.")
        return 0
    try:
        apply_schema()
    except Exception as exc:
        print(f"automatic apply failed (expected on hosted PostgREST): {exc}")
        return 0
    print("automatic apply: ok")
    return 0


def cmd_ping() -> int:
    reset_settings()
    if not configured():
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are empty — nothing to ping")
        return 2
    result = ping()
    print(f"{'ok' if result['ok'] else 'fail'}: {result['detail']}")
    return 0 if result["ok"] else 1


def cmd_push(path: Path, *, dry_run: bool) -> int:
    reset_settings()
    if not configured():
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are empty — add them to .env")
        return 2
    events = list(_iter_events(path))
    print(f"read {len(events)} events from {path}")
    if dry_run:
        print("dry run: nothing sent")
        return 0
    sent = 0
    for i in range(0, len(events), BATCH):
        chunk = events[i : i + BATCH]
        sent += upsert_events(chunk)
        print(f"  upserted {min(i + BATCH, len(events))}/{len(events)}", flush=True)
    print(f"done: {sent} rows offered (duplicates ignored)")
    return 0


def cmd_push_db(*, dry_run: bool) -> int:
    reset_settings()
    if not configured():
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are empty — add them to .env")
        return 2
    settings = get_settings()
    logs_dir = settings.calls_log_path.parent
    product = settings.product_db_path
    extras = (
        (logs_dir / "rebooking.sqlite3", "rebooking_requests", "request_id"),
        (logs_dir / "voiceconfig.db", "voiceconfig", "id"),
        (logs_dir / "personalities.db", "personalities", "slug"),
    )

    failures = 0
    if product.exists():
        print(f"product db: {product}")
        for table, on_conflict in PRODUCT_TABLES:
            rows = _sqlite_rows(product, table)
            try:
                sent = _upsert_batches(table, rows, on_conflict, dry_run=dry_run)
                print(f"  {table}: offered {sent} of {len(rows)}")
            except Exception as exc:
                failures += 1
                print(f"  {table}: FAIL {exc}")
    else:
        print(f"skip product db — missing {product}")

    for path, table, on_conflict in extras:
        if not path.exists():
            print(f"skip {table} — missing {path.name}")
            continue
        rows = _sqlite_rows(path, table)
        print(f"{path.name}: {len(rows)} {table} rows")
        try:
            sent = _upsert_batches(table, rows, on_conflict, dry_run=dry_run)
            print(f"  {table}: offered {sent} of {len(rows)}")
        except Exception as exc:
            failures += 1
            print(f"  {table}: FAIL {exc}")

    return 1 if failures else 0


def cmd_count() -> int:
    reset_settings()
    if not configured():
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are empty — nothing to count")
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
    parser = argparse.ArgumentParser(description="Hosted call log (Supabase).")
    parser.add_argument("command", choices=("ping", "schema", "push", "push-db", "count"))
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "ping":
        return cmd_ping()
    if args.command == "schema":
        return cmd_schema()
    if args.command == "push-db":
        return cmd_push_db(dry_run=args.dry_run)
    if args.command == "count":
        return cmd_count()
    return cmd_push(args.log or get_settings().calls_log_path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
