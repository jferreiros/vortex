"""The real voice pipeline: pipecat over the Twilio-shaped socket.

    transport.input -> STT (Deepgram) -> user aggregator -> LLM (OpenAI)
                    -> TTS (OpenAI) -> transport.output -> assistant aggregator

One pipeline per socket. The serializer takes the ``stream_sid`` of this call,
the context takes this call's prompt, and every tool handler closes over this
call's ``ToolContext``. Nothing here is module-level state.

Owner: the line lane for the wiring; the conversation lane for prompt, turn
settings and tool exposure (it edits ``vortex/conversation/*``, not this file).

Imports of pipecat live inside the function so the server starts, and the
smoke test runs, with the stub pipeline when the keys are missing.

TODO(line):
- Run one real call end to end once DEEPGRAM_API_KEY and OPENAI_API_KEY exist.
- Confirm the 8 kHz µ-law path: serializer ``twilio_sample_rate=8000`` in, and
  the TTS resampled by the output transport. Check for choppy audio.
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
from vortex.conversation.prompt import GREETING, initial_messages
from vortex.conversation.turns import TurnSettings, default_turn_settings
from vortex.line.session import CallSession

log = logging.getLogger(__name__)


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
    from pipecat.services.deepgram.stt import DeepgramSTTService, LiveOptions
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.openai.tts import OpenAITTSService
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    settings = session.settings
    turns = turn_settings or default_turn_settings()
    ctx = session.ctx
    ctx.log.event("voice.mode", mode="pipecat")

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

    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        live_options=LiveOptions(
            model=settings.deepgram_stt_model,
            language=turns.stt_language,
            smart_format=True,
            interim_results=True,
        ),
    )
    llm = OpenAILLMService(api_key=settings.openai_api_key, model=settings.openai_llm_model)
    tts = OpenAITTSService(
        api_key=settings.openai_api_key,
        model=settings.openai_tts_model,
        voice=settings.openai_tts_voice,
    )

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

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
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
