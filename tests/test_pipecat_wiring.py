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
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_TTS_CREDENTIALS_JSON",
    "GOOGLE_TTS_VOICE_ES",
    "GOOGLE_TTS_VOICE_CA",
    "GOOGLE_TTS_VOICE_GL",
    "GOOGLE_TTS_VOICE_EU",
    "AZURE_TTS_VOICE_ES",
    "AZURE_TTS_VOICE_CA",
    "DEEPGRAM_TTS_MODEL",
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


def test_pipecat_modules_import() -> None:
    pytest.importorskip("pipecat")
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: F401
    from pipecat.frames.frames import TTSUpdateSettingsFrame  # noqa: F401
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (  # noqa: F401
        LLMContextAggregatorPair,
    )
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.services.azure.tts import AzureTTSService  # noqa: F401
    from pipecat.services.deepgram.tts import DeepgramTTSService  # noqa: F401
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
    from pipecat.services.azure.tts import AzureTTSService
    from pipecat.services.deepgram.tts import DeepgramTTSService
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
    assert stt.language_hints == [Language.ES, Language.CA]

    llm = OpenAILLMService.Settings(
        model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        temperature=0.2,
        max_tokens=120,
        extra={"chat_template_kwargs": {"enable_thinking": False}},
    )
    assert llm.extra["chat_template_kwargs"] == {"enable_thinking": False}

    azure = AzureTTSService.Settings(voice="es-ES-ElviraNeural", language=Language.ES_ES)
    assert azure.voice == "es-ES-ElviraNeural"

    deepgram = DeepgramTTSService.Settings(voice="aura-2-celeste-es")
    assert deepgram.voice == "aura-2-celeste-es"

    google = GoogleHttpTTSService.Settings(voice="es-ES-Chirp3-HD-Aoede", language=Language.ES_ES)
    assert google.voice == "es-ES-Chirp3-HD-Aoede"


def test_language_switch_picks_the_catalan_voice(voice_settings) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import detect_language, tts_voice_for

    settings = voice_settings(VORTEX_TTS_PROVIDER="azure")
    assert detect_language("bon dia, voldria una hora", hint=Language.CA) == "ca"
    assert detect_language("buenos días", hint=Language.ES_ES) == "es"
    # No hint: the marker list carries it.
    assert detect_language("bon dia, si us plau") == "ca"
    assert detect_language("") == "es"

    voice, language = tts_voice_for("ca", settings)
    assert voice == settings.azure_tts_voice_ca
    assert language == Language.CA_ES
    voice, language = tts_voice_for("de", settings)
    assert voice == settings.azure_tts_voice_es
    assert language == Language.ES_ES


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


async def test_language_watcher_pushes_a_tts_settings_frame(voice_settings) -> None:
    """The watcher turns a Catalan transcript into a voice switch, once."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame, TTSUpdateSettingsFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageWatcher

    settings = voice_settings(VORTEX_TTS_PROVIDER="azure")
    events: list[tuple[str, dict]] = []
    pushed: list[object] = []

    class Log:
        def event(self, kind: str, **kwargs: object) -> None:
            events.append((kind, kwargs))

    class Session:
        pass

    Session.settings = settings
    Session.ctx = type("ctx", (), {"log": Log()})

    watcher = _LanguageWatcher(Session())

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
    assert pushed[0].delta.voice == settings.azure_tts_voice_ca
    assert pushed[0].delta.language == Language.CA_ES
    assert pushed[1].delta.voice == settings.azure_tts_voice_es


async def test_language_watcher_reaches_galician_and_basque_on_google(voice_settings) -> None:
    """Google is the only provider with gl and eu, so the watcher must use them."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageWatcher

    settings = voice_settings()  # google is the default
    assert settings.tts_provider == "google"
    assert settings.tts_supports_language_switch is True

    pushed: list[object] = []

    class Session:
        pass

    Session.settings = settings
    Session.ctx = type("ctx", (), {"log": type("log", (), {"event": lambda *a, **k: None})()})

    watcher = _LanguageWatcher(Session())

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


def test_make_tts_builds_the_google_service(voice_settings) -> None:
    """_make_tts wires our settings into GoogleHttpTTSService at 8 kHz."""
    pytest.importorskip("pipecat")
    pytest.importorskip("cryptography")
    google_tts = pytest.importorskip("pipecat.services.google.tts")

    from vortex.line.pipecat_voice import _make_tts

    settings = voice_settings(GOOGLE_TTS_CREDENTIALS_JSON=fake_service_account_json())
    tts = _make_tts(settings)

    assert isinstance(tts, google_tts.GoogleHttpTTSService)
    assert tts._init_sample_rate == 8000
    assert tts._settings.voice == settings.google_tts_voice_es
    assert tts._settings.language == "es-ES"
