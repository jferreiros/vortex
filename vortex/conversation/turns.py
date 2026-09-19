"""Turn-taking and tool exposure. Consumed by ``line/pipecat_voice.py``.

Owner: the conversation lane.

Interruption handling is entirely ours (the platform does no barge-in).

**Where interruptions live in pipecat 1.11.** ``PipelineParams`` no longer has
``allow_interruptions``: passing it is accepted and silently ignored. The
switch now belongs to the *user turn strategies* the user aggregator runs
(``pipecat.turns``). Two paths, chosen by ``soniox_turn_detection``:

- ``True`` (default): Soniox's own endpoint detection ends the turn
  (``vad_force_turn_endpoint=False``). We pass our own strategies so the
  ``interrupt_min_words`` barge-in gate still runs: ``MinWordsUserTurnStartStrategy``
  starts the turn, ``ExternalUserTurnStopStrategy`` closes it on Soniox's
  ``ProposedUserStoppedSpeakingFrame``. Without that override the STT would
  install ``ExternalUserTurnStrategies`` and every VAD blip would interrupt.
- ``False``: pipecat's VAD starts the turn. End-of-turn is
  ``LocalSmartTurnAnalyzerV3`` (bundled v3.2) behind
  ``TurnAnalyzerUserTurnStopStrategy``, with VAD ``stop_secs`` shortened to
  ``smart_turn_vad_stop_secs`` (0.2) so the model sees short silence windows.
  Set ``use_smart_turn=False`` to fall back to a plain speech-timeout stop.

Either way the line lane passes the strategies, never a ``PipelineParams``
flag. ``LLMUserAggregatorParams(user_turn_strategies=...)`` is the argument.

Noise (problem 12) and the eight-second silence (problem 13) both live here:
the VAD thresholds keep a passing bus from becoming a barge-in, and
``user_idle_secs`` is when the aggregator fires ``on_user_turn_idle`` so the
agent can ask "are you still there?" (``prompt.idle_prompt_for``) instead of
letting the platform cut a quiet call.

The offline A/B of VAD+Smart Turn vs Soniox endpointing lives in
``vortex/line/smart_turn_ab.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Every tool in vortex/tools.py plus submit_action. The model sees all of
# them at once: the flow is short and staging would cost a round trip per
# stage on a three-minute call.
DEFAULT_EXPOSED_TOOLS: list[str] = [
    "find_patient",
    "validate_national_id",
    "build_registration",
    "resolve_date",
    "find_slots",
    "list_appointments",
    "prepare_booking",
    "prepare_reschedule",
    "prepare_cancel",
    "check_eligibility",
    "triage",
    "nearest_location",
    "find_provider",
    "clinic_facts",
    "submit_action",
]


@dataclass(frozen=True)
class TurnSettings:
    # The caller may talk over the agent while it reads options (problem 13).
    enable_interruptions: bool = True
    # Words the caller must say before a barge-in counts while the bot speaks.
    # One word is "uh-huh" or the television; two is a correction. Applies in
    # both Soniox and VAD turn modes (via MinWordsUserTurnStartStrategy).
    interrupt_min_words: int = 2
    # Noisy-caller settings (problem 12): a higher bar before Silero calls it
    # speech, so a bus going past does not become a barge-in. No denoiser in
    # front of STT: Deepgram/AssemblyAI both document worse WER after
    # suppression, and Soniox v5 is trained for telephony noise.
    vad_confidence: float = 0.85
    vad_start_secs: float = 0.3
    vad_stop_secs: float = 0.4
    vad_min_volume: float = 0.7
    # In VAD mode without Smart Turn, seconds of silence after speech before
    # the turn is over. Longer than the mid-id pause ("one two, three four").
    user_speech_timeout_secs: float = 1.2
    # When soniox_turn_detection is False and use_smart_turn is True, VAD
    # stop_secs must be short so Smart Turn sees 200 ms silence windows
    # (pipecat docs). The ML silence fallback is smart_turn_stop_secs.
    use_smart_turn: bool = True
    smart_turn_stop_secs: float = 2.0
    smart_turn_vad_stop_secs: float = 0.2
    smart_turn_cpu_count: int = 2
    # Seconds of caller silence before the agent prompts again. 0 disables.
    # The difficult caller goes quiet for about eight seconds; the platform's
    # own cut-off for a quiet line is unpublished, so nudge before it could.
    user_idle_secs: float = 6.0
    exposed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_EXPOSED_TOOLS))

    # --- Soniox STT ---------------------------------------------------------
    # Hints, not a lock: stt-rt-v5 still transcribes anything it hears, and with
    # language identification on it tags every token with the language it heard.
    # English first: it is the clinic's default and 69 of 73 public cases.
    stt_language_hints: tuple[str, ...] = ("en", "es", "ca")
    # True  -> Soniox's own endpoint detection ends the turn (vad_force_turn_endpoint=False)
    # False -> pipecat's VAD ends the turn and finalises Soniox
    soniox_turn_detection: bool = True
    # The three below only bite when soniox_turn_detection is True.
    # 1500 ms tolerates the pause callers make mid-DNI ("twelve, thirty-four ...").
    stt_max_endpoint_delay_ms: int = 1500
    stt_endpoint_sensitivity: float = 0.3
    stt_endpoint_latency_adjustment_level: int = 2


def default_turn_settings() -> TurnSettings:
    return TurnSettings()


def effective_vad_stop_secs(settings: TurnSettings | None = None) -> float:
    """VAD ``stop_secs`` for these settings.

    Smart Turn wants a short VAD stop (0.2 s) so it can classify each pause;
    Soniox mode and plain speech-timeout VAD keep ``vad_stop_secs``.
    """
    turns = settings or default_turn_settings()
    if not turns.soniox_turn_detection and turns.use_smart_turn:
        return turns.smart_turn_vad_stop_secs
    return turns.vad_stop_secs


def user_turn_strategies(settings: TurnSettings | None = None) -> Any | None:
    """The pipecat ``UserTurnStrategies`` for these settings.

    Soniox mode: word-count start gate plus Soniox's external stop proposal, so
    noise cannot barge in on a single VAD blip while endpointing still closes
    the turn. VAD mode: VAD start (optionally gated on ``interrupt_min_words``)
    and either Smart Turn v3.2 or a speech-timeout stop. Both honour
    ``enable_interruptions``.

    Imports pipecat lazily so the server and the tests start without it.
    """
    turns = settings or default_turn_settings()
    from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    if turns.soniox_turn_detection:
        from pipecat.turns.user_stop import ExternalUserTurnStopStrategy

        return UserTurnStrategies(
            start=[
                MinWordsUserTurnStartStrategy(
                    min_words=turns.interrupt_min_words,
                    use_interim=True,
                    enable_interruptions=turns.enable_interruptions,
                )
            ],
            stop=[
                ExternalUserTurnStopStrategy(timeout=0.5, wait_for_transcript=True),
            ],
        )

    from pipecat.turns.user_start import VADUserTurnStartStrategy

    start: list[Any] = [
        VADUserTurnStartStrategy(enable_interruptions=turns.enable_interruptions),
    ]
    if turns.interrupt_min_words > 1:
        start.append(
            MinWordsUserTurnStartStrategy(
                min_words=turns.interrupt_min_words,
                enable_interruptions=turns.enable_interruptions,
            )
        )
    if turns.use_smart_turn:
        from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
        from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy

        analyzer = LocalSmartTurnAnalyzerV3(
            cpu_count=turns.smart_turn_cpu_count,
            params=SmartTurnParams(stop_secs=turns.smart_turn_stop_secs),
        )
        stop: list[Any] = [
            TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=analyzer,
                wait_for_transcript=True,
                enable_interruptions=turns.enable_interruptions,
            )
        ]
    else:
        from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy

        stop = [
            SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=turns.user_speech_timeout_secs)
        ]
    return UserTurnStrategies(start=start, stop=stop)
