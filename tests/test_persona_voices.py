"""Persona voices steer only the Google HTTP adapter, not ElevenLabs."""

import pytest

from vortex import settings as settings_module
from vortex.line import personalities
from vortex.line.pipecat_voice import _make_tts, _persona_voice


class _State:
    language = "es"


@pytest.fixture
def voice_settings(monkeypatch):
    keys = (
        "VORTEX_TTS_PROVIDER", "VORTEX_TTS_HTTP_BASE_URL", "ELEVENLABS_API_KEY",
        "ELEVENLABS_MODEL", "ELEVENLABS_VOICE_ID_ES", "ELEVENLABS_VOICE_ID_DEFAULT",
        "ELEVENLABS_BASE_URL",
    )
    def build(**env):
        for key in keys:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        settings_module.reset_settings()
        return settings_module.get_settings()
    yield build
    settings_module.reset_settings()


@pytest.fixture
def google_persona():
    return personalities.Personality(
        slug="lucia",
        name="Lucía",
        role="Recepcionista de mostrador",
        description="Warm front desk.",
        tone="Warm.",
        greetings={},
        voices={
            "es": "es-ES-Chirp3-HD-Kore",
            "en": "en-US-Chirp3-HD-Kore",
        },
        elevenlabs_voices={
            "es": "eleven-lucia-es",
            "en": "eleven-lucia-en",
        },
        avatar="headset.svg",
    )


def test_persona_voice_picks_google_language_and_fallback(voice_settings, google_persona):
    settings = voice_settings(VORTEX_TTS_HTTP_BASE_URL="http://127.0.0.1:8799")
    assert _persona_voice(google_persona, "es", settings) == "es-ES-Chirp3-HD-Kore"
    assert _persona_voice(google_persona, "gl", settings) == "es-ES-Chirp3-HD-Kore"
    assert _persona_voice(None, "es", settings) == ""


def test_stock_elevenlabs_uses_its_own_persona_map(voice_settings, google_persona):
    settings = voice_settings(ELEVENLABS_API_KEY="el-x")
    assert _persona_voice(google_persona, "es", settings) == "eleven-lucia-es"
    assert _persona_voice(google_persona, "en", settings) == "eleven-lucia-en"


def test_google_adapter_uses_persona_voice(voice_settings, google_persona):
    pytest.importorskip("pipecat")
    from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService

    settings = voice_settings(
        VORTEX_TTS_HTTP_BASE_URL="http://127.0.0.1:8799",
        ELEVENLABS_VOICE_ID_DEFAULT="opaque-provider-id",
    )
    tts = _make_tts(settings, state=_State(), persona=google_persona)
    assert isinstance(tts, ElevenLabsHttpTTSService)
    assert tts._settings.voice == "es-ES-Chirp3-HD-Kore"


def test_elevenlabs_keeps_its_own_voice(voice_settings, google_persona):
    pytest.importorskip("pipecat")
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    settings = voice_settings(
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_DEFAULT="eleven-global-id",
    )
    tts = _make_tts(settings, state=_State(), persona=google_persona)
    assert isinstance(tts, ElevenLabsTTSService)
    assert tts._settings.voice == "eleven-lucia-es"
