"""Provider selection from the environment: LLM presets and the TTS pair.

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
    "HELMCODE_BASE_URL",
    "HELMCODE_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "VERCEL_AI_GATEWAY_KEY",
    "ARBITER_PROVIDER",
    "ARBITER_BASE_URL",
    "ARBITER_API_KEY",
    "ARBITER_MODEL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_TTS_CREDENTIALS_JSON",
    "GOOGLE_TTS_VOICE_EN",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID_ES",
    "ELEVENLABS_MODEL",
    "ELEVENLABS_BASE_URL",
    "VORTEX_TTS_PROVIDER",
    "VORTEX_TTS_PROVIDER_ALT",
    "VORTEX_VOICE_MODE",
    "VORTEX_GEOCODER_URL",
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
    assert s.llm_model == "qwen3.6"
    assert s.llm_api_key == ""  # no key yet


def test_each_preset_fills_base_url_and_model(clean_env) -> None:
    s = _settings(clean_env, LLM_PROVIDER="custom")
    assert s.llm_base_url == ""  # custom brings its own
    assert s.llm_model == "Qwen/Qwen3-30B-A3B-Instruct-2507"

    s = _settings(clean_env, LLM_PROVIDER="vercel")
    assert s.llm_base_url == "https://ai-gateway.vercel.sh/v1"
    assert s.llm_model == "anthropic/claude-haiku-4.5"

    s = _settings(clean_env, LLM_PROVIDER="cloudflare", CLOUDFLARE_ACCOUNT_ID="acc-123")
    assert s.llm_base_url == "https://api.cloudflare.com/client/v4/accounts/acc-123/ai/v1"
    assert s.llm_model == "@cf/qwen/qwen3-30b-a3b-fp8"


def test_cloudflare_without_an_account_id_has_no_base_url(clean_env) -> None:
    """Half a Cloudflare URL would look configured and 404 on the first call."""
    s = _settings(clean_env, LLM_PROVIDER="cloudflare", CLOUDFLARE_API_TOKEN="cf-x")
    assert s.llm_base_url == ""
    assert s.llm_api_key == "cf-x"
    assert s.voice_is_pipecat is False


def test_helmcode_base_url_has_its_own_override(clean_env) -> None:
    s = _settings(clean_env, HELMCODE_BASE_URL="https://helm.example.invalid/v2")
    assert s.llm_base_url == "https://helm.example.invalid/v2"


def test_each_preset_reads_its_own_key_variable(clean_env) -> None:
    """All four keys can sit in one .env; the preset picks which one is used."""
    keys = {
        "HELMCODE_API_KEY": "helm-x",
        "CLOUDFLARE_API_TOKEN": "cf-x",
        "VERCEL_AI_GATEWAY_KEY": "vercel-x",
        "LLM_API_KEY": "",
    }
    assert _settings(clean_env, LLM_PROVIDER="helmcode", **keys).llm_api_key == "helm-x"
    assert _settings(clean_env, LLM_PROVIDER="cloudflare").llm_api_key == "cf-x"
    assert _settings(clean_env, LLM_PROVIDER="vercel").llm_api_key == "vercel-x"
    assert _settings(clean_env, LLM_PROVIDER="custom").llm_api_key == ""


def test_the_overrides_always_win(clean_env) -> None:
    s = _settings(
        clean_env,
        LLM_PROVIDER="vercel",
        VERCEL_AI_GATEWAY_KEY="vercel-x",
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
        ARBITER_PROVIDER="cloudflare",
        CLOUDFLARE_ACCOUNT_ID="acc-9",
        CLOUDFLARE_API_TOKEN="cf-x",
        ARBITER_MODEL="my/judge",
    )
    assert s.arbiter_base_url == "https://api.cloudflare.com/client/v4/accounts/acc-9/ai/v1"
    assert s.arbiter_api_key == "cf-x"
    assert s.arbiter_model == "my/judge"
    # The arbiter is its own choice: the chat model stays on its own preset.
    assert s.llm_provider == "helmcode"


def test_llm_max_tokens_defaults_to_300(clean_env) -> None:
    """120 cut off a nested-slot tool call mid-argument; 300 gives it room."""
    s = _settings(clean_env)
    assert s.llm_max_tokens == 300

    s = _settings(clean_env, LLM_MAX_TOKENS="500")
    assert s.llm_max_tokens == 500


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


def test_google_gates_on_the_credentials_path(clean_env) -> None:
    s = _settings(
        clean_env,
        SONIOX_API_KEY="soniox-x",
        HELMCODE_API_KEY="helm-x",
    )
    assert s.voice_is_pipecat is False  # no Google credentials yet

    s = _settings(clean_env, GOOGLE_APPLICATION_CREDENTIALS="google-tts.json")
    assert s.has_google_tts_credentials is True
    assert s.voice_is_pipecat is True

    # An ElevenLabs key does not stand in for the Google credentials.
    s = _settings(clean_env, GOOGLE_APPLICATION_CREDENTIALS="", ELEVENLABS_API_KEY="el-x")
    assert s.voice_is_pipecat is False


def test_inline_json_credentials_count_too(clean_env) -> None:
    s = _settings(
        clean_env,
        SONIOX_API_KEY="soniox-x",
        HELMCODE_API_KEY="helm-x",
        GOOGLE_TTS_CREDENTIALS_JSON='{"type": "service_account"}',
    )
    assert s.google_application_credentials == ""
    assert s.has_google_tts_credentials is True
    assert s.voice_is_pipecat is True


def test_a_missing_llm_base_url_keeps_the_stub(clean_env) -> None:
    s = _settings(
        clean_env,
        LLM_PROVIDER="cloudflare",  # no account id -> no base URL
        CLOUDFLARE_API_TOKEN="cf-x",
        SONIOX_API_KEY="soniox-x",
        GOOGLE_APPLICATION_CREDENTIALS="google-tts.json",
    )
    assert s.voice_is_pipecat is False
    assert _settings(clean_env, CLOUDFLARE_ACCOUNT_ID="acc-1").voice_is_pipecat is True


def test_elevenlabs_gates_on_the_elevenlabs_key(clean_env) -> None:
    s = _settings(
        clean_env,
        VORTEX_TTS_PROVIDER="elevenlabs",
        VORTEX_TTS_PROVIDER_ALT="elevenlabs",
        SONIOX_API_KEY="soniox-x",
        HELMCODE_API_KEY="helm-x",
        GOOGLE_APPLICATION_CREDENTIALS="google-tts.json",
    )
    assert s.tts_provider == "elevenlabs"
    assert s.tts_is_routed is False
    # Spanish only, so there is nothing to switch to.
    assert s.tts_supports_language_switch is False
    assert s.voice_is_pipecat is False  # the Google credentials are irrelevant here

    s = _settings(clean_env, ELEVENLABS_API_KEY="el-x")
    assert s.voice_is_pipecat is True


def test_a_routed_pair_needs_both_keys(clean_env) -> None:
    s = _settings(
        clean_env,
        VORTEX_TTS_PROVIDER="elevenlabs",  # ALT defaults to google
        SONIOX_API_KEY="soniox-x",
        HELMCODE_API_KEY="helm-x",
        ELEVENLABS_API_KEY="el-x",
    )
    assert s.tts_is_routed is True
    assert s.tts_providers_in_use == ("elevenlabs", "google")
    assert s.voice_is_pipecat is False  # the alternate has no credentials

    s = _settings(clean_env, GOOGLE_APPLICATION_CREDENTIALS="google-tts.json")
    assert s.voice_is_pipecat is True
    assert s.tts_supports_language_switch is True
    assert sorted(s.tts_covered_languages) == ["ca", "en", "es", "eu", "gl"]


def test_an_unknown_provider_falls_back_to_google(clean_env) -> None:
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="cartesia").tts_provider == "google"
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="").tts_provider == "google"
    assert _settings(clean_env, VORTEX_TTS_PROVIDER="GOOGLE").tts_provider == "google"
    assert _settings(clean_env, VORTEX_TTS_PROVIDER_ALT="azure").tts_provider_alt == "google"


def test_google_is_the_default_on_both_sides(clean_env) -> None:
    s = _settings(clean_env)
    assert s.tts_provider == "google"
    assert s.tts_provider_alt == "google"
    assert s.tts_is_routed is False
    assert s.tts_supports_language_switch is True
    assert s.has_google_tts_credentials is False
    assert s.has_tts_key is False


def test_which_provider_speaks_which_language(clean_env) -> None:
    s = _settings(clean_env, VORTEX_TTS_PROVIDER="elevenlabs")  # ALT google
    assert s.tts_provider_for("es") == "elevenlabs"
    for code in ("ca", "gl", "eu"):
        assert s.tts_provider_for(code) == "google"
    # A language neither covers stays with the primary, which answers in Spanish.
    assert s.tts_provider_for("de") == "elevenlabs"

    s = _settings(clean_env, VORTEX_TTS_PROVIDER="google", VORTEX_TTS_PROVIDER_ALT="google")
    for code in ("es", "ca", "gl", "eu", "de"):
        assert s.tts_provider_for(code) == "google"


def test_voice_mode_overrides_the_keys(clean_env) -> None:
    assert _settings(clean_env, VORTEX_VOICE_MODE="pipecat").voice_is_pipecat is True
    assert (
        _settings(
            clean_env,
            VORTEX_VOICE_MODE="stub",
            SONIOX_API_KEY="soniox-x",
            HELMCODE_API_KEY="helm-x",
            GOOGLE_APPLICATION_CREDENTIALS="google-tts.json",
        ).voice_is_pipecat
        is False
    )


def test_google_voice_defaults_cover_the_five_languages(clean_env) -> None:
    s = _settings(clean_env)
    assert s.google_tts_voice_en == "en-GB-Chirp3-HD-Aoede"
    assert s.google_tts_voice_es == "es-ES-Chirp3-HD-Aoede"
    assert s.google_tts_voice_ca == "ca-ES-Standard-B"
    assert s.google_tts_voice_gl == "gl-ES-Standard-A"
    assert s.google_tts_voice_eu == "eu-ES-Standard-A"
    assert s.tts_voice == s.google_tts_voice_es


def test_google_speaks_english_and_it_can_be_overridden(clean_env) -> None:
    """69 of 73 published cases are English; google must cover it out of the box."""
    s = _settings(clean_env)
    assert "en" in s.tts_languages("google")
    assert s.tts_provider_for("en") == "google"

    s = _settings(clean_env, GOOGLE_TTS_VOICE_EN="en-US-Chirp3-HD-Puck")
    assert s.google_tts_voice_en == "en-US-Chirp3-HD-Puck"


def test_elevenlabs_has_no_default_voice(clean_env) -> None:
    s = _settings(clean_env, VORTEX_TTS_PROVIDER="elevenlabs", ELEVENLABS_API_KEY="el-x")
    assert s.elevenlabs_model == "eleven_flash_v2_5"
    assert s.tts_voice == ""
    assert s.tts_voices_missing == ["elevenlabs"]
    assert s.describe()["tts_voices_missing"] == ["elevenlabs"]

    s = _settings(clean_env, ELEVENLABS_VOICE_ID_ES="voice-1")
    assert s.tts_voice == "voice-1"
    assert s.tts_voices_missing == []


# --- geocoder ----------------------------------------------------------------


def test_geocoder_url_is_off_by_default(clean_env) -> None:
    """Off by default: evals and offline work never depend on a network call."""
    s = _settings(clean_env)
    assert s.geocoder_url == ""


def test_geocoder_url_reads_the_env_var(clean_env) -> None:
    s = _settings(clean_env, VORTEX_GEOCODER_URL="https://nominatim.example.invalid/search")
    assert s.geocoder_url == "https://nominatim.example.invalid/search"


# --- describe() --------------------------------------------------------------


def test_describe_never_leaks_a_key(clean_env) -> None:
    secrets = {
        "PLATFORM_API_KEY": "platform-secret",
        "SONIOX_API_KEY": "soniox-secret",
        "HELMCODE_API_KEY": "helmcode-secret",
        "ELEVENLABS_API_KEY": "elevenlabs-secret",
        "ARBITER_API_KEY": "arbiter-secret",
    }
    s = _settings(clean_env, VORTEX_TTS_PROVIDER="elevenlabs", **secrets)
    described = s.describe()
    text = repr(described)
    for value in secrets.values():
        assert value not in text
    assert described["has_soniox_key"] is True
    assert described["has_llm_key"] is True
    assert described["has_elevenlabs_key"] is True
    assert described["has_arbiter_key"] is True
    assert described["llm_provider"] == "helmcode"
    assert described["tts_provider"] == "elevenlabs"
    assert described["tts_provider_alt"] == "google"
    assert described["tts_routed"] is True


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
    assert described["tts_languages"] == ["ca", "en", "es", "eu", "gl"]
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
    # English is the clinic's default: it has its own voice, and it is the
    # fallback for anything unsupported.
    from vortex.conversation.language import DEFAULT_GOOGLE_VOICE_EN

    assert tts_voice_for("en", s) == (DEFAULT_GOOGLE_VOICE_EN, Language.EN_GB)
    assert tts_voice_for("de", s) == (DEFAULT_GOOGLE_VOICE_EN, Language.EN_GB)
    # A configured GOOGLE_TTS_VOICE_EN wins over the language module's fallback.
    s = _settings(clean_env, GOOGLE_TTS_VOICE_EN="en-US-Chirp3-HD-Puck")
    assert tts_voice_for("en", s) == ("en-US-Chirp3-HD-Puck", Language.EN_GB)


def test_elevenlabs_says_english_and_spanish_with_one_voice(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import tts_voice_for

    s = _settings(clean_env, VORTEX_TTS_PROVIDER="elevenlabs", ELEVENLABS_VOICE_ID_ES="voice-1")
    # ElevenLabs takes a bare code, not the regional one; its voices are
    # multilingual, so the one id speaks Spanish and English.
    assert tts_voice_for("es", s) == ("voice-1", Language.ES)
    assert tts_voice_for("en", s) == ("voice-1", Language.EN)
    # What it cannot say falls back to English, the clinic's default.
    for code in ("ca", "gl", "eu", "de"):
        assert tts_voice_for(code, s) == ("voice-1", Language.EN)


def test_the_provider_argument_overrides_the_primary(clean_env) -> None:
    """A routed call asks for the provider that serves the language, not the primary."""
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import tts_voice_for

    s = _settings(clean_env, VORTEX_TTS_PROVIDER="elevenlabs", ELEVENLABS_VOICE_ID_ES="voice-1")
    assert tts_voice_for("es", s, s.tts_provider_for("es")) == ("voice-1", Language.ES)
    assert tts_voice_for("ca", s, s.tts_provider_for("ca")) == (
        s.google_tts_voice_ca,
        Language.CA_ES,
    )
    assert tts_voice_for("gl", s, "google") == (s.google_tts_voice_gl, Language.GL_ES)
    # An unknown provider name reads the Google map rather than raising.
    assert tts_voice_for("ca", s, "nope") == (s.google_tts_voice_ca, Language.CA_ES)


def test_tts_voice_for_never_raises(clean_env) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import DEFAULT_GOOGLE_VOICE_EN, tts_voice_for

    s = _settings(clean_env)
    assert tts_voice_for(None, s) == (DEFAULT_GOOGLE_VOICE_EN, Language.EN_GB)  # type: ignore[arg-type]
    # A settings stand-in with nothing on it still answers.
    assert tts_voice_for("ca", object()) == ("", Language.CA_ES)
