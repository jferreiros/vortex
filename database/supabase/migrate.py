"""Apply ``database/supabase/migrations/*.sql`` to the hosted Postgres.

    uv run python -m database.supabase.migrate            # apply what is pending
    uv run python -m database.supabase.migrate --dry-run  # just list it

Needs ``SUPABASE_DB_URL``: the *direct Postgres* URI, Supabase Dashboard ->
Project Settings -> Database -> Connection string -> URI. That is not the
same thing as ``SUPABASE_URL`` (the PostgREST origin everything at runtime
uses) — DDL cannot go through PostgREST, so this one script, and only this
one, opens a real connection with psycopg.

Files are applied in lexical order, one transaction each. The id (the file
name without ``.sql``) is inserted into ``public.schema_migrations`` inside
that same transaction, so a file either lands whole and is recorded, or
lands not at all and is retried on the next run. An id already in the table
is skipped — which is why an applied file must never be edited: a database
that already recorded ``0001_init`` will never read it again. A later change
is a new file, ``0002_<name>.sql``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Created before anything is read, so a database that has never run a
#: migration can still answer "what have you applied?". 0001 declares it too,
#: with the same ``if not exists``, so the file also stands on its own.
_BOOKKEEPING = """
create table if not exists public.schema_migrations (
    id          text primary key,
    applied_at  timestamptz not null default now()
)
"""


def database_url() -> str:
    """``SUPABASE_DB_URL``, with ``.env`` loaded first — the same file every
    other entry point reads. Exits with a usable message when it is unset."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:  # pragma: no cover - python-dotenv is a hard dep
        pass
    url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not url:
        raise SystemExit(
            "SUPABASE_DB_URL is not set.\n"
            "  Supabase Dashboard -> Project Settings -> Database -> "
            "Connection string -> URI\n"
            "  Put it in .env as SUPABASE_DB_URL=postgresql://postgres:...@...:5432/postgres\n"
            "  (this is the direct Postgres URI, not SUPABASE_URL)"
        )
    return url


def migration_files() -> list[Path]:
    """Every ``*.sql`` under ``migrations/``, lexically — which is why they
    are numbered with a fixed width."""
    if not MIGRATIONS_DIR.is_dir():
        raise SystemExit(f"no migrations directory at {MIGRATIONS_DIR}")
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied_ids(conn: Any) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(_BOOKKEEPING)
        conn.commit()
        cur.execute("select id from public.schema_migrations")
        return {str(row[0]) for row in cur.fetchall()}


def apply(path: Path, conn: Any) -> None:
    """One file, one transaction, id recorded inside it."""
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "insert into public.schema_migrations (id) values (%s) on conflict (id) do nothing",
            (path.stem,),
        )
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the Supabase migrations.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the files that would be applied; change nothing.",
    )
    args = parser.parse_args(argv)

    files = migration_files()
    if not files:
        print(f"no migrations in {MIGRATIONS_DIR}")
        return 0

    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed — run: uv sync --all-groups", file=sys.stderr)
        return 1

    url = database_url()
    try:
        conn = psycopg.connect(url, autocommit=False)
    except Exception as exc:
        print(f"could not connect to SUPABASE_DB_URL: {exc}", file=sys.stderr)
        return 1

    try:
        done = applied_ids(conn)
        pending = [path for path in files if path.stem not in done]
        if args.dry_run:
            for path in files:
                mark = "pending" if path.stem in {p.stem for p in pending} else "applied"
                print(f"{mark:>7}  {path.name}")
            print(f"{len(pending)} pending")
            return 0
        for path in files:
            if path.stem in done:
                print(f"skipped  {path.stem}")
                continue
            try:
                apply(path, conn)
            except Exception as exc:
                conn.rollback()
                print(f"FAILED   {path.stem}: {exc}", file=sys.stderr)
                return 1
            print(f"applied  {path.stem}")
        print(f"{len(pending)} applied, {len(files) - len(pending)} already there")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
