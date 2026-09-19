"""``estudios/cache-latency/bench.py``: every scenario times its own client.

The regression: the slot the booking and reschedule recipes need was always
warmed on a ``FakeClinicClient``, so a ``--live`` run handed fixture provider,
location and start-time values to the production API, the live re-check found
no such slot, and the live table reported an error for exactly the two tools
the study is about. The same held for every other clinic-side identifier: a
fixture ``patient_id`` or ``appointment_id`` comes back from the live API as a
typed rejection, which the loop would have timed as if it were a booking.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from evals.common.context import make_context
from vortex.clinic.client import ClinicClient, FakeClinicClient
from vortex.tools import TOOLS

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cache_latency_bench", ROOT / "estudios" / "cache-latency" / "bench.py"
)
assert SPEC and SPEC.loader
bench = importlib.util.module_from_spec(SPEC)
sys.modules["cache_latency_bench"] = bench
SPEC.loader.exec_module(bench)


class RenamingClinic:
    """The fixtures behind ids only this client knows, like a live clinic's."""

    def __init__(self) -> None:
        self._fake = FakeClinicClient()

    async def catalogue(self):
        return await self._fake.catalogue()

    async def directory(self, **query):
        found = await self._fake.directory(**query)
        return [
            record.model_copy(update={"patient_id": f"LIVE-{record.patient_id}"})
            for record in found
        ]

    async def appointments(self, patient_id: str, *, when: str = "upcoming"):
        return await self._fake.appointments(patient_id.removeprefix("LIVE-"), when=when)

    async def availability(self, **query):
        return await self._fake.availability(**query)

    async def aclose(self) -> None:
        await self._fake.aclose()


class UnknownPatientsClinic(RenamingClinic):
    """A clinic that recognises none of the fixture patients."""

    async def directory(self, **query):
        return []


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
    assert {type(client) for client in warmups} == {ClinicClient}
    assert sum(state.requests.values()) > before


async def test_the_fresh_client_scenario_closes_the_client_it_warmed_with(
    local_platform: tuple[object, str], warmups: list[object]
) -> None:
    state, base_url = local_platform
    await _scenario("no_cache", base_url, state, share_client=False, in_memory=False)
    assert warmups
    for warm_client in warmups:
        assert isinstance(warm_client, ClinicClient)
        assert warm_client._http.is_closed


async def test_the_in_memory_scenario_warms_on_the_fake_client(
    local_platform: tuple[object, str], warmups: list[object]
) -> None:
    state, base_url = local_platform
    before = sum(state.requests.values())
    tools = await _scenario("full_memory", base_url, state, share_client=True, in_memory=True)
    assert {type(client) for client in warmups} == {FakeClinicClient}
    assert sum(state.requests.values()) == before
    assert "error" not in tools["prepare_booking"]


def test_the_recipes_carry_no_clinic_identifier() -> None:
    """Nothing a live API has to recognise may be hardcoded in the recipes."""
    recipes = bench.tool_recipes()
    for name, arguments in bench.RESOLVED_INPUTS.items():
        assert set(arguments) & set(recipes[name]) == set(), name


async def test_every_identifier_comes_from_the_client() -> None:
    resolved = await bench.resolve_inputs(RenamingClinic())
    assert resolved["patient_id"].startswith("LIVE-")
    assert resolved["appointment_patient_id"].startswith("LIVE-")
    assert resolved["policy_id"] == "mapfre"
    assert resolved["appointment_policy_id"] == "sanitas"
    assert resolved["booking_slot"]["specialty_id"] == resolved["specialty_id"]
    assert resolved["reschedule_slot"]["specialty_id"] == resolved["specialty_id"]

    recipes = bench.tool_recipes()
    assert bench.apply_resolved_inputs(recipes, resolved) == {}
    assert recipes["prepare_booking"]["patient_id"] == resolved["patient_id"]
    assert recipes["prepare_booking"]["slot"] == resolved["booking_slot"]
    assert recipes["prepare_cancel"]["patient_id"] == resolved["appointment_patient_id"]
    assert recipes["prepare_reschedule"]["appointment_id"] == resolved["appointment_id"]
    assert recipes["prepare_reschedule"]["slot"] == resolved["reschedule_slot"]


async def test_each_operation_gets_a_slot_its_own_patient_is_offered() -> None:
    """``prepare_booking`` re-checks availability for its patient, and a slot
    warmed without one carries the wrong appointment type for that patient."""
    client = FakeClinicClient()
    resolved = await bench.resolve_inputs(client)
    recipes = bench.tool_recipes()
    assert bench.apply_resolved_inputs(recipes, resolved) == {}

    for name in ("prepare_booking", "prepare_reschedule"):
        spec = TOOLS[name]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(call_id=f"bench-test-{name}", log_dir=Path(tmp), clinic=client)
            result = await spec.fn(ctx, spec.input_model.model_validate(recipes[name]))
        assert result.rejection is None, (name, result.rejection)
        assert result.action is not None


async def test_a_clinic_that_knows_no_patient_leaves_those_recipes_out() -> None:
    resolved = await bench.resolve_inputs(UnknownPatientsClinic())
    skipped = bench.apply_resolved_inputs(bench.tool_recipes(), resolved)
    assert set(skipped) == {
        "find_patient",
        "list_appointments",
        "prepare_booking",
        "prepare_reschedule",
        "prepare_cancel",
        "check_eligibility",
    }
    assert "find_slots" not in skipped


async def test_a_skipped_recipe_is_reported_instead_of_timed(
    local_platform: tuple[object, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recipe with no live-compatible input must not produce a latency row."""
    state, base_url = local_platform
    real = bench.resolve_inputs

    async def without_patients(client):
        resolved = await real(client)
        for key in ("patient_id", "policy_id"):
            resolved.pop(key)
        return resolved

    monkeypatch.setattr(bench, "resolve_inputs", without_patients)
    tools = await _scenario("current", base_url, state, share_client=True, in_memory=False)
    assert tools["prepare_booking"] == {"skipped": "no live-compatible patient_id, policy_id"}
    assert "p50_ms" in tools["find_slots"]
    assert "p50_ms" in tools["prepare_cancel"]
