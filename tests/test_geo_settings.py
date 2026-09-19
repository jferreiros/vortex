"""Geocoding reads its backend from Settings, not the raw environment.

No network here: with no geocoder configured, ``geocode_live`` returns
``None`` without ever importing ``httpx``. CartoCiudad and Nominatim paths
are exercised against canned JSON via a patched ``_http_get_json``.
"""

from __future__ import annotations

from typing import Any

import pytest

from vortex import settings as settings_module
from vortex.rules import geo

# Portal coords CartoCiudad returned for Calle Alcalá 200 on 2026-09-19.
ALCALA_200_PORTAL = (40.430286615645414, -3.663858388589292)

CARTOCIUDAD_ALCALA_PAYLOAD: list[dict[str, Any]] = [
    {
        "type": "portal",
        "province": "Málaga",
        "lat": 36.67,
        "lng": -4.72,
        "address": "CALLE ALCALA DEL VALLE 200, El Rodeo (Coín)",
    },
    {
        "type": "portal",
        "province": "Madrid",
        "lat": ALCALA_200_PORTAL[0],
        "lng": ALCALA_200_PORTAL[1],
        "address": "CALLE ALCALA 200, Madrid",
    },
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VORTEX_GEOCODER", raising=False)
    monkeypatch.delenv("VORTEX_GEOCODER_URL", raising=False)
    settings_module.reset_settings()
    yield monkeypatch
    settings_module.reset_settings()


async def test_geocode_live_is_off_by_default(clean_env) -> None:
    assert await geo.geocode_live("Calle Mayor 1, Madrid", settings_module.Settings()) is None


async def test_geocode_live_reads_the_url_from_settings_not_os_environ(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw os.environ write must not reach geocode_live: only Settings does."""
    monkeypatch.setenv("VORTEX_GEOCODER_URL", "https://nominatim.example.invalid/search")
    # Settings must be passed explicitly; env alone never enables the live path.
    assert await geo.geocode_live("Calle Mayor 1, Madrid", settings_module.Settings()) is None

    settings_module.reset_settings()
    settings = settings_module.get_settings()
    assert settings.geocoder_url == "https://nominatim.example.invalid/search"
    off = settings_module.Settings(geocoder="", geocoder_url="")
    assert await geo.geocode_live("Calle Mayor 1, Madrid", off) is None


async def test_locate_and_geocode_live_require_settings(clean_env) -> None:
    """No get_settings() fallback: callers must pass the socket Settings."""
    with pytest.raises(TypeError):
        await geo.geocode_live("Calle Mayor 1, Madrid")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        await geo.locate("Calle Mayor 3, Madrid")  # type: ignore[call-arg]


async def test_locate_prefers_the_offline_gazetteer(clean_env) -> None:
    """A recognised place never needs the geocoder, on or off."""
    point = await geo.locate("Calle Mayor 3, Madrid", settings_module.Settings())
    assert point is not None


def test_pick_cartociudad_point_keeps_madrid_portal_not_malaga() -> None:
    assert geo.pick_cartociudad_point(CARTOCIUDAD_ALCALA_PAYLOAD) == ALCALA_200_PORTAL


async def test_cartociudad_resolves_alcala_200_to_a_portal(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake_get(url: str, *, params: dict[str, Any], headers=None):
        calls.append(params["q"])
        assert "cartociudad.es" in url
        return CARTOCIUDAD_ALCALA_PAYLOAD

    monkeypatch.setattr(geo, "_http_get_json", fake_get)
    settings = settings_module.Settings(geocoder="cartociudad", geocoder_url="")
    point = await geo.geocode_live("Calle Alcalá 200", settings)
    assert point == ALCALA_200_PORTAL
    assert calls == ["Calle Alcalá 200"]


async def test_cartociudad_tolerates_the_alcla_misspelling(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get(url: str, *, params: dict[str, Any], headers=None):
        assert "alcla" in params["q"].lower()
        return CARTOCIUDAD_ALCALA_PAYLOAD

    monkeypatch.setattr(geo, "_http_get_json", fake_get)
    settings = settings_module.Settings(geocoder="cartociudad")
    point = await geo.geocode_live("calle alcla 200 madrid", settings)
    assert point == ALCALA_200_PORTAL


async def test_geocode_results_are_cached_by_normalised_query_within_one_call(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def fake_get(url: str, *, params: dict[str, Any], headers=None):
        nonlocal calls
        calls += 1
        return CARTOCIUDAD_ALCALA_PAYLOAD

    monkeypatch.setattr(geo, "_http_get_json", fake_get)
    settings = settings_module.Settings(geocoder="cartociudad")
    one_call: geo.GeocodeCache = {}
    first = await geo.geocode_live("Calle Alcalá 200", settings, one_call)
    # Accents and case fold away: second call must hit the cache, not the wire.
    second = await geo.geocode_live("CALLE ALCALA 200", settings, one_call)
    assert first == second == ALCALA_200_PORTAL
    assert calls == 1


async def test_geocode_keeps_nothing_between_calls(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second socket asking the same address must not read the first one's hit."""
    calls = 0

    async def fake_get(url: str, *, params: dict[str, Any], headers=None):
        nonlocal calls
        calls += 1
        return CARTOCIUDAD_ALCALA_PAYLOAD

    monkeypatch.setattr(geo, "_http_get_json", fake_get)
    settings = settings_module.Settings(geocoder="cartociudad")
    first_call: geo.GeocodeCache = {}
    second_call: geo.GeocodeCache = {}
    assert await geo.geocode_live("Calle Alcalá 200", settings, first_call) == ALCALA_200_PORTAL
    assert await geo.geocode_live("Calle Alcalá 200", settings, second_call) == ALCALA_200_PORTAL
    assert calls == 2
    assert second_call and first_call.keys() == second_call.keys()
    # No cache at all is the same story: nothing is retained anywhere.
    assert await geo.geocode_live("Calle Alcalá 200", settings) == ALCALA_200_PORTAL
    assert await geo.geocode_live("Calle Alcalá 200", settings) == ALCALA_200_PORTAL
    assert calls == 4


async def test_nominatim_remains_available_via_geocoder_setting(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get(url: str, *, params: dict[str, Any], headers=None):
        assert "nominatim" in url
        return [{"lat": "40.42", "lon": "-3.70"}]

    monkeypatch.setattr(geo, "_http_get_json", fake_get)
    settings = settings_module.Settings(
        geocoder="nominatim",
        geocoder_url="https://nominatim.example.invalid/search",
    )
    point = await geo.geocode_live("somewhere obscure", settings)
    assert point == (40.42, -3.70)
