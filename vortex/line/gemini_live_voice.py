"""Jury demo: Gemini 3.8 Live speech-to-speech with the same Vortex tools.

    transport.input -> user aggregator -> GeminiLiveLLMService
                  -> transport.output -> assistant aggregator

No Soniox, no separate TTS. Gemini hears 16 kHz PCM and speaks 24 kHz; the
Twilio serializer and transport resample to and from the line's 8 kHz µ-law.

Opt-in only: ``VORTEX_VOICE_MODE=gemini-live`` plus ``GOOGLE_API_KEY``. The
cascaded pipecat path stays the scoring pipeline — agentic S2S still sits under
52 % on tau-Voice. Show this to the jury; do not Run All with it.

One pipeline per socket. Tools close over this call's ``CallSession``. Nothing
here is module-level state.

Owner: the line lane (wiring). Prompt and tool list come from conversation /
``vortex.tools`` unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from vortex import tools as registry
from vortex.conversation.prompt import GREETING, build_system_prompt
from vortex.conversation.turns import TurnSettings, default_turn_settings
from vortex.line.recording import recording_serializer
from vortex.line.session import CallSession

log = logging.getLogger(__name__)

# Wire format stays 8 kHz µ-law; Gemini Live's native rates are handled inside
# the service and the transport resampler.
LINE_SAMPLE_RATE = 8000

# Default model id when settings omit it. Keep in sync with Settings default.
DEFAULT_GEMINI_LIVE_MODEL = "models/gemini-3.8-live"
DEFAULT_GEMINI_LIVE_VOICE = "Aoede"


def tool_schemas_for(exposed_tools: tuple[str, ...] | list[str]) -> list[Any]:
    """Build pipecat ``FunctionSchema`` rows for the tools this call exposes.

    Same shape as the cascaded pipeline: nested ``$defs`` travel inside
    ``properties`` so Gemini sees Slot / Action without a separate defs map.
    """
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    schemas: list[Any] = []
    for fn in registry.function_schemas(exposed_tools):
        params_schema = fn["parameters"]
        properties = dict(params_schema["properties"])
        if params_schema.get("$defs"):
            properties["$defs"] = params_schema["$defs"]
        schemas.append(
            FunctionSchema(
                name=fn["name"],
                description=fn["description"],
                properties=properties,
                required=params_schema["required"],
            )
        )
    return schemas


def build_gemini_live_service(
    *,
    api_key: str,
    model: str,
    voice: str,
    system_instruction: str,
    schemas: list[Any],
    session: CallSession,
) -> Any:
    """Construct ``GeminiLiveLLMService`` and register Vortex tool handlers.

    Does not open a WebSocket to Google. Tests call this with a throwaway key
    to pin constructor and register signatures offline.
    """
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.transcriptions.language import Language

    llm = GeminiLiveLLMService(
        api_key=api_key,
        settings=GeminiLiveLLMService.Settings(
            model=model,
            voice=voice,
            system_instruction=system_instruction,
            language=Language.EN,
        ),
        tools=ToolsSchema(standard_tools=schemas),
        # Wait for the greeting kick-off frame so we control the first words.
        inference_on_context_initialization=False,
    )

    def make_handler(tool_name: str):
        async def handler(params: FunctionCallParams) -> None:
            try:
                result = await session.call_tool(tool_name, dict(params.arguments))
                await params.result_callback(result.model_dump(mode="json"))
            except Exception as exc:
                await params.result_callback({"error": f"{type(exc).__name__}: {exc}"})

        return handler

    for schema in schemas:
        # cancel_on_interruption=False -> Gemini NON_BLOCKING on 3.8 Live, so a
        # clinic API round-trip does not kill the tool when the caller speaks.
        llm.register_function(
            schema.name,
            make_handler(schema.name),
            cancel_on_interruption=False,
        )
    return llm


async def run_gemini_live_call(
    ws: WebSocket, session: CallSession, turn_settings: TurnSettings | None = None
) -> str:
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    settings = session.settings
    turns = turn_settings or default_turn_settings()
    ctx = session.ctx
    model = settings.gemini_live_model or DEFAULT_GEMINI_LIVE_MODEL
    voice = settings.gemini_live_voice or DEFAULT_GEMINI_LIVE_VOICE
    ctx.log.event(
        "voice.mode",
        mode="gemini-live",
        model=model,
        voice=voice,
        demo=True,
    )

    if not settings.google_api_key:
        log.error("gemini-live mode needs GOOGLE_API_KEY; refusing to dial Google")
        raise RuntimeError("GOOGLE_API_KEY is required for VORTEX_VOICE_MODE=gemini-live")

    # The standard Twilio serializer, teeing inbound media into the recording.
    serializer = recording_serializer(session)
    transport = FastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    caller = await session.resolve_caller_line()
    schemas = tool_schemas_for(turns.exposed_tools)
    llm = build_gemini_live_service(
        api_key=settings.google_api_key,
        model=model,
        voice=voice,
        system_instruction=build_system_prompt(ctx.now, caller=caller),
        schemas=schemas,
        session=session,
    )

    # Empty context: system prompt lives on the service. Tools are already on
    # the LLM; the aggregators keep the transcript for reconnect/resume.
    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        realtime_service_mode=True,
    )

    task = PipelineTask(
        Pipeline(
            [
                transport.input(),
                user_aggregator,
                llm,
                transport.output(),
                assistant_aggregator,
            ]
        ),
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
        # Kick the Live session: ask it to speak the clinic greeting once.
        context.add_message(
            {
                "role": "user",
                "content": (
                    f'Say exactly this greeting to the caller, then wait and listen: "{GREETING}"'
                ),
            }
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(transport: Any, client: Any) -> None:
        ctx.log.event("voice.client_disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
    return "pipeline_finished"


def _CallLogObserver(session: CallSession):  # noqa: N802 - factory that returns an observer
    """Log user/assistant text, bound each turn for ``turn.metrics``, and
    count media frames from the frame stream."""
    from pipecat.frames.frames import (
        InputAudioRawFrame,
        InterruptionFrame,
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        OutputAudioRawFrame,
        TranscriptionFrame,
        TTSTextFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
    from pipecat.observers.base_observer import BaseObserver, FramePushed

    from vortex.line.turnclock import TurnClock

    clock = TurnClock()

    class Observer(BaseObserver):
        async def on_push_frame(self, data: FramePushed) -> None:
            frame = data.frame
            if isinstance(frame, TranscriptionFrame):
                started_ts, ended_ts = clock.user_bounds()
                session.ctx.log.user_turn(frame.text, started_ts=started_ts, ended_ts=ended_ts)
            elif isinstance(frame, TTSTextFrame):
                started_ts, ended_ts, ttfb_ms = clock.assistant_bounds()
                session.ctx.log.assistant_turn(
                    frame.text, started_ts=started_ts, ended_ts=ended_ts, ttfb_ms=ttfb_ms
                )
            elif isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
                clock.on_user_speech_start()
            elif isinstance(frame, (UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)):
                clock.on_user_turn_end()
            elif isinstance(frame, LLMFullResponseStartFrame):
                clock.on_agent_response_start()
            elif isinstance(frame, (LLMFullResponseEndFrame, InterruptionFrame)):
                clock.on_agent_response_end()
            elif isinstance(frame, InputAudioRawFrame):
                session.media_frames_in += 1
            elif isinstance(frame, OutputAudioRawFrame):
                session.media_frames_out += 1

    return Observer()
