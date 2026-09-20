"""Load the committed product-data seeds into the hosted Postgres.

    uv run python database/scripts/load_seed.py
    uv run python database/scripts/load_seed.py --only rebooking.sql

``database/seed/*.sql`` are the board's own starting state — the slots the
control centre has already cancelled and the rebooking callbacks they left
behind — so everyone demos from the same diary instead of an empty one.

Data only: the tables come from ``database/supabase/migrations/``, so run
``make supabase-migrate`` first. Every seed is written to be re-runnable
(``on conflict do nothing`` / ``where not exists``), so loading twice is not
destructive and a live store is never silently wiped.

Goes through ``SUPABASE_DB_URL`` with psycopg rather than PostgREST: these
are SQL files, and plain SQL is the one thing PostgREST does not take.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from database.supabase.migrate import database_url  # noqa: E402

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

#: Load order matters: a rebooking request points at the cancellation that
#: created it, so the cancellations go in first. ``wall_documents.sql`` is
#: independent of both — the Pathways/Patterns editors' starting documents.
SEEDS = ("vortex_product.sql", "rebooking.sql", "wall_documents.sql")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load database/seed/*.sql into Supabase.")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="FILE",
        help=f"Load just this seed file. Repeatable. One of: {', '.join(SEEDS)}",
    )
    args = parser.parse_args()

    names = args.only or list(SEEDS)
    unknown = [name for name in names if name not in SEEDS]
    if unknown:
        print(f"unknown seed(s): {', '.join(unknown)}", file=sys.stderr)
        return 1

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
        for name in names:
            seed = SEED_DIR / name
            if not seed.exists():
                print(f"missing {seed} — nothing committed for this store")
                continue
            try:
                with conn.cursor() as cur:
                    cur.execute(seed.read_text(encoding="utf-8"))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                print(f"FAILED  {name}: {exc}", file=sys.stderr)
                return 1
            print(f"loaded  {name}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
