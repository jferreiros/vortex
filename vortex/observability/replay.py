"""Drip the ``synthetic-data/`` calls into the live store, as if in real time.

The pack under ``synthetic-data/logs/*.jsonl`` holds one CallLog-shaped call
per published case (plus probes), every event frozen at the same instant. This
module reads those fixture files and replays them into ``public.call_events``
with a synthetic cadence: several calls overlapping at once, a small gap
between the events of one call, and a jittered gap between arrivals. The live
board polls the table twice a second, so the calls appear to land one after
another.

Nothing is ever written back into ``synthetic-data/`` — this reads there and
writes only through :class:`CallLog`. Each call gets its own log, so no state
is shared between them (see the concurrency rule in ``CLAUDE.md``).

The ``path`` arguments below are vestigial: ``CallLog`` ignores them now that
Postgres is the only store. They stay for one release so existing callers
keep working.

The pure helpers (``load_synthetic_calls``, ``restamp``) carry no timing and
are what the selftest exercises; the ``replay_*`` coroutines add the sleeps.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

from vortex.observability.calllog import CallLog

#: Keys a source event carries that the writer re-derives itself.
_REWRITTEN = ("ts", "call_id", "kind")

#: Event delay bounds (seconds, before ``--speed`` scaling). One call runs
#: through a handful of events, so keep them short enough to feel live.
_EVENT_DELAY_MIN = 0.3
_EVENT_DELAY_MAX = 1.2

#: Gap between one call arriving and the next (seconds, before scaling).
_ARRIVAL_GAP_MIN = 0.4
_ARRIVAL_GAP_MAX = 2.5


def _log_files(data_dir: Path) -> list[Path]:
    """The per-problem JSONL logs, minus any rolled-up ``all.jsonl``."""
    logs_dir = data_dir / "logs"
    return sorted(p for p in logs_dir.glob("*.jsonl") if p.name != "all.jsonl")


def _is_probe(events: list[dict[str, Any]]) -> bool:
    head = events[0] if events else {}
    call_id = str(head.get("call_id") or "")
    return head.get("source") == "probe" or call_id.startswith("probe:")


def load_synthetic_calls(
    data_dir: Path,
    *,
    include_probes: bool = False,
    only: str | None = None,
) -> list[list[dict[str, Any]]]:
    """Read ``data_dir/logs/*.jsonl`` and group the events into whole calls.

    Returns one list of events per ``call_id``, each in the order it was
    written. Order across calls is the file order (stable); the scheduler
    shuffles arrivals itself. A ``call_id`` seen twice keeps its first group,
    so a stray ``all.jsonl`` copy cannot double a call.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in _log_files(data_dir):
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            call_id = str(event.get("call_id") or "")
            if not call_id:
                continue
            grouped.setdefault(call_id, []).append(event)

    calls = list(grouped.values())
    if not include_probes:
        calls = [c for c in calls if not _is_probe(c)]
    if only:
        calls = [c for c in calls if (c[0].get("problem_id") == only if c else False)]
    return calls


def restamp(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Split a source event into ``(kind, data)`` for a fresh re-emit.

    The writer stamps ``ts`` and ``call_id`` itself, so both are dropped here
    along with ``kind`` (returned separately). Everything else — the payload,
    the actions, the summary shape — is passed through untouched.
    """
    kind = str(event.get("kind") or "event")
    data = {k: v for k, v in event.items() if k not in _REWRITTEN}
    return kind, data


def _new_call_id(call_id: str, *, run_tag: str | None, keep_ids: bool) -> str:
    if keep_ids or not run_tag:
        return call_id
    return f"{call_id}-{run_tag}"


async def replay_call(
    path: Path,
    events: list[dict[str, Any]],
    *,
    speed: float = 1.0,
    run_tag: str | None = None,
    keep_ids: bool = False,
    rng: random.Random | None = None,
) -> str:
    """Write one call to ``path`` event by event, pausing between events."""
    rng = rng or random.Random()
    source_id = str(events[0].get("call_id") or "call") if events else "call"
    call_id = _new_call_id(source_id, run_tag=run_tag, keep_ids=keep_ids)
    log = CallLog(call_id, path)
    scale = 1.0 / speed if speed > 0 else 0.0
    for index, event in enumerate(events):
        kind, data = restamp(event)
        log.event(kind, **data)
        if index < len(events) - 1 and scale:
            await asyncio.sleep(rng.uniform(_EVENT_DELAY_MIN, _EVENT_DELAY_MAX) * scale)
    return call_id


async def replay_stream(
    path: Path,
    calls: list[list[dict[str, Any]]],
    *,
    concurrency: int = 5,
    speed: float = 1.0,
    loop: bool = False,
    keep_ids: bool = False,
    rng: random.Random | None = None,
) -> int:
    """Drip ``calls`` into ``path`` with overlapping arrivals and jitter.

    At most ``concurrency`` calls are in flight at once. Between launching one
    call and the next there is a jittered gap. With ``loop`` the whole set
    replays again (a fresh run tag each cycle). Returns the number of calls
    replayed.
    """
    rng = rng or random.Random()
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    scale = 1.0 / speed if speed > 0 else 0.0
    total = 0

    async def _run(events: list[dict[str, Any]], run_tag: str | None) -> None:
        async with semaphore:
            await replay_call(
                path,
                events,
                speed=speed,
                run_tag=run_tag,
                keep_ids=keep_ids,
                rng=rng,
            )

    cycle = 0
    while True:
        run_tag = None if keep_ids else f"{int(time.time())}-{cycle:02d}"
        order = list(calls)
        rng.shuffle(order)
        tasks: list[asyncio.Task[None]] = []
        for events in order:
            tasks.append(asyncio.create_task(_run(events, run_tag)))
            total += 1
            if scale:
                await asyncio.sleep(rng.uniform(_ARRIVAL_GAP_MIN, _ARRIVAL_GAP_MAX) * scale)
        if tasks:
            await asyncio.gather(*tasks)
        cycle += 1
        if not loop:
            break
    return total
