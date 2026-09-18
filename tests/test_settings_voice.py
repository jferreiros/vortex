"""Voice-provider gating: which keys turn the real pipeline on, per provider."""

from __future__ import annotations

import pytest

from vortex import settings as settings_module

VOICE_KEYS = (
    "SONIOX_API_KEY",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "AZURE_SPEECH_KEY",
    "DEEPGRAM_API_KEY",
    "VORTEX_TTS_PROVIDER",
    "VORTEX_VOICE_MODE",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for key in VOICE_KEYS:
        monkeypatch.delenv(key, raising=False)
    settings_module.reset_settings()
    yield monkeypatch
    settings_module.reset_settings()


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> settings_module.Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings_module.reset_settings()
    return settings_module.get_settings()


def test_no_keys_means_stub(clean_env) -> None:
    assert _settings(clean_env).voice_is_pipecat is False


def test_azure_needs_all_four_keys(clean_env) -> None:
    s = _settings(
        clean_env,
        SONIOX_API_KEY="soniox-x",
        LLM_API_KEY="llm-x",
        LLM_BASE_URL="https://api.eu.groq.com/openai/v1",
    )
    assert s.tts_is_azure is True
    assert s.voice_is_pipecat is False  # no Azure key yet

    s = _settings(clean_env, AZURE_SPEECH_KEY="azure-x")
    assert s.voice_is_pipecat is True

    # A Deepgram key does not stand in for the Azure one.
    s = _settings(clean_env, AZURE_SPEECH_KEY="", DEEPGRAM_API_KEY="dg-x")
    assert s.voice_is_pipecat is False


def test_deepgram_provider_gates_on_the_deepgram_key(clean_env) -> None:
    s = _settings(
        clean_env,
        VORTEX_TTS_PROVIDER="deepgram",
        SONIOX_API_KEY="soniox-x",
        LLM_API_KEY="llm-x",
        LLM_BASE_URL="https://api.eu.groq.com/openai/v1",
    )
    assert s.tts_is_azure is False
    assert s.voice_is_pipecat is False  # no Deepgram key yet

    s = _settings(clean_env, DEEPGRAM_API_KEY="dg-x")
    assert s.voice_is_pipecat is True

    # An Azure key is irrelevant while the provider is deepgram.
    s = _settings(clean_env, DEEPGRAM_API_KEY="", AZURE_SPEECH_KEY="azure-x")
    assert s.voice_is_pipecat is False


def test_llm_base_url_is_required(clean_env) -> None:
    s = _settings(
        clean_env,
        SONIOX_API_KEY="soniox-x",
        LLM_API_KEY="llm-x",
        AZURE_SPEECH_KEY="azure-x",
    )
    assert s.voice_is_pipecat is False


def test_voice_mode_overrides_the_keys(clean_env) -> None:
    assert _settings(clean_env, VORTEX_VOICE_MODE="pipecat").voice_is_pipecat is True
    assert (
        _settings(
            clean_env,
            VORTEX_VOICE_MODE="stub",
            SONIOX_API_KEY="soniox-x",
            LLM_API_KEY="llm-x",
            LLM_BASE_URL="https://example.invalid/v1",
            AZURE_SPEECH_KEY="azure-x",
        ).voice_is_pipecat
        is False
    )


def test_describe_never_leaks_a_key(clean_env) -> None:
    secrets = {
        "PLATFORM_API_KEY": "platform-secret",
        "SONIOX_API_KEY": "soniox-secret",
        "LLM_API_KEY": "llm-secret",
        "AZURE_SPEECH_KEY": "azure-secret",
        "DEEPGRAM_API_KEY": "deepgram-secret",
    }
    s = _settings(clean_env, LLM_BASE_URL="https://api.eu.groq.com/openai/v1", **secrets)
    described = repr(s.describe())
    for value in secrets.values():
        assert value not in described
    assert s.describe()["has_soniox_key"] is True
    assert s.describe()["has_llm_key"] is True
    assert s.describe()["has_azure_speech_key"] is True
    assert s.describe()["tts_provider"] == "azure"
