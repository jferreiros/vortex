"""Load the committed product-data seeds into the local runtime files.

    uv run python database/scripts/load_seed.py
    uv run python database/scripts/load_seed.py --replace

``database/seed/*.sql`` are text dumps of the board's own stores — the
product DB (``wall_cancellations``, plus any ``calls``/``appointments`` rows)
and the rebooking queue (``rebooking_requests``). They exist so everyone
starts the demo from the same cancelled slots instead of an empty store.

Each dump loads only into a file that does not already carry its tables —
a live store is never touched silently. ``--replace`` renames the existing
file to ``<name>.bak-<timestamp>`` first. The real paths follow
``VORTEX_PRODUCT_DB``; ``rebooking.sqlite3`` always sits next to it, the
same place ``vortex/observability/live.py`` writes it.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vortex.settings import get_settings  # noqa: E402

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

#: seed file -> the tables it is expected to create, used to tell an
#: already-loaded store apart from an empty file.
SEEDS = (
    ("vortex_product.sql", {"calls", "appointments", "wall_cancellations"}),
    ("rebooking.sql", {"rebooking_requests"}),
)


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {str(row[0]) for row in rows}


def load_one(seed: Path, target: Path, replace: bool) -> str:
    if target.exists():
        existing = _tables(sqlite3.connect(target))
        if existing & _expected(seed):
            if not replace:
                return f"skip {target} (already has {sorted(existing & _expected(seed))})"
            backup = target.with_name(
                f"{target.name}.bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
            )
            shutil.move(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.executescript(seed.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return f"loaded {seed.name} -> {target}"


def _expected(seed: Path) -> set[str]:
    return dict(SEEDS)[seed.name]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Back the existing store up and load the seed over it.",
    )
    args = parser.parse_args()

    product_db = Path(get_settings().product_db_path)
    targets = {
        "vortex_product.sql": product_db,
        "rebooking.sql": product_db.with_name("rebooking.sqlite3"),
    }
    for seed_name, _tables_expected in SEEDS:
        seed = SEED_DIR / seed_name
        if not seed.exists():
            print(f"missing {seed} — nothing committed for this store")
            continue
        print(load_one(seed, targets[seed_name], args.replace))


if __name__ == "__main__":
    main()
