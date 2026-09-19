"""The real voice pipeline: pipecat over the Twilio-shaped socket.

    transport.input -> STT (Soniox stt-rt-v5) -> language watcher
                    -> user aggregator -> LLM (OpenAI-compatible or Vertex, EU)
                    -> TTS (Google Chirp / Gemini-TTS, or ElevenLabs)
                    -> transport.output -> assistant aggregator

Soniox transcribes, the endpoint named by ``LLM_PROVIDER`` answers, and the
voice is Google Cloud Text-to-Speech — the only provider here with Catalan,
Galician *and* Basque.

Every preset but one is an OpenAI-compatible endpoint under the first-token
guard. ``LLM_PROVIDER=vertex`` is Gemini on Google Cloud instead, in the region
``VERTEX_LOCATION`` names, on the service account the TTS already uses:
Google's own protocol, so no ``extra_body``, no tracing client and no
first-token guard. ``_make_vertex_llm`` says why for each.

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

We hang up from our side. Once the platform has accepted an action the model
sent, the session is armed; ``_make_hangup_watcher`` then ends the pipeline
with an ``EndFrame`` as soon as the agent has finished speaking its farewell,
and the socket closes. ``auto_hang_up`` stays False: that flag is the
serializer's own Twilio REST call, and we have no Twilio account.

TODO(line):
- Run one real call end to end once the four keys exist.
- Confirm the 8 kHz µ-law path: serializer ``twilio_sample_rate=8000`` in, and
  the TTS asked for 8 kHz PCM out (Google LINEAR16 @ 8000, ElevenLabs
  ``pcm_8000``; Gemini-TTS stays at 24 kHz and the transport resamples).
  Check for choppy audio.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from vortex import tools as registry
from vortex.conversation.language import (
    DEFAULT_LANGUAGE,
    detect_language,
    normalise_language,
    tts_voice_for,
)
from vortex.conversation.prompt import (
    GREETING,
    initial_messages,
    wait_prompt_for,
)
from vortex.conversation.stt_context import stt_context_text, stt_terms
from vortex.conversation.turns import (
    ConfirmationPolicy,
    IdlePolicy,
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

    # ---- LLM: any OpenAI-compatible endpoint, or Gemini on Vertex. Both EU. --
    llm = _make_llm(settings, ctx, language_state)

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
        schemas.append(
            FunctionSchema(
                name=fn["name"],
                description=fn["description"],
                properties=_tool_properties(params_schema, inline_defs=settings.llm_is_vertex),
                required=params_schema["required"],
            )
        )
        llm.register_function(fn["name"], make_handler(fn["name"]))

    # Before the greeting: the caller id is an exact directory query, so the
    # prompt can open knowing who the line belongs to instead of spending the
    # first minute of the call asking.
    caller = await session.resolve_caller_line()
    context = LLMContext(
        initial_messages(ctx.now, caller=caller), tools=ToolsSchema(standard_tools=schemas)
    )
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
        observers=[_CallLogObserver(session), hangup],
    )
    hangup.bind(task)

    @transport.event_handler("on_client_connected")
    async def _on_connected(transport: Any, client: Any) -> None:
        ctx.log.assistant_turn(GREETING)
        await task.queue_frames([TTSSpeakFrame(GREETING)])

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
        _make_tool_filler_speaker(session, language_state, task),
    )

    async def _on_user_turn_started(aggregator: Any, *args: Any) -> None:
        # Fires the moment the caller starts talking, before the transcript
        # exists, so the pause they just ended stops counting against them.
        idle_policy.on_user_speech()

    user_aggregator.add_event_handler("on_user_turn_started", _on_user_turn_started)

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


def _make_llm(settings: Any, ctx: Any, language_state: _LanguageState) -> Any:
    """The turn model: Gemini on Vertex, or any OpenAI-compatible endpoint."""
    if settings.llm_is_vertex:
        return _make_vertex_llm(settings, ctx)
    return _make_openai_llm(settings, ctx, language_state)


def _make_openai_llm(settings: Any, ctx: Any, language_state: _LanguageState) -> Any:
    """Any OpenAI-compatible endpoint, under the first-token guard."""
    from pipecat.services.openai.llm import OpenAILLMService

    llm_settings = OpenAILLMService.Settings(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        extra=_llm_extra_body(settings),
    )
    return traced_openai_llm_service(
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


def _make_vertex_llm(settings: Any, ctx: Any) -> Any:
    """Gemini on Vertex AI, from the region ``VERTEX_LOCATION`` names.

    Everything around it is unchanged — Soniox, the Google TTS, the tools, the
    observers. Three things do *not* come along, and each one is a deliberate
    omission rather than an oversight:

    - ``_llm_extra_body``. ``chat_template_kwargs`` and ``reasoning_effort``
      are fields of an OpenAI chat-completions request. Gemini has neither;
      pipecat would splice them into ``GenerateContentConfig`` and google-genai
      rejects the request. Reasoning is switched off through Google's own
      setting instead, below.
    - ``traced_openai_llm_service``. It swaps in an instrumented
      ``AsyncOpenAI``; there is no OpenAI client here to swap.
    - ``first_token_guard``. It wraps ``get_chat_completions``, which is the
      OpenAI entry point. ``GoogleLLMService`` streams through
      ``_stream_content``, so the subclass would install cleanly and then never
      fire — the worst kind of guard. It is left off and said out loud at
      startup, so a hung Vertex request shows up as silence we can name rather
      than a retry we imagine we have.
    """
    from pipecat.services.google.vertex.llm import GoogleVertexLLMService

    project_id = settings.vertex_project_id
    if not project_id:
        # Vertex takes the project from us, not from the token, so an empty one
        # is a 400 on the first turn. Say which variable fixes it.
        log.warning(
            "LLM_PROVIDER=vertex with no project: set VERTEX_PROJECT_ID, or point "
            "GOOGLE_APPLICATION_CREDENTIALS at a service-account JSON that carries one"
        )
    log.warning(
        "LLM_PROVIDER=vertex: the first-token guard is OpenAI-only and is not installed, "
        "so LLM_FIRST_TOKEN_TIMEOUT_SECS (%.1fs) and LLM_RETRIES (%d) do not apply to this call",
        settings.llm_first_token_timeout_secs,
        settings.llm_retries,
    )
    ctx.log.event(
        "llm.vertex",
        model=settings.llm_model,
        location=settings.vertex_location,
        project=project_id,
        first_token_guard=False,
    )

    credentials = settings.vertex_credentials
    # The credential is either the JSON itself or a path to it, exactly as the
    # TTS reads it, and pipecat takes those under two different keywords.
    credential_kwargs: dict[str, Any] = (
        {"credentials": credentials}
        if credentials.lstrip().startswith("{")
        else {"credentials_path": credentials or None}
    )
    return GoogleVertexLLMService(
        project_id=project_id,
        location=settings.vertex_location,
        settings=GoogleVertexLLMService.Settings(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            **_vertex_thinking(settings.llm_model),
        ),
        **credential_kwargs,
    )


def _vertex_thinking(model: str) -> dict[str, Any]:
    """Thinking off for the Gemini 2.5 family. Newer models: pipecat's default.

    A three-minute phone call cannot wait for a reasoning phase, which is the
    same reason ``LLM_DISABLE_THINKING`` exists for the OpenAI presets. Gemini
    2.5 switches it off with ``thinking_budget=0``. Gemini 3 replaced the
    budget with ``thinking_level`` and may reject a budget set alongside it, so
    anything that is not 2.5 is left to pipecat's own model-aware default,
    which picks the lowest level that model accepts — the same intent, in the
    field that model actually reads.
    """
    if not model.startswith("gemini-2.5"):
        return {}
    from pipecat.services.google.llm import GoogleLLMService

    return {"thinking": GoogleLLMService.ThinkingConfig(thinking_budget=0)}


def _tool_properties(params_schema: dict[str, Any], inline_defs: bool = False) -> dict[str, Any]:
    """A tool's parameter properties, in the dialect the provider accepts.

    ``model_json_schema()`` lifts every nested model (``Slot``, the six
    ``Action`` variants) into a sibling ``$defs`` and leaves ``$ref`` pointers
    behind. ``FunctionSchema`` carries properties and nothing else, so the
    definitions have to travel inside them, and the two providers need that
    done differently:

    - OpenAI-compatible hosts take the whole JSON Schema, so ``$defs`` rides
      along as one more property and the ``$ref`` pointers resolve against it.
      This is what every preset but ``vertex`` has always sent, and it is left
      exactly as it was.
    - Gemini's schema object follows OpenAPI 3.0's, which predates the JSON
      Schema keywords pydantic emits. google-genai validates the request
      locally and rejects it before it leaves the process ("Extra inputs are
      not permitted"). Verified against gemini-2.5-flash in europe-west1 on
      19 Sep 2026: every tool with a nested model failed on ``$ref``/``$defs``
      and ``submit_action``'s discriminated union failed again on ``const``,
      so neither fix is optional. ``_gemini_schema`` does both.

    pipecat's own ``GeminiLLMAdapter`` drops ``additionalProperties`` and
    adapts union types on top of this, so those are not repeated here.
    """
    properties = dict(params_schema.get("properties", {}))
    defs = params_schema.get("$defs") or {}
    if not inline_defs:
        if defs:
            properties["$defs"] = defs
        return properties
    return {name: _gemini_schema(value, defs) for name, value in properties.items()}


def _gemini_schema(node: Any, defs: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    """One property's schema, in the subset Gemini accepts.

    Two rewrites, both loss-free:

    - ``{"$ref": "#/$defs/X"}`` becomes the definition of ``X``. Sibling keys
      of the ``$ref`` (pydantic puts ``description`` and ``default`` there) win
      over the definition's own, which is how JSON Schema 2020-12 reads them.
      ``seen`` carries the chain of names already expanded, so a
      self-referential model stops at a bare object instead of inlining for
      ever and hanging the pipeline build.
    - ``const`` becomes a one-member ``enum``, which is what it means and is a
      keyword Gemini has. This is how each ``Action`` variant names its
      ``kind`` ("book", "cancel" ...), so without it the model cannot tell the
      six apart. A non-string ``const`` has no equivalent and is dropped,
      exactly as the adapter drops a non-string ``enum``.
    """
    if isinstance(node, list):
        return [_gemini_schema(item, defs, seen) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        name = ref.removeprefix("#/$defs/")
        if name in seen or name not in defs:
            return {"type": "object"}
        resolved = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
        return _gemini_schema(resolved, defs, (*seen, name))
    adapted = {
        key: _gemini_schema(value, defs, seen) for key, value in node.items() if key != "const"
    }
    if "const" in node and isinstance(node["const"], str):
        adapted["enum"] = [node["const"]]
    return adapted


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


def _make_idle_speaker(
    session: CallSession,
    state: _LanguageState,
    task: Any,
    policy: IdlePolicy | None = None,
) -> Any:
    """The handler the user aggregator fires when the caller goes quiet.

    The line comes from ``conversation.turns.IdlePolicy``: the short nudge
    first, a "take your time" line second, then silence. The platform cuts a
    call that goes quiet, so the first silence has to answer — but answering
    every silence is what put 147 nudges into the 20 calls of 2026-09-18, each
    one restarting a sentence the caller was already saying.

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
        if decision.text is not None:
            await task.queue_frames([TTSSpeakFrame(decision.text)])

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


def _CallLogObserver(  # noqa: N802 - factory that returns an observer
    session: CallSession, confirmations: ConfirmationPolicy | None = None
):
    """Log user and assistant text, count media frames, and watch for the yes.

    The frame stream is where both sides of the call already pass in order, so
    the confirmation guard reads it here: TTS text is the agent's turn, a
    transcription is the caller's reply to it. When that reply is an agreement
    to a read-back, ``CallSession.confirm_prepared`` submits what is prepared
    instead of letting the model ask a second time.
    """
    from pipecat.frames.frames import (
        InputAudioRawFrame,
        OutputAudioRawFrame,
        TranscriptionFrame,
        TTSTextFrame,
    )
    from pipecat.observers.base_observer import BaseObserver, FramePushed

    policy = confirmations if confirmations is not None else ConfirmationPolicy()

    class Observer(BaseObserver):
        async def on_push_frame(self, data: FramePushed) -> None:
            frame = data.frame
            if isinstance(frame, TranscriptionFrame):
                session.ctx.log.user_turn(frame.text)
                decision = policy.on_user_text(
                    frame.text, prepared=session.memory.prepared is not None
                )
                if decision.confirmed:
                    session.confirm_prepared(decision.why)
            elif isinstance(frame, TTSTextFrame):
                session.ctx.log.assistant_turn(frame.text)
                policy.on_assistant_text(frame.text)
            elif isinstance(frame, InputAudioRawFrame):
                session.media_frames_in += 1
            elif isinstance(frame, OutputAudioRawFrame):
                session.media_frames_out += 1

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
