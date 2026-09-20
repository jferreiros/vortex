"""The pipecat pipeline builds with dummy keys. Nothing runs, nothing connects.

This catches import paths and constructor signatures that drift between
pipecat releases, without a key and without a network.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

import pytest

from vortex import settings as settings_module
from vortex import tools as registry
from vortex.contract import MADRID
from vortex.conversation.prompt import initial_messages
from vortex.conversation.turns import default_turn_settings

TTS_ENV = (
    "VORTEX_TTS_PROVIDER",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_MODEL",
    "ELEVENLABS_VOICE_ID_ES",
    "ELEVENLABS_VOICE_ID_DEFAULT",
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
    assert stt.language_hints == [
        Language.EN,
        Language.ES,
        Language.CA,
        Language.GL,
        Language.EU,
    ]

    from vortex.line.pipecat_voice import _llm_extra_body
    from vortex.settings import Settings

    extra = _llm_extra_body(Settings())
    llm = OpenAILLMService.Settings(model="qwen3.6", temperature=0.2, max_tokens=120, extra=extra)
    # Both dialects of "do not reason": vLLM's chat_template_kwargs and
    # Helmcode's reasoning_effort. Hosts ignore the one they do not know.
    assert llm.extra["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert llm.extra["reasoning_effort"] == "none"
    assert "chat_template_kwargs" not in llm.extra  # not a create() kwarg

    elevenlabs = ElevenLabsTTSService.Settings(
        voice="voice-1", model="eleven_flash_v2_5", language=Language.ES
    )
    assert elevenlabs.voice == "voice-1"


def test_language_switch_picks_the_catalan_voice(voice_settings) -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    from vortex.conversation.language import detect_language, tts_voice_for

    settings = voice_settings(ELEVENLABS_VOICE_ID_DEFAULT="voice-1")
    # The tag alone does not move the call; the words have to agree with it.
    assert detect_language("bon dia, voldria una hora", hint=Language.CA) == "ca"
    assert detect_language("buenos días", hint=Language.ES_ES) == "es"
    # No hint: the marker vote carries it. Nothing to vote on: English, the default.
    assert detect_language("bon dia, si us plau") == "ca"
    assert detect_language("") == "en"

    voice, language = tts_voice_for("ca", settings)
    assert voice == "voice-1"
    assert language == Language.CA
    # Unsupported falls back to English, the clinic's default.
    voice, language = tts_voice_for("de", settings)
    assert voice == "voice-1"
    assert language == Language.EN


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

    settings = voice_settings(ELEVENLABS_VOICE_ID_DEFAULT="voice-1")
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
    assert pushed[0].delta.voice == "voice-1"
    assert pushed[0].delta.language == Language.CA
    assert pushed[1].delta.voice == "voice-1"
    # Every switch names the provider that will say it.
    assert [kwargs["provider"] for _, kwargs in events] == ["elevenlabs", "elevenlabs"]


async def test_language_watcher_reaches_galician_and_basque(voice_settings) -> None:
    """One multilingual voice says gl and eu too, so the watcher must reach them."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageWatcher

    settings = voice_settings(ELEVENLABS_VOICE_ID_DEFAULT="voice-1")
    assert settings.tts_provider == "elevenlabs"
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
        ("voice-1", Language.CA),
        ("voice-1", Language.GL),
        ("voice-1", Language.EU),
        ("voice-1", Language.ES),
    ]


def test_make_tts_builds_the_elevenlabs_service(voice_settings) -> None:
    """ElevenLabs at 8 kHz: the service maps that rate to its pcm_8000 format."""
    pytest.importorskip("pipecat")
    elevenlabs_tts = pytest.importorskip("pipecat.services.elevenlabs.tts")

    from vortex.line.pipecat_voice import _make_tts

    settings = voice_settings(
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_DEFAULT="voice-1",
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


async def test_the_watcher_moves_the_state_before_the_voice_update(voice_settings) -> None:
    """A switch has to land on the branch that is about to speak, not the old one."""
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _LanguageState, _LanguageWatcher

    settings = voice_settings(
        ELEVENLABS_API_KEY="el-x",
        ELEVENLABS_VOICE_ID_DEFAULT="voice-1",
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
    # One provider says all three, so every update names it.
    assert [kwargs["provider"] for _, kwargs in events] == ["elevenlabs"] * 3
    assert [kwargs["voice"] for _, kwargs in events] == ["voice-1"] * 3


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

    settings = voice_settings(ELEVENLABS_VOICE_ID_DEFAULT="voice-1")
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
    assert pushed[0].delta.voice == "voice-1"


async def test_the_idle_handler_reprompts_once_then_submits(offline_settings) -> None:
    """First idle asks if they are there; second idle summarises and submits.

    The difficult caller goes quiet for about eight seconds. One nudge, then a
    submit on the next idle, so the three-minute call does not end empty. The
    line is read at fire time, so a mid-call language switch moves it — the
    submit line below comes out in Catalan because the call did.
    """
    pytest.importorskip("pipecat")

    from datetime import datetime

    from vortex.contract import MADRID, BookAction
    from vortex.conversation.prompt import idle_prompt_for, idle_submit_line_for
    from vortex.conversation.turns import IdlePolicy, default_turn_settings
    from vortex.line.pipecat_voice import _LanguageState, _make_idle_speaker
    from vortex.line.session import CallSession
    from vortex.line.twilio import StartPayload

    events: list[tuple[str, dict]] = []

    class Task:
        def __init__(self) -> None:
            self.queued: list[object] = []

        async def queue_frames(self, frames: list[object]) -> None:
            self.queued.extend(frames)

    start = StartPayload(streamSid="MZ-idle", callSid="CA-idle", customParameters={})
    session = CallSession.open(start, settings=offline_settings)
    original_event = session.ctx.log.event

    def _event(kind: str, **kwargs: object) -> None:
        events.append((kind, kwargs))
        original_event(kind, **kwargs)

    session.ctx.log.event = _event  # type: ignore[method-assign]

    booking = BookAction(
        patient_id="P00042",
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
        slot=datetime(2026, 9, 24, 16, 30, tzinfo=MADRID),
        policy_id="sanitas",
    )
    session.memory.remember_prepared("prepare_booking", booking)

    now = [0.0]
    policy = IdlePolicy(default_turn_settings(), clock=lambda: now[0])
    state = _LanguageState("es")
    task = Task()
    handler = _make_idle_speaker(session, state, task, policy)

    await handler(None)
    assert events[-1] == (
        "voice.user_idle",
        {"count": 1, "level": 1, "spoke": True, "suppressed": None},
    )
    assert [frame.text for frame in task.queued] == [idle_prompt_for("es")]
    assert session.submitted == []

    # Second silence, after the caller switched the call to Catalan: no more
    # nudging. The prepared booking counts as confirmed by the second silence.
    now[0] = 12.0
    state.language = "ca"
    await handler(None)
    idle_events = [kwargs for kind, kwargs in events if kind == "voice.user_idle"]
    assert idle_events[-1]["count"] == 2
    assert idle_events[-1]["level"] == 2
    idle_submit = next(kwargs for kind, kwargs in events if kind == "submit.idle")
    assert idle_submit["branch"] == "prepared_on_idle"
    assert task.queued[-1].text == idle_submit_line_for("ca")
    assert len(session.submitted) == 1
    assert session.sent_actions[0] == booking
    assert session.memory.confirmed is True

    # A third event inside the mute window is logged but speaks nothing and
    # never submits twice.
    now[0] = 20.0
    await handler(None)
    idle_events = [kwargs for kind, kwargs in events if kind == "voice.user_idle"]
    assert idle_events[-1]["spoke"] is False
    assert idle_events[-1]["suppressed"] == "muted"
    assert len(task.queued) == 2
    assert len(session.submitted) == 1
    await session.close(reason="test")


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
    from vortex.conversation.prompt import TOOL_FILLERS, FillerPicker, tool_filler_for
    from vortex.line.pipecat_voice import (
        _LanguageState,
        _make_tool_filler_speaker,
        _ToolFillerGuard,
    )

    for code in SUPPORTED_LANGUAGES:
        pool = TOOL_FILLERS[code]
        assert pool
        for phrase in pool:
            assert phrase.strip().endswith(".")
            assert phrase.count(".") == 1
        assert tool_filler_for(code) in pool

    assert tool_filler_for("de", rng=random.Random(0)) in TOOL_FILLERS["en"]
    assert tool_filler_for(None, rng=random.Random(1)) in TOOL_FILLERS["en"]
    picker = FillerPicker(rng=random.Random(2))
    first, second = picker.pick("es"), picker.pick("es")
    assert first != second

    from vortex.conversation.prompt import strip_tool_wait_talk

    assert strip_tool_wait_talk("Gracias. Un momento, lo reviso.") == "Gracias."
    assert strip_tool_wait_talk("Un segundo, lo compruebo.") == ""
    assert strip_tool_wait_talk("¿Qué tipo de cita necesitas?") == "¿Qué tipo de cita necesitas?"

    settings = voice_settings()
    events: list[tuple[str, dict]] = []
    queued: list[object] = []

    class Task:
        async def queue_frames(self, frames: list[object]) -> None:
            queued.extend(frames)

    state = _LanguageState("es")
    guard = _ToolFillerGuard()
    handler = _make_tool_filler_speaker(_session(settings, events), state, Task(), guard=guard)

    await handler(None, [{"name": "find_patient"}])
    assert [kind for kind, _ in events] == ["voice.tool_filler"]
    assert events[0][1]["language"] == "es"
    assert events[0][1]["tools"] == 1
    assert events[0][1]["text"] in TOOL_FILLERS["es"]
    assert len(queued) == 1
    assert isinstance(queued[0], TTSSpeakFrame)
    assert queued[0].text in TOOL_FILLERS["es"]
    assert queued[0].append_to_context is False

    state.language = "ca"
    guard.on_caller_turn()  # the caller answered: a new interaction may mask
    await handler(None, [{}, {}])
    assert queued[-1].text in TOOL_FILLERS["ca"]
    assert events[-1][1]["tools"] == 2
    assert [kind for kind, _ in events] == ["voice.tool_filler"] * 2


async def test_the_filler_guard_speaks_one_filler_per_interaction(voice_settings) -> None:
    """A tool chain that fires batch after batch speaks the phrase once.

    Evidence CA-voicetest-1789811447: five completions in seven seconds, each
    starting a tool batch, each re-speaking "Un momento.". The caller heard
    the filler flood instead of an answer. The guard speaks the first batch
    and stays quiet until the caller speaks again; typing covers the rest.
    """
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import TTSSpeakFrame

    from vortex.line.pipecat_voice import (
        _LanguageState,
        _make_tool_filler_speaker,
        _ToolFillerGuard,
    )

    settings = voice_settings()
    events: list[tuple[str, dict]] = []
    queued: list[object] = []

    class Task:
        async def queue_frames(self, frames: list[object]) -> None:
            queued.extend(frames)

    now = [0.0]
    guard = _ToolFillerGuard(cooldown_secs=4.0, clock=lambda: now[0])
    handler = _make_tool_filler_speaker(
        _session(settings, events), _LanguageState("es"), Task(), guard=guard
    )

    # First batch speaks.
    await handler(None, [{"name": "find_patient"}])
    assert len(queued) == 1

    # The next hops of the same chain stay quiet, whatever the language.
    now[0] = 1.4
    await handler(None, [{"name": "resolve_date"}])
    now[0] = 2.9
    await handler(None, [{"name": "triage"}])
    assert len(queued) == 1
    assert events[-1][1]["suppressed"] == "same_turn"

    # Past any old cooldown the chain still stays quiet: typing is the wait.
    now[0] = 5.0
    await handler(None, [{"name": "find_slots"}])
    assert len(queued) == 1

    # A caller turn re-arms the slot.
    now[0] = 5.5
    guard.on_caller_turn()
    await handler(None, [{"name": "find_patient"}])
    assert len(queued) == 2
    assert isinstance(queued[-1], TTSSpeakFrame)


def test_user_aggregator_params_carry_idle_and_stop_timeouts() -> None:
    """Acceptance: the idle timeout follows settings; the stop safety net is 6 s."""
    pytest.importorskip("pipecat")
    from vortex.conversation.turns import TurnSettings
    from vortex.line.pipecat_voice import _user_aggregator_params

    turns = TurnSettings()
    params = _user_aggregator_params(turns)
    assert params.user_idle_timeout == turns.user_idle_secs
    assert params.user_turn_stop_timeout == 6.0


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


def test_soniox_endpoint_knobs_are_the_conservative_pair(voice_settings) -> None:
    """The pipeline's Soniox settings endpoint conservatively, not eagerly.

    Evidence CA-voicetest-1789811447: sensitivity 0.3 with latency adjustment 2
    endpointed the caller after every breath group, the agent answered the
    fragments and talked over the rest of the sentence. The builder pins the
    knobs to the conservative pair regardless of the turn settings' tuning.
    """
    pytest.importorskip("pipecat")
    from pipecat.services.soniox.stt import SonioxSTTService
    from pipecat.transcriptions.language import Language

    from vortex.line.pipecat_voice import _soniox_stt_settings

    class Ctx:
        from vortex.clinic.client import FakeClinicClient

        clinic = FakeClinicClient()

    built = _soniox_stt_settings(voice_settings(), default_turn_settings(), Ctx())
    assert isinstance(built, SonioxSTTService.Settings)
    assert built.endpoint_sensitivity == 0.0
    assert built.endpoint_latency_adjustment_level == 0
    # The acoustic fallback keeps its ceiling: a true stall cannot hold the
    # line longer than this, even with the semantic endpointer set loose.
    assert built.max_endpoint_delay_ms == default_turn_settings().stt_max_endpoint_delay_ms
    assert built.language_hints == [
        Language.EN,
        Language.ES,
        Language.CA,
        Language.GL,
        Language.EU,
    ]


async def test_the_stall_guard_finalizes_a_starved_turn() -> None:
    """No inbound audio with a turn open: the guard asks Soniox to flush.

    Soniox emits ``<end>`` only while audio flows, so a caller that stops
    streaming mid-turn holds the transcript open forever (evidence
    CA-voicetest-1789811079: every turn was lost this way). After half a
    second of starvation the guard sends the same finalize message the service
    sends on a VAD stop, and logs that it did.
    """
    pytest.importorskip("pipecat")
    from vortex.line.soniox_stall import make_stall_guarded_soniox_stt

    events: list[tuple[str, dict]] = []
    sent: list[str] = []

    class FakeWS:
        state = None  # not OPEN is checked; any object passes

        async def send(self, data: str) -> None:
            sent.append(data)

    from websockets.protocol import State

    now = [0.0]
    stt_cls = make_stall_guarded_soniox_stt(
        on_event=lambda kind, **kw: events.append((kind, kw)), clock=lambda: now[0]
    )
    svc = stt_cls(api_key="test", vad_force_turn_endpoint=False)
    svc._websocket = FakeWS()
    FakeWS.state = State.OPEN

    # Audio flows at t=4.0 with no turn open: however long the silence, there
    # is nothing to finalize.
    now[0] = 4.0
    svc.note_audio()
    now[0] = 4.6
    assert svc.stall_due() is False

    # The turn opens; audio is still fresh, so not due yet.
    await svc._user_turn_started()
    now[0] = 4.1
    assert svc.stall_due() is False

    # Half a second of starvation with the turn open: due.
    now[0] = 4.6
    assert svc.stall_due() is True
    finalize = asyncio.create_task(svc.request_finalize())
    await asyncio.sleep(0.01)  # the finalize goes out; the wait loop spins
    assert sent == ['{"type": "finalize"}']
    assert events[0][0] == "voice.stt_stall_finalize"
    assert events[0][1]["silence_secs"] == 0.6
    now[0] = 10.0  # Soniox answered, the turn closed, the window runs out
    await finalize

    # One episode per starvation: no second finalize without new audio.
    assert svc.stall_due() is False


async def test_the_stall_guard_promotes_the_last_interim_when_soniox_is_dead() -> None:
    """A finalize Soniox never answers: the last interim becomes the final.

    The words the caller said must reach the model even when the STT socket
    died mid-turn. After the fallback window the guard pushes the interim text
    as a final transcript plus the turn-stop proposal, so the strategies close
    the turn with the text in hand.
    """
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import ProposedUserStoppedSpeakingFrame, TranscriptionFrame

    from vortex.line.soniox_stall import make_stall_guarded_soniox_stt

    events: list[tuple[str, dict]] = []
    pushed: list[object] = []
    sent: list[str] = []

    class FakeWS:
        from websockets.protocol import State

        state = State.OPEN

        async def send(self, data: str) -> None:
            sent.append(data)

    now = [0.0]
    stt_cls = make_stall_guarded_soniox_stt(
        on_event=lambda kind, **kw: events.append((kind, kw)), clock=lambda: now[0]
    )
    svc = stt_cls(api_key="test")
    svc._websocket = FakeWS()
    svc._user_turn_open = True
    svc.note_audio()
    svc.note_interim("Hola, buenos días.")
    now[0] = 1.0

    async def capture(frame: object, direction: object = None) -> None:
        pushed.append(frame)

    svc.push_frame = capture  # type: ignore[method-assign]

    finalize = asyncio.create_task(svc.request_finalize())
    await asyncio.sleep(0.01)  # the finalize goes out, then the wait loop spins
    now[0] = 10.0  # past the fallback window: Soniox never answered
    await finalize

    assert sent == ['{"type": "finalize"}']
    assert [kind for kind, _ in events] == ["voice.stt_stall_finalize", "voice.stt_stall_fallback"]
    assert isinstance(pushed[0], TranscriptionFrame)
    assert pushed[0].text == "Hola, buenos días."
    assert isinstance(pushed[1], ProposedUserStoppedSpeakingFrame)


async def test_the_stall_guard_stays_quiet_when_a_final_arrives() -> None:
    """A real final consumes the interim: no synthesized duplicate can fire."""
    pytest.importorskip("pipecat")
    from vortex.line.soniox_stall import make_stall_guarded_soniox_stt

    events: list[tuple[str, dict]] = []
    now = [0.0]
    stt_cls = make_stall_guarded_soniox_stt(
        on_event=lambda kind, **kw: events.append((kind, kw)), clock=lambda: now[0]
    )
    svc = stt_cls(api_key="test", vad_force_turn_endpoint=False)
    svc._user_turn_open = True
    svc.note_audio()
    svc.note_interim("Hola.")
    svc.note_final()
    await svc._user_turn_stopped()  # the <end> closed the turn, as the real path does
    now[0] = 5.0
    assert svc.stall_due() is False  # the turn closed; nothing to do
    await svc.request_finalize()
    assert [kind for kind, _ in events] == ["voice.stt_stall_finalize"]
    assert not any(kind == "voice.stt_stall_fallback" for kind, _ in events)


async def test_the_reply_latency_probe_reports_the_wait(voice_settings) -> None:
    """End of speech -> turn closed -> first audio, logged once per turn.

    Both legs land on ``voice.reply_latency``: detection (endpointing) and
    total (end of speech to first agent audio), so the post-mortem can see
    where a slow answer spent its time.
    """
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import (
        OutputAudioRawFrame,
        UserStoppedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
    from pipecat.observers.base_observer import FramePushed
    from pipecat.processors.frame_processor import FrameDirection

    from vortex.line.pipecat_voice import _CallLogObserver

    settings = voice_settings()
    events: list[tuple[str, dict]] = []
    fake = _session(settings, events)
    fake.memory = type("Memory", (), {"prepared": None})()
    fake.confirm_prepared = lambda why: None
    fake.media_frames_in = 0
    fake.media_frames_out = 0

    now = [0.0]
    observer = _CallLogObserver(fake, clock=lambda: now[0])

    async def push(frame: object) -> None:
        await observer.on_push_frame(
            FramePushed(
                source=None,
                destination=None,
                frame=frame,
                direction=FrameDirection.DOWNSTREAM,
                timestamp=0,
            )
        )

    # The caller stops speaking at t=1.0; detection closes the turn at 1.6;
    # the first agent audio leaves at 2.9.
    now[0] = 1.0
    await push(VADUserStoppedSpeakingFrame(stop_secs=0.4))
    now[0] = 1.6
    await push(UserStoppedSpeakingFrame())
    now[0] = 2.9
    await push(OutputAudioRawFrame(audio=b"", sample_rate=8000, num_channels=1))
    assert [kind for kind, _ in events] == ["voice.reply_latency"]
    assert events[-1][1]["detection_secs"] == 0.6
    assert events[-1][1]["total_secs"] == 1.9

    # Further audio of the same reply does not re-report the turn.
    now[0] = 3.5
    await push(OutputAudioRawFrame(audio=b"", sample_rate=8000, num_channels=1))
    assert [kind for kind, _ in events] == ["voice.reply_latency"]


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

    class OfflineOpenAILLMService(OpenAILLMService):
        """The registry lives on the service, so no credential and no client."""

        def create_client(self, **kwargs: object) -> None:
            return None

    llm = OfflineOpenAILLMService()
    exposed = default_turn_settings().exposed_tools
    schemas = register_call_tools(llm, exposed, _noop_handler)

    for schema in schemas:
        assert llm.has_function(schema.name)
        item = llm._functions[schema.name]
        assert item.cancel_on_interruption is False, f"{schema.name} dies on barge-in"


# --- usage metering ----------------------------------------------------------


def _pipeline_params_kwargs() -> dict[str, object]:
    """The keywords ``run_pipecat_call`` builds ``PipelineParams`` with.

    Read off the source, like the hangup wiring test: building the real
    pipeline needs the four provider keys. The keywords are then handed to the
    real ``PipelineParams``, so a flag pipecat renamed fails here too.
    """
    import ast
    import inspect

    from vortex.line import pipecat_voice

    tree = ast.parse(inspect.getsource(pipecat_voice.run_pipecat_call))
    for node in ast.walk(tree):
        is_params = isinstance(node, ast.Call) and getattr(node.func, "id", "") == "PipelineParams"
        if not is_params:
            continue
        kwargs: dict[str, object] = {}
        for keyword in node.keywords:
            assert keyword.arg is not None, "**kwargs would hide the flags"
            if isinstance(keyword.value, ast.Constant):
                kwargs[keyword.arg] = keyword.value.value
            elif isinstance(keyword.value, ast.Name):
                kwargs[keyword.arg] = getattr(pipecat_voice, keyword.value.id)
            else:
                raise AssertionError(f"unreadable PipelineParams keyword {keyword.arg}")
        return kwargs
    raise AssertionError("run_pipecat_call builds no PipelineParams")


def test_pipeline_enables_usage_metrics() -> None:
    """Without both flags pipecat measures nothing the wall can price a call with.

    ``enable_metrics`` alone gives latencies only: the three
    ``start_*_usage_metrics`` hooks are gated on ``enable_usage_metrics`` and
    return silently without it, so no STT second, no token and no character is
    ever pushed as a frame.
    """
    pytest.importorskip("pipecat")
    from pipecat.pipeline.task import PipelineParams

    params = PipelineParams(**_pipeline_params_kwargs())

    assert params.enable_metrics is True
    assert params.enable_usage_metrics is True


def test_the_lane_marks_the_call_as_metered() -> None:
    """``metered`` is the flag's echo, so it is set where the flag is."""
    pytest.importorskip("pipecat")
    import inspect

    from vortex.line.pipecat_voice import run_pipecat_call

    assert "session.usage.metered = True" in inspect.getsource(run_pipecat_call)


def _metrics_frame(*data: object):
    from pipecat.frames.frames import MetricsFrame

    return MetricsFrame(data=list(data))


def _pushed(frame: object):
    from pipecat.processors.frame_processor import FrameDirection

    return type(
        "FramePushed",
        (),
        {"frame": frame, "direction": FrameDirection.DOWNSTREAM},
    )()


async def test_the_observer_meters_stt_llm_and_each_tts_service(offline_settings) -> None:
    """Usage frames in, one ``call.usage`` line out, split per TTS service.

    Chirp 3 HD and Gemini-TTS bill at different rates, so their characters may
    never land in the same bucket. Every frame is pushed twice here because
    pipecat pushes it at every link it crosses: the totals must not double.
    """
    pytest.importorskip("pipecat")

    from pipecat.metrics.metrics import (
        LLMTokenUsage,
        LLMUsageMetricsData,
        STTUsage,
        STTUsageMetricsData,
        TTFBMetricsData,
        TTSUsageMetricsData,
    )

    from vortex.line.pipecat_voice import _CallLogObserver
    from vortex.line.session import CallSession
    from vortex.line.twilio import StartPayload

    call_id = "CA-usage"
    start = StartPayload(streamSid="MZ-usage", callSid=call_id, customParameters={})
    session = CallSession.open(start, settings=offline_settings)
    session.usage.metered = True
    observer = _CallLogObserver(session)

    soniox = "SonioxSTTService#0"
    frames = [
        _metrics_frame(STTUsageMetricsData(processor=soniox, value=STTUsage(audio_seconds=30.25))),
        _metrics_frame(STTUsageMetricsData(processor=soniox, value=STTUsage(audio_seconds=17.05))),
        _metrics_frame(
            LLMUsageMetricsData(
                processor="OpenAILLMService#0",
                model="whatever-the-host-called-it",
                value=LLMTokenUsage(
                    prompt_tokens=11840,
                    completion_tokens=512,
                    total_tokens=12352,
                    cache_read_input_tokens=64,
                ),
            )
        ),
        # Two legs: the service reports no model on one of them, so the
        # configured id stands in and the two land in different buckets.
        _metrics_frame(
            TTSUsageMetricsData(processor="ElevenLabsTTSService#0", model="", value=1000)
        ),
        _metrics_frame(
            TTSUsageMetricsData(processor="ElevenLabsTTSService#0", model="", value=180)
        ),
        _metrics_frame(
            TTSUsageMetricsData(
                processor="ElevenLabsTTSService#0", model="eleven_multilingual_v2", value=90
            )
        ),
        # A latency frame: measured, not billed.
        _metrics_frame(TTFBMetricsData(processor="OpenAILLMService#0", value=0.4)),
    ]
    for frame in frames:
        await observer.on_push_frame(_pushed(frame))
        await observer.on_push_frame(_pushed(frame))

    usage = session.usage
    assert usage.stt_audio_seconds == pytest.approx(47.3)
    assert usage.stt_requests == 2
    assert usage.prompt_tokens == 11840
    assert usage.completion_tokens == 512
    assert usage.reasoning_tokens == 0
    assert usage.cache_read_input_tokens == 64
    assert usage.llm_requests == 1
    assert usage.tts_characters == 1270

    await session.close(reason="test")

    from conftest import captured_events

    lines = captured_events()
    kinds = [line["kind"] for line in lines if line["call_id"] == call_id]
    assert kinds.index("call.usage") == kinds.index("call.ended") - 1

    event = next(line for line in lines if line["kind"] == "call.usage")
    event.pop("ts")
    assert event == {
        "call_id": call_id,
        "kind": "call.usage",
        "metered": True,
        "stt": {
            "provider": "soniox",
            "model": offline_settings.soniox_stt_model,
            "audio_seconds": 47.3,
            "requests": 2,
        },
        "llm": {
            "provider": offline_settings.llm_provider,
            "model": offline_settings.llm_model,
            "prompt_tokens": 11840,
            "completion_tokens": 512,
            "reasoning_tokens": 0,
            "cache_read_input_tokens": 64,
            "requests": 1,
        },
        "tts": [
            {
                "provider": "elevenlabs",
                "service": "ElevenLabsTTSService",
                "model": offline_settings.elevenlabs_model,
                "characters": 1180,
                "requests": 2,
            },
            {
                "provider": "elevenlabs",
                "service": "ElevenLabsTTSService",
                "model": "eleven_multilingual_v2",
                "characters": 90,
                "requests": 1,
            },
        ],
    }
