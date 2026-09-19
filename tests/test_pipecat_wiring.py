"""The pipecat pipeline builds with dummy keys. Nothing runs, nothing connects.

This catches import paths and constructor signatures that drift between
pipecat releases, without a key and without a network.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from vortex import settings as settings_module
from vortex import tools as registry
from vortex.contract import MADRID
from vortex.conversation.prompt import initial_messages
from vortex.conversation.turns import default_turn_settings

TTS_ENV = (
    "VORTEX_TTS_PROVIDER",
    "VORTEX_TTS_PROVIDER_ALT",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_TTS_CREDENTIALS_JSON",
    "GOOGLE_TTS_VOICE_ES",
    "GOOGLE_TTS_VOICE_CA",
    "GOOGLE_TTS_VOICE_GL",
    "GOOGLE_TTS_VOICE_EU",
    "GOOGLE_TTS_GEMINI_MODEL",
    "GOOGLE_TTS_STANDARD_FALLBACK",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_MODEL",
    "ELEVENLABS_VOICE_ID_ES",
    "ELEVENLABS_BASE_URL",
)


@pytest.fixture
def voice_settings(monkeypatch: pytest.MonkeyPatch):
    """Build Settings from a clean TTS environment, so a local .env cannot steer it."""

    def build(**env: str) -> settings_module.Settings:
        for key in TTS_ENV:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        settings_module.reset_settings()
        return settings_module.get_settings()

    yield build
    settings_module.reset_settings()


def fake_service_account_json() -> str:
    """A syntactically valid service account with a throwaway key. Never authenticates."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "vortex-test",
            "private_key_id": "0" * 40,
            "private_key": private_key,
            "client_email": "vortex-test@vortex-test.iam.gserviceaccount.com",
            "client_id": "000000000000000000000",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def _session(settings: settings_module.Settings, events: list | None = None):
    """A CallSession stand-in: the watcher only reads ``settings`` and ``ctx.log``."""

    class Log:
        def event(self, kind: str, **kwargs: object) -> None:
            if events is not None:
                events.append((kind, kwargs))

    class Session:
        pass

    Session.settings = settings
    Session.ctx = type("ctx", (), {"log": Log()})
    return Session()


def test_pipecat_modules_import() -> None:
    pytest.importorskip("pipecat")
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: F401
    from pipecat.frames.frames import TTSUpdateSettingsFrame  # noqa: F401
    from pipecat.pipeline.parallel_pipeline import ParallelPipeline  # noqa: F401
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (  # noqa: F401
        LLMContextAggregatorPair,
    )
    from pipecat.processors.filters.function_filter import FunctionFilter  # noqa: F401
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService  # noqa: F401
    from pipecat.services.google.tts import GoogleHttpTTSService  # noqa: F401
    from pipecat.services.openai.llm import OpenAILLMService  # noqa: F401
    from pipecat.services.soniox.stt import (  # noqa: F401
        SonioxContextObject,
        SonioxSTTService,
    )
    from pipecat.transports.websocket.fastapi import (  # noqa: F401
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    serializer = TwilioFrameSerializer(
        stream_sid="MZ-x",
        call_sid="CA-x",
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    assert serializer is not None

    schemas = []
    for fn in registry.function_schemas(default_turn_settings().exposed_tools):
        props = dict(fn["parameters"]["properties"])
        if fn["parameters"].get("$defs"):
            props["$defs"] = fn["parameters"]["$defs"]
        schemas.append(
            FunctionSchema(
                name=fn["name"],
                description=fn["description"],
                properties=props,
                required=fn["parameters"]["required"],
            )
        )
    context = LLMContext(
        initial_messages(datetime.now(MADRID)), tools=ToolsSchema(standard_tools=schemas)
    )
    assert context is not None


def test_service_settings_take_our_shape() -> None:
    """The settings objects the pipeline builds are accepted by the services."""
    pytest.importorskip("pipecat")
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
    from pipecat.services.google.tts import GoogleHttpTTSService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.soniox.stt import SonioxContextObject, SonioxSTTService
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _language_hints

    turns = default_turn_settings()
    stt = SonioxSTTService.Settings(
        model="stt-rt-v5",
        language_hints=_language_hints(turns.stt_language_hints),
        enable_language_identification=True,
        context=SonioxContextObject(terms=["Clínica Arenal"]),
        max_endpoint_delay_ms=turns.stt_max_endpoint_delay_ms,
        endpoint_sensitivity=turns.stt_endpoint_sensitivity,
        endpoint_latency_adjustment_level=turns.stt_endpoint_latency_adjustment_level,
    )
    assert stt.language_hints == [Language.EN, Language.ES, Language.CA]

    from vortex.line.pipecat_voice import _llm_extra_body
    from vortex.settings import Settings

    extra = _llm_extra_body(Settings())
    llm = OpenAILLMService.Settings(model="qwen3.6", temperature=0.2, max_tokens=120, extra=extra)
    # Both dialects of "do not reason": vLLM's chat_template_kwargs and
    # Helmcode's reasoning_effort. Hosts ignore the one they do not know.
    assert llm.extra["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert llm.extra["reasoning_effort"] == "none"
    assert "chat_template_kwargs" not in llm.extra  # not a create() kwarg

    google = GoogleHttpTTSService.Settings(voice="es-ES-Chirp3-HD-Aoede", language=Language.ES_ES)
    assert google.voice == "es-ES-Chirp3-HD-Aoede"

    elevenlabs = ElevenLabsTTSService.Settings(
        voice="voice-1", model="eleven_flash_v2_5", language=Language.ES
    )
    assert elevenlabs.voice == "voice-1"


def test_language_switch_picks_the_catalan_voice(voice_settings) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import detect_language, tts_voice_for

    settings = voice_settings()  # google on both sides
    assert detect_language("bon dia, voldria una hora", hint=Language.CA) == "ca"
    assert detect_language("buenos días", hint=Language.ES_ES) == "es"
    # No hint: the marker vote carries it. Nothing to vote on: English, the default.
    assert detect_language("bon dia, si us plau") == "ca"
    assert detect_language("") == "en"

    voice, language = tts_voice_for("ca", settings)
    assert voice == settings.google_tts_voice_ca
    assert language == Language.CA_ES
    # Unsupported falls back to English, the clinic's default.
    from vortex.conversation.language import DEFAULT_GOOGLE_VOICE_EN

    voice, language = tts_voice_for("de", settings)
    assert voice == DEFAULT_GOOGLE_VOICE_EN
    assert language == Language.EN_GB


def test_stt_terms_boost_the_clinic_vocabulary() -> None:
    from vortex.clinic.client import FakeClinicClient
    from vortex.conversation.stt_context import stt_terms

    class Ctx:
        clinic = FakeClinicClient()

    terms = stt_terms(Ctx())
    assert "Clínica Arenal" in terms
    # The near-miss surnames the STT has to keep apart.
    assert "Dra. Sáenz" in terms
    assert "Dr. Sáez" in terms
    assert "Arenal Centro" in terms
    assert len(terms) == len(set(terms))

    # A context with no clinic at all still answers, and still never raises.
    assert "Clínica Arenal" in stt_terms(object())


def test_stt_terms_include_dictation_vocabulary() -> None:
    """Letter names, email punctuation, domains, months and insurers (T57)."""
    from vortex.clinic.client import FakeClinicClient
    from vortex.clinic.fixtures import INSURER_NAMES
    from vortex.conversation.stt_context import (
        MAX_CONTEXT_CHARS,
        stt_context_size,
        stt_terms,
    )

    class Ctx:
        clinic = FakeClinicClient()

    terms = stt_terms(Ctx())

    for letter in ("be", "uve", "i griega", "zeta", "eñe", "equis", "hache"):
        assert letter in terms
    for letter in ("efa", "enya", "ve baixa", "i grega", "ics", "essa"):
        assert letter in terms

    for punct in ("arroba", "punto", "guion", "guion bajo"):
        assert punct in terms

    for domain in ("gmail", "gmail.com", "hotmail", "outlook.com", "yahoo.es", "icloud.com"):
        assert domain in terms

    for month in ("enero", "septiembre", "gener", "setembre", "January", "September"):
        assert month in terms

    for insurer in INSURER_NAMES.values():
        assert insurer in terms
    assert "Caser" in terms
    assert "Nueva Mutua" in terms

    assert stt_context_size(Ctx()) < MAX_CONTEXT_CHARS
    assert stt_context_size(object()) < MAX_CONTEXT_CHARS


async def test_language_watcher_pushes_a_tts_settings_frame(voice_settings) -> None:
    """The watcher turns a Catalan transcript into a voice switch, once."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame, TTSUpdateSettingsFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageWatcher

    settings = voice_settings()
    events: list[tuple[str, dict]] = []
    pushed: list[object] = []

    watcher = _LanguageWatcher(_session(settings, events))

    async def capture(frame: object, direction: object = FrameDirection.DOWNSTREAM) -> None:
        pushed.append(frame)

    watcher.push_frame = capture  # type: ignore[method-assign]

    def transcript(text: str, language: Language) -> TranscriptionFrame:
        return TranscriptionFrame(text=text, user_id="u", timestamp="t", language=language)

    await watcher._maybe_switch(transcript("bon dia", Language.CA))
    await watcher._maybe_switch(transcript("vull una hora", Language.CA))  # no second switch
    await watcher._maybe_switch(transcript("buenos días", Language.ES_ES))

    assert [kind for kind, _ in events] == ["voice.language_switch"] * 2
    assert len(pushed) == 2
    assert all(isinstance(frame, TTSUpdateSettingsFrame) for frame in pushed)
    assert pushed[0].delta.voice == settings.google_tts_voice_ca
    assert pushed[0].delta.language == Language.CA_ES
    assert pushed[1].delta.voice == settings.google_tts_voice_es
    # Every switch names the provider that will say it.
    assert [kwargs["provider"] for _, kwargs in events] == ["google", "google"]


async def test_language_watcher_reaches_galician_and_basque_on_google(voice_settings) -> None:
    """Google is the only provider with gl and eu, so the watcher must use them."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageWatcher

    settings = voice_settings()  # google is the default on both sides
    assert settings.tts_provider == "google"
    assert settings.tts_supports_language_switch is True

    pushed: list[object] = []
    watcher = _LanguageWatcher(_session(settings))

    async def capture(frame: object, direction: object = FrameDirection.DOWNSTREAM) -> None:
        pushed.append(frame)

    watcher.push_frame = capture  # type: ignore[method-assign]

    def transcript(text: str, language: Language) -> TranscriptionFrame:
        return TranscriptionFrame(text=text, user_id="u", timestamp="t", language=language)

    await watcher._maybe_switch(transcript("bon dia", Language.CA))
    await watcher._maybe_switch(transcript("bos días", Language.GL))
    await watcher._maybe_switch(transcript("egun on", Language.EU))
    await watcher._maybe_switch(transcript("buenos días", Language.ES_ES))

    assert [(f.delta.voice, f.delta.language) for f in pushed] == [
        (settings.google_tts_voice_ca, Language.CA_ES),
        (settings.google_tts_voice_gl, Language.GL_ES),
        (settings.google_tts_voice_eu, Language.EU_ES),
        (settings.google_tts_voice_es, Language.ES_ES),
    ]


async def test_google_http_tts_applies_a_language_delta() -> None:
    """The real service, built offline: a settings delta swaps voice and language.

    ``GoogleHttpTTSService.run_tts`` reads ``self._settings.voice`` and passes
    ``self._settings.language`` as the ``language_code``, so a delta carrying
    both is all a mid-call switch needs. ``TTSService._update_settings``
    converts the pipecat ``Language`` to Google's own string on the way in —
    that conversion is what this asserts. Google's verified map only lists the
    Chirp 3 HD locales, so ca/gl/eu resolve through the full-code fallback.
    """
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    google_tts = pytest.importorskip("pipecat.services.google.tts")
    from pipecat.services.settings import TTSSettings
    from pipecat.transcriptions.language import Language

    service = google_tts.GoogleHttpTTSService(
        # Inline JSON: the constructor parses it and builds the client, but
        # nothing is sent anywhere until run_tts is awaited.
        credentials=fake_service_account_json(),
        sample_rate=8000,
        settings=google_tts.GoogleHttpTTSService.Settings(
            voice="es-ES-Chirp3-HD-Aoede", language=Language.ES_ES
        ),
    )
    # sample_rate resolves at pipeline setup; the requested one is kept here.
    assert service._init_sample_rate == 8000
    assert service._settings.voice == "es-ES-Chirp3-HD-Aoede"
    assert service._settings.language == "es-ES"

    for voice, language, expected in (
        ("ca-ES-Standard-B", Language.CA_ES, "ca-ES"),
        ("gl-ES-Standard-A", Language.GL_ES, "gl-ES"),
        ("eu-ES-Standard-A", Language.EU_ES, "eu-ES"),
        ("es-ES-Chirp3-HD-Aoede", Language.ES_ES, "es-ES"),
    ):
        await service._update_settings(TTSSettings(voice=voice, language=language))
        assert service._settings.voice == voice
        assert service._settings.language == expected


def test_make_tts_builds_the_google_chirp_gemini_pair(voice_settings) -> None:
    """Default Google path: Chirp HTTP for en/es, GeminiTTSService for ca/gl/eu."""
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    google_tts = pytest.importorskip("pipecat.services.google.tts")
    from pipecat.pipeline.parallel_pipeline import ParallelPipeline

    from vortex.line.pipecat_voice import _LanguageState, _make_tts
    from vortex.settings import DEFAULT_GEMINI_TTS_MODEL, DEFAULT_GEMINI_TTS_VOICE

    settings = voice_settings(GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json())
    assert settings.google_tts_uses_gemini is True
    tts = _make_tts(settings, state=_LanguageState())

    from vortex.conversation.language import DEFAULT_GOOGLE_VOICE_EN

    assert isinstance(tts, ParallelPipeline)
    (gemini_filter, gemini), (chirp_filter, chirp) = _router_branches(tts)
    assert isinstance(gemini, google_tts.GeminiTTSService)
    assert isinstance(chirp, google_tts.GoogleHttpTTSService)
    assert chirp._init_sample_rate == 8000
    # Call opens in English on Chirp; Gemini waits for ca/gl/eu.
    assert chirp._settings.voice == DEFAULT_GOOGLE_VOICE_EN
    assert chirp._settings.language == "en-GB"
    assert gemini._settings.voice == DEFAULT_GEMINI_TTS_VOICE
    assert gemini._settings.model == DEFAULT_GEMINI_TTS_MODEL
    assert gemini._settings.language == "ca-ES"
    assert gemini_filter is not None and chirp_filter is not None


def test_make_tts_standard_fallback_is_a_single_http_service(voice_settings) -> None:
    """GOOGLE_TTS_STANDARD_FALLBACK keeps one GoogleHttpTTSService for every language."""
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    google_tts = pytest.importorskip("pipecat.services.google.tts")

    from vortex.line.pipecat_voice import _make_tts

    settings = voice_settings(
        GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json(),
        GOOGLE_TTS_STANDARD_FALLBACK="true",
    )
    assert settings.google_tts_uses_gemini is False
    tts = _make_tts(settings)

    from vortex.conversation.language import DEFAULT_GOOGLE_VOICE_EN

    assert isinstance(tts, google_tts.GoogleHttpTTSService)
    assert tts._init_sample_rate == 8000
    assert tts._settings.voice == DEFAULT_GOOGLE_VOICE_EN
    assert tts._settings.language == "en-GB"
    assert settings.google_tts_voice_ca == "ca-ES-Standard-B"


async def test_google_gemini_gate_sends_ca_to_gemini_and_es_to_chirp(
    voice_settings,
) -> None:
    """Inside the Google pair, ca/gl/eu feed GeminiTTSService; es/en feed Chirp."""
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    google_tts = pytest.importorskip("pipecat.services.google.tts")
    from pipecat.frames.frames import TextFrame

    from vortex.line.pipecat_voice import _LanguageState, _make_tts

    state = _LanguageState()
    settings = voice_settings(GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json())
    router = _make_tts(settings, state=state)
    (gemini_filter, gemini), (chirp_filter, chirp) = _router_branches(router)
    assert isinstance(gemini, google_tts.GeminiTTSService)
    assert isinstance(chirp, google_tts.GoogleHttpTTSService)

    state.language = "ca"
    assert await gemini_filter._filter(TextFrame(text="bon dia")) is True
    assert await chirp_filter._filter(TextFrame(text="bon dia")) is False

    state.language = "gl"
    assert await gemini_filter._filter(TextFrame(text="bos días")) is True
    assert await chirp_filter._filter(TextFrame(text="bos días")) is False

    state.language = "es"
    assert await gemini_filter._filter(TextFrame(text="hola")) is False
    assert await chirp_filter._filter(TextFrame(text="hola")) is True

    state.language = "en"
    assert await gemini_filter._filter(TextFrame(text="hello")) is False
    assert await chirp_filter._filter(TextFrame(text="hello")) is True


def test_make_tts_builds_the_elevenlabs_service(voice_settings) -> None:
    """ElevenLabs at 8 kHz: the service maps that rate to its pcm_8000 format."""
    pytest.importorskip("pipecat")
    elevenlabs_tts = pytest.importorskip("pipecat.services.elevenlabs.tts")

    from vortex.line.pipecat_voice import _make_tts

    settings = voice_settings(
        VORTEX_TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_ES="voice-1",
    )
    tts = _make_tts(settings)

    assert isinstance(tts, elevenlabs_tts.ElevenLabsTTSService)
    assert tts._init_sample_rate == 8000
    assert elevenlabs_tts.output_format_from_sample_rate(8000) == "pcm_8000"
    assert tts._settings.voice == "voice-1"
    assert tts._settings.model == "eleven_flash_v2_5"
    # A bare code: the regional one only earns a "not verified" warning.
    # English first; the one multilingual voice id speaks both.
    assert tts._settings.language == "en"
    # No override -> the service's own origin.
    assert tts._url == "wss://api.elevenlabs.io"


def test_elevenlabs_base_url_override_is_passed_through(voice_settings) -> None:
    """ELEVENLABS_BASE_URL is the WebSocket origin, for a gateway in front of it."""
    pytest.importorskip("pipecat")
    pytest.importorskip("pipecat.services.elevenlabs.tts")

    from vortex.line.pipecat_voice import _make_tts

    settings = voice_settings(
        VORTEX_TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_ES="voice-1",
        ELEVENLABS_BASE_URL="wss://gateway.example.invalid",
    )
    assert _make_tts(settings)._url == "wss://gateway.example.invalid"


def test_one_provider_on_both_sides_builds_chirp_gemini_router(voice_settings) -> None:
    """google/google with Gemini on: one ParallelPipeline, not a provider router."""
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    google_tts = pytest.importorskip("pipecat.services.google.tts")
    from pipecat.pipeline.parallel_pipeline import ParallelPipeline

    from vortex.line.pipecat_voice import _LanguageState, _make_tts_stage

    settings = voice_settings(GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json())
    assert settings.tts_is_routed is False
    stage = _make_tts_stage(settings, _LanguageState())
    assert isinstance(stage, ParallelPipeline)
    (_gemini_filter, gemini), (_chirp_filter, chirp) = _router_branches(stage)
    assert isinstance(gemini, google_tts.GeminiTTSService)
    assert isinstance(chirp, google_tts.GoogleHttpTTSService)


def test_standard_fallback_keeps_a_single_google_service(voice_settings) -> None:
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    google_tts = pytest.importorskip("pipecat.services.google.tts")

    from vortex.line.pipecat_voice import _LanguageState, _make_tts_stage

    settings = voice_settings(
        GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json(),
        GOOGLE_TTS_STANDARD_FALLBACK="true",
    )
    assert settings.tts_is_routed is False
    stage = _make_tts_stage(settings, _LanguageState())
    assert isinstance(stage, google_tts.GoogleHttpTTSService)


def _router_branches(router) -> list[list]:
    """[[filter, service], ...] — ParallelPipeline wraps each branch in source/sink."""
    return [branch.processors[1:-1] for branch in router.processors]


def test_a_mixed_pair_builds_a_router(voice_settings) -> None:
    """ElevenLabs for Spanish, Google (Chirp|Gemini) for the rest."""
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    elevenlabs_tts = pytest.importorskip("pipecat.services.elevenlabs.tts")
    google_tts = pytest.importorskip("pipecat.services.google.tts")
    from pipecat.pipeline.parallel_pipeline import ParallelPipeline
    from pipecat.processors.filters.function_filter import FunctionFilter

    from vortex.line.pipecat_voice import _LanguageState, _make_tts_stage

    settings = voice_settings(
        VORTEX_TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_ES="voice-1",
        GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json(),
    )
    assert settings.tts_is_routed is True

    router = _make_tts_stage(settings, _LanguageState())
    assert isinstance(router, ParallelPipeline)

    branches = _router_branches(router)
    assert len(branches) == 2
    (primary_filter, primary), (alt_filter, alternate) = branches
    assert isinstance(primary_filter, FunctionFilter)
    assert isinstance(alt_filter, FunctionFilter)
    assert isinstance(primary, elevenlabs_tts.ElevenLabsTTSService)
    # Google side is itself Chirp|Gemini when the Gemini path is on.
    assert isinstance(alternate, ParallelPipeline)
    (_g_filter, gemini), (_c_filter, chirp) = _router_branches(alternate)
    assert isinstance(gemini, google_tts.GeminiTTSService)
    assert isinstance(chirp, google_tts.GoogleHttpTTSService)
    from vortex.conversation.language import DEFAULT_GOOGLE_VOICE_EN

    assert primary._settings.voice == "voice-1"
    assert chirp._settings.voice == DEFAULT_GOOGLE_VOICE_EN


async def test_the_router_sends_each_language_to_one_branch(voice_settings) -> None:
    """The gates are keyed on the shared language state: exactly one branch speaks."""
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    pytest.importorskip("pipecat.services.elevenlabs.tts")
    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from vortex.line.pipecat_voice import _LanguageState, _make_tts_stage

    settings = voice_settings(
        VORTEX_TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_ES="voice-1",
        GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json(),
    )
    state = _LanguageState()
    assert state.language == "en"

    (primary_filter, _), (alt_filter, _) = _router_branches(_make_tts_stage(settings, state))

    seen: dict[str, list[str]] = {"primary": [], "alt": []}

    def capture(bucket: str):
        async def push(frame: object, direction: object = FrameDirection.DOWNSTREAM) -> None:
            seen[bucket].append(frame.text)

        return push

    primary_filter.push_frame = capture("primary")  # type: ignore[method-assign]
    alt_filter.push_frame = capture("alt")  # type: ignore[method-assign]

    for language, text in (("es", "hola"), ("ca", "bon dia"), ("gl", "bos días"), ("es", "adiós")):
        state.language = language
        for gate in (primary_filter, alt_filter):
            await gate.process_frame(TextFrame(text), FrameDirection.DOWNSTREAM)

    assert seen["primary"] == ["hola", "adiós"]  # ElevenLabs: Spanish only
    assert seen["alt"] == ["bon dia", "bos días"]  # Google: everything else


async def test_the_watcher_moves_the_state_before_the_voice_update(voice_settings) -> None:
    """A switch has to land on the branch that is about to speak, not the old one."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageState, _LanguageWatcher

    settings = voice_settings(
        VORTEX_TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_ES="voice-1",
        GOOGLE_TTS_CREDENTIALS_JSON="{}",
    )
    state = _LanguageState()
    events: list[tuple[str, dict]] = []
    watcher = _LanguageWatcher(_session(settings, events), state)

    languages: list[str] = []

    async def capture(frame: object, direction: object = FrameDirection.DOWNSTREAM) -> None:
        # The gate reads the state as the frame passes, so record it here.
        languages.append(state.language)

    watcher.push_frame = capture  # type: ignore[method-assign]

    def transcript(text: str, language: Language) -> TranscriptionFrame:
        return TranscriptionFrame(text=text, user_id="u", timestamp="t", language=language)

    await watcher._maybe_switch(transcript("bon dia", Language.CA))
    await watcher._maybe_switch(transcript("bos días", Language.GL))
    await watcher._maybe_switch(transcript("buenos días", Language.ES_ES))

    assert languages == ["ca", "gl", "es"]
    # The voice on each update belongs to the provider that serves it.
    assert [kwargs["provider"] for _, kwargs in events] == ["google", "google", "elevenlabs"]
    assert [kwargs["voice"] for _, kwargs in events] == [
        settings.google_tts_voice_ca,
        settings.google_tts_voice_gl,
        "voice-1",
    ]


async def test_a_short_ambiguous_turn_keeps_the_call_language(voice_settings) -> None:
    """A turn with no hint and no markers must not flip the language mid-call.

    The detector only has a memory of the call's language when the watcher
    passes ``current=``. Without it an "ok" re-detects English and the voice
    jumps back, mid-call, to the clinic's default.
    """
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    from vortex.line.pipecat_voice import _LanguageState, _LanguageWatcher

    settings = voice_settings()
    events: list[tuple[str, dict]] = []
    pushed: list[object] = []
    state = _LanguageState("es")
    watcher = _LanguageWatcher(_session(settings, events), state)

    async def capture(frame: object, direction: object = FrameDirection.DOWNSTREAM) -> None:
        pushed.append(frame)

    watcher.push_frame = capture  # type: ignore[method-assign]

    def transcript(text: str) -> TranscriptionFrame:
        # No ``language``: an untagged token, so the STT hint is absent.
        return TranscriptionFrame(text=text, user_id="u", timestamp="t")

    # "ok" votes for nothing: the call stays in Spanish, and nothing is pushed.
    await watcher._maybe_switch(transcript("ok"))
    assert state.language == "es"
    assert events == []
    assert pushed == []

    # A real marker still switches: ``current`` is a fallback, not a lock.
    await watcher._maybe_switch(transcript("bon dia"))
    assert state.language == "ca"
    assert [kind for kind, _ in events] == ["voice.language_switch"]
    assert pushed[0].delta.voice == settings.google_tts_voice_ca


async def test_the_idle_handler_speaks_the_prompt_in_the_call_language(voice_settings) -> None:
    """A silent caller hears the nudge in the language of the call.

    The platform cuts a call that goes quiet, so the first silence has to
    answer. The line is read at fire time, so a mid-call language switch moves
    it — the second nudge below comes out in Catalan because the call did.
    """
    pytest.importorskip("pipecat")

    from vortex.conversation.prompt import idle_patience_for, idle_prompt_for
    from vortex.conversation.turns import IdlePolicy, default_turn_settings
    from vortex.line.pipecat_voice import _LanguageState, _make_idle_speaker

    settings = voice_settings()
    events: list[tuple[str, dict]] = []
    queued: list[object] = []

    class Task:
        async def queue_frames(self, frames: list[object]) -> None:
            queued.extend(frames)

    now = [0.0]
    policy = IdlePolicy(default_turn_settings(), clock=lambda: now[0])
    state = _LanguageState("es")
    handler = _make_idle_speaker(_session(settings, events), state, Task(), policy)

    await handler(None)
    assert [kind for kind, _ in events] == ["voice.user_idle"]
    assert [frame.text for frame in queued] == [idle_prompt_for("es")]
    assert events[-1][1]["count"] == 1
    assert events[-1][1]["level"] == 1

    now[0] = 12.0
    state.language = "ca"
    await handler(None)
    assert queued[-1].text == idle_patience_for("ca")
    assert [kind for kind, _ in events] == ["voice.user_idle"] * 2
    assert events[-1][1]["level"] == 2

    # Third event inside the mute window: logged, but nothing is spoken.
    now[0] = 20.0
    await handler(None)
    assert len(queued) == 2
    assert events[-1][1]["spoke"] is False
    assert events[-1][1]["suppressed"] == "muted"


async def test_the_idle_escalation_is_per_socket(voice_settings) -> None:
    """Two handlers never share a count. Run All opens ten sockets at once."""
    pytest.importorskip("pipecat")

    from vortex.conversation.prompt import idle_prompt_for
    from vortex.line.pipecat_voice import _LanguageState, _make_idle_speaker

    settings = voice_settings()

    def make() -> tuple[object, list[object]]:
        queued: list[object] = []

        class Task:
            async def queue_frames(self, frames: list[object]) -> None:
                queued.extend(frames)

        handler = _make_idle_speaker(_session(settings, []), _LanguageState("en"), Task())
        return handler, queued

    first, first_queued = make()
    second, second_queued = make()

    await first(None)
    await second(None)

    assert [f.text for f in first_queued] == [idle_prompt_for("en")]
    assert [f.text for f in second_queued] == [idle_prompt_for("en")]


async def test_tool_filler_speaks_one_short_phrase_per_language(voice_settings) -> None:
    """on_function_calls_started queues a short TTSSpeakFrame in the call language.

    The phrase masks LLM tool latency (~1.3 s). It is bot speech, so it does
    not trip the word gate or start the idle timer. Under ~1 s of audio.
    """
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TTSSpeakFrame

    from vortex.conversation.language import SUPPORTED_LANGUAGES
    from vortex.line.pipecat_voice import (
        TOOL_FILLERS,
        _LanguageState,
        _make_tool_filler_speaker,
        tool_filler_for,
    )

    for code in SUPPORTED_LANGUAGES:
        phrase = tool_filler_for(code)
        assert phrase == TOOL_FILLERS[code]
        assert phrase.strip()
        assert len(phrase.split()) <= 3

    assert tool_filler_for("de") == tool_filler_for("en") == TOOL_FILLERS["en"]
    assert tool_filler_for(None) == TOOL_FILLERS["en"]

    settings = voice_settings()
    events: list[tuple[str, dict]] = []
    queued: list[object] = []

    class Task:
        async def queue_frames(self, frames: list[object]) -> None:
            queued.extend(frames)

    state = _LanguageState("es")
    handler = _make_tool_filler_speaker(_session(settings, events), state, Task())

    await handler(None, [{"name": "find_patient"}])
    assert [kind for kind, _ in events] == ["voice.tool_filler"]
    assert events[0][1]["language"] == "es"
    assert events[0][1]["tools"] == 1
    assert events[0][1]["text"] == TOOL_FILLERS["es"]
    assert len(queued) == 1
    assert isinstance(queued[0], TTSSpeakFrame)
    assert queued[0].text == TOOL_FILLERS["es"]
    assert queued[0].append_to_context is True

    state.language = "ca"
    await handler(None, [{}, {}])
    assert queued[-1].text == TOOL_FILLERS["ca"]
    assert events[-1][1]["tools"] == 2
    assert [kind for kind, _ in events] == ["voice.tool_filler"] * 2


def test_vad_mode_wires_our_turn_strategies() -> None:
    """The aggregator always gets the conversation lane's strategies.

    VAD+Smart Turn installs LocalSmartTurnAnalyzerV3 with VAD stop_secs=0.2.
    Soniox mode overrides ExternalUserTurnStrategies so interrupt_min_words runs.
    """
    pytest.importorskip("pipecat")
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
    from pipecat.turns.user_start import MinWordsUserTurnStartStrategy, VADUserTurnStartStrategy
    from pipecat.turns.user_stop import (
        ExternalUserTurnStopStrategy,
        TurnAnalyzerUserTurnStopStrategy,
    )
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    from vortex.conversation.turns import TurnSettings
    from vortex.line.pipecat_voice import _user_aggregator_params

    params = _user_aggregator_params(TurnSettings(soniox_turn_detection=False))
    assert isinstance(params, LLMUserAggregatorParams)
    assert isinstance(params.user_turn_strategies, UserTurnStrategies)
    assert [type(s) for s in params.user_turn_strategies.start] == [
        VADUserTurnStartStrategy,
        MinWordsUserTurnStartStrategy,
    ]
    assert [type(s) for s in params.user_turn_strategies.stop] == [TurnAnalyzerUserTurnStopStrategy]
    assert isinstance(params.user_turn_strategies.stop[0]._turn_analyzer, LocalSmartTurnAnalyzerV3)
    assert isinstance(params.vad_analyzer.params, VADParams)
    assert params.vad_analyzer.params.stop_secs == 0.2

    soniox_params = _user_aggregator_params(TurnSettings())
    assert isinstance(soniox_params.user_turn_strategies, UserTurnStrategies)
    assert [type(s) for s in soniox_params.user_turn_strategies.start] == [
        MinWordsUserTurnStartStrategy,
    ]
    assert [type(s) for s in soniox_params.user_turn_strategies.stop] == [
        ExternalUserTurnStopStrategy,
    ]
    assert soniox_params.user_turn_strategies.start[0]._min_words == 2
    assert soniox_params.user_turn_strategies.stop[0].resolves_proposed_turn_stop_frames is True
    assert soniox_params.vad_analyzer.params.stop_secs == 0.4
    assert soniox_params.user_idle_timeout == TurnSettings().user_idle_secs


def test_smart_turn_is_built_only_where_the_vad_mode_asks_for_it() -> None:
    """The default pipeline never constructs ``LocalSmartTurnAnalyzerV3``.

    It used to, once per socket: ``user_turn_strategies=None`` made the
    aggregator build ``UserTurnStrategies()``, whose ``__post_init__`` fills an
    empty ``stop`` from ``default_user_turn_stop_strategies()``, which builds an
    ``onnxruntime.InferenceSession`` over ``smart-turn-v3.2-cpu.onnx`` eagerly
    in ``__init__``. Soniox's own endpoint detection then made it redundant, so
    every call loaded and threw away a model.

    The VAD path builds it on purpose. That is where it earns its keep.
    Silero VAD is a different model and stays in both: it feeds the aggregator.
    """
    pytest.importorskip("pipecat")
    import pipecat.audio.turn.smart_turn.local_smart_turn_v3 as smart_turn_v3
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

    from vortex.conversation.turns import TurnSettings
    from vortex.line.pipecat_voice import _user_aggregator_params

    built: list[object] = []
    original = smart_turn_v3.LocalSmartTurnAnalyzerV3.__init__

    def spy(self, *args, **kwargs):
        built.append(self)
        return original(self, *args, **kwargs)

    def count(turns: TurnSettings) -> int:
        built.clear()
        smart_turn_v3.LocalSmartTurnAnalyzerV3.__init__ = spy
        try:
            # Constructing the aggregator is where the fallback used to bite.
            LLMContextAggregatorPair(LLMContext([]), user_params=_user_aggregator_params(turns))
        finally:
            smart_turn_v3.LocalSmartTurnAnalyzerV3.__init__ = original
        return len(built)

    assert count(TurnSettings()) == 0, "Soniox mode loaded a model it never uses"
    assert count(TurnSettings(soniox_turn_detection=False, use_smart_turn=False)) == 0
    assert count(TurnSettings(soniox_turn_detection=False)) == 1, "VAD mode wants it"


def _noop_handler(tool_name: str):
    async def handler(params: object) -> None:  # pragma: no cover - never invoked
        raise AssertionError("the handler is not called in this test")

    return handler


def test_every_tool_is_registered_as_uncancellable_on_barge_in() -> None:
    """No tool may be registered with pipecat's cancel-on-interruption default.

    Observed on a live call: the caller gave name and DNI, the model called
    ``find_patient``, the caller added one more sentence ~10 ms later, and the
    interruption cancelled the in-flight call. The model then answered with no
    result and told an existing patient they were not on file. A cancelled
    ``submit_action`` is worse: the case is lost with nothing posted.
    """
    from vortex.line.pipecat_voice import register_call_tools

    seen: dict[str, dict] = {}

    class SpyLLM:
        def register_function(self, name, handler, **kwargs):
            seen[name] = kwargs

    exposed = default_turn_settings().exposed_tools
    schemas = register_call_tools(SpyLLM(), exposed, _noop_handler)

    assert seen, "no tool was registered"
    assert {s.name for s in schemas} == set(seen)
    assert "find_patient" in seen
    assert "submit_action" in seen
    for name, kwargs in seen.items():
        assert kwargs.get("cancel_on_interruption") is False, (
            f"{name} would be cancelled when the caller talks over the lookup"
        )


def test_the_real_llm_service_records_the_tools_as_async() -> None:
    """Pin it on pipecat's own registry, not just on the keyword we pass."""
    pytest.importorskip("pipecat")
    from pipecat.services.openai.llm import OpenAILLMService

    from vortex.line.pipecat_voice import register_call_tools

    llm = OpenAILLMService(api_key="test-key-not-real")
    exposed = default_turn_settings().exposed_tools
    schemas = register_call_tools(llm, exposed, _noop_handler)

    for schema in schemas:
        assert llm.has_function(schema.name)
        item = llm._functions[schema.name]
        assert item.cancel_on_interruption is False, f"{schema.name} dies on barge-in"
