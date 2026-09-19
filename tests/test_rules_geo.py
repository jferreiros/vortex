"""rules/geo.py and rules.nearest_location: problem 15, the nearest site.

``evals/logic/cases/rules.yaml`` has the ``rules.nearest.*`` cases against the
tool. What lives here is the pure distance math (no clinic, no network — the
gazetteer must resolve an address entirely offline) and the specialty-gap
rule in isolation: the closest site without the specialty is skipped for the
next nearest one that has it, never turned into a refusal.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from vortex.clinic.client import FakeClinicClient
from vortex.contract import MADRID, NearestLocationInput, ToolContext
from vortex.line.submit import DryRunSubmitClient
from vortex.observability.calllog import CallLog
from vortex.rules import geo
from vortex.rules.tools import nearest_location

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        call_id="CA-geo",
        now=NOW,
        from_number="+34612345678",
        clinic=FakeClinicClient(),
        log=CallLog("CA-geo", tmp_path / "calls.jsonl"),
        submitter=DryRunSubmitClient(),
    )


# ---- pure distance math, no clinic involved --------------------------------


def test_nearest_picks_the_closer_of_two_known_points() -> None:
    class Site:
        def __init__(self, location_id: str, lat: float, lon: float) -> None:
            self.location_id = location_id
            self.latitude = lat
            self.longitude = lon

    getafe = (40.3082, -3.7325)
    near = Site("sur", 40.3080, -3.7320)  # metres away
    far = Site("norte", 40.4700, -3.6880)  # ~18 km away

    found = geo.nearest(getafe, [near, far])
    assert found is not None
    site, distance = found
    assert site.location_id == "sur"
    assert distance < 1.0


def test_the_gazetteer_resolves_a_town_and_a_castellana_address_offline() -> None:
    """No ``VORTEX_GEOCODER`` is set in tests: this must never hit a network."""
    assert geo.gazetteer_lookup("Getafe") is not None
    assert geo.gazetteer_lookup("Paseo de la Castellana 200, Madrid") is not None
    assert geo.gazetteer_lookup("somewhere nobody has ever published") is None


# ---- nearest_location: the specialty gap -----------------------------------


async def test_the_closest_site_lacking_the_specialty_is_skipped(ctx: ToolContext) -> None:
    """Puerta del Sol sits next to Centro, but physiotherapy only exists at Sur."""
    result = await nearest_location(
        ctx, NearestLocationInput(address="Puerta del Sol, Madrid", specialty_id="physiotherapy")
    )
    assert result.rejection is None
    assert result.location_id == "sur"


async def test_the_callers_own_site_address_resolves_to_itself(ctx: ToolContext) -> None:
    """The published example: Sur's own address, asked for orthopaedics."""
    result = await nearest_location(
        ctx,
        NearestLocationInput(address="Calle de Madrid 54, Getafe", specialty_id="orthopaedics"),
    )
    assert result.rejection is None
    assert result.location_id == "sur"


async def test_an_address_nobody_can_place_is_a_question_not_a_refusal_reason(
    ctx: ToolContext,
) -> None:
    result = await nearest_location(
        ctx,
        NearestLocationInput(
            address="somewhere with no street or town name at all", specialty_id="general_practice"
        ),
    )
    assert result.location_id is None
    assert result.rejection is not None
    assert result.rejection.reason == "out_of_scope"


async def test_nearest_location_passes_socket_settings_to_locate(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live geocoding must use the call's Settings, never get_settings()."""
    from vortex.settings import Settings

    socket_settings = Settings(geocoder="cartociudad", geocoder_url="")
    ctx.settings = socket_settings  # type: ignore[attr-defined]
    seen: list[Settings] = []

    caches: list[geo.GeocodeCache] = []

    async def fake_locate(address: str, settings: Settings, cache: geo.GeocodeCache):
        seen.append(settings)
        caches.append(cache)
        return geo.gazetteer_lookup(address)

    monkeypatch.setattr(geo, "locate", fake_locate)
    await nearest_location(
        ctx, NearestLocationInput(address="Getafe", specialty_id="general_practice")
    )
    assert seen == [socket_settings]
    # The cache the tool hands down is this call's own, never a module global.
    assert caches == [ctx.state[geo.GEOCODE_CACHE_KEY]]
