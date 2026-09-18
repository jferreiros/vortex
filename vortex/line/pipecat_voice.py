"""The real voice pipeline: pipecat over the Twilio-shaped socket.

    transport.input -> STT (Soniox stt-rt-v5) -> language watcher
                    -> user aggregator -> LLM (OpenAI-compatible, EU)
                    -> TTS (Google Cloud, Azure Neural or Deepgram Aura-2)
                    -> transport.output -> assistant aggregator

Every provider is EU-hosted: Soniox for transcription, an OpenAI-compatible
endpoint (IONOS / Nebius / Groq EU) running a small non-thinking Qwen for the
model, and Google Cloud Text-to-Speech for the voice — the only one with
Catalan, Galician *and* Basque. ``VORTEX_TTS_PROVIDER=azure`` swaps it for
Azure Neural (es/ca), ``=deepgram`` for Aura-2 on Deepgram's EU endpoint
(es only, no mid-call switch).

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
  the TTS asked for 8 kHz PCM out (Google LINEAR16 @ 8000, Azure
  Raw8Khz16BitMonoPcm). Check for choppy audio.
- Decide the idle policy: the platform cuts a call that goes quiet. Keep a
  user-idle prompt so the agent is never silent for long.
- Hang up from our side when the agent says goodbye (send EndFrame, let the
  platform close the socket). auto_hang_up stays False: no Twilio account.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from vortex import tools as registry
from vortex.conversation.language import DEFAULT_LANGUAGE, detect_language, tts_voice_for
from vortex.conversation.prompt import GREETING, initial_messages
from vortex.conversation.stt_context import stt_terms
from vortex.conversation.turns import TurnSettings, default_turn_settings
from vortex.line.session import CallSession

log = logging.getLogger(__name__)

# Both the line in and the voice out are 8 kHz: the platform speaks µ-law at
# 8 kHz and the serializer does the companding.
LINE_SAMPLE_RATE = 8000


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
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import TTSSpeakFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
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
    transport = FastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
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
            context=SonioxContextObject(terms=stt_terms(ctx)),
            max_endpoint_delay_ms=turns.stt_max_endpoint_delay_ms,
            endpoint_sensitivity=turns.stt_endpoint_sensitivity,
            endpoint_latency_adjustment_level=turns.stt_endpoint_latency_adjustment_level,
        ),
        # False hands the end of the turn to Soniox's own endpoint detection.
        vad_force_turn_endpoint=not turns.soniox_turn_detection,
        should_interrupt=turns.enable_interruptions,
    )

    # ---- LLM: any OpenAI-compatible endpoint, as long as it is in the EU. ----
    llm_settings = OpenAILLMService.Settings(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        # vLLM/SGLang read this off the request and skip the reasoning block.
        extra={"chat_template_kwargs": {"enable_thinking": False}}
        if settings.llm_disable_thinking
        else {},
    )
    llm = OpenAILLMService(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        settings=llm_settings,
    )

    tts = _make_tts(settings)

    # ---- tools: every registry entry becomes a function the model can call ----
    def make_handler(tool_name: str):
        async def handler(params: FunctionCallParams) -> None:
            try:
                result = await registry.call_tool(tool_name, ctx, dict(params.arguments))
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
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=turns.vad_confidence,
                    start_secs=turns.vad_start_secs,
                    stop_secs=turns.vad_stop_secs,
                    min_volume=turns.vad_min_volume,
                )
            ),
            user_idle_timeout=turns.user_idle_secs,
        ),
    )

    stages: list[Any] = [transport.input(), stt]
    if settings.tts_supports_language_switch:
        # Google (es/ca/gl/eu) and Azure (es/ca) have a voice to switch to.
        # Deepgram has one Spanish voice, so the watcher would be a no-op.
        stages.append(_LanguageWatcher(session))
    stages += [
        aggregators.user(),
        llm,
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

    @aggregators.user().event_handler("on_user_turn_idle")
    async def _on_user_idle(aggregator: Any, *args: Any) -> None:
        # TODO(conversation): the "are you still there?" prompt lives here.
        ctx.log.event("voice.user_idle")

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
    return "pipeline_finished"


def _providers(settings: Any) -> dict[str, object]:
    return {
        "stt": f"soniox/{settings.soniox_stt_model}",
        "llm": settings.llm_model,
        "tts": settings.tts_provider,
    }


def _make_tts(settings: Any) -> Any:
    """Google Cloud by default; Azure Neural or Deepgram Aura-2 on request.

    All three are asked for 8 kHz PCM: Google encodes LINEAR16 at that rate,
    Azure maps it to ``Raw8Khz16BitMonoPcm``, and the Twilio serializer does
    the µ-law companding on the way out.
    """
    if settings.tts_provider == "google":
        # The HTTP service, not the streaming ``GoogleTTSService``: streaming
        # only speaks Chirp 3 HD / Journey, and ca/gl/eu exist solely as
        # Standard voices. The HTTP one takes both families, so a single
        # service covers every language through a voice swap.
        from pipecat.services.google.tts import GoogleHttpTTSService

        voice, language = tts_voice_for(DEFAULT_LANGUAGE, settings)
        return GoogleHttpTTSService(
            # Inline JSON wins when both are set, matching pipecat's own order.
            credentials=settings.google_tts_credentials_json or None,
            credentials_path=settings.google_application_credentials or None,
            sample_rate=LINE_SAMPLE_RATE,
            settings=GoogleHttpTTSService.Settings(voice=voice, language=language),
        )

    if settings.tts_provider == "azure":
        from pipecat.services.azure.tts import AzureTTSService
        from pipecat.transcriptions.language import Language

        return AzureTTSService(
            api_key=settings.azure_speech_key,
            region=settings.azure_speech_region,
            sample_rate=LINE_SAMPLE_RATE,
            settings=AzureTTSService.Settings(
                voice=settings.azure_tts_voice_es,
                language=Language.ES_ES,
            ),
        )

    from pipecat.services.deepgram.tts import DeepgramTTSService

    return DeepgramTTSService(
        api_key=settings.deepgram_api_key,
        # The streaming service wants a WebSocket origin; the env var holds the
        # HTTP one so it reads like every other base URL.
        base_url=_as_websocket_url(settings.deepgram_base_url),
        sample_rate=LINE_SAMPLE_RATE,
        settings=DeepgramTTSService.Settings(voice=settings.deepgram_tts_model),
    )


def _as_websocket_url(url: str) -> str:
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


def _LanguageWatcher(session: CallSession):  # noqa: N802 - factory that returns a processor
    """Switch the voice when the caller switches language.

    Soniox tags each transcription frame with the language it heard. When that
    flips (es <-> ca / gl / eu on Google, es <-> ca on Azure) we push a
    ``TTSUpdateSettingsFrame`` downstream; the TTS service applies the delta in
    place, so the voice changes without rebuilding the pipeline. There is no
    public ``update_settings()`` coroutine on ``TTSService`` in pipecat 1.11 —
    the control frame is the supported way in.

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

    class LanguageWatcher(FrameProcessor):
        def __init__(self) -> None:
            super().__init__()
            self._language = "es"

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                await self._maybe_switch(frame)
            await self.push_frame(frame, direction)

        async def _maybe_switch(self, frame: TranscriptionFrame) -> None:
            try:
                language = detect_language(frame.text, hint=frame.language)
                if language == self._language:
                    return
                voice, tts_language = tts_voice_for(language, session.settings)
                previous, self._language = self._language, language
                session.ctx.log.event(
                    "voice.language_switch", was=previous, now=language, voice=voice
                )
                await self.push_frame(
                    TTSUpdateSettingsFrame(delta=TTSSettings(voice=voice, language=tts_language)),
                    FrameDirection.DOWNSTREAM,
                )
            except Exception as exc:  # a failed switch must never end the call
                log.warning("language switch failed: %s", exc)

    return LanguageWatcher()


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
