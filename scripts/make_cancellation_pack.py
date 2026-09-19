"""Regenerate ``synthetic-data/logs/cancellation_demo.jsonl``.

    uv run python scripts/make_cancellation_pack.py

The file holds seven CallLog-shaped calls — five cancellations and two
bookings that take the exact slots two of them freed — so the Insights
"Cancelaciones" panel shows relocated, lost and pending at once. The slot
dates are relative to the moment this runs (freed slots at -2/-1/+1/+2/+4
days), which is what keeps "lost" and "pending" honest: regenerate before a
demo if the file has aged past those dates.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vortex.observability.demo import CANCELLATION_PACK, write_cancellation_pack  # noqa: E402


def main() -> int:
    # The writer appends like CallLog does; a pack file is regenerated whole.
    CANCELLATION_PACK.parent.mkdir(parents=True, exist_ok=True)
    CANCELLATION_PACK.write_text("", encoding="utf-8")
    written = asyncio.run(write_cancellation_pack(CANCELLATION_PACK, delay_s=0))
    print(f"wrote {len(written)} calls to {CANCELLATION_PACK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
