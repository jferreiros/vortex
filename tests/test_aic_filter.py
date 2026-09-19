"""AICFilter wiring stays off by default and never calls the vendor in tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from vortex import settings as settings_module
from vortex.line.aic_filter import AIC_MODEL_ID, build_audio_in_filter

AIC_ENV = ("VORTEX_AIC_FILTER", "AIC_SDK_LICENSE", "VORTEX_AIC_MODEL")


@pytest.fixture
def clean_aic_env(monkeypatch: pytest.MonkeyPatch):
    for key in AIC_ENV:
        monkeypatch.delenv(key, raising=False)
    settings_module.reset_settings()
    yield monkeypatch
    settings_module.reset_settings()


class FakeAICFilter:
    """Stand-in for pipecat's AICFilter: records constructor args, no SDK."""

    def __init__(self, *, license_key: str, model_id: str | None = None, **_: object) -> None:
        self.license_key = license_key
        self.model_id = model_id


def test_aic_filter_defaults_off(clean_aic_env) -> None:
    s = settings_module.get_settings()
    assert s.aic_filter_enabled is False
    assert s.aic_model_id == AIC_MODEL_ID
    assert build_audio_in_filter(s, filter_cls=FakeAICFilter) is None
    assert s.describe()["aic_filter"] == "off"


def test_aic_filter_on_without_license_stays_off(
    clean_aic_env, caplog: pytest.LogCaptureFixture
) -> None:
    clean_aic_env.setenv("VORTEX_AIC_FILTER", "on")
    settings_module.reset_settings()
    s = settings_module.get_settings()
    assert s.aic_filter_enabled is True
    with caplog.at_level("WARNING"):
        assert build_audio_in_filter(s, filter_cls=FakeAICFilter) is None
    assert "AIC_SDK_LICENSE" in caplog.text
    assert s.describe()["aic_filter"] == "off"


def test_aic_filter_builds_quail_8khz_when_enabled(clean_aic_env) -> None:
    clean_aic_env.setenv("VORTEX_AIC_FILTER", "on")
    clean_aic_env.setenv("AIC_SDK_LICENSE", "test-license-not-real")
    settings_module.reset_settings()
    s = settings_module.get_settings()
    filt = build_audio_in_filter(s, filter_cls=FakeAICFilter)
    assert isinstance(filt, FakeAICFilter)
    assert filt.license_key == "test-license-not-real"
    assert filt.model_id == "quail-ms-l-8khz"
    assert s.describe()["aic_filter"] == "on"


def test_aic_filter_model_override(clean_aic_env) -> None:
    clean_aic_env.setenv("VORTEX_AIC_FILTER", "true")
    clean_aic_env.setenv("AIC_SDK_LICENSE", "key")
    clean_aic_env.setenv("VORTEX_AIC_MODEL", "quail-ms-s-8khz")
    settings_module.reset_settings()
    s = settings_module.get_settings()
    filt = build_audio_in_filter(s, filter_cls=FakeAICFilter)
    assert filt is not None
    assert filt.model_id == "quail-ms-s-8khz"


def test_aic_filter_missing_extra_stays_off(
    clean_aic_env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = SimpleNamespace(
        aic_filter_enabled=True,
        aic_sdk_license="key",
        aic_model_id=AIC_MODEL_ID,
    )
    # Hide the real module so the builder's import fails without touching the vendor.
    monkeypatch.setitem(sys.modules, "pipecat.audio.filters.aic_filter", None)
    with caplog.at_level("WARNING"):
        assert build_audio_in_filter(settings, filter_cls=None) is None
    assert "aic" in caplog.text.lower()


def test_transport_params_accept_audio_in_filter() -> None:
    """Pipecat's Twilio transport params expose audio_in_filter (wiring target)."""
    pytest.importorskip("pipecat")
    from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

    class StubFilter(BaseAudioFilter):
        async def start(self, sample_rate: int) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def process_frame(self, frame: object) -> None:
            return None

        async def filter(self, audio: bytes) -> bytes:
            return audio

    stub = StubFilter()
    params = FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,
        audio_in_filter=stub,
    )
    assert params.audio_in_filter is stub


def test_real_aic_filter_constructs_without_network() -> None:
    """With aic-sdk installed, AICFilter accepts our model id (no download yet)."""
    pytest.importorskip("aic_sdk")
    from pipecat.audio.filters.aic_filter import AICFilter

    filt = AICFilter(license_key="test-license-not-real", model_id=AIC_MODEL_ID)
    assert filt is not None
