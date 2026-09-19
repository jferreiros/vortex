"""``estudios/cache-latency/bench.py``: every scenario times its own client.

The regression: the slot the booking and reschedule recipes need was always
warmed on a ``FakeClinicClient``, so a ``--live`` run handed fixture provider,
location and start-time values to the production API, the live re-check found
no such slot, and the live table reported an error for exactly the two tools
the study is about.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from vortex.clinic.client import ClinicClient, FakeClinicClient

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cache_latency_bench", ROOT / "estudios" / "cache-latency" / "bench.py"
)
assert SPEC and SPEC.loader
bench = importlib.util.module_from_spec(SPEC)
sys.modules["cache_latency_bench"] = bench
SPEC.loader.exec_module(bench)


@pytest.fixture
def local_platform() -> Iterator[tuple[object, str]]:
    """The study's own server, speaking the platform routes over the fixtures."""
    server, state, base_url = bench.start_server()
    try:
        yield state, base_url
    finally:
        server.shutdown()


@pytest.fixture
def warmups(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every client the warmup was given, in order."""
    seen: list[object] = []
    real = bench.warmup_slot

    async def spy(client, *args, **kwargs):
        seen.append(client)
        return await real(client, *args, **kwargs)

    monkeypatch.setattr(bench, "warmup_slot", spy)
    return seen


async def _scenario(label: str, base_url: str, state, **strategy) -> dict:
    out: dict = {"scenarios": {label: {"tools": {}}}}
    await bench.run_scenario(label, base_url, "bench", runs=1, state=state, out=out, **strategy)
    return out["scenarios"][label]["tools"]


async def test_a_live_style_scenario_warms_the_slot_over_http(
    local_platform: tuple[object, str], warmups: list[object]
) -> None:
    state, base_url = local_platform
    before = sum(state.requests.values())
    await _scenario("current", base_url, state, share_client=True, in_memory=False)
    assert [type(client) for client in warmups] == [ClinicClient]
    assert sum(state.requests.values()) > before


async def test_the_fresh_client_scenario_closes_the_client_it_warmed_with(
    local_platform: tuple[object, str], warmups: list[object]
) -> None:
    state, base_url = local_platform
    await _scenario("no_cache", base_url, state, share_client=False, in_memory=False)
    (warm_client,) = warmups
    assert isinstance(warm_client, ClinicClient)
    assert warm_client._http.is_closed


async def test_the_in_memory_scenario_warms_on_the_fake_client(
    local_platform: tuple[object, str], warmups: list[object]
) -> None:
    state, base_url = local_platform
    before = sum(state.requests.values())
    tools = await _scenario("full_memory", base_url, state, share_client=True, in_memory=True)
    assert [type(client) for client in warmups] == [FakeClinicClient]
    assert sum(state.requests.values()) == before
    assert "error" not in tools["prepare_booking"]
