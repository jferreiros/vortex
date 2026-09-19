"""Geocoding reads its endpoint from Settings, not the raw environment.

No network here: with no ``geocoder_url`` set, ``geocode_live`` must return
``None`` without ever importing ``httpx``.
"""

from __future__ import annotations

import pytest

from vortex import settings as settings_module
from vortex.rules import geo


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VORTEX_GEOCODER_URL", raising=False)
    settings_module.reset_settings()
    yield monkeypatch
    settings_module.reset_settings()


async def test_geocode_live_is_off_by_default(clean_env) -> None:
    assert await geo.geocode_live("Calle Mayor 1, Madrid") is None


async def test_geocode_live_reads_the_url_from_settings_not_os_environ(
    clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw os.environ write must not reach geocode_live: only Settings does."""
    monkeypatch.setenv("VORTEX_GEOCODER_URL", "https://nominatim.example.invalid/search")
    # geo.py no longer reads os.environ directly, so the stale cached Settings
    # (with no geocoder configured) still wins here.
    assert await geo.geocode_live("Calle Mayor 1, Madrid") is None

    settings_module.reset_settings()
    settings = settings_module.get_settings()
    assert settings.geocoder_url == "https://nominatim.example.invalid/search"
    # An explicit settings argument is honoured without needing get_settings().
    off = settings_module.Settings(geocoder_url="")
    assert await geo.geocode_live("Calle Mayor 1, Madrid", off) is None


async def test_locate_prefers_the_offline_gazetteer(clean_env) -> None:
    """A recognised place never needs the geocoder, on or off."""
    point = await geo.locate("Calle Mayor 3, Madrid")
    assert point is not None
