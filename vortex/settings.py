"""Process-wide settings, read once from the environment.

Every value has a default that works with no key configured. When a key is
missing, the matching component runs in fake mode:

- no ``PLATFORM_API_KEY``  -> fake clinic data and a dry-run submit client
- no voice keys            -> the stub voice pipeline (beeps, no STT/LLM/TTS)

The voice pipeline is Soniox for STT, ElevenLabs for TTS, and an
OpenAI-compatible endpoint for the LLM (picked with ``LLM_PROVIDER``). There is
no second TTS: ElevenLabs' multilingual models speak all five languages the
clinic answers in.

**LLM presets** keep every provider swappable from ``.env`` alone.
``LLM_PROVIDER`` names a preset that fills in the base URL, the key variable
and the model id. ``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL`` always win
when set, so a preset is a shortcut, never a cage. Each preset reads its *own*
key variable, so both can sit in one ``.env``.
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

    ``base_url`` is empty for both presets: helmcode and azure assemble theirs
    in :meth:`Settings._preset_base_url` from their own variables.
    """

    base_url: str
    key_field: str
    model: str


# Confirmed from https://helmcode.com/docs/integrations (18 Sep 2026).
HELMCODE_BASE_URL = "https://api.helmcode.com/v1"
# Azure OpenAI's OpenAI-compatible surface: the resource endpoint plus this
# path, the key as a plain bearer token, the deployment name as the model.
# Verified 20 Sep 2026 against hackspain-vortex.openai.azure.com (200, gpt-4.1).
AZURE_V1_PATH = "/openai/v1"
DEFAULT_AZURE_DEPLOYMENT = "gpt-4.1"

LLM_PRESETS: dict[str, LlmPreset] = {
    # Hackathon perk: 600M tokens. deepseek-v4-flash, not the faster qwen3.6:
    # measured on 2026-09-19, qwen3.6 fails both problem-1 scenarios. It loops
    # prepare_booking and submit_action for 20 tool calls against a cap of 12,
    # submits nothing, and the session fallback sends no-action. deepseek-v4-flash
    # passes both, in a third of the time and a quarter of the tokens.
    "helmcode": LlmPreset("", "helmcode_api_key", "deepseek-v4-flash"),
    # Azure OpenAI. The model id is the *deployment* name, which is why
    # AZURE_OPENAI_DEPLOYMENT overrides the preset default below.
    "azure": LlmPreset("", "azure_openai_api_key", DEFAULT_AZURE_DEPLOYMENT),
}

DEFAULT_LLM_PROVIDER = "helmcode"
# The arbiter reads the whole call after the hangup, so it can afford a bigger
# model than the one answering the phone. deepseek-v4-flash reasons on its own
# schedule (cannot be switched off), which is fine after the hangup.
DEFAULT_ARBITER_PROVIDER = "helmcode"
DEFAULT_ARBITER_MODEL = "deepseek-v4-flash"

# A ``submit_action`` with a nested ``BookAction`` measured 107 completion
# tokens on qwen3.6; ``prepare_booking`` with a full ``Slot`` measured 150.
# 120 was chosen for the spoken turn and silently capped the tool call too,
# so a leftover ``LLM_MAX_TOKENS=120`` in .env made every booking impossible.
# Anything below this floor is raised to the default. Do not lower it.
MIN_TOKENS_FOR_A_BOOKING = 256
DEFAULT_LLM_MAX_TOKENS = 320
# Off unless set. qwen3.6 is ~2 s with tools on the same Helmcode perk, but
# it loops prepare_booking/submit_action on problem 1, so a hang must not
# spend the retry there. Set LLM_ALT_MODEL=qwen3.6 only if Helmcode is mute
# and problem 1 is not on the line.
DEFAULT_LLM_ALT_MODEL = ""


def _llm_max_tokens() -> int:
    raw = _env("LLM_MAX_TOKENS", str(DEFAULT_LLM_MAX_TOKENS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LLM_MAX_TOKENS
    if value < MIN_TOKENS_FOR_A_BOOKING:
        return DEFAULT_LLM_MAX_TOKENS
    return value


def _llm_provider(var: str, default: str) -> str:
    """Fold an ``LLM_PROVIDER``-shaped variable to a known preset."""
    name = _env(var, default).lower()
    return name if name in LLM_PRESETS else default


# --- TTS providers -----------------------------------------------------------

TTS_PROVIDERS: tuple[str, ...] = ("elevenlabs",)
DEFAULT_TTS_PROVIDER = "elevenlabs"

# ElevenLabs' multilingual models cover every language the clinic answers in,
# so one provider carries the whole line and nothing has to be routed.
TTS_LANGUAGES: dict[str, frozenset[str]] = {
    "elevenlabs": frozenset({"en", "es", "ca", "gl", "eu"}),
}

#: The one-shot HTTP surface used for pre-rendered MP3s (the confirmation call's
#: <Play> lines and the wall's voice preview). The pipeline speaks over the
#: WebSocket API instead, which is what ``ELEVENLABS_BASE_URL`` overrides.
ELEVENLABS_HTTP_BASE_URL = "https://api.elevenlabs.io"


def _tts_provider(var: str = "VORTEX_TTS_PROVIDER") -> str:
    """Fold a TTS provider variable to a known provider. Anything odd -> elevenlabs."""
    name = _env(var, DEFAULT_TTS_PROVIDER).lower()
    return name if name in TTS_PROVIDERS else DEFAULT_TTS_PROVIDER


def _env_flag(name: str, default: str = "false") -> bool:
    """Truthy for 1/true/yes/on; everything else is false."""
    return _env(name, default).lower() in ("1", "true", "yes", "on")


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
    # LLM_PROVIDER: helmcode | azure (unknown -> helmcode)
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
    # Azure OpenAI: the resource endpoint (https://<resource>.openai.azure.com),
    # its key, and the *deployment* name, which is what Azure calls a model.
    azure_openai_endpoint: str = field(default_factory=lambda: _env("AZURE_OPENAI_ENDPOINT"))
    azure_openai_api_key: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_KEY"))
    azure_openai_deployment: str = field(default_factory=lambda: _env("AZURE_OPENAI_DEPLOYMENT"))
    # Only the dated API surface needs this; the /openai/v1 base URL above does
    # not. When set it travels as an ``api-version`` query parameter.
    azure_openai_api_version: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_VERSION"))

    llm_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2")))
    # 120 was chosen for the spoken turn (one or two sentences) and silently
    # capped the *tool call* as well, which is the same completion: a
    # prepare_booking/submit_action with a nested slot was cut off mid-argument,
    # the tool call never closed and the call submitted nothing. A leftover
    # ``LLM_MAX_TOKENS=120`` in .env survived the default bump to 320 and
    # shipped that way; ``_llm_max_tokens`` raises anything below
    # ``MIN_TOKENS_FOR_A_BOOKING``. Measured with scripts/rehearse_text.py.
    llm_max_tokens: int = field(default_factory=_llm_max_tokens)
    # Same host as ``llm_model``. On a first-token timeout the retry uses this
    # instead of the hung model. Empty disables the swap.
    llm_alt_model: str = field(default_factory=lambda: _env("LLM_ALT_MODEL", DEFAULT_LLM_ALT_MODEL))
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
    jev_arbiter: bool = field(default_factory=lambda: _env_flag("VORTEX_JEV_ARBITER", "0"))

    # --- TTS: ElevenLabs, and nothing else ------------------------------------
    # VORTEX_TTS_PROVIDER is kept so the variable still folds to a known name,
    # but there is only one provider left to fold to.
    tts_provider: str = field(default_factory=_tts_provider)

    # A multilingual ElevenLabs model speaks all five languages with one voice,
    # so which voice speaks which language (and which one the wall's male switch
    # picks) is a fixed preset in code — ``conversation.language.VoicePreset`` —
    # not a row of environment variables. These two only exist so an account
    # with its own voice can override the preset's female column.
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    elevenlabs_model: str = field(
        default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    )
    #: Overrides the preset for every language.
    elevenlabs_voice_id_default: str = field(
        default_factory=lambda: _env("ELEVENLABS_VOICE_ID_DEFAULT")
    )
    #: Overrides it for Spanish alone.
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

    # Observability and the product's own data both live in one store:
    # Supabase/Postgres, reached through PostgREST. There is no file log and
    # no local database. Empty keys = no store at all: reads come back empty
    # and writes raise, which is a developer machine, never a deploy.
    # The service-role key is server-side; never ship it to the browser.
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_service_role_key: str = field(
        default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_SECRET_KEY")
    )
    # Direct Postgres connection string. Only the migrator uses it
    # (``database/supabase/migrations``); nothing on the call path opens a
    # socket to Postgres, so this stays optional everywhere else.
    supabase_db_url: str = field(default_factory=lambda: _env("SUPABASE_DB_URL"))
    langfuse_public_key: str = field(default_factory=lambda: _env("LANGFUSE_PUBLIC_KEY"))
    langfuse_secret_key: str = field(default_factory=lambda: _env("LANGFUSE_SECRET_KEY"))
    langfuse_base_url: str = field(
        default_factory=lambda: _env("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    )
    langfuse_environment: str = field(
        default_factory=lambda: _env("LANGFUSE_TRACING_ENVIRONMENT") or _env("VORTEX_ENV")
    )
    # HuggingFace Inference token: the Clinic View summarises a visit note when
    # it is set (vortex/observability/calendar.py ``summarize_note``). Empty =
    # the note is shown raw.
    hf_token: str = field(default_factory=lambda: _env("HF_TOKEN"))

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

    # How long the caller-id lookup may hold up the pipeline before the call
    # starts without it. The directory answers in ~0.3 s; past this the note is
    # worth less than the silence it costs, and the model just asks as before.
    caller_id_lookup_timeout_secs: float = 2.0

    # How long the last-resort booking may spend asking for a slot once the line
    # is dead. It has to stay well inside the submit window above: the refusal it
    # would replace is already decided, and a booking that misses the window is
    # worth less than a refusal that makes it.
    cold_booking_timeout_secs: float = 6.0

    # --- SMS confirmations (Twilio) -------------------------------------------
    # After an accepted book/cancel we text the calling number. Opt-in: live
    # messaging needs the flag on, and is dry-run when the Twilio keys below are
    # missing. Off by default so no deployment texts a patient unasked.
    sms_confirmations: bool = field(default_factory=lambda: _env_flag("VORTEX_SMS_CONFIRMATIONS"))
    twilio_account_sid: str = field(default_factory=lambda: _env("TWILIO_ACCOUNT_SID"))
    twilio_auth_token: str = field(default_factory=lambda: _env("TWILIO_AUTH_TOKEN"))
    # Prefer a Messaging Service; otherwise a bare From number works.
    twilio_messaging_service_sid: str = field(
        default_factory=lambda: _env("TWILIO_MESSAGING_SERVICE_SID")
    )
    twilio_from_number: str = field(default_factory=lambda: _env("TWILIO_FROM_NUMBER"))
    # When set, every confirmation goes here instead of the caller's from_number.
    # Hackathon/demo only: leave empty in production so each caller gets their own text.
    sms_force_to: str = field(default_factory=lambda: _env("VORTEX_SMS_FORCE_TO"))
    # Also text the day before the slot (same opt-in as confirmations). Default on.
    sms_day_before_reminders: bool = field(
        default_factory=lambda: _env_flag("VORTEX_SMS_DAY_BEFORE", "true")
    )
    # How far ahead of the slot the reminder fires. 24 = one day before.
    # Lower it in demos (e.g. 0.01) to exercise the worker without waiting.
    sms_reminder_lead_hours: float = field(
        default_factory=lambda: float(_env("VORTEX_SMS_REMINDER_LEAD_HOURS", "24") or "24")
    )
    # JSON file for pending day-before reminders. Empty = next to the calls log.
    sms_reminders_path: str = field(default_factory=lambda: _env("VORTEX_SMS_REMINDERS_PATH"))
    sms_reminder_poll_secs: float = field(
        default_factory=lambda: float(_env("VORTEX_SMS_REMINDER_POLL_SECS", "30") or "30")
    )

    # --- Outbound scheduled calls (Twilio Voice) -------------------------------
    # One flag for the whole outbound-calling subsystem in
    # vortex/line/confirmation_calls.py, not just its first job: with this
    # off, server.py never starts ConfirmationWorker (which otherwise runs
    # for the process's whole lifetime, independent of any inbound call) and
    # session.py never queues a row, whatever the row's `motivo` would have
    # been (confirmacion / recordatorio / reprogramacion / seguimiento /
    # call_now — see KNOWN_MOTIVOS). The day before an accepted booking we
    # call the patient, say the appointment in their language and ask
    # whether they will come; the answer is stored per appointment
    # (logs/confirmation_calls.json). Dry-run without Twilio keys or a
    # public URL. The TwiML comes from this server's /confirmation/*
    # routes, so Twilio needs to reach them: public_base_url is the https
    # tunnel base (e.g. the `make tunnel` host).
    confirmation_calls: bool = field(default_factory=lambda: _env_flag("VORTEX_CONFIRMATION_CALLS"))
    public_base_url: str = field(default_factory=lambda: _env("VORTEX_PUBLIC_BASE_URL"))
    # How far ahead of the slot the call fires. 24 = one day before.
    # Lower it in demos (e.g. 0.01) to exercise the worker without waiting.
    confirmation_lead_hours: float = field(
        default_factory=lambda: float(_env("VORTEX_CONFIRMATION_LEAD_HOURS", "24") or "24")
    )
    # JSON file for pending confirmation calls. Empty = next to the calls log.
    confirmation_calls_path: str = field(
        default_factory=lambda: _env("VORTEX_CONFIRMATION_CALLS_PATH")
    )
    confirmation_poll_secs: float = field(
        default_factory=lambda: float(_env("VORTEX_CONFIRMATION_POLL_SECS", "30") or "30")
    )
    # When set, every confirmation call goes here instead of the patient's
    # number. Hackathon/demo only (a Twilio trial can only call verified
    # numbers anyway). Falls back to sms_force_to, the demo's one demo number.
    confirmation_force_to: str = field(default_factory=lambda: _env("VORTEX_CONFIRMATION_FORCE_TO"))

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
        if provider == "azure":
            # No endpoint, no URL: half an Azure URL is worse than none,
            # because it would look configured and 404 on the first call.
            endpoint = self.azure_openai_endpoint.rstrip("/")
            if not endpoint:
                return ""
            if endpoint.endswith(AZURE_V1_PATH):
                return endpoint
            return endpoint + AZURE_V1_PATH
        return LLM_PRESETS[provider].base_url

    def _preset_api_key(self, provider: str) -> str:
        return str(getattr(self, LLM_PRESETS[provider].key_field, ""))

    def _preset_model(self, provider: str) -> str:
        """Azure calls a model a *deployment*, so its own variable wins."""
        if provider == "azure" and self.azure_openai_deployment:
            return self.azure_openai_deployment
        return LLM_PRESETS[provider].model

    @property
    def llm_base_url(self) -> str:
        return self.llm_base_url_env or self._preset_base_url(self.llm_provider)

    @property
    def llm_api_key(self) -> str:
        return self.llm_api_key_env or self._preset_api_key(self.llm_provider)

    @property
    def llm_model(self) -> str:
        return self.llm_model_env or self._preset_model(self.llm_provider)

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
    def elevenlabs_http_base_url(self) -> str:
        """The https origin for one-shot synthesis (pre-rendered MP3s).

        ``ELEVENLABS_BASE_URL`` overrides it only when it is an http(s) origin;
        a ``wss://`` gateway is for the pipeline's WebSocket API, not this.
        """
        base = self.elevenlabs_base_url.strip().rstrip("/")
        if base.startswith(("http://", "https://")):
            return base
        return ELEVENLABS_HTTP_BASE_URL

    def tts_languages(self, provider: str | None = None) -> frozenset[str]:
        """The languages a provider can say. Unknown providers say nothing."""
        return TTS_LANGUAGES.get(provider or self.tts_provider, frozenset())

    @property
    def tts_covered_languages(self) -> frozenset[str]:
        """Everything the line can say."""
        return self.tts_languages(self.tts_provider)

    @property
    def tts_supports_language_switch(self) -> bool:
        """Can the voice change mid-call? Only if it speaks more than one language."""
        return len(self.tts_covered_languages) > 1

    def elevenlabs_voice_for(self, language: str = "es", gender: str = "female") -> str:
        """The voice id for a language and gender. See ``VoicePreset`` for the map."""
        from vortex.conversation.language import elevenlabs_voice_id

        return elevenlabs_voice_id(language, self, gender)

    def tts_voice_es(self, provider: str | None = None) -> str:
        """The Spanish voice: what the line starts the call with."""
        return self.elevenlabs_voice_for("es")

    @property
    def tts_voice(self) -> str:
        """The voice the line starts the call with (Spanish)."""
        return self.tts_voice_es()

    def has_provider_tts_key(self, provider: str) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def has_tts_key(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def tts_voices_missing(self) -> list[str]:
        """``["elevenlabs"]`` when no voice id is configured at all."""
        return [] if self.tts_voice_es() else [self.tts_provider]

    @property
    def voice_is_pipecat(self) -> bool:
        if self.voice_mode == "pipecat":
            return True
        if self.voice_mode == "stub":
            return False
        return bool(
            self.soniox_api_key and self.llm_api_key and self.llm_base_url and self.has_tts_key
        )

    @property
    def voice_label(self) -> str:
        """What ``/health`` reports under ``voice``."""
        if self.voice_is_pipecat:
            return "pipecat"
        return "stub"

    @property
    def store(self) -> str:
        """Which persistent store is live: ``supabase`` or ``none``.

        ``none`` is a developer machine with no keys: reads come back empty
        and writes raise. It is never a deploy — see ``__post_init__``.
        """
        return "supabase" if self.supabase_url and self.supabase_service_role_key else "none"

    @property
    def is_production(self) -> bool:
        return _env("VORTEX_ENV").lower() in {"production", "prod"}

    def __post_init__(self) -> None:
        """A production boot without a store is a silent data loss, so it is a
        crash instead.

        Every call event, every appointment and every console setting goes to
        ``public.call_events`` and its sibling tables. With no keys the line
        still answers the phone and still submits, but nothing is recorded —
        and the board shows an empty wall that reads exactly like "no calls
        came in". Fail at boot, where somebody is watching.
        """
        if self.is_production and self.store != "supabase":
            raise RuntimeError(
                "VORTEX_ENV=production but the store is not configured: set "
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. Postgres is the "
                "only store — there is no file log and no local database to "
                "fall back to, so a deploy without these records nothing."
            )

    def describe(self) -> dict[str, object]:
        """A safe summary for logs and /health. Never includes key values."""
        return {
            "clinic": "live" if self.clinic_is_live else "fake",
            "voice": self.voice_label,
            "platform_api_base_url": self.platform_api_base_url,
            "has_platform_key": bool(self.platform_api_key),
            "has_soniox_key": bool(self.soniox_api_key),
            "has_llm_key": bool(self.llm_api_key),
            "has_elevenlabs_key": bool(self.elevenlabs_api_key),
            "stt_model": self.soniox_stt_model,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_alt_model": self.llm_alt_model,
            "llm_max_tokens": self.llm_max_tokens,
            "llm_base_url": self.llm_base_url,
            "llm_first_token_timeout_secs": self.llm_first_token_timeout_secs,
            "llm_retries": self.llm_retries,
            "arbiter_provider": self.arbiter_provider,
            "arbiter_model": self.arbiter_model,
            "arbiter_base_url": self.arbiter_base_url,
            "has_arbiter_key": bool(self.arbiter_api_key),
            "jev_arbiter": self.jev_arbiter,
            "has_typesafe_key": bool(_env("TYPESAFE_API_KEY")),
            "tts_provider": self.tts_provider,
            "tts_model": self.elevenlabs_model,
            "tts_voice": self.tts_voice,
            "tts_languages": sorted(self.tts_covered_languages),
            "tts_language_switch": self.tts_supports_language_switch,
            # A provider with a key but no voice id builds and then fails on
            # every utterance, so say so before the first call.
            "tts_voices_missing": self.tts_voices_missing,
            "aic_filter": "on" if self.aic_filter_enabled and self.aic_sdk_license else "off",
            "aic_model": self.aic_model_id,
            "has_aic_license": bool(self.aic_sdk_license),
            "user_idle_secs": self.user_idle_secs,
            "ws_path": self.ws_path,
            "store": self.store,
            "has_supabase": self.store == "supabase",
            "has_langfuse_keys": bool(self.langfuse_public_key and self.langfuse_secret_key),
            "has_hf_token": bool(self.hf_token),
            "langfuse_base_url": self.langfuse_base_url,
            "langfuse_environment": self.langfuse_environment,
            "geocoder": self.geocoder or ("nominatim" if self.geocoder_url else ""),
            "sms_confirmations": self.sms_confirmations,
            "sms_force_to_set": bool(self.sms_force_to),
            "sms_day_before_reminders": self.sms_day_before_reminders,
            "confirmation_calls": self.confirmation_calls,
            "confirmation_calls_public_url_set": bool(self.public_base_url),
            "confirmation_force_to_set": bool(self.confirmation_force_to or self.sms_force_to),
            "has_twilio_voice": bool(
                self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number
            ),
            "sms_reminder_lead_hours": self.sms_reminder_lead_hours,
            "has_twilio_sms": bool(
                self.twilio_account_sid
                and self.twilio_auth_token
                and (self.twilio_messaging_service_sid or self.twilio_from_number)
            ),
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
