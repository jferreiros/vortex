"""The real voice pipeline: pipecat over the Twilio-shaped socket.

    transport.input -> STT (Soniox stt-rt-v5) -> language watcher
                    -> user aggregator -> LLM (OpenAI-compatible, EU)
                    -> TTS (ElevenLabs)
                    -> transport.output -> assistant aggregator

Soniox transcribes, an OpenAI-compatible endpoint named by ``LLM_PROVIDER``
(``helmcode`` or ``azure``) answers, and ElevenLabs speaks. One TTS service
carries the whole line: its multilingual models say English, Spanish, Catalan,
Galician and Basque, so a language switch is a new voice id on the same
service, never a second service to route to.

One pipeline per socket. The serializer takes the ``stream_sid`` of this call,
the context takes this call's prompt, and every tool handler closes over this
call's ``ToolContext``. Nothing here is module-level state.

Owner: the line lane for the wiring; the conversation lane for prompt, turn
settings, STT vocabulary and language (it edits ``vortex/conversation/*``).

Imports of pipecat live inside the function so the server starts, and the
smoke test runs, with the stub pipeline when the keys are missing.

We hang up from our side. Once the platform has accepted an action the model
sent, the session is armed; ``_make_hangup_watcher`` then ends the pipeline
with an ``EndFrame`` as soon as the agent has finished speaking its farewell,
and the socket closes. ``auto_hang_up`` stays False: that flag is the
serializer's own Twilio REST call, and we have no Twilio account.

TODO(line):
- Run one real call end to end once the three keys exist.
- Confirm the 8 kHz µ-law path: serializer ``twilio_sample_rate=8000`` in, and
  the TTS asked for 8 kHz PCM out (ElevenLabs ``pcm_8000``). Check for choppy
  audio.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

from vortex import tools as registry
from vortex.contract import action_route
from vortex.conversation.language import (
    DEFAULT_LANGUAGE,
    detect_language,
    normalise_language,
    tts_voice_for,
)
from vortex.conversation.prompt import (
    FillerPicker,
    greeting_for,
    handoff_greeting_for,
    idle_submit_line_for,
    initial_messages,
    wait_prompt_for,
)
from vortex.conversation.turns import (
    ConfirmationPolicy,
    IdlePolicy,
    TurnSettings,
    default_turn_settings,
    effective_vad_stop_secs,
    is_refusal_acceptance,
    user_turn_strategies,
)
from vortex.line import voice_config
from vortex.line.aic_filter import build_audio_in_filter
from vortex.line.ambience import OFFICE_SOUND, TYPING_SOUND, _make_ambience_mixer
from vortex.line.elevenlabs_voice import ElevenLabsVoicePreset
from vortex.line.llm_timeout import first_token_guard
from vortex.line.session import CallSession
from vortex.line.soniox_stall import make_stall_guarded_soniox_stt
from vortex.observability.tracing import traced_openai_llm_service

log = logging.getLogger(__name__)

# Both the line in and the voice out are 8 kHz: the platform speaks µ-law at
# 8 kHz and the serializer does the companding.
LINE_SAMPLE_RATE = 8000

# Soniox endpoint knobs, back at Soniox's own defaults. The pair the turn
# settings carry (sensitivity 0.3, latency adjustment 2) was tuned for speed
# and measured on the 2026-09-19 live-audio run (CA-voicetest-1789811447) to
# endpoint the caller's telephony audio after every breath group - "Hola." /
# "Buenos días." / ... - so the agent answered each fragment and talked over
# the caller mid-sentence. Half the turns of that call were eaten this way.
# The conservative pair holds the turn while the caller breathes; the acoustic
# fallback (``stt_max_endpoint_delay_ms``) still bounds a true stall, and the
# stall guard in ``vortex.line.soniox_stall`` bounds the no-audio case.
SONIOX_ENDPOINT_SENSITIVITY = 0.0
SONIOX_ENDPOINT_LATENCY_ADJUSTMENT_LEVEL = 0

# The tool filler masks LLM latency, but a tool chain runs several completions
# in a row and each one started a batch. Speak once per caller turn; after that
# only the keyboard. A 4 s cooldown used to re-speak mid-lookup (CA-mic-1789862225014).
FILLER_REPEAT_COOLDOWN_SECS = 4.0


def _language_hints(codes: tuple[str, ...]) -> list[Any]:
    """Turn our ISO codes into pipecat ``Language`` members, dropping unknowns."""
    from pipecat.transcriptions.language import Language

    hints = []
    for code in codes:
        try:
            hints.append(Language(code))
        except ValueError:
            log.warning("unknown STT language hint %r, ignored", code)
    return hints


def _soniox_stt_settings(settings: Any, turns: Any, ctx: Any) -> Any:
    """The Soniox settings the pipeline runs, endpoint knobs included.

    The endpoint knobs come from this module, not from the turn settings: the
    eager pair the turn settings carry fragments telephony audio (see the
    constants above for the measurement). Everything else stays the turn
    settings' call.
    """
    from pipecat.services.soniox.stt import SonioxContextObject, SonioxSTTService

    from vortex.conversation.stt_context import stt_context_text, stt_terms

    return SonioxSTTService.Settings(
        model=settings.soniox_stt_model,
        language_hints=_language_hints(turns.stt_language_hints),
        enable_language_identification=True,
        context=SonioxContextObject(text=stt_context_text(), terms=stt_terms(ctx)),
        max_endpoint_delay_ms=turns.stt_max_endpoint_delay_ms,
        endpoint_sensitivity=SONIOX_ENDPOINT_SENSITIVITY,
        endpoint_latency_adjustment_level=SONIOX_ENDPOINT_LATENCY_ADJUSTMENT_LEVEL,
    )


def register_call_tools(
    llm: Any, exposed_tools: list[str], make_handler: Callable[[str], Any]
) -> list[Any]:
    """Advertise every exposed registry tool on ``llm`` and bind its handler.

    Returns the ``FunctionSchema`` list the LLM context is built with.

    Every tool is registered with ``cancel_on_interruption=False``. Pipecat's
    default is ``True``: an in-flight tool call is cancelled the moment an
    ``InterruptionFrame`` reaches the LLM service, which on a phone line is any
    caller who keeps talking. Our tools are short read-only clinic lookups plus
    ``submit_action``, and none of them is worth abandoning half-way.

    With the flag off the call is asynchronous in pipecat's sense: the handler
    runs to completion and its result still reaches the model. When nothing
    moved on in the meantime the result settles in place, exactly like a
    synchronous call; when the caller did speak, it arrives as a developer
    message and the model answers the new turn with the result in scope.
    """
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    schemas: list[Any] = []
    for fn in registry.function_schemas(exposed_tools):
        params_schema = fn["parameters"]
        properties = dict(params_schema["properties"])
        if params_schema.get("$defs"):
            # Nested models (Slot, Action ...) need their definitions inline.
            properties["$defs"] = params_schema["$defs"]
        schemas.append(
            FunctionSchema(
                name=fn["name"],
                description=fn["description"],
                properties=properties,
                required=params_schema["required"],
            )
        )
        llm.register_function(
            fn["name"],
            make_handler(fn["name"]),
            # Barge-in must never kill a tool: a cancelled find_patient makes the
            # model deny a patient who exists, a cancelled submit_action loses
            # the case with nothing posted.
            cancel_on_interruption=False,
        )
    return schemas


async def run_pipecat_call(
    ws: WebSocket, session: CallSession, turn_settings: TurnSettings | None = None
) -> str:
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.frames.frames import TTSSpeakFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    settings = session.settings
    turns = turn_settings or default_turn_settings()
    ctx = session.ctx
    ctx.log.event("voice.mode", mode="pipecat", **_providers(settings))

    serializer = TwilioFrameSerializer(
        stream_sid=session.stream_sid,
        call_sid=session.call_id,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    # Optional AICFilter (Quail 8 kHz) before Silero/Soniox. Default off —
    # only enable after entity CER drops on the T54 5 dB bench.
    audio_in_filter = build_audio_in_filter(settings)
    if audio_in_filter is not None:
        ctx.log.event(
            "voice.aic_filter",
            model=settings.aic_model_id,
            enabled=True,
        )
    ambience_mixer = _make_ambience_mixer()
    if ambience_mixer is not None:
        ctx.log.event("voice.ambience", sound="office")
    transport = FastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=LINE_SAMPLE_RATE,
            add_wav_header=False,
            serializer=serializer,
            audio_in_filter=audio_in_filter,
            audio_out_mixer=ambience_mixer,
        ),
    )

    # ---- STT: Soniox. Language identification tags every transcription frame,
    # which is what the language watcher below switches the voice on. ----------
    stt_cls = make_stall_guarded_soniox_stt(on_event=ctx.log.event)
    stt = stt_cls(
        api_key=settings.soniox_api_key,
        settings=_soniox_stt_settings(settings, turns, ctx),
        # False hands the end of the turn to Soniox's own endpoint detection.
        vad_force_turn_endpoint=not turns.soniox_turn_detection,
        should_interrupt=turns.enable_interruptions,
    )

    # The language this call is in, shared by the watcher that updates it and
    # the router that reads it. Per call: a closure, never a module global.
    # A call that arrives through an outbound-call handoff already has its
    # language: the patient picked it during the confirmation call.
    language_state = _LanguageState()
    if session.handoff:
        if handoff_language := normalise_language(session.handoff.get("language")):
            language_state.language = handoff_language

    # ---- LLM: any OpenAI-compatible endpoint, as long as it is in the EU. ----
    llm_settings = OpenAILLMService.Settings(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        extra=_llm_extra_body(settings),
    )
    llm = traced_openai_llm_service(
        # The guard goes underneath the tracing subclass, which only overrides
        # ``create_client``: a request that never streams a first token is
        # abandoned, re-issued, and in the worst case answered with a short
        # spoken line. See vortex/line/llm_timeout.py for the post-mortem.
        first_token_guard(OpenAILLMService),
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        settings=llm_settings,
        first_token_timeout_secs=settings.llm_first_token_timeout_secs,
        llm_retries=settings.llm_retries,
        retry_model=settings.llm_alt_model,
        # Read at fire time, so a mid-call language switch moves the line and
        # the TTS router sends it down the branch that can say it.
        timeout_fallback_text=lambda: wait_prompt_for(language_state.language),
        timeout_log_event=ctx.log.event,
    )

    # The wall's two cards, read once per socket: a change lands on the next
    # call, never mid-flight. "Voz del agente" carries the delivery; the
    # Personalities page carries who is answering.
    voice_cfg = voice_config.load(settings)
    persona = _active_personality(settings)
    ctx.log.event(
        "voice.personality",
        slug=getattr(persona, "slug", "") if persona else "",
        name=getattr(persona, "name", "") if persona else "",
    )
    tts = _make_tts_stage(settings, language_state, voice_cfg)

    # ---- tools: every registry entry becomes a function the model can call ----
    def make_handler(tool_name: str):
        async def handler(params: FunctionCallParams) -> None:
            try:
                # Through the session, not the registry: it remembers what the
                # end-of-call fallback needs (the last refusal, the last
                # prepared action) and records the model's own submissions.
                result = await session.call_tool(tool_name, dict(params.arguments))
                await params.result_callback(result.model_dump(mode="json"))
            except Exception as exc:  # the model must hear about failures, typed
                await params.result_callback({"error": f"{type(exc).__name__}: {exc}"})

        return handler

    schemas = register_call_tools(llm, turns.exposed_tools, make_handler)

    # Before the greeting: the caller id is an exact directory query, so the
    # prompt can open knowing who the line belongs to instead of spending the
    # first minute of the call asking.
    caller = await session.resolve_caller_line()
    # The prompt's LANGUAGE line renders this. Without it the system prompt said
    # "Answer in English" on every call, including a handoff that already knew
    # the patient's language from the confirmation call.
    messages = initial_messages(
        ctx.now, language=language_state.language, caller=caller, handoff=session.handoff
    )
    # Who is on the phone, before how they say it: the persona gives the model a
    # name to answer to, the sliders only colour the delivery.
    if block := _persona_directive(persona):
        messages[0]["content"] += f"\n{block}"
    # Tono/Amabilidad are not TTS fields: they arrive as one extra line on the
    # system prompt. Empty at neutral, so an untouched card changes nothing.
    if directive := voice_config.style_directive(voice_cfg):
        messages[0]["content"] += f"\n{directive}"
    context = LLMContext(messages, tools=ToolsSchema(standard_tools=schemas))
    aggregators = LLMContextAggregatorPair(context, user_params=_user_aggregator_params(turns))

    # Ends the call from our side once the platform holds an action and the
    # agent has said its goodbye. It is both an observer of the frame stream
    # (for the farewell) and a handler on the user aggregator (for a caller who
    # goes quiet after the submission), so it is built before either exists and
    # handed the task below. A second handler is not a change to the first: the
    # aggregator appends them, so the idle nudge still fires on every call that
    # is not armed.
    hangup = _make_hangup_watcher(session)
    aggregators.user().add_event_handler("on_user_turn_idle", hangup.on_user_idle)

    # One filler guard and picker per call, shared by the speaker and the observer.
    filler_guard = _ToolFillerGuard()
    filler_picker = FillerPicker()

    stages: list[Any] = [transport.input(), stt]
    # Always on: one multilingual service speaks all five languages, so there
    # is no configuration in which the watcher is a no-op. It used to be gated
    # on ``tts_supports_language_switch``, which was False whenever the primary
    # provider was declared Spanish-only — and that silently froze the call in
    # English *and* left ``session.language`` unset, so the day-before
    # confirmation call was dialled in the wrong language too.
    stages.append(_LanguageWatcher(session, language_state, voice_cfg))
    stages += [
        aggregators.user(),
        llm,
        _PrivacyGuard(session, language_state),
        tts,
        _AmbienceSwitcher(session),
        transport.output(),
        aggregators.assistant(),
    ]

    task = PipelineTask(
        Pipeline(stages),
        params=PipelineParams(
            audio_in_sample_rate=LINE_SAMPLE_RATE,
            audio_out_sample_rate=LINE_SAMPLE_RATE,
            enable_metrics=True,
            # The one flag behind all three usage emitters: without it
            # ``FrameProcessor.start_{llm,stt,tts}_usage_metrics`` return
            # silently and no ``MetricsFrame`` carrying usage is ever pushed,
            # so the jury wall has no quantities to price a call with.
            enable_usage_metrics=True,
        ),
        observers=[_CallLogObserver(session, filler_guard=filler_guard), hangup],
    )
    # The params above are what makes the counters real; say so on the session
    # so ``call.usage`` can tell a measured zero from an unmeasured lane.
    session.usage.metered = True
    hangup.bind(task)

    greeting = (
        handoff_greeting_for(language_state.language)
        if session.handoff
        else _persona_greeting(persona, language_state.language)
        or greeting_for(language_state.language)
    )

    @transport.event_handler("on_client_connected")
    async def _on_connected(transport: Any, client: Any) -> None:
        ctx.log.assistant_turn(greeting)
        await task.queue_frames([TTSSpeakFrame(greeting)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(transport: Any, client: Any) -> None:
        ctx.log.event("voice.client_disconnected")
        await task.cancel()

    # Per socket, like everything else here: the escalation must not carry
    # from one call into the next.
    idle_policy = IdlePolicy(turns)
    user_aggregator = aggregators.user()
    user_aggregator.add_event_handler(
        "on_user_turn_idle", _make_idle_speaker(session, language_state, task, idle_policy)
    )
    llm.add_event_handler(
        "on_function_calls_started",
        _make_tool_filler_speaker(
            session,
            language_state,
            task,
            guard=filler_guard,
            picker=filler_picker,
            tts=tts,
            output=transport.output(),
        ),
    )

    async def _on_user_turn_started(aggregator: Any, *args: Any) -> None:
        # Fires the moment the caller starts talking, before the transcript
        # exists, so the pause they just ended stops counting against them.
        idle_policy.on_user_speech()

    user_aggregator.add_event_handler("on_user_turn_started", _on_user_turn_started)

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
    return "pipeline_finished"


def _active_personality(settings: Any) -> Any | None:
    """The receptionist the wall's Personalities page put on the phone.

    One tiny sqlite read per socket. ``None`` when the store cannot be read at
    all: a clinic whose db is missing or corrupt still answers its phone, with
    the prompt and the greeting it had before the page existed.

    ``personality.voices`` is deliberately not wired: those are Google Chirp
    names and ElevenLabs is the primary, so the voice stays the provider's.
    """
    try:
        from vortex.line import personalities

        return personalities.active(settings)
    except Exception as exc:  # a broken db must never stop a call
        log.warning("no personality on this call: %s", exc)
        return None


def _persona_directive(person: Any | None) -> str:
    """The PERSONA line appended to the system prompt, or "" when there is none.

    The tone is free text a human typed on the wall, capped at
    ``personalities.TONE_MAX_CHARS`` so it stays a fragment inside the prompt's
    token budget rather than a second prompt.
    """
    if person is None:
        return ""
    name = str(getattr(person, "name", "") or "").strip()
    if not name:
        return ""
    role = str(getattr(person, "role", "") or "").strip()
    tone = str(getattr(person, "tone", "") or "").strip()
    head = f"PERSONA. Your name is {name}, {role}." if role else f"PERSONA. Your name is {name}."
    return f"{head} {tone}".strip()


def _persona_greeting(person: Any | None, language: str) -> str:
    """The persona's own opening line in this language, or "" to fall back.

    ``greetings`` may be partial (the wall seeds Spanish and English), so a
    call that opens in Catalan reads the clinic's own greeting instead.
    """
    if person is None:
        return ""
    try:
        code = normalise_language(language) or DEFAULT_LANGUAGE
        return str((getattr(person, "greetings", None) or {}).get(code, "")).strip()
    except Exception as exc:
        log.warning("personality greeting unusable: %s", exc)
        return ""


def _providers(settings: Any) -> dict[str, object]:
    return {
        "stt": f"soniox/{settings.soniox_stt_model}",
        "llm": settings.llm_model,
        "tts": settings.tts_provider,
        "tts_model": settings.elevenlabs_model,
        "aic_filter": "on" if settings.aic_filter_enabled and settings.aic_sdk_license else "off",
    }


def _user_aggregator_params(turns: TurnSettings) -> Any:
    """The user aggregator's params: VAD, idle timeout and the turn strategies.

    Strategies always come from the conversation lane. In VAD+Smart Turn mode
    that installs ``LocalSmartTurnAnalyzerV3`` and shortens VAD ``stop_secs``
    to 0.2 s. In Soniox mode it overrides the STT's
    ``ExternalUserTurnStrategies`` with a word-count start gate plus an
    external stop, so ``interrupt_min_words`` actually runs — and, because
    both branches pass an explicit ``start`` and ``stop``, the aggregator
    never falls back to ``UserTurnStrategies()`` and loads a smart-turn ONNX
    session per socket that Soniox mode would then throw away.

    Silero VAD stays in both modes: it feeds the aggregator's VAD controller,
    which is what starts and stops user speech and what the idle timer hangs
    off. It is not the smart-turn model.

    Imports pipecat lazily so the server starts without the keys.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams

    return LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(
            params=VADParams(
                confidence=turns.vad_confidence,
                start_secs=turns.vad_start_secs,
                stop_secs=effective_vad_stop_secs(turns),
                min_volume=turns.vad_min_volume,
            )
        ),
        user_idle_timeout=turns.user_idle_secs,
        user_turn_stop_timeout=turns.user_turn_stop_secs,
        user_turn_strategies=user_turn_strategies(turns),
    )


class _LanguageState:
    """The language this call is being spoken in, right now.

    One instance per call. The watcher writes it as the caller switches; the
    router reads it to decide which TTS branch the next text frame belongs to.
    Frames cross the pipeline in order, so a write from the watcher is always
    visible to the router by the time the matching text arrives.
    """

    __slots__ = ("language",)

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self.language = language


class _ToolFillerGuard:
    """At most one tool filler per interaction, not one per tool batch.

    A tool chain runs one LLM completion per hop and every completion that
    starts a batch fires ``on_function_calls_started``; without a guard the
    caller hears the phrase once per hop. The rule: speak the first batch
    after the caller said anything, then stay quiet for the cooldown unless
    the caller spoke again.
    """

    __slots__ = ("_clock", "_cooldown", "_last_spoken_at", "_caller_spoke")

    def __init__(
        self,
        cooldown_secs: float = FILLER_REPEAT_COOLDOWN_SECS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cooldown = cooldown_secs
        self._clock = clock
        self._last_spoken_at = float("-inf")
        self._caller_spoke = True  # the call's first batch may always speak

    def on_caller_turn(self) -> None:
        """The caller said something. The next tool batch may speak again."""
        self._caller_spoke = True

    def wants_to_speak(self) -> bool:
        """Consume one filler slot. ``True`` means the phrase should go out."""
        if not self._caller_spoke:
            return False
        self._caller_spoke = False
        self._last_spoken_at = self._clock()
        return True


def _make_tts_stage(
    settings: Any, state: _LanguageState, vcfg: voice_config.VoiceConfig | None = None
) -> Any:
    """The call's one TTS service. One provider, so there is nothing to route."""
    return _make_tts(settings, settings.tts_provider, state, vcfg)


def _llm_extra_body(settings: Any) -> dict[str, Any]:
    """Request fields that turn reasoning off, for every host we might hit.

    vLLM/SGLang read ``chat_template_kwargs.enable_thinking``; Helmcode reads
    ``reasoning_effort`` ("none" skips the phase on qwen3.6/gemma4). Hosts
    ignore the one they do not know.
    """
    # pipecat spreads this dict as keyword arguments of the SDK's
    # ``chat.completions.create``: ``reasoning_effort`` is one of its
    # parameters, ``chat_template_kwargs`` is not and has to travel in
    # ``extra_body`` to reach the request JSON.
    extra: dict[str, Any] = {}
    if settings.llm_disable_thinking:
        extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    if settings.llm_reasoning_effort:
        extra["reasoning_effort"] = settings.llm_reasoning_effort
    # Azure's /openai/v1 surface needs no api-version; a dated endpoint does,
    # and it only fits in the query string.
    if settings.llm_provider == "azure" and settings.azure_openai_api_version:
        extra["extra_query"] = {"api-version": settings.azure_openai_api_version}
    return extra


def _make_tts(
    settings: Any,
    provider: str | None = None,
    state: _LanguageState | None = None,
    vcfg: voice_config.VoiceConfig | None = None,
) -> Any:
    """Build the call's ElevenLabs TTS service, asked for 8 kHz PCM.

    The wire format never changes with the language: a switch is a new voice id
    pushed as a ``TTSUpdateSettingsFrame``, which the same service applies in
    place. See ``_LanguageWatcher``.
    """
    name = provider or settings.tts_provider
    start_language = state.language if state is not None else DEFAULT_LANGUAGE
    gender = vcfg.voice if vcfg else "female"
    voice, language = tts_voice_for(start_language, settings, name, gender)
    if not voice:
        # Builds fine, then fails on every utterance. Say so once, loudly.
        log.warning("TTS provider %s has no voice id configured", name)

    if settings.tts_http_base_url:
        # An HTTP REST stand-in for ElevenLabs (VORTEX_TTS_HTTP_BASE_URL) —
        # e.g. scripts/elevenlabs_google_shim.py backed by Google Chirp3 —
        # speaks the with-timestamps endpoint, so the pipeline swaps the
        # websocket client for pipecat's HTTP one. Distinct from
        # ELEVENLABS_BASE_URL, which stays a *websocket* AI-gateway origin.
        import aiohttp
        from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService

        class _LazySession:
            """ClientSession created on first use: _build_tts can run
            outside a running loop (tests), run_tts never does."""

            def __init__(self) -> None:
                self._real: aiohttp.ClientSession | None = None

            def post(self, *args: Any, **kwargs: Any) -> Any:
                if self._real is None or self._real.closed:
                    self._real = aiohttp.ClientSession()
                return self._real.post(*args, **kwargs)

            async def close(self) -> None:
                if self._real is not None and not self._real.closed:
                    await self._real.close()

        return ElevenLabsHttpTTSService(
            api_key=settings.elevenlabs_api_key or "shim",
            base_url=settings.tts_http_base_url,
            aiohttp_session=_LazySession(),
            sample_rate=LINE_SAMPLE_RATE,
            settings=ElevenLabsHttpTTSService.Settings(
                voice=voice or "shim",
                model=settings.elevenlabs_model,
                language=language,
            ),
        )

    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

    # The voice character is a hardcoded preset, not an env knob.
    preset = ElevenLabsVoicePreset.RECEPTIONIST.value
    return ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key,
        # A WebSocket origin, so an AI Gateway in front of ElevenLabs goes
        # here. Empty keeps the service's own default.
        **({"url": settings.elevenlabs_base_url} if settings.elevenlabs_base_url else {}),
        sample_rate=LINE_SAMPLE_RATE,
        settings=ElevenLabsTTSService.Settings(
            voice=voice,
            model=settings.elevenlabs_model,
            language=language,
            stability=preset.stability,
            similarity_boost=preset.similarity_boost,
            style=preset.style,
            use_speaker_boost=preset.use_speaker_boost,
            **({"speed": voice_config.elevenlabs_speed(vcfg)} if vcfg else {}),
        ),
    )


def _AmbienceSwitcher(  # noqa: N802 - factory that returns a processor
    session: CallSession,
):
    """Switch the output mixer to typing during tool lookups.

    Typing starts on ``FunctionCallInProgressFrame``. It stays up through the
    filler and the post-tool silence, then returns to office on the first
    ``LLMFullResponseStartFrame`` after a ``FunctionCallResultFrame`` (the
    spoken answer). If the result frame is all we get, that is the off switch
    too. A call that never tools never switches.
    """
    from pipecat.frames.frames import (
        Frame,
        FunctionCallInProgressFrame,
        FunctionCallResultFrame,
        FunctionCallsStartedFrame,
        LLMFullResponseStartFrame,
        MixerUpdateSettingsFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    class AmbienceSwitcher(FrameProcessor):
        def __init__(self) -> None:
            super().__init__()
            self._sound = OFFICE_SOUND
            self._lookup = False
            self._saw_result = False

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM:
                if isinstance(frame, (FunctionCallsStartedFrame, FunctionCallInProgressFrame)):
                    self._lookup = True
                    await self._switch(TYPING_SOUND)
                elif isinstance(frame, FunctionCallResultFrame) and self._lookup:
                    self._saw_result = True
                elif (
                    self._lookup
                    and self._saw_result
                    and isinstance(frame, LLMFullResponseStartFrame)
                ):
                    await self._switch(OFFICE_SOUND)
                    self._lookup = False
                    self._saw_result = False
            await self.push_frame(frame, direction)

        async def _switch(self, sound: str) -> None:
            if self._sound == sound:
                return
            self._sound = sound
            session.ctx.log.event("voice.ambience", sound=sound)
            await self.push_frame(
                MixerUpdateSettingsFrame(settings={"sound": sound}),
                FrameDirection.DOWNSTREAM,
            )

    return AmbienceSwitcher()


def _PrivacyGuard(  # noqa: N802 - factory that returns a processor
    session: CallSession, state: _LanguageState | None = None
):
    """Block national_id and phone values before they reach TTS.

    Every ``TextFrame`` and ``TTSSpeakFrame`` is normalised and compared to the
    national ids and phones this call has already seen (directory records on
    the session, plus ``from_number``). A match replaces the phrase with a
    safe refusal and logs ``voice.privacy_block``. The call stays open.

    The LLM streams its answer in chunks, and a phone split over "612 ",
    "345 " and "678" matches nothing chunk by chunk while the TTS glues the
    chunks back into one spoken sentence. So the chunks of one response are
    held here and scanned as a single text when ``LLMFullResponseEndFrame``
    closes it; an interruption drops what is still held. The prompt asks for
    one or two short sentences, so what is held is one turn of speech.
    """
    from pipecat.frames.frames import (
        Frame,
        InterruptionFrame,
        LLMFullResponseEndFrame,
        LLMTextFrame,
        TextFrame,
        TTSSpeakFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    from vortex.conversation.prompt import refusal_line_for, strip_tool_wait_talk
    from vortex.line.privacy import PRIVACY_BLOCK_LINE, scrub_session_text

    language_state = state if state is not None else _LanguageState()

    class PrivacyGuard(FrameProcessor):
        def __init__(self) -> None:
            super().__init__()
            self._held: list[LLMTextFrame] = []

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM:
                if isinstance(frame, LLMTextFrame):
                    self._held.append(frame)
                    return
                if isinstance(frame, InterruptionFrame):
                    self._held.clear()
                elif isinstance(frame, LLMFullResponseEndFrame):
                    await self._release(direction)
                elif isinstance(frame, (TextFrame, TTSSpeakFrame)):
                    await self._scrub(frame)
            await self.push_frame(frame, direction)

        async def _release(self, direction: FrameDirection) -> None:
            held, self._held = self._held, []
            if not held:
                return
            response = held[0]
            joined = "".join(chunk.text or "" for chunk in held)
            cleaned = strip_tool_wait_talk(joined)
            if not cleaned.strip():
                return
            response.text = cleaned
            await self._scrub(response)
            await self.push_frame(response, direction)

        async def _scrub(self, frame: TextFrame | TTSSpeakFrame) -> None:
            text = frame.text or ""
            if not text.strip():
                return
            _, leaks = scrub_session_text(session.ctx, text)
            if not leaks:
                return
            frame.text = refusal_line_for(language_state.language) or PRIVACY_BLOCK_LINE
            session.ctx.log.event(
                "voice.privacy_block",
                kinds=sorted({leak.split(" ", 1)[0] for leak in leaks}),
                leaks=len(leaks),
            )

    return PrivacyGuard()


def _LanguageWatcher(  # noqa: N802 - factory that returns a processor
    session: CallSession,
    state: _LanguageState | None = None,
    vcfg: voice_config.VoiceConfig | None = None,
):
    """Switch the voice when the caller switches language.

    Soniox tags each transcription frame with the language it heard. When that
    flips we write the new language into the shared ``_LanguageState`` and push
    a ``TTSUpdateSettingsFrame`` downstream; the TTS service applies the delta
    in place, so the voice changes without rebuilding the pipeline. There is no
    public ``update_settings()`` coroutine on ``TTSService`` in pipecat 1.11 —
    the control frame is the supported way in.

    One provider speaks all five languages, so the update is a voice id and a
    ``Language`` on the service that is already running: nothing is rebuilt and
    nothing is routed. ``TTSService._update_settings`` converts the pipecat
    ``Language`` into the provider's own code before storing it.
    """
    from pipecat.frames.frames import Frame, TranscriptionFrame, TTSUpdateSettingsFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.services.settings import TTSSettings

    language_state = state if state is not None else _LanguageState()

    class LanguageWatcher(FrameProcessor):
        def __init__(self) -> None:
            super().__init__()
            self._state = language_state

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                await self._maybe_switch(frame)
            await self.push_frame(frame, direction)

        async def _maybe_switch(self, frame: TranscriptionFrame) -> None:
            try:
                settings = session.settings
                # ``current`` is the detector's memory of the call's language:
                # without it a short turn with no markers re-detects English.
                language = detect_language(
                    frame.text, hint=frame.language, current=self._state.language
                )
                if language == self._state.language:
                    return
                provider = settings.tts_provider
                gender = vcfg.voice if vcfg else "female"
                voice, tts_language = tts_voice_for(language, settings, provider, gender)
                previous, self._state.language = self._state.language, language
                # The session carries it too: the day-before confirmation call
                # is dialled in the language this caller actually spoke.
                session.language = language
                session.ctx.log.event(
                    "voice.language_switch",
                    was=previous,
                    now=language,
                    voice=voice,
                    provider=provider,
                )
                await self.push_frame(
                    TTSUpdateSettingsFrame(delta=TTSSettings(voice=voice, language=tts_language)),
                    FrameDirection.DOWNSTREAM,
                )
            except Exception as exc:  # a failed switch must never end the call
                log.warning("language switch failed: %s", exc)

    return LanguageWatcher()


def _make_idle_speaker(
    session: CallSession,
    state: _LanguageState,
    task: Any,
    policy: IdlePolicy | None = None,
) -> Any:
    """The handler the user aggregator fires when the caller goes quiet.

    The line comes from ``conversation.turns.IdlePolicy``: the short nudge
    first. The platform cuts a call that goes quiet, so the first silence has
    to answer — but answering every silence is what put 147 nudges into the
    20 calls of 2026-09-18, each one restarting a sentence the caller was
    already saying. So the second silence does not nudge again: it speaks
    ``prompt.idle_submit_line_for`` and submits the best known action (a
    prepared booking counts as confirmed by the second silence; anything else
    sends the same refusal ``close()`` would). Further idles are silent.

    The language is read at fire time, so a mid-call switch moves the line, and
    the TTS router reads the same state, so it comes out on the right voice.
    ``voice.user_idle`` carries the count and the level, so the post-mortem can
    tell a first nudge from a second and a chosen silence from a missing one.
    """
    from pipecat.frames.frames import TTSSpeakFrame

    idle = policy if policy is not None else IdlePolicy()

    async def _on_user_idle(aggregator: Any, *args: Any) -> None:
        decision = idle.on_idle(state.language)
        session.ctx.log.event(
            "voice.user_idle",
            count=decision.count,
            level=decision.level,
            spoke=decision.speaks,
            suppressed=decision.suppressed,
        )
        if decision.level == 2:
            # Second silence: no more nudging. Say we are noting what the call
            # has and send it - a quiet call still counts on the platform.
            await task.queue_frames([TTSSpeakFrame(idle_submit_line_for(state.language))])
            await _submit_best_known_on_idle(session)
            return
        if decision.text is not None:
            await task.queue_frames([TTSSpeakFrame(decision.text)])

    return _on_user_idle


async def _submit_best_known_on_idle(session: CallSession) -> None:
    """Second idle: send prepared work, or the fallback refusal, once."""
    if session.has_accepted_submission:
        return
    memory = session.memory
    if memory.prepared is not None:
        memory.mark_confirmed()
        branch, action, why = (
            "prepared_on_idle",
            memory.prepared,
            f"{memory.prepared_tool} prepared; second idle confirms",
        )
    else:
        branch, action, why = session.fallback_action()
    repeat = action in session.sent_actions
    session.ctx.log.event(
        "submit.idle",
        branch=branch,
        why=why,
        route=action_route(action),
        skipped=repeat,
    )
    if repeat:
        return
    await session.submit(action)


def _make_tool_filler_speaker(
    session: CallSession,
    state: _LanguageState,
    task: Any,
    guard: _ToolFillerGuard | None = None,
    picker: FillerPicker | None = None,
    tts: Any | None = None,
    output: Any | None = None,
) -> Any:
    """Speak one short filler when the LLM starts executing tool calls.

    Wired to ``LLMService.on_function_calls_started``. One phrase per
    interaction, read at fire time so a mid-call language switch moves it.
    ``TTSSpeakFrame`` is bot speech: ``MinWordsUserTurnStartStrategy`` guards it
    and the idle timer does not run during it. The guard keeps a tool chain
    that runs batch after batch from re-speaking the phrase every second.

    The speak frame is queued on the TTS processor, not the pipeline head:
    ``task.queue_frames`` waits behind the LLM while tools run, which is the
    exact silence this line is meant to cover.
    """
    from pipecat.frames.frames import MixerUpdateSettingsFrame, TTSSpeakFrame
    from pipecat.processors.frame_processor import FrameDirection

    filler_guard = guard if guard is not None else _ToolFillerGuard()
    filler_picker = picker if picker is not None else FillerPicker()

    async def _start_typing() -> None:
        if output is None:
            return
        await output.queue_frame(
            MixerUpdateSettingsFrame(settings={"sound": TYPING_SOUND}),
            FrameDirection.DOWNSTREAM,
        )
        session.ctx.log.event("voice.ambience", sound=TYPING_SOUND)

    async def _speak(phrase: str) -> None:
        frame = TTSSpeakFrame(phrase, append_to_context=False)
        if tts is not None:
            await tts.queue_frame(frame, FrameDirection.DOWNSTREAM)
            return
        await task.queue_frames([frame])

    async def _on_function_calls_started(service: Any, function_calls: Any = None) -> None:
        await _start_typing()
        if not filler_guard.wants_to_speak():
            session.ctx.log.event(
                "voice.tool_filler",
                language=state.language,
                tools=len(function_calls or ()),
                suppressed="same_turn",
            )
            return
        phrase = filler_picker.pick(state.language)
        session.ctx.log.event(
            "voice.tool_filler",
            language=state.language,
            tools=len(function_calls or ()),
            text=phrase,
        )
        await _speak(phrase)

    return _on_function_calls_started


def _CallLogObserver(  # noqa: N802 - factory that returns an observer
    session: CallSession,
    confirmations: ConfirmationPolicy | None = None,
    filler_guard: _ToolFillerGuard | None = None,
    clock: Callable[[], float] = time.monotonic,
):
    """Log user and assistant text, count media frames, meter the providers.

    The frame stream is where both sides of the call already pass in order, so
    the confirmation guard reads it here: TTS text is the agent's turn, a
    transcription is the caller's reply to it. When that reply is an agreement
    to a read-back, ``CallSession.confirm_prepared`` submits what is prepared
    instead of letting the model ask a second time.

    It is also where the providers' own usage lands. With
    ``enable_usage_metrics`` on, Soniox, the LLM service and each TTS service
    push a ``MetricsFrame`` with what they just billed; the observer sums them
    into ``session.usage`` for the ``call.usage`` line. A frame is pushed at
    every link it crosses, so each one is counted once, keyed by frame id -
    pipecat's own ``MetricsLogObserver`` de-duplicates the same way.

    The observer also measures how long the caller waited for an answer. The
    VAD's end-of-speech frame is the moment the caller finished; the turn-end
    frame closes detection; the first outbound audio frame is the reply
    starting. Each answered turn logs ``voice.reply_latency`` with both legs,
    so the post-mortem can see whether waiting went into endpointing or into
    the pipeline behind it.
    """
    from pipecat.frames.frames import (
        InputAudioRawFrame,
        MetricsFrame,
        OutputAudioRawFrame,
        TranscriptionFrame,
        TTSTextFrame,
        UserStoppedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
    from pipecat.metrics.metrics import (
        LLMUsageMetricsData,
        STTUsageMetricsData,
        TTSUsageMetricsData,
    )
    from pipecat.observers.base_observer import BaseObserver, FramePushed

    policy = confirmations if confirmations is not None else ConfirmationPolicy()
    # Frame ids already counted. Per observer, so per socket.
    metered_frames: set[int] = set()

    def record_usage(frame: Any) -> None:
        if frame.id in metered_frames:
            return
        counted = False
        for item in frame.data or ():
            if isinstance(item, LLMUsageMetricsData):
                session.usage.add_llm(item.value)
            elif isinstance(item, STTUsageMetricsData):
                session.usage.add_stt(item.value.audio_seconds)
            elif isinstance(item, TTSUsageMetricsData):
                session.usage.add_tts(item.processor, item.model, item.value)
            else:
                # TTFB, processing time, turn predictions: timings, not money.
                continue
            counted = True
        if counted:
            metered_frames.add(frame.id)

    guard = filler_guard

    class Observer(BaseObserver):
        def __init__(self) -> None:
            super().__init__()
            self._speech_end: float | None = None
            self._turn_end: float | None = None

        async def on_push_frame(self, data: FramePushed) -> None:
            frame = data.frame
            if isinstance(frame, MetricsFrame):
                record_usage(frame)
            elif isinstance(frame, TranscriptionFrame):
                session.ctx.log.user_turn(frame.text)
                if guard is not None:
                    guard.on_caller_turn()
                decision = policy.on_user_text(
                    frame.text, prepared=session.memory.prepared is not None
                )
                if decision.confirmed:
                    session.confirm_prepared(decision.why)
                elif (
                    session.memory.prepared is None
                    and session.memory.last_rejection is not None
                    and is_refusal_acceptance(frame.text)
                ):
                    session.accept_refusal(f"caller accepted the refusal: {frame.text.strip()}")
            elif isinstance(frame, TTSTextFrame):
                session.ctx.log.assistant_turn(frame.text)
                policy.on_assistant_text(frame.text)
            elif isinstance(frame, InputAudioRawFrame):
                session.media_frames_in += 1
            elif isinstance(frame, OutputAudioRawFrame):
                session.media_frames_out += 1
                self._on_reply_audio()
            elif isinstance(frame, VADUserStoppedSpeakingFrame):
                self._speech_end = clock()
            elif isinstance(frame, UserStoppedSpeakingFrame):
                if self._speech_end is not None:
                    self._turn_end = clock()

        def _on_reply_audio(self) -> None:
            """First agent audio after a turn closed: report what the wait was."""
            if self._turn_end is None:
                return
            now, speech_end, turn_end = clock(), self._speech_end, self._turn_end
            self._turn_end = None
            if speech_end is None:
                return
            session.ctx.log.event(
                "voice.reply_latency",
                detection_secs=round(turn_end - speech_end, 3),
                total_secs=round(now - speech_end, 3),
            )

    return Observer()


def _make_hangup_watcher(session: CallSession) -> Any:
    """End the call from our side once the platform holds an action.

    Every call used to run until the harness cut it at three minutes, booked
    calls included: the socket stayed open with nothing left to do on it. So
    the session arms this the moment ``submit_action`` comes back accepted (or
    duplicate, which means the platform already holds that action), and the
    watcher picks one of two moments to end the pipeline:

    - **the farewell is out**. The output transport pushes
      ``BotStoppedSpeakingFrame`` when the last audio of an utterance has gone
      down the wire, so ending there never cuts the agent off mid-word. We wait
      for an utterance that *started* after the submission was accepted: the
      sentence the model spoke before its tool call can still be playing when
      the platform answers, and that one is not the goodbye.
    - **the caller went quiet**, one idle period after the submission. A model
      that submits and then says nothing would otherwise hold the line open to
      the cap.

    The end is a graceful one: ``stop_when_done`` queues an ``EndFrame``, which
    travels the pipeline behind everything already in flight and drains it.
    ``cancel`` would cut the audio still on its way out, which is the goodbye.

    A rejected submission, a late one and a dry run arm nothing - see
    ``CallSession.arm_hangup``. Neither does the end-of-call fallback, which
    only runs once the socket is already gone.
    """
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
    from pipecat.observers.base_observer import BaseObserver, FramePushed

    class HangupWatcher(BaseObserver):
        def __init__(self) -> None:
            super().__init__()
            self._task: Any = None
            self._spoke_since_armed = False
            self._requested = False

        def bind(self, task: Any) -> None:
            """Hand over the task. It does not exist yet when this is built."""
            self._task = task

        async def on_push_frame(self, data: FramePushed) -> None:
            if self._requested or not session.hangup_armed:
                return
            # The transport pushes each of these twice, up and down. Both are
            # the same moment, and ``_requested`` keeps the second one quiet.
            if isinstance(data.frame, BotStartedSpeakingFrame):
                self._spoke_since_armed = True
            elif isinstance(data.frame, BotStoppedSpeakingFrame) and self._spoke_since_armed:
                await self._end("farewell_spoken")

        async def on_user_idle(self, aggregator: Any, *args: Any) -> None:
            if session.hangup_armed:
                await self._end("idle_after_submit")

        async def _end(self, reason: str) -> None:
            if self._requested or self._task is None:
                return
            self._requested = True
            session.ctx.log.event(
                "call.hangup_requested", reason=reason, armed_by=session.hangup_reason
            )
            await self._task.stop_when_done()

    return HangupWatcher()
