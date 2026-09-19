"""Turn-taking and tool exposure. Consumed by ``line/pipecat_voice.py``.

Owner: the conversation lane.

Interruption handling is entirely ours (the platform does no barge-in).

**Where interruptions live in pipecat 1.11.** ``PipelineParams`` no longer has
``allow_interruptions``: passing it is accepted and silently ignored. The
switch now belongs to the *user turn strategies* the user aggregator runs
(``pipecat.turns``). Two paths, chosen by ``soniox_turn_detection``:

- ``True`` (default): Soniox's own endpoint detection ends the turn. The STT
  service is built with ``vad_force_turn_endpoint=False`` and
  ``should_interrupt=enable_interruptions``; it then installs
  ``ExternalUserTurnStrategies(enable_interruptions=...)`` on the aggregator
  itself through its metadata frame. Nothing else to wire.
- ``False``: pipecat's VAD starts and ends the turn. Then the aggregator must
  be given ``user_turn_strategies=user_turn_strategies(settings)`` (below), or
  it falls back to its defaults, which load the smart-turn v3 model and ignore
  ``enable_interruptions``.

Either way the line lane passes the strategies, never a ``PipelineParams``
flag. ``LLMUserAggregatorParams(user_turn_strategies=...)`` is the argument.

Noise (problem 12) and the eight-second silence (problem 13) both live here:
the VAD thresholds keep a passing bus from becoming a barge-in, and
``user_idle_secs`` is when the aggregator fires ``on_user_turn_idle``. The
first idle re-prompts (``prompt.idle_prompt_for``); the second summarises and
submits what the call already knows, so eight seconds of quiet does not burn
the three-minute cap with nothing sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# First ``on_user_turn_idle`` re-prompts; the next one submits. Further idles
# are no-ops (the call already sent what it had).
MAX_IDLE_REPROMPTS = 1

IdlePhase = Literal["reprompt", "submit", "done"]


def idle_phase(count: int, *, max_reprompts: int = MAX_IDLE_REPROMPTS) -> IdlePhase:
    """What to do on the Nth ``on_user_turn_idle`` (1-based) for this call."""
    if count < 1:
        raise ValueError(f"idle count must be >= 1, got {count}")
    if count <= max_reprompts:
        return "reprompt"
    if count == max_reprompts + 1:
        return "submit"
    return "done"


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
    # In VAD mode, words the caller must say before a barge-in counts. One
    # word is "uh-huh" or the television; two is a correction.
    interrupt_min_words: int = 2
    # Noisy-caller settings (problem 12): a higher bar before Silero calls it
    # speech, so a bus going past does not become a barge-in. No denoiser in
    # front of STT: Deepgram/AssemblyAI both document worse WER after
    # suppression, and Soniox v5 is trained for telephony noise.
    vad_confidence: float = 0.85
    vad_start_secs: float = 0.3
    vad_stop_secs: float = 0.4
    vad_min_volume: float = 0.7
    # In VAD mode, seconds of silence after speech before the turn is over.
    # Longer than the mid-id pause ("one two, three four ... five six").
    user_speech_timeout_secs: float = 1.2
    # Seconds of caller silence before the first re-prompt. 0 disables.
    # The difficult caller goes quiet for about eight seconds; nudge at 5 s so
    # one re-prompt still fits before the platform could cut the line.
    user_idle_secs: float = 5.0
    # Safety net: if no stop strategy ends the user turn, force it after this.
    user_turn_stop_secs: float = 6.0
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


def user_turn_strategies(settings: TurnSettings | None = None) -> Any | None:
    """The pipecat ``UserTurnStrategies`` for these settings, or ``None``.

    ``None`` in Soniox turn-detection mode: the STT service installs
    ``ExternalUserTurnStrategies`` itself, and a value passed here would
    override it and break turn endings. In VAD mode it returns a VAD start
    strategy gated on ``interrupt_min_words`` while the bot speaks, and a
    speech-timeout stop strategy, both honouring ``enable_interruptions``.

    Imports pipecat lazily so the server and the tests start without it.
    """
    turns = settings or default_turn_settings()
    if turns.soniox_turn_detection:
        return None
    from pipecat.turns.user_start import (
        MinWordsUserTurnStartStrategy,
        VADUserTurnStartStrategy,
    )
    from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

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
    stop = [SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=turns.user_speech_timeout_secs)]
    return UserTurnStrategies(start=start, stop=stop)
