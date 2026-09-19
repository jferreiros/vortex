"""The synthetic-data replayer: grouping, probe filtering and event re-stamping."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from evals.corpus.hydrate import SYNTHETIC_DATA_DIR
from vortex.observability.replay import (
    load_synthetic_calls,
    replay_call,
    restamp,
)


def test_load_groups_events_by_call_and_skips_probes() -> None:
    calls = load_synthetic_calls(SYNTHETIC_DATA_DIR)
    assert calls
    # One group per call_id, each event carrying that same id, in file order.
    for events in calls:
        ids = {e.get("call_id") for e in events}
        assert len(ids) == 1
        assert events[0].get("kind") == "call.started"
    # Probes are excluded by default, included on request.
    assert all(not str(events[0].get("call_id", "")).startswith("probe:") for events in calls)
    with_probes = load_synthetic_calls(SYNTHETIC_DATA_DIR, include_probes=True)
    assert len(with_probes) > len(calls)


def test_only_filters_to_one_problem() -> None:
    calls = load_synthetic_calls(SYNTHETIC_DATA_DIR, only="simple_booking")
    assert calls
    assert all(events[0].get("problem_id") == "simple_booking" for events in calls)


def test_restamp_drops_stamped_fields_and_keeps_payload() -> None:
    event = {
        "ts": "2026-09-18T09:00:00+02:00",
        "call_id": "simple_booking-abc",
        "kind": "submit.result",
        "route": "book",
        "payload": {"action": "BOOK", "patient_id": "P00001"},
    }
    kind, data = restamp(event)
    assert kind == "submit.result"
    assert "ts" not in data and "call_id" not in data and "kind" not in data
    assert data["route"] == "book"
    assert data["payload"] == {"action": "BOOK", "patient_id": "P00001"}


def test_replay_call_writes_fresh_stamps_and_run_tag(tmp_path: Path) -> None:
    log_path = tmp_path / "calls.jsonl"
    events = [
        {
            "ts": "2026-09-18T09:00:00+02:00",
            "call_id": "simple_booking-abc",
            "kind": "call.started",
            "problem_id": "simple_booking",
        },
        {
            "ts": "2026-09-18T09:00:00+02:00",
            "call_id": "simple_booking-abc",
            "kind": "call.ended",
            "reason": "synthetic-data",
        },
    ]

    async def _run() -> str:
        # speed=0 disables the inter-event sleep so the test does not wait.
        return await replay_call(log_path, events, speed=0, run_tag="run1", rng=random.Random(0))

    call_id = asyncio.run(_run())
    assert call_id == "simple_booking-abc-run1"
    written = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [e["kind"] for e in written] == ["call.started", "call.ended"]
    assert all(e["call_id"] == "simple_booking-abc-run1" for e in written)
    # Timestamps are re-derived at write time, not the frozen source instant.
    assert all(not e["ts"].startswith("2026-09-18T09:00:00+02:00") for e in written)
    assert written[0]["problem_id"] == "simple_booking"
