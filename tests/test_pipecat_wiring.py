"""The pipecat pipeline builds with dummy keys. Nothing runs, nothing connects.

This catches import paths and constructor signatures that drift between
pipecat releases, without a key and without a network.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from vortex import tools as registry
from vortex.contract import MADRID
from vortex.conversation.prompt import initial_messages
from vortex.conversation.turns import default_turn_settings


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


def test_language_switch_picks_the_catalan_voice() -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import detect_language, tts_voice_for
    from vortex.settings import Settings

    settings = Settings()
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


async def test_language_watcher_pushes_a_tts_settings_frame() -> None:
    """The watcher turns a Catalan transcript into a voice switch, once."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame, TTSUpdateSettingsFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageWatcher
    from vortex.settings import Settings

    events: list[tuple[str, dict]] = []
    pushed: list[object] = []

    class Log:
        def event(self, kind: str, **kwargs: object) -> None:
            events.append((kind, kwargs))

    class Session:
        settings = Settings()

        class ctx:  # noqa: N801 - a stand-in for ToolContext
            log = Log()

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
    assert pushed[0].delta.voice == Session.settings.azure_tts_voice_ca
    assert pushed[0].delta.language == Language.CA_ES
    assert pushed[1].delta.voice == Session.settings.azure_tts_voice_es
