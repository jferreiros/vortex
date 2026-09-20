"""Provider selection from the environment: the LLM presets and the one TTS.

Nothing here touches the network. These tests pin the two things a teammate
changes without reading the code: which variable picks a provider, and which
key has to be present before the real pipeline turns on.
"""

from __future__ import annotations

import pytest

from vortex import settings as settings_module

VOICE_KEYS = (
    "SONIOX_API_KEY",
    "LLM_PROVIDER",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_MAX_TOKENS",
    "LLM_ALT_MODEL",
    "HELMCODE_BASE_URL",
    "HELMCODE_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "ARBITER_PROVIDER",
    "ARBITER_BASE_URL",
    "ARBITER_API_KEY",
    "ARBITER_MODEL",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID_ES",
    "ELEVENLABS_VOICE_ID_DEFAULT",
    "ELEVENLABS_MODEL",
    "ELEVENLABS_BASE_URL",
    "VORTEX_TTS_PROVIDER",
    "VORTEX_VOICE_MODE",
    "VORTEX_AIC_FILTER",
    "AIC_SDK_LICENSE",
    "VORTEX_AIC_MODEL",
    "VORTEX_GEOCODER",
    "VORTEX_GEOCODER_URL",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_TRACING_ENVIRONMENT",
    "HF_TOKEN",
    "VORTEX_ENV",
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


# --- LLM presets -------------------------------------------------------------


def test_helmcode_is_the_default_preset(clean_env) -> None:
    s = _settings(clean_env)
    assert s.llm_provider == "helmcode"
    assert s.llm_base_url == "https://api.helmcode.com/v1"
    # Not qwen3.6: it loops its tool calls and fails both problem-1 scenarios.
    assert s.llm_model == "deepseek-v4-flash"
    assert s.llm_api_key == ""  # no key yet


def test_azure_builds_the_openai_compatible_v1_base_url(clean_env) -> None:
    """Verified live on 20 Sep 2026: <endpoint>/openai/v1 with a bearer key."""
    s = _settings(
        clean_env,
        LLM_PROVIDER="azure",
        AZURE_OPENAI_ENDPOINT="https://hackspain-vortex.openai.azure.com",
        AZURE_OPENAI_API_KEY="az-x",
    )
    assert s.llm_base_url == "https://hackspain-vortex.openai.azure.com/openai/v1"
    assert s.llm_api_key == "az-x"
    # The deployment name is what Azure calls a model.
    assert s.llm_model == "gpt-4.1"
    assert _settings(clean_env, AZURE_OPENAI_DEPLOYMENT="gpt-4.1-mini").llm_model == "gpt-4.1-mini"
    # A trailing slash, and an endpoint that already carries the path, both fold.
    assert (
        _settings(
            clean_env, AZURE_OPENAI_ENDPOINT="https://hackspain-vortex.openai.azure.com/"
        ).llm_base_url
        == "https://hackspain-vortex.openai.azure.com/openai/v1"
    )
    assert (
        _settings(
            clean_env, AZURE_OPENAI_ENDPOINT="https://hackspain-vortex.openai.azure.com/openai/v1"
        ).llm_base_url
        == "https://hackspain-vortex.openai.azure.com/openai/v1"
    )


def test_azure_without_an_endpoint_has_no_base_url(clean_env) -> None:
    """Half an Azure URL would look configured and 404 on the first call."""
    s = _settings(clean_env, LLM_PROVIDER="azure", AZURE_OPENAI_API_KEY="az-x")
    assert s.llm_base_url == ""
    assert s.llm_api_key == "az-x"
    assert s.voice_is_pipecat is False


def test_helmcode_base_url_has_its_own_override(clean_env) -> None:
    s = _settings(clean_env, HELMCODE_BASE_URL="https://helm.example.invalid/v2")
    assert s.llm_base_url == "https://helm.example.invalid/v2"


def test_each_preset_reads_its_own_key_variable(clean_env) -> None:
    """Both keys can sit in one .env; the preset picks which one is used."""
    keys = {
        "HELMCODE_API_KEY": "helm-x",
        "AZURE_OPENAI_API_KEY": "az-x",
        "LLM_API_KEY": "",
    }
    assert _settings(clean_env, LLM_PROVIDER="helmcode", **keys).llm_api_key == "helm-x"
    assert _settings(clean_env, LLM_PROVIDER="azure").llm_api_key == "az-x"


def test_the_overrides_always_win(clean_env) -> None:
    s = _settings(
        clean_env,
        LLM_PROVIDER="azure",
        AZURE_OPENAI_API_KEY="az-x",
        LLM_BASE_URL="https://mine.example.invalid/v1",
        LLM_API_KEY="mine-x",
        LLM_MODEL="mine/model-1",
    )
    assert s.llm_base_url == "https://mine.example.invalid/v1"
    assert s.llm_api_key == "mine-x"
    assert s.llm_model == "mine/model-1"


def test_an_unknown_preset_falls_back_to_the_default(clean_env) -> None:
    assert _settings(clean_env, LLM_PROVIDER="nebius").llm_provider == "helmcode"
    assert _settings(clean_env, LLM_PROVIDER="").llm_provider == "helmcode"
    assert _settings(clean_env, LLM_PROVIDER="HELMCODE").llm_provider == "helmcode"


def test_the_arbiter_resolves_like_the_llm(clean_env) -> None:
    s = _settings(clean_env, HELMCODE_API_KEY="helm-x")
    assert s.arbiter_provider == "helmcode"
    assert s.arbiter_base_url == "https://api.helmcode.com/v1"
    assert s.arbiter_api_key == "helm-x"
    assert s.arbiter_model == "deepseek-v4-flash"

    s = _settings(
        clean_env,
        ARBITER_PROVIDER="azure",
        AZURE_OPENAI_ENDPOINT="https://judge.openai.azure.com",
        AZURE_OPENAI_API_KEY="az-x",
        ARBITER_MODEL="my/judge",
    )
    assert s.arbiter_base_url == "https://judge.openai.azure.com/openai/v1"
    assert s.arbiter_api_key == "az-x"
    assert s.arbiter_model == "my/judge"
    # The arbiter is its own choice: the chat model stays on its own preset.
    assert s.llm_provider == "helmcode"


def test_llm_max_tokens_defaults_to_320(clean_env) -> None:
    """120 cut off a nested-slot tool call mid-argument; 320 gives it room.

    Measured on qwen3.6: ``submit_action`` with a ``BookAction`` is 107 tokens
    and ``prepare_booking`` with a full ``Slot`` is 150, beside a spoken turn.
    """
    s = _settings(clean_env)
    assert s.llm_max_tokens == 320
    assert s.llm_alt_model == ""
    assert s.describe()["llm_max_tokens"] == 320
    assert s.describe()["llm_alt_model"] == ""

    s = _settings(clean_env, LLM_MAX_TOKENS="500")
    assert s.llm_max_tokens == 500
    assert s.describe()["llm_max_tokens"] == 500


def test_llm_max_tokens_below_the_booking_floor_is_raised_to_320(clean_env) -> None:
    """A leftover ``LLM_MAX_TOKENS=120`` in .env must not ship again.

    120 is enough for a spoken turn and too little for a nested-slot tool
    call. The floor is 256; anything under it becomes the 320 default so
    ``/health`` reports the value the line actually uses.
    """
    s = _settings(clean_env, LLM_MAX_TOKENS="120")
    assert s.llm_max_tokens == 320
    assert s.describe()["llm_max_tokens"] == 320

    s = _settings(clean_env, LLM_MAX_TOKENS="255")
    assert s.llm_max_tokens == 320

    s = _settings(clean_env, LLM_MAX_TOKENS="256")
    assert s.llm_max_tokens == 256


def test_llm_alt_model_can_be_cleared(clean_env) -> None:
    s = _settings(clean_env, LLM_ALT_MODEL="")
    assert s.llm_alt_model == ""
    assert s.describe()["llm_alt_model"] == ""

    s = _settings(clean_env, LLM_ALT_MODEL="glm5.3-flash")
    assert s.llm_alt_model == "glm5.3-flash"


def test_the_arbiter_overrides_win_too(clean_env) -> None:
    s = _settings(
        clean_env,
        ARBITER_BASE_URL="https://judge.example.invalid/v1",
        ARBITER_API_KEY="judge-x",
    )
    assert s.arbiter_base_url == "https://judge.example.invalid/v1"
    assert s.arbiter_api_key == "judge-x"


# --- voice gating ------------------------------------------------------------


def test_no_keys_means_stub(clean_env) -> None:
    assert _settings(clean_env).voice_is_pipecat is False


def test_a_missing_llm_base_url_keeps_the_stub(clean_env) -> None:
    s = _settings(
        clean_env,
        LLM_PROVIDER="azure",  # no endpoint -> no base URL
        AZURE_OPENAI_API_KEY="az-x",
        SONIOX_API_KEY="soniox-x",
        ELEVENLABS_API_KEY="el-x",
    )
    assert s.voice_is_pipecat is False
    assert (
        _settings(clean_env, AZURE_OPENAI_ENDPOINT="https://r.openai.azure.com").voice_is_pipecat
        is True
    )


def test_the_pipeline_gates_on_the_elevenlabs_key(clean_env) -> None:
    s = _settings(
        clean_env,
        SONIOX_API_KEY="soniox-x",
        HELMCODE_API_KEY="helm-x",
    )
    assert s.tts_provider == "elevenlabs"
    assert s.has_tts_key is False
    assert s.voice_is_pipecat is False

    s = _settings(clean_env, ELEVENLABS_API_KEY="el-x")
    assert s.has_tts_key is True
    assert s.voice_is_pipecat is True


def test_elevenlabs_is_the_only_provider_and_speaks_all_five(clean_env) -> None:
    s = _settings(clean_env)
    assert settings_module.TTS_PROVIDERS == ("elevenlabs",)
    assert s.tts_provider == "elevenlabs"
    assert sorted(s.tts_covered_languages) == ["ca", "en", "es", "eu", "gl"]
    # More than one language, so the pipeline always installs the watcher.
    assert s.tts_supports_language_switch is True
    assert s.has_tts_key is False


def test_an_unknown_provider_falls_back_to_elevenlabs(clean_env) -> None:
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="cartesia").tts_provider == "elevenlabs"
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="").tts_provider == "elevenlabs"
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="ELEVENLABS").tts_provider == "elevenlabs"


def test_voice_mode_overrides_the_keys(clean_env) -> None:
    assert _settings(clean_env, VORTEX_VOICE_MODE="pipecat").voice_is_pipecat is True
    assert (
        _settings(
            clean_env,
            VORTEX_VOICE_MODE="stub",
            SONIOX_API_KEY="soniox-x",
            HELMCODE_API_KEY="helm-x",
            ELEVENLABS_API_KEY="el-x",
        ).voice_is_pipecat
        is False
    )
    assert _settings(clean_env, VORTEX_VOICE_MODE="stub").voice_label == "stub"


def test_the_voice_preset_covers_every_language_and_both_genders(clean_env) -> None:
    """Voice ids are a preset in code, not a row of environment variables."""
    from vortex.conversation.language import SUPPORTED_LANGUAGES, VoicePreset

    s = _settings(clean_env)
    for code in SUPPORTED_LANGUAGES:
        row = VoicePreset[code.upper()]
        assert row.female.strip(), code
        assert row.male.strip(), code
        assert s.elevenlabs_voice_for(code) == row.female
        assert s.elevenlabs_voice_for(code, "male") == row.male
    assert s.tts_voice == VoicePreset.ES.female
    assert s.tts_voices_missing == []


def test_the_two_env_overrides_beat_the_preset(clean_env) -> None:
    from vortex.conversation.language import VoicePreset

    s = _settings(clean_env, ELEVENLABS_VOICE_ID_DEFAULT="voice-all")
    assert s.elevenlabs_voice_for("en") == "voice-all"
    assert s.elevenlabs_voice_for("es") == "voice-all"
    # Male stays on the preset: the switch never lands on a voice nobody chose.
    assert s.elevenlabs_voice_for("es", "male") == VoicePreset.ES.male

    s = _settings(clean_env, ELEVENLABS_VOICE_ID_ES="voice-es")
    assert s.elevenlabs_voice_for("es") == "voice-es"
    assert s.elevenlabs_voice_for("ca") == "voice-all"


def test_the_http_base_url_ignores_a_websocket_gateway(clean_env) -> None:
    """The pipeline speaks over the WebSocket API; pre-rendered MP3s do not."""
    assert _settings(clean_env).elevenlabs_http_base_url == "https://api.elevenlabs.io"
    assert (
        _settings(
            clean_env, ELEVENLABS_BASE_URL="wss://gw.example.invalid"
        ).elevenlabs_http_base_url
        == "https://api.elevenlabs.io"
    )
    assert (
        _settings(
            clean_env, ELEVENLABS_BASE_URL="https://gw.example.invalid/"
        ).elevenlabs_http_base_url
        == "https://gw.example.invalid"
    )


# --- geocoder ----------------------------------------------------------------


def test_geocoder_is_off_by_default(clean_env) -> None:
    """Off by default: evals and offline work never depend on a network call."""
    s = _settings(clean_env)
    assert s.geocoder == ""
    assert s.geocoder_url == ""


def test_geocoder_reads_cartociudad_and_nominatim_url(clean_env) -> None:
    s = _settings(clean_env, VORTEX_GEOCODER="cartociudad")
    assert s.geocoder == "cartociudad"
    s = _settings(
        clean_env,
        VORTEX_GEOCODER="nominatim",
        VORTEX_GEOCODER_URL="https://nominatim.example.invalid/search",
    )
    assert s.geocoder == "nominatim"
    assert s.geocoder_url == "https://nominatim.example.invalid/search"


def test_geocoder_url_reads_the_env_var(clean_env) -> None:
    s = _settings(clean_env, VORTEX_GEOCODER_URL="https://nominatim.example.invalid/search")
    assert s.geocoder_url == "https://nominatim.example.invalid/search"


# --- describe() --------------------------------------------------------------


def test_describe_never_leaks_a_key(clean_env) -> None:
    secrets = {
        "PLATFORM_API_KEY": "platform-secret",
        "SONIOX_API_KEY": "soniox-secret",
        "HELMCODE_API_KEY": "helmcode-secret",
        "AZURE_OPENAI_API_KEY": "azure-secret",
        "ELEVENLABS_API_KEY": "elevenlabs-secret",
        "ARBITER_API_KEY": "arbiter-secret",
        "TYPESAFE_API_KEY": "typesafe-secret",
        "LANGFUSE_PUBLIC_KEY": "pk-lf-secret",
        "LANGFUSE_SECRET_KEY": "sk-lf-secret",
        "HF_TOKEN": "hf-secret",
        "SUPABASE_URL": "https://xxxx.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "supabase-service-secret",
    }
    s = _settings(clean_env, **secrets)
    described = s.describe()
    text = repr(described)
    for value in secrets.values():
        assert value not in text
    assert described["has_soniox_key"] is True
    assert described["has_llm_key"] is True
    assert described["has_elevenlabs_key"] is True
    assert described["has_arbiter_key"] is True
    assert described["has_typesafe_key"] is True
    assert described["jev_arbiter"] is False
    assert described["has_langfuse_keys"] is True
    assert described["has_supabase"] is True
    assert described["has_hf_token"] is True
    assert described["llm_provider"] == "helmcode"
    assert described["tts_provider"] == "elevenlabs"
    assert described["tts_model"] == "eleven_flash_v2_5"


def test_describe_reports_the_voice_without_a_key(clean_env) -> None:
    s = _settings(clean_env)
    described = s.describe()
    assert described["tts_provider"] == "elevenlabs"
    assert described["tts_voice"] == s.tts_voice_es()
    assert described["has_elevenlabs_key"] is False
    assert described["tts_language_switch"] is True
    assert described["tts_languages"] == ["ca", "en", "es", "eu", "gl"]


# --- tts_voice_for: the voice map --------------------------------------------


def test_the_voice_map_covers_every_language(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import VoicePreset, tts_voice_for

    s = _settings(clean_env, ELEVENLABS_VOICE_ID_DEFAULT="voice-1")
    # ElevenLabs takes a bare code, not the regional one.
    assert tts_voice_for("es", s) == ("voice-1", Language.ES)
    assert tts_voice_for("en", s) == ("voice-1", Language.EN)
    assert tts_voice_for("ca", s) == ("voice-1", Language.CA)
    assert tts_voice_for("gl", s) == ("voice-1", Language.GL)
    assert tts_voice_for("eu", s) == ("voice-1", Language.EU)
    # A pipecat Language and a regional string both fold to our code.
    assert tts_voice_for(Language.CA_ES, s) == ("voice-1", Language.CA)
    assert tts_voice_for("gl-ES", s) == ("voice-1", Language.GL)
    # Anything outside the five falls back to English, the clinic's default.
    assert tts_voice_for("de", s) == ("voice-1", Language.EN)
    # The male column comes from the preset.
    assert tts_voice_for("es", s, gender="male") == (VoicePreset.ES.male, Language.ES)


def test_tts_voice_for_never_raises(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import VoicePreset, tts_voice_for

    s = _settings(clean_env)
    assert tts_voice_for(None, s) == (VoicePreset.EN.female, Language.EN)  # type: ignore[arg-type]
    # A settings stand-in with nothing on it still answers, off the preset.
    assert tts_voice_for("ca", object()) == (VoicePreset.CA.female, Language.CA)
