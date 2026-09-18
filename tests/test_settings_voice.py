"""Voice-provider gating: which keys turn the real pipeline on, per provider."""

from __future__ import annotations

import pytest

from vortex import settings as settings_module

VOICE_KEYS = (
    "SONIOX_API_KEY",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_TTS_CREDENTIALS_JSON",
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
        VORTEX_TTS_PROVIDER="azure",
        SONIOX_API_KEY="soniox-x",
        LLM_API_KEY="llm-x",
        LLM_BASE_URL="https://api.eu.groq.com/openai/v1",
    )
    assert s.tts_provider == "azure"
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
    assert s.tts_provider == "deepgram"
    assert s.tts_supports_language_switch is False
    assert s.voice_is_pipecat is False  # no Deepgram key yet

    s = _settings(clean_env, DEEPGRAM_API_KEY="dg-x")
    assert s.voice_is_pipecat is True

    # An Azure key is irrelevant while the provider is deepgram.
    s = _settings(clean_env, DEEPGRAM_API_KEY="", AZURE_SPEECH_KEY="azure-x")
    assert s.voice_is_pipecat is False


def test_llm_base_url_is_required(clean_env) -> None:
    s = _settings(
        clean_env,
        VORTEX_TTS_PROVIDER="azure",
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
            VORTEX_TTS_PROVIDER="azure",
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
    s = _settings(
        clean_env,
        VORTEX_TTS_PROVIDER="azure",
        LLM_BASE_URL="https://api.eu.groq.com/openai/v1",
        **secrets,
    )
    described = repr(s.describe())
    for value in secrets.values():
        assert value not in described
    assert s.describe()["has_soniox_key"] is True
    assert s.describe()["has_llm_key"] is True
    assert s.describe()["has_azure_speech_key"] is True
    assert s.describe()["tts_provider"] == "azure"


# --- Google, the default provider -------------------------------------------


def test_google_is_the_default_provider(clean_env) -> None:
    s = _settings(clean_env)
    assert s.tts_provider == "google"
    assert s.tts_supports_language_switch is True
    assert s.has_google_tts_credentials is False
    assert s.has_tts_key is False


def test_an_unknown_provider_falls_back_to_google(clean_env) -> None:
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="elevenlabs").tts_provider == "google"
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="").tts_provider == "google"
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="GOOGLE").tts_provider == "google"


def test_google_gates_on_the_credentials_path(clean_env) -> None:
    s = _settings(
        clean_env,
        SONIOX_API_KEY="soniox-x",
        LLM_API_KEY="llm-x",
        LLM_BASE_URL="https://api.eu.groq.com/openai/v1",
    )
    assert s.voice_is_pipecat is False  # no Google credentials yet

    s = _settings(clean_env, GOOGLE_APPLICATION_CREDENTIALS="google-tts.json")
    assert s.has_google_tts_credentials is True
    assert s.voice_is_pipecat is True

    # Neither of the other two keys stands in for the Google credentials.
    s = _settings(
        clean_env,
        GOOGLE_APPLICATION_CREDENTIALS="",
        AZURE_SPEECH_KEY="azure-x",
        DEEPGRAM_API_KEY="dg-x",
    )
    assert s.voice_is_pipecat is False


def test_inline_json_credentials_count_too(clean_env) -> None:
    s = _settings(
        clean_env,
        SONIOX_API_KEY="soniox-x",
        LLM_API_KEY="llm-x",
        LLM_BASE_URL="https://api.eu.groq.com/openai/v1",
        GOOGLE_TTS_CREDENTIALS_JSON='{"type": "service_account"}',
    )
    assert s.google_application_credentials == ""
    assert s.has_google_tts_credentials is True
    assert s.voice_is_pipecat is True


def test_google_voice_defaults_cover_the_four_languages(clean_env) -> None:
    s = _settings(clean_env)
    assert s.google_tts_voice_es == "es-ES-Chirp3-HD-Aoede"
    assert s.google_tts_voice_ca == "ca-ES-Standard-B"
    assert s.google_tts_voice_gl == "gl-ES-Standard-A"
    assert s.google_tts_voice_eu == "eu-ES-Standard-A"
    assert s.tts_voice == s.google_tts_voice_es


def test_describe_reports_google_without_the_credentials(clean_env) -> None:
    s = _settings(
        clean_env,
        GOOGLE_TTS_CREDENTIALS_JSON='{"private_key": "google-secret"}',
        GOOGLE_APPLICATION_CREDENTIALS="/secrets/google-tts.json",
    )
    described = s.describe()
    assert described["tts_provider"] == "google"
    assert described["tts_voice"] == s.google_tts_voice_es
    assert described["has_google_tts_credentials"] is True
    assert described["tts_language_switch"] is True
    assert described["azure_speech_region"] == ""
    text = repr(described)
    assert "google-secret" not in text
    assert "/secrets/google-tts.json" not in text


# --- tts_voice_for: the voice map, per provider ------------------------------


def test_google_voice_map_covers_es_ca_gl_eu(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import tts_voice_for

    s = _settings(clean_env)
    assert tts_voice_for("es", s) == (s.google_tts_voice_es, Language.ES_ES)
    assert tts_voice_for("ca", s) == (s.google_tts_voice_ca, Language.CA_ES)
    assert tts_voice_for("gl", s) == (s.google_tts_voice_gl, Language.GL_ES)
    assert tts_voice_for("eu", s) == (s.google_tts_voice_eu, Language.EU_ES)
    # A pipecat Language, a regional string and an unsupported one all fold.
    assert tts_voice_for(Language.CA_ES, s) == (s.google_tts_voice_ca, Language.CA_ES)
    assert tts_voice_for("gl-ES", s) == (s.google_tts_voice_gl, Language.GL_ES)
    assert tts_voice_for("de", s) == (s.google_tts_voice_es, Language.ES_ES)
    assert tts_voice_for("en", s) == (s.google_tts_voice_es, Language.ES_ES)


def test_azure_has_no_galician_or_basque_voice(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import tts_voice_for

    s = _settings(clean_env, VORTEX_TTS_PROVIDER="azure")
    assert tts_voice_for("ca", s) == (s.azure_tts_voice_ca, Language.CA_ES)
    # gl and eu fall back to Spanish: Azure has no voice for either.
    assert tts_voice_for("gl", s) == (s.azure_tts_voice_es, Language.ES_ES)
    assert tts_voice_for("eu", s) == (s.azure_tts_voice_es, Language.ES_ES)
    assert tts_voice_for("es", s) == (s.azure_tts_voice_es, Language.ES_ES)


def test_deepgram_says_everything_in_spanish(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import tts_voice_for

    s = _settings(clean_env, VORTEX_TTS_PROVIDER="deepgram")
    for code in ("es", "ca", "gl", "eu", "de"):
        assert tts_voice_for(code, s) == (s.deepgram_tts_model, Language.ES_ES)


def test_tts_voice_for_never_raises(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import tts_voice_for

    s = _settings(clean_env)
    assert tts_voice_for(None, s) == (s.google_tts_voice_es, Language.ES_ES)  # type: ignore[arg-type]
    # A settings stand-in with nothing on it still answers.
    assert tts_voice_for("ca", object()) == ("", Language.CA_ES)
