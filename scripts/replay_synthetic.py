"""Drip the synthetic-data pack into the live call log for the board.

    uv run python scripts/replay_synthetic.py               # default cadence
    uv run python scripts/replay_synthetic.py --speed 2     # twice as fast
    uv run python scripts/replay_synthetic.py --only triage # one problem
    uv run python scripts/replay_synthetic.py --loop        # never stop

Reads ``synthetic-data/logs/*.jsonl`` and writes only to ``logs/calls.jsonl``
(the path ``VORTEX_CALLS_LOG`` / settings resolve). Start ``make board`` and
watch the calls land at ``/wall``. Probes are skipped unless ``--include-probes``.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vortex.observability.replay import load_synthetic_calls, replay_stream  # noqa: E402
from vortex.settings import get_settings  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python scripts/replay_synthetic.py", description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "synthetic-data",
        help="source pack (default: synthetic-data/)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="destination call log (default: settings.calls_log_path)",
    )
    parser.add_argument("--concurrency", type=int, default=5, help="max calls in flight at once")
    parser.add_argument("--speed", type=float, default=1.0, help="time multiplier (2 = twice fast)")
    parser.add_argument("--only", default=None, help="replay a single problem_id")
    parser.add_argument("--include-probes", action="store_true", help="also replay probe calls")
    parser.add_argument("--loop", action="store_true", help="replay the whole set forever")
    parser.add_argument("--seed", type=int, default=None, help="seed the arrival shuffle/jitter")
    parser.add_argument(
        "--keep-ids", action="store_true", help="keep original call_ids (no per-run suffix)"
    )
    parser.add_argument(
        "--clean", action="store_true", help="truncate the destination log before starting"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_path = args.log or get_settings().calls_log_path

    calls = load_synthetic_calls(args.data_dir, include_probes=args.include_probes, only=args.only)
    if not calls:
        print(f"no calls found under {args.data_dir / 'logs'} (only={args.only})", file=sys.stderr)
        return 1

    if args.clean:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        print(f"cleaned {log_path}")

    rng = random.Random(args.seed)
    print(
        f"replaying {len(calls)} calls into {log_path} "
        f"(concurrency={args.concurrency}, speed={args.speed}, loop={args.loop})"
    )
    try:
        total = asyncio.run(
            replay_stream(
                log_path,
                calls,
                concurrency=args.concurrency,
                speed=args.speed,
                loop=args.loop,
                keep_ids=args.keep_ids,
                rng=rng,
            )
        )
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        return 130
    print(f"done: {total} calls replayed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
