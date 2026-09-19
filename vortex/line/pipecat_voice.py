"""The real voice pipeline: pipecat over the Twilio-shaped socket.

    transport.input -> STT (Soniox stt-rt-v5) -> language watcher
                    -> user aggregator -> LLM (OpenAI-compatible, EU)
                    -> TTS (Google Chirp / Gemini-TTS, or ElevenLabs)
                    -> transport.output -> assistant aggregator

Soniox transcribes, an OpenAI-compatible endpoint named by ``LLM_PROVIDER``
answers, and the voice is Google Cloud Text-to-Speech — the only provider here
with Catalan, Galician *and* Basque.

Two TTS services can run at once. ``VORTEX_TTS_PROVIDER`` speaks Spanish and
``VORTEX_TTS_PROVIDER_ALT`` speaks what the primary cannot, so
``VORTEX_TTS_PROVIDER=elevenlabs`` with the default ``_ALT=google`` gives
ElevenLabs Spanish and Google ca/gl/eu. When the two are the same (the
default, google/google) English and Spanish stay on Chirp 3 HD
(``GoogleHttpTTSService``) and ca/gl/eu speak through ``GeminiTTSService``
(``gemini-2.5-flash-tts``). ``GOOGLE_TTS_STANDARD_FALLBACK`` restores the old
single ``GoogleHttpTTSService`` with Standard-* voices.

One pipeline per socket. The serializer takes the ``stream_sid`` of this call,
the context takes this call's prompt, and every tool handler closes over this
call's ``ToolContext``. Nothing here is module-level state.

Owner: the line lane for the wiring; the conversation lane for prompt, turn
settings, STT vocabulary and language (it edits ``vortex/conversation/*``).

Imports of pipecat live inside the function so the server starts, and the
smoke test runs, with the stub pipeline when the keys are missing.

TODO(line):
- Run one real call end to end once the four keys exist.
- Confirm the 8 kHz µ-law path: serializer ``twilio_sample_rate=8000`` in, and
  the TTS asked for 8 kHz PCM out (Google LINEAR16 @ 8000, ElevenLabs
  ``pcm_8000``; Gemini-TTS stays at 24 kHz and the transport resamples).
  Check for choppy audio.
- Hang up from our side when the agent says goodbye (send EndFrame, let the
  platform close the socket). auto_hang_up stays False: no Twilio account.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from vortex import tools as registry
<<<<<<< HEAD
from vortex.conversation.language import (
    DEFAULT_LANGUAGE,
    detect_language,
    normalise_language,
    tts_voice_for,
)
from vortex.conversation.prompt import GREETING, idle_prompt_for, initial_messages
=======
from vortex.conversation.language import DEFAULT_LANGUAGE, detect_language, tts_voice_for
from vortex.conversation.prompt import (
    GREETING,
    idle_prompt_for,
    initial_messages,
    wait_prompt_for,
)
>>>>>>> origin/main
from vortex.conversation.stt_context import stt_context_text, stt_terms
from vortex.conversation.turns import (
    TurnSettings,
    default_turn_settings,
    effective_vad_stop_secs,
    user_turn_strategies,
)
from vortex.line.aic_filter import build_audio_in_filter
from vortex.line.llm_timeout import first_token_guard
from vortex.line.session import CallSession
from vortex.observability.tracing import traced_openai_llm_service
from vortex.settings import GEMINI_TTS_LANGUAGES

log = logging.getLogger(__name__)

# Both the line in and the voice out are 8 kHz: the platform speaks µ-law at
# 8 kHz and the serializer does the companding.
LINE_SAMPLE_RATE = 8000

# Spoken the instant a tool call starts, so the caller hears something while
# the LLM waits on the clinic API (~1.3 s p50). Keep each line under ~1 s of
# audio. Pipecat treats TTSSpeakFrame as bot speech, so the word gate and the
# idle timer stay quiet for the duration. See docs/research/03-turn-detection.md.
TOOL_FILLERS: dict[str, str] = {
    "en": "One moment.",
    "es": "Un momento.",
    "ca": "Un moment.",
    "gl": "Un momento.",
    "eu": "Momentu bat.",
}


def tool_filler_for(language: str | None = None) -> str:
    """Short filler for the call's current language. Falls back to English."""
    code = normalise_language(language) or DEFAULT_LANGUAGE
    return TOOL_FILLERS.get(code, TOOL_FILLERS[DEFAULT_LANGUAGE])


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


async def run_pipecat_call(
    ws: WebSocket, session: CallSession, turn_settings: TurnSettings | None = None
) -> str:
    from pipecat.adapters.schemas.function_schema import FunctionSchema
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
    from pipecat.services.soniox.stt import SonioxContextObject, SonioxSTTService
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
    transport = FastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
            audio_in_filter=audio_in_filter,
        ),
    )

    # ---- STT: Soniox. Language identification tags every transcription frame,
    # which is what the language watcher below switches the voice on. ----------
    stt = SonioxSTTService(
        api_key=settings.soniox_api_key,
        settings=SonioxSTTService.Settings(
            model=settings.soniox_stt_model,
            language_hints=_language_hints(turns.stt_language_hints),
            enable_language_identification=True,
            context=SonioxContextObject(text=stt_context_text(), terms=stt_terms(ctx)),
            max_endpoint_delay_ms=turns.stt_max_endpoint_delay_ms,
            endpoint_sensitivity=turns.stt_endpoint_sensitivity,
            endpoint_latency_adjustment_level=turns.stt_endpoint_latency_adjustment_level,
        ),
        # False hands the end of the turn to Soniox's own endpoint detection.
        vad_force_turn_endpoint=not turns.soniox_turn_detection,
        should_interrupt=turns.enable_interruptions,
    )

    # The language this call is in, shared by the watcher that updates it and
    # the router that reads it. Per call: a closure, never a module global.
    language_state = _LanguageState()

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
        # Read at fire time, so a mid-call language switch moves the line and
        # the TTS router sends it down the branch that can say it.
        timeout_fallback_text=lambda: wait_prompt_for(language_state.language),
        timeout_log_event=ctx.log.event,
    )

    tts = _make_tts_stage(settings, language_state)

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

    schemas: list[Any] = []
    for fn in registry.function_schemas(turns.exposed_tools):
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
        llm.register_function(fn["name"], make_handler(fn["name"]))

    context = LLMContext(initial_messages(ctx.now), tools=ToolsSchema(standard_tools=schemas))
    aggregators = LLMContextAggregatorPair(context, user_params=_user_aggregator_params(turns))

    stages: list[Any] = [transport.input(), stt]
    if settings.tts_supports_language_switch:
        # Only worth a processor when the pair can say more than one language.
        # ElevenLabs alone is Spanish-only, so the watcher would be a no-op.
        stages.append(_LanguageWatcher(session, language_state))
    stages += [
        aggregators.user(),
        llm,
        _PrivacyGuard(session, language_state),
        tts,
        transport.output(),
        aggregators.assistant(),
    ]

    task = PipelineTask(
        Pipeline(stages),
        params=PipelineParams(
            audio_in_sample_rate=LINE_SAMPLE_RATE,
            audio_out_sample_rate=LINE_SAMPLE_RATE,
            enable_metrics=True,
        ),
        observers=[_CallLogObserver(session)],
    )

    @transport.event_handler("on_client_connected")
    async def _on_connected(transport: Any, client: Any) -> None:
        ctx.log.assistant_turn(GREETING)
        await task.queue_frames([TTSSpeakFrame(GREETING)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(transport: Any, client: Any) -> None:
        ctx.log.event("voice.client_disconnected")
        await task.cancel()

    aggregators.user().add_event_handler(
        "on_user_turn_idle", _make_idle_speaker(session, language_state, task)
    )
    llm.add_event_handler(
        "on_function_calls_started",
        _make_tool_filler_speaker(session, language_state, task),
    )

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
    return "pipeline_finished"


def _providers(settings: Any) -> dict[str, object]:
    return {
        "stt": f"soniox/{settings.soniox_stt_model}",
        "llm": settings.llm_model,
        "tts": settings.tts_provider,
        "tts_alt": settings.tts_provider_alt,
        "aic_filter": "on" if settings.aic_filter_enabled and settings.aic_sdk_license else "off",
    }


def _user_aggregator_params(turns: TurnSettings) -> Any:
    """The user aggregator's params: VAD, idle timeout and the turn strategies.

    Strategies always come from the conversation lane. In VAD+Smart Turn mode
    that installs ``LocalSmartTurnAnalyzerV3`` and shortens VAD ``stop_secs``
    to 0.2 s. In Soniox mode it overrides the STT's
    ``ExternalUserTurnStrategies`` with a word-count start gate plus an
    external stop, so ``interrupt_min_words`` actually runs.

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


def _make_tts_stage(settings: Any, state: _LanguageState) -> Any:
    """One TTS service, or a router over two when primary and alternate differ."""
    primary = _make_tts(settings, settings.tts_provider, state)
    if not settings.tts_is_routed:
        return primary
    return _TTSRouter(
        settings, state, primary, _make_tts(settings, settings.tts_provider_alt, state)
    )


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
    return extra


def _make_tts(
    settings: Any, provider: str | None = None, state: _LanguageState | None = None
) -> Any:
    """Build one TTS service (or a Chirp|Gemini pair for Google).

    Google Chirp / ElevenLabs are asked for 8 kHz PCM. Gemini-TTS only emits
    24 kHz; the Twilio serializer resamples on the way out. The wire format
    never changes with the provider.
    """
    name = provider or settings.tts_provider
    voice, language = tts_voice_for(DEFAULT_LANGUAGE, settings, name)
    if not voice:
        # Builds fine, then fails on every utterance. Say so once, loudly.
        log.warning("TTS provider %s has no Spanish voice configured", name)

    if name == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

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
            ),
        )

    return _make_google_tts(settings, voice, language, state)


def _make_google_tts(
    settings: Any,
    voice: str,
    language: Any,
    state: _LanguageState | None,
) -> Any:
    """Chirp HTTP for en/es; Gemini-TTS for ca/gl/eu unless Standard fallback."""
    from pipecat.services.google.tts import GoogleHttpTTSService

    chirp = GoogleHttpTTSService(
        # Inline JSON wins when both are set, matching pipecat's own order.
        credentials=settings.google_tts_credentials_json or None,
        credentials_path=settings.google_application_credentials or None,
        sample_rate=LINE_SAMPLE_RATE,
        settings=GoogleHttpTTSService.Settings(voice=voice, language=language),
    )
    if not settings.google_tts_uses_gemini:
        # Research 06 fallback: one HTTP service, Standard-* for ca/gl/eu.
        return chirp

    from pipecat.services.google.tts import GeminiTTSService

    gemini_voice, gemini_language = tts_voice_for("ca", settings, "google")
    gemini = GeminiTTSService(
        credentials=settings.google_tts_credentials_json or None,
        credentials_path=settings.google_application_credentials or None,
        # Gemini-TTS is fixed at 24 kHz; the transport resamples to 8 kHz.
        settings=GeminiTTSService.Settings(
            model=settings.google_tts_gemini_model,
            voice=gemini_voice,
            language=gemini_language,
        ),
    )
    language_state = state if state is not None else _LanguageState()
    return _language_gate_router(language_state, GEMINI_TTS_LANGUAGES, gemini, chirp)


def _language_gate_router(
    state: _LanguageState,
    primary_languages: frozenset[str],
    primary: Any,
    alternate: Any,
) -> Any:
    """ParallelPipeline that feeds ``primary`` only when ``state.language`` matches."""
    from pipecat.pipeline.parallel_pipeline import ParallelPipeline
    from pipecat.processors.filters.function_filter import FunctionFilter
    from pipecat.processors.frame_processor import FrameDirection

    async def to_primary(_frame: Any) -> bool:
        return state.language in primary_languages

    async def to_alternate(_frame: Any) -> bool:
        return state.language not in primary_languages

    def gate(fn: Any) -> Any:
        return FunctionFilter(
            filter=fn, direction=FrameDirection.DOWNSTREAM, enable_direct_mode=True
        )

    return ParallelPipeline([gate(to_primary), primary], [gate(to_alternate), alternate])


def _TTSRouter(  # noqa: N802 - factory that returns a processor
    settings: Any, state: _LanguageState, primary: Any, alternate: Any
) -> Any:
    """Route each spoken language to the service that can say it.

    A ``ParallelPipeline`` with two branches, each fronted by a
    ``FunctionFilter`` keyed on ``state.language``: the primary branch takes
    every language in its capability set, the alternate branch takes the rest.
    Only one branch is ever fed text, so only one branch produces audio.

    Why the filters are shaped this way:

    - ``FunctionFilter`` lets ``StartFrame``/``EndFrame``/``CancelFrame``
      through unconditionally, so both services start, stop and cancel with the
      pipeline even while idle.
    - System frames are left unfiltered (``filter_system_frames`` off), so an
      interruption reaches both services and neither is left mid-utterance.
      ``ParallelPipeline`` de-duplicates by frame id on the way out, so a frame
      that crossed both branches still leaves once.
    - Everything that makes a TTS speak — ``TextFrame``, ``TTSSpeakFrame``, the
      ``LLMFullResponse*`` brackets — is a data or control frame, so it is
      gated, and the idle branch stays silent.
    - ``TTSUpdateSettingsFrame`` is gated too, which is what makes the watcher
      work unchanged: it writes the language first, so its voice update lands
      on whichever branch is about to speak.

    This is the same construction pipecat's own ``ServiceSwitcher`` uses
    (``ParallelPipeline`` of filter + service). We key the filters on the
    detected language directly instead of driving a switcher with
    ``ManuallySwitchServiceFrame``: routing is a pure function of the language,
    so a second source of truth about which service is "active" would only be
    something else to keep in sync.
    """
    return _language_gate_router(
        state, settings.tts_languages(settings.tts_provider), primary, alternate
    )


def _PrivacyGuard(  # noqa: N802 - factory that returns a processor
    session: CallSession, state: _LanguageState | None = None
):
    """Block national_id and phone values before they reach TTS.

    Every ``TextFrame`` and ``TTSSpeakFrame`` is normalised and compared to the
    national ids and phones this call has already seen (directory records on
    the session, plus ``from_number``). A match replaces the phrase with a
    safe refusal and logs ``voice.privacy_block``. The call stays open.
    """
    from pipecat.frames.frames import Frame, TextFrame, TTSSpeakFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    from vortex.conversation.prompt import refusal_line_for
    from vortex.line.privacy import PRIVACY_BLOCK_LINE, scrub_session_text

    language_state = state if state is not None else _LanguageState()

    class PrivacyGuard(FrameProcessor):
        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM and isinstance(
                frame, (TextFrame, TTSSpeakFrame)
            ):
                await self._scrub(frame)
            await self.push_frame(frame, direction)

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
    session: CallSession, state: _LanguageState | None = None
):
    """Switch the voice when the caller switches language.

    Soniox tags each transcription frame with the language it heard. When that
    flips we write the new language into the shared ``_LanguageState`` and push
    a ``TTSUpdateSettingsFrame`` downstream; the TTS service applies the delta
    in place, so the voice changes without rebuilding the pipeline. There is no
    public ``update_settings()`` coroutine on ``TTSService`` in pipecat 1.11 —
    the control frame is the supported way in.

    The voice comes from the provider that serves the new language, which is
    the primary unless the alternate is the one that covers it. The state is
    written *before* the frame is pushed, so when a router is in the pipeline
    the update travels down the branch that is about to speak.

    ``TTSService._update_settings`` converts the pipecat ``Language`` we send
    into the provider's own code before storing it, which is what
    ``GoogleHttpTTSService.run_tts`` passes as ``language_code`` next to the
    new voice name. Google's verified map only lists the Chirp 3 HD locales,
    so ca/gl/eu log a "not verified" warning and fall through to the full code
    ("ca-ES", "gl-ES", "eu-ES") — the right value either way.
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
                provider = settings.tts_provider_for(language)
                voice, tts_language = tts_voice_for(language, settings, provider)
                previous, self._state.language = self._state.language, language
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


def _make_idle_speaker(session: CallSession, state: _LanguageState, task: Any) -> Any:
    """The handler the user aggregator fires when the caller goes quiet.

    Speaks ``prompt.idle_prompt_for`` in the language the call is in now — the
    platform cuts a call that goes quiet, so silence has to answer — and keeps
    the ``voice.user_idle`` event on the call log. The prompt is read at fire
    time, so a mid-call language switch moves it, and the TTS router reads the
    same state, so it comes out on the right voice.
    """
    from pipecat.frames.frames import TTSSpeakFrame

    async def _on_user_idle(aggregator: Any, *args: Any) -> None:
        session.ctx.log.event("voice.user_idle")
        await task.queue_frames([TTSSpeakFrame(idle_prompt_for(state.language))])

    return _on_user_idle


def _make_tool_filler_speaker(session: CallSession, state: _LanguageState, task: Any) -> Any:
    """Speak one short filler when the LLM starts executing tool calls.

    Wired to ``LLMService.on_function_calls_started``. One phrase per batch,
    read at fire time so a mid-call language switch moves it. ``TTSSpeakFrame``
    is bot speech: ``MinWordsUserTurnStartStrategy`` guards it and the idle
    timer does not run during it.
    """
    from pipecat.frames.frames import TTSSpeakFrame

    async def _on_function_calls_started(service: Any, function_calls: Any = None) -> None:
        phrase = tool_filler_for(state.language)
        session.ctx.log.event(
            "voice.tool_filler",
            language=state.language,
            tools=len(function_calls or ()),
            text=phrase,
        )
        await task.queue_frames([TTSSpeakFrame(phrase)])

    return _on_function_calls_started


def _CallLogObserver(session: CallSession):  # noqa: N802 - factory that returns an observer
    """Log user and assistant text, and count media frames, from the frame stream."""
    from pipecat.frames.frames import (
        InputAudioRawFrame,
        OutputAudioRawFrame,
        TranscriptionFrame,
        TTSTextFrame,
    )
    from pipecat.observers.base_observer import BaseObserver, FramePushed

    class Observer(BaseObserver):
        async def on_push_frame(self, data: FramePushed) -> None:
            frame = data.frame
            if isinstance(frame, TranscriptionFrame):
                session.ctx.log.user_turn(frame.text)
            elif isinstance(frame, TTSTextFrame):
                session.ctx.log.assistant_turn(frame.text)
            elif isinstance(frame, InputAudioRawFrame):
                session.media_frames_in += 1
            elif isinstance(frame, OutputAudioRawFrame):
                session.media_frames_out += 1

    return Observer()
