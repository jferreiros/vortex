"""Process-wide settings, read once from the environment.

Every value has a default that works with no key configured. When a key is
missing, the matching component runs in fake mode:

- no ``PLATFORM_API_KEY``  -> fake clinic data and a dry-run submit client
- no voice keys            -> the stub voice pipeline (beeps, no STT/LLM/TTS)

The voice pipeline is Soniox for STT, any OpenAI-compatible endpoint for the
LLM (picked with ``LLM_PROVIDER``), and Google Cloud TTS or ElevenLabs for the
voice.

Two ideas make every provider swappable from ``.env`` alone:

- **LLM presets.** ``LLM_PROVIDER`` names a preset that fills in the base URL,
  the key variable and the model id. ``LLM_BASE_URL`` / ``LLM_API_KEY`` /
  ``LLM_MODEL`` always win when set, so a preset is a shortcut, never a cage.
  Each preset reads its *own* key variable, so several can sit in one ``.env``.
- **A primary and an alternate TTS.** ``VORTEX_TTS_PROVIDER`` speaks Spanish;
  ``VORTEX_TTS_PROVIDER_ALT`` speaks whatever the primary cannot. With both on
  ``google`` (the default) English/Spanish ride Chirp 3 HD and ca/gl/eu ride
  Gemini-TTS, unless ``GOOGLE_TTS_STANDARD_FALLBACK`` restores Standard-*.

UNVERIFIED markers below flag base URLs and model ids nobody has called yet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- LLM presets -------------------------------------------------------------


@dataclass(frozen=True)
class LlmPreset:
    """One OpenAI-compatible endpoint: where it lives, which key, which model.

    ``base_url`` is empty for presets whose URL is assembled elsewhere
    (``custom`` reads it from the environment, ``cloudflare`` and ``helmcode``
    are built in :meth:`Settings._preset_base_url`).
    """

    base_url: str
    key_field: str
    model: str


# UNVERIFIED: Cloudflare's OpenAI-compatible path for Workers AI. The account id
# is the one from the dashboard URL.
CLOUDFLARE_LLM_BASE_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
# Confirmed from https://helmcode.com/docs/integrations (18 Sep 2026).
HELMCODE_BASE_URL = "https://api.helmcode.com/v1"

LLM_PRESETS: dict[str, LlmPreset] = {
    # Bring your own endpoint: the three LLM_* variables and nothing else.
    "custom": LlmPreset("", "llm_api_key_env", "Qwen/Qwen3-30B-A3B-Instruct-2507"),
    # Hackathon perk: 600M tokens. deepseek-v4-flash, not the faster qwen3.6:
    # measured on 2026-09-19, qwen3.6 fails both problem-1 scenarios. It loops
    # prepare_booking and submit_action for 20 tool calls against a cap of 12,
    # submits nothing, and the session fallback sends no-action. deepseek-v4-flash
    # passes both, in a third of the time and a quarter of the tokens.
    "helmcode": LlmPreset("", "helmcode_api_key", "deepseek-v4-flash"),
    # Hackathon perk: $100 of AI Gateway. UNVERIFIED model id.
    "cloudflare": LlmPreset(
        CLOUDFLARE_LLM_BASE_URL, "cloudflare_api_token", "@cf/qwen/qwen3-30b-a3b-fp8"
    ),
    # Hackathon perk: $50 of AI Gateway.
    "vercel": LlmPreset(
        "https://ai-gateway.vercel.sh/v1", "vercel_ai_gateway_key", "anthropic/claude-haiku-4.5"
    ),
}

DEFAULT_LLM_PROVIDER = "helmcode"
# The arbiter reads the whole call after the hangup, so it can afford a bigger
# model than the one answering the phone. deepseek-v4-flash reasons on its own
# schedule (cannot be switched off), which is fine after the hangup.
DEFAULT_ARBITER_PROVIDER = "helmcode"
DEFAULT_ARBITER_MODEL = "deepseek-v4-flash"


def _llm_provider(var: str, default: str) -> str:
    """Fold an ``LLM_PROVIDER``-shaped variable to a known preset."""
    name = _env(var, default).lower()
    return name if name in LLM_PRESETS else default


# --- TTS providers -----------------------------------------------------------

TTS_PROVIDERS: tuple[str, ...] = ("google", "elevenlabs")
DEFAULT_TTS_PROVIDER = "google"

# Which languages each provider can actually say. Google carries English plus
# the three co-official languages; ElevenLabs is here for Spanish.
TTS_LANGUAGES: dict[str, frozenset[str]] = {
    "google": frozenset({"en", "es", "ca", "gl", "eu"}),
    "elevenlabs": frozenset({"es"}),
}


def _tts_provider(var: str = "VORTEX_TTS_PROVIDER") -> str:
    """Fold a TTS provider variable to a known provider. Anything odd -> google."""
    name = _env(var, DEFAULT_TTS_PROVIDER).lower()
    return name if name in TTS_PROVIDERS else DEFAULT_TTS_PROVIDER


def _env_flag(name: str, default: str = "false") -> bool:
    """Truthy for 1/true/yes/on; everything else is false."""
    return _env(name, default).lower() in ("1", "true", "yes", "on")


# Chirp 3 HD has no ca/gl/eu. Gemini-TTS does (Preview). Short names match the
# Spanish Chirp identity (Aoede). Standard-* only when the fallback flag is on.
DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-tts"
DEFAULT_GEMINI_TTS_VOICE = "Aoede"
GOOGLE_TTS_STANDARD_CA = "ca-ES-Standard-B"
GOOGLE_TTS_STANDARD_GL = "gl-ES-Standard-A"
GOOGLE_TTS_STANDARD_EU = "eu-ES-Standard-A"
# Languages that leave Chirp and speak through GeminiTTSService.
GEMINI_TTS_LANGUAGES: frozenset[str] = frozenset({"ca", "gl", "eu"})


def _google_tts_voice_coofficial(env_var: str, standard_default: str) -> str:
    """Gemini short name by default; Standard-* when GOOGLE_TTS_STANDARD_FALLBACK."""
    if _env_flag("GOOGLE_TTS_STANDARD_FALLBACK"):
        return _env(env_var, standard_default)
    return _env(env_var, DEFAULT_GEMINI_TTS_VOICE)


@dataclass(frozen=True)
class Settings:
    # Platform (the organisers' API: clinic reads + submit routes)
    platform_api_key: str = field(default_factory=lambda: _env("PLATFORM_API_KEY"))
    platform_api_base_url: str = field(
        default_factory=lambda: _env("PLATFORM_API_BASE_URL", "http://localhost:9999")
    )

    # --- STT: Soniox real-time ------------------------------------------------
    soniox_api_key: str = field(default_factory=lambda: _env("SONIOX_API_KEY"))
    soniox_stt_model: str = field(default_factory=lambda: _env("SONIOX_STT_MODEL", "stt-rt-v5"))

    # --- LLM: a preset, or the raw LLM_* variables ----------------------------
    # LLM_PROVIDER: custom | helmcode | cloudflare | vercel (unknown -> helmcode)
    llm_provider: str = field(
        default_factory=lambda: _llm_provider("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)
    )
    # The three overrides. Empty means "take it from the preset".
    llm_base_url_env: str = field(default_factory=lambda: _env("LLM_BASE_URL"))
    llm_api_key_env: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model_env: str = field(default_factory=lambda: _env("LLM_MODEL"))

    # One key variable per preset, so a single .env can hold them all.
    helmcode_base_url: str = field(
        default_factory=lambda: _env("HELMCODE_BASE_URL", HELMCODE_BASE_URL)
    )
    helmcode_api_key: str = field(default_factory=lambda: _env("HELMCODE_API_KEY"))
    cloudflare_account_id: str = field(default_factory=lambda: _env("CLOUDFLARE_ACCOUNT_ID"))
    cloudflare_api_token: str = field(default_factory=lambda: _env("CLOUDFLARE_API_TOKEN"))
    vercel_ai_gateway_key: str = field(default_factory=lambda: _env("VERCEL_AI_GATEWAY_KEY"))

    llm_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2")))
    # 120 was chosen for the spoken turn (one or two sentences) and silently
    # capped the *tool call* as well, which is the same completion: a
    # prepare_booking/submit_action with a nested slot was cut off mid-argument,
    # the tool call never closed and the call submitted nothing. A
    # ``submit_action`` carrying a ``BookAction`` measures 107 tokens on
    # qwen3.6 and ``prepare_booking`` with a full ``Slot`` measures 150, so at
    # 120 the model could never emit a booking at all. Measured with
    # scripts/rehearse_text.py.
    llm_max_tokens: int = field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "320")))
    # Qwen3 hybrid builds think by default; a phone call cannot wait for that.
    llm_disable_thinking: bool = field(
        default_factory=lambda: (
            _env("LLM_DISABLE_THINKING", "true").lower() not in ("0", "false", "no")
        )
    )
    # Helmcode (and other OpenAI-style hosts) take ``reasoning_effort`` instead:
    # "none" skips the reasoning phase on qwen3.6/gemma4. Empty sends nothing.
    llm_reasoning_effort: str = field(
        default_factory=lambda: _env("LLM_REASONING_EFFORT", "none").lower()
    )
    # How long one completion may go without producing its *first* token before
    # the line gives up on it and re-issues it. On 2026-09-18 two scored calls
    # sat mute for 36 s on a request the provider accepted and never streamed,
    # and the harness cut them. Only the first token is on the clock: once the
    # answer is flowing it is allowed to take as long as it takes. 0 disables
    # the guard. See vortex/line/llm_timeout.py.
    llm_first_token_timeout_secs: float = field(
        default_factory=lambda: float(_env("LLM_FIRST_TOKEN_TIMEOUT_SECS", "8.0"))
    )
    # How many times a request that produced no first token is re-issued. One
    # retry costs at most another LLM_FIRST_TOKEN_TIMEOUT_SECS of the call's
    # three minutes; after the last one the agent speaks a short holding line
    # rather than saying nothing.
    llm_retries: int = field(default_factory=lambda: int(_env("LLM_RETRIES", "1")))

    # --- Arbiter: the post-hangup submission judge ----------------------------
    # Nothing consumes this yet. It is here so the key and the model id can be
    # in .env before the arbiter lane needs them.
    arbiter_provider: str = field(
        default_factory=lambda: _llm_provider("ARBITER_PROVIDER", DEFAULT_ARBITER_PROVIDER)
    )
    arbiter_base_url_env: str = field(default_factory=lambda: _env("ARBITER_BASE_URL"))
    arbiter_api_key_env: str = field(default_factory=lambda: _env("ARBITER_API_KEY"))
    arbiter_model_env: str = field(default_factory=lambda: _env("ARBITER_MODEL"))

    # --- TTS: a primary and an alternate --------------------------------------
    # VORTEX_TTS_PROVIDER     speaks Spanish (google | elevenlabs)
    # VORTEX_TTS_PROVIDER_ALT speaks whatever the primary cannot
    tts_provider: str = field(default_factory=_tts_provider)
    tts_provider_alt: str = field(default_factory=lambda: _tts_provider("VORTEX_TTS_PROVIDER_ALT"))

    # Google Cloud Text-to-Speech. The only provider here with Catalan,
    # Galician *and* Basque voices, which is why it is the default. Credentials
    # come either as a path to the service-account JSON or as the JSON itself.
    google_application_credentials: str = field(
        default_factory=lambda: _env("GOOGLE_APPLICATION_CREDENTIALS")
    )
    google_tts_credentials_json: str = field(
        default_factory=lambda: _env("GOOGLE_TTS_CREDENTIALS_JSON")
    )
    # English is the clinic's default language (69 of 73 published cases).
    # Same Chirp 3 HD family as Spanish; British, to match the conversation
    # lane's own hardcoded fallback before this setting existed.
    google_tts_voice_en: str = field(
        default_factory=lambda: _env("GOOGLE_TTS_VOICE_EN", "en-GB-Chirp3-HD-Aoede")
    )
    # Spanish stays on Chirp 3 HD. ca/gl/eu speak through Gemini-TTS
    # (gemini-2.5-flash-tts) with the same short voice name as Spanish Chirp
    # (Aoede), unless GOOGLE_TTS_STANDARD_FALLBACK turns Standard-* back on.
    google_tts_voice_es: str = field(
        default_factory=lambda: _env("GOOGLE_TTS_VOICE_ES", "es-ES-Chirp3-HD-Aoede")
    )
    google_tts_voice_ca: str = field(
        default_factory=lambda: _google_tts_voice_coofficial(
            "GOOGLE_TTS_VOICE_CA", GOOGLE_TTS_STANDARD_CA
        )
    )
    google_tts_voice_gl: str = field(
        default_factory=lambda: _google_tts_voice_coofficial(
            "GOOGLE_TTS_VOICE_GL", GOOGLE_TTS_STANDARD_GL
        )
    )
    google_tts_voice_eu: str = field(
        default_factory=lambda: _google_tts_voice_coofficial(
            "GOOGLE_TTS_VOICE_EU", GOOGLE_TTS_STANDARD_EU
        )
    )
    # Off by default: GeminiTTSService for ca/gl/eu. Set true to keep the old
    # GoogleHttpTTSService + Standard-B path (research 06 fallback).
    google_tts_standard_fallback: bool = field(
        default_factory=lambda: _env_flag("GOOGLE_TTS_STANDARD_FALLBACK")
    )
    google_tts_gemini_model: str = field(
        default_factory=lambda: _env("GOOGLE_TTS_GEMINI_MODEL", DEFAULT_GEMINI_TTS_MODEL)
    )

    # ElevenLabs. Spanish only here: it has no Catalan, Galician or Basque
    # voice worth putting on a clinic line, so pair it with google as the ALT.
    # There is no default voice id — a voice is an account-level choice.
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    elevenlabs_model: str = field(
        default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    )
    elevenlabs_voice_id_es: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE_ID_ES"))
    # Optional WebSocket origin override, e.g. an AI Gateway in front of
    # ElevenLabs. Empty means the service's own default.
    elevenlabs_base_url: str = field(default_factory=lambda: _env("ELEVENLABS_BASE_URL"))

    # --- Turn-taking (the conversation lane reads this through TurnSettings) ---
    # Seconds of caller silence before the agent asks whether they are still
    # there. 0 disables the nudge. The 2026-09-18 run measured the harness
    # caller answering in a median of 4.5 s, p90 10 s and max 22 s, so 6 s
    # fired 147 times over 20 calls, mostly while the caller was still
    # thinking. 10 s clears the p90.
    user_idle_secs: float = field(
        default_factory=lambda: float(_env("VORTEX_USER_IDLE_SECS", "10"))
    )

    # Server
    host: str = field(default_factory=lambda: _env("VORTEX_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("VORTEX_PORT", "7860")))
    ws_path: str = field(default_factory=lambda: _env("VORTEX_WS_PATH", "/ws"))

    # Forced modes. "auto" derives the mode from the keys above.
    # VORTEX_VOICE_MODE: auto | stub | pipecat
    voice_mode: str = field(default_factory=lambda: _env("VORTEX_VOICE_MODE", "auto"))
    # VORTEX_CLINIC_MODE: auto | fake | live
    clinic_mode: str = field(default_factory=lambda: _env("VORTEX_CLINIC_MODE", "auto"))

    # Optional ai-coustics AICFilter on the Twilio input (8 kHz Quail).
    # Default off: only flip on after the T54 entity-CER bench shows a drop
    # with the filter. License from developers.ai-coustics.com.
    # VORTEX_AIC_FILTER: off | on   (unknown / empty -> off)
    aic_filter_enabled: bool = field(
        default_factory=lambda: (
            _env("VORTEX_AIC_FILTER", "off").lower() in ("1", "true", "yes", "on")
        )
    )
    aic_sdk_license: str = field(default_factory=lambda: _env("AIC_SDK_LICENSE"))
    aic_model_id: str = field(default_factory=lambda: _env("VORTEX_AIC_MODEL", "quail-ms-l-8khz"))

    # Observability
    calls_log_path: Path = field(
        default_factory=lambda: Path(_env("VORTEX_CALLS_LOG", str(REPO_ROOT / "logs/calls.jsonl")))
    )
    langfuse_public_key: str = field(default_factory=lambda: _env("LANGFUSE_PUBLIC_KEY"))
    langfuse_secret_key: str = field(default_factory=lambda: _env("LANGFUSE_SECRET_KEY"))
    langfuse_base_url: str = field(
        default_factory=lambda: _env("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    )
    langfuse_environment: str = field(
        default_factory=lambda: _env("LANGFUSE_TRACING_ENVIRONMENT") or _env("VORTEX_ENV")
    )

    # Live geocoder for problem 15 (vortex/rules/geo.py). Empty = gazetteer only.
    # VORTEX_GEOCODER: cartociudad | nominatim | "" (off).
    # cartociudad = IGN free candidates API, no key. nominatim needs a URL.
    geocoder: str = field(default_factory=lambda: _env("VORTEX_GEOCODER"))
    # Nominatim-compatible search URL when geocoder is nominatim (or when this
    # is set alone, for older .env files that never set VORTEX_GEOCODER).
    geocoder_url: str = field(default_factory=lambda: _env("VORTEX_GEOCODER_URL"))

    # Submission window: the platform closes it 30 s after the socket closes.
    # We keep a margin so a late retry still lands inside it.
    submit_window_secs: float = 30.0
    submit_deadline_margin_secs: float = 5.0

    @property
    def clinic_is_live(self) -> bool:
        if self.clinic_mode == "live":
            return True
        if self.clinic_mode == "fake":
            return False
        return bool(self.platform_api_key)

    # --- LLM resolution -------------------------------------------------------

    def _preset_base_url(self, provider: str) -> str:
        """The preset's endpoint, before any override."""
        if provider == "helmcode":
            return self.helmcode_base_url
        if provider == "cloudflare":
            # No account id, no URL: half a Cloudflare URL is worse than none,
            # because it would look configured and 404 on the first call.
            if not self.cloudflare_account_id:
                return ""
            return CLOUDFLARE_LLM_BASE_URL.format(account_id=self.cloudflare_account_id)
        return LLM_PRESETS[provider].base_url

    def _preset_api_key(self, provider: str) -> str:
        return str(getattr(self, LLM_PRESETS[provider].key_field, ""))

    @property
    def llm_base_url(self) -> str:
        return self.llm_base_url_env or self._preset_base_url(self.llm_provider)

    @property
    def llm_api_key(self) -> str:
        return self.llm_api_key_env or self._preset_api_key(self.llm_provider)

    @property
    def llm_model(self) -> str:
        return self.llm_model_env or LLM_PRESETS[self.llm_provider].model

    @property
    def arbiter_base_url(self) -> str:
        return self.arbiter_base_url_env or self._preset_base_url(self.arbiter_provider)

    @property
    def arbiter_api_key(self) -> str:
        return self.arbiter_api_key_env or self._preset_api_key(self.arbiter_provider)

    @property
    def arbiter_model(self) -> str:
        """The arbiter carries its own default, not the preset's chat model."""
        return self.arbiter_model_env or DEFAULT_ARBITER_MODEL

    # --- TTS resolution -------------------------------------------------------

    @property
    def has_google_tts_credentials(self) -> bool:
        """Either the path to the service-account file or the JSON itself."""
        return bool(self.google_application_credentials or self.google_tts_credentials_json)

    @property
    def tts_is_routed(self) -> bool:
        """True when the two providers differ and the pipeline needs a router."""
        return self.tts_provider_alt != self.tts_provider

    @property
    def tts_providers_in_use(self) -> tuple[str, ...]:
        """The primary, plus the alternate when it is a different service."""
        if self.tts_is_routed:
            return (self.tts_provider, self.tts_provider_alt)
        return (self.tts_provider,)

    def tts_languages(self, provider: str | None = None) -> frozenset[str]:
        """The languages a provider can say. Unknown providers say nothing."""
        return TTS_LANGUAGES.get(provider or self.tts_provider, frozenset())

    def tts_provider_for(self, language: str) -> str:
        """Which of the two services speaks this language.

        The primary gets everything it covers; the alternate gets the rest.
        A language neither covers goes to the primary, which answers it in
        Spanish (see ``tts_voice_for``).
        """
        if language in self.tts_languages(self.tts_provider):
            return self.tts_provider
        if self.tts_is_routed and language in self.tts_languages(self.tts_provider_alt):
            return self.tts_provider_alt
        return self.tts_provider

    @property
    def tts_covered_languages(self) -> frozenset[str]:
        """Everything the pair can say between them."""
        covered = self.tts_languages(self.tts_provider)
        if self.tts_is_routed:
            covered = covered | self.tts_languages(self.tts_provider_alt)
        return covered

    @property
    def tts_supports_language_switch(self) -> bool:
        """Can the voice change mid-call? Only if the pair speaks more than one."""
        return len(self.tts_covered_languages) > 1

    def tts_voice_es(self, provider: str | None = None) -> str:
        """The Spanish voice of a provider: what it starts the call with."""
        name = provider or self.tts_provider
        if name == "elevenlabs":
            return self.elevenlabs_voice_id_es
        return self.google_tts_voice_es

    @property
    def google_tts_uses_gemini(self) -> bool:
        """True when ca/gl/eu ride GeminiTTSService instead of Standard-*."""
        return not self.google_tts_standard_fallback

    @property
    def tts_voice(self) -> str:
        """The voice the primary provider starts the call with (Spanish)."""
        return self.tts_voice_es(self.tts_provider)

    def has_provider_tts_key(self, provider: str) -> bool:
        if provider == "elevenlabs":
            return bool(self.elevenlabs_api_key)
        return self.has_google_tts_credentials

    @property
    def has_tts_key(self) -> bool:
        """Keys for the primary and, when they differ, for the alternate too."""
        return all(self.has_provider_tts_key(name) for name in self.tts_providers_in_use)

    @property
    def tts_voices_missing(self) -> list[str]:
        """Providers in use with no Spanish voice configured (ElevenLabs has none by default)."""
        return [name for name in self.tts_providers_in_use if not self.tts_voice_es(name)]

    @property
    def voice_is_pipecat(self) -> bool:
        if self.voice_mode == "pipecat":
            return True
        if self.voice_mode == "stub":
            return False
        return bool(
            self.soniox_api_key and self.llm_api_key and self.llm_base_url and self.has_tts_key
        )

    def describe(self) -> dict[str, object]:
        """A safe summary for logs and /health. Never includes key values."""
        return {
            "clinic": "live" if self.clinic_is_live else "fake",
            "voice": "pipecat" if self.voice_is_pipecat else "stub",
            "platform_api_base_url": self.platform_api_base_url,
            "has_platform_key": bool(self.platform_api_key),
            "has_soniox_key": bool(self.soniox_api_key),
            "has_llm_key": bool(self.llm_api_key),
            "has_google_tts_credentials": self.has_google_tts_credentials,
            "has_elevenlabs_key": bool(self.elevenlabs_api_key),
            "stt_model": self.soniox_stt_model,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "llm_first_token_timeout_secs": self.llm_first_token_timeout_secs,
            "llm_retries": self.llm_retries,
            "arbiter_provider": self.arbiter_provider,
            "arbiter_model": self.arbiter_model,
            "arbiter_base_url": self.arbiter_base_url,
            "has_arbiter_key": bool(self.arbiter_api_key),
            "tts_provider": self.tts_provider,
            "tts_provider_alt": self.tts_provider_alt,
            "tts_routed": self.tts_is_routed,
            "tts_voice": self.tts_voice,
            "tts_languages": sorted(self.tts_covered_languages),
            "tts_language_switch": self.tts_supports_language_switch,
            "google_tts_gemini": self.google_tts_uses_gemini,
            "google_tts_gemini_model": self.google_tts_gemini_model
            if self.google_tts_uses_gemini
            else "",
            # A provider with a key but no voice id builds and then fails on
            # every utterance, so say so before the first call.
            "tts_voices_missing": self.tts_voices_missing,
            "aic_filter": "on" if self.aic_filter_enabled and self.aic_sdk_license else "off",
            "aic_model": self.aic_model_id,
            "has_aic_license": bool(self.aic_sdk_license),
            "user_idle_secs": self.user_idle_secs,
            "ws_path": self.ws_path,
            "calls_log_path": str(self.calls_log_path),
            "has_langfuse_keys": bool(self.langfuse_public_key and self.langfuse_secret_key),
            "langfuse_base_url": self.langfuse_base_url,
            "langfuse_environment": self.langfuse_environment,
            "geocoder": self.geocoder or ("nominatim" if self.geocoder_url else ""),
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings. Tests call this after they change the environment."""
    global _settings
    _settings = None
