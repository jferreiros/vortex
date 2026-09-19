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
``user_idle_secs`` is when the aggregator fires ``on_user_turn_idle`` so the
agent can ask "are you still there?" (``prompt.idle_prompt_for``) instead of
letting the platform cut a quiet call.

**Why Soniox mode passes strategies instead of ``None``.** ``None`` looks free
but is not: ``LLMUserContextAggregator.__init__`` does
``self._params.user_turn_strategies or UserTurnStrategies()``, and
``UserTurnStrategies.__post_init__`` fills an empty ``stop`` from
``default_user_turn_stop_strategies()``, which constructs
``LocalSmartTurnAnalyzerV3()`` — an ``onnxruntime.InferenceSession`` over
``smart-turn-v3.2-cpu.onnx``, built eagerly in ``__init__``. The Soniox
recommendation only lands later, from the STT service's metadata frame, so the
model was loaded once per socket and then thrown away. Passing
``ExternalUserTurnStrategies(enable_interruptions=...)`` ourselves is the same
object Soniox recommends (``services/soniox/stt.py`` builds exactly
``ExternalUserTurnStrategies(enable_interruptions=self._should_interrupt)``,
and we pass ``should_interrupt=enable_interruptions``), so behaviour is
unchanged and nothing loads the ONNX model.

**The idle escalation.** :class:`IdlePolicy` decides what an idle event says.
On the 2026-09-18 scored run the handler spoke the same "are you still there?"
every time the timer expired: 147 nudges over 20 calls, up to 13 in one, each
one making the caller restart the sentence they were already halfway through.
The timer re-arms on ``BotStoppedSpeakingFrame``, so every nudge bought itself
the next one. The policy now says the short nudge once, then a "take your
time" line, then nothing for ``idle_mute_secs``.

**What pipecat's idle timer already guarantees** (``turns/user_idle_controller``
in 1.11): the timer is armed on ``BotStoppedSpeakingFrame`` and cancelled on
``BotStartedSpeakingFrame``, ``UserStartedSpeakingFrame`` and
``FunctionCallsStartedFrame``. So it is measured from the end of the bot's turn,
never from the caller's last word, and it cannot fire while the bot is speaking
or while a tool call is in flight. ``idle_bot_grace_secs`` is a floor on top of
that for the one case the controller cannot see: our own nudge, queued as a
``TTSSpeakFrame`` that has not reached the transport yet.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vortex.settings import get_settings

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


# Seconds the agent stays quiet after the second nudge. Long enough that the
# caller who is reading a card back to themselves is never cut twice.
IDLE_MUTE_SECS = 20.0
# The agent never nudges within this many seconds of its own last line.
IDLE_BOT_GRACE_SECS = 2.0


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
    # Seconds of caller silence before the agent prompts again. 0 disables.
    # ``VORTEX_USER_IDLE_SECS`` in .env moves it; the default lives in
    # ``settings.Settings.user_idle_secs``, which is where the measurement that
    # set it is written down. Short version: 6 s fired inside the caller's own
    # thinking pause 147 times over the 20 calls of 2026-09-18; the harness
    # caller answers in 4.5 s median, 10 s p90, 22 s max.
    user_idle_secs: float = field(default_factory=lambda: get_settings().user_idle_secs)
    # After the second nudge, how long the agent says nothing at all.
    idle_mute_secs: float = IDLE_MUTE_SECS
    # A floor between the agent's own last line and the next nudge.
    idle_bot_grace_secs: float = IDLE_BOT_GRACE_SECS
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


def user_turn_strategies(settings: TurnSettings | None = None) -> Any:
    """The pipecat ``UserTurnStrategies`` for these settings. Never ``None``.

    In Soniox turn-detection mode it returns the same
    ``ExternalUserTurnStrategies(enable_interruptions=...)`` the STT service
    recommends through its metadata frame, so turn endings are unchanged and
    the aggregator never falls back to ``UserTurnStrategies()`` — whose default
    stop strategy builds ``LocalSmartTurnAnalyzerV3()`` and loads an ONNX model
    per socket for nothing. In VAD mode it returns a VAD start strategy gated
    on ``interrupt_min_words`` while the bot speaks, and a speech-timeout stop
    strategy. Neither path ever constructs a smart-turn analyzer.

    Imports pipecat lazily so the module imports without it.
    """
    turns = settings or default_turn_settings()
    if turns.soniox_turn_detection:
        from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies

        return ExternalUserTurnStrategies(enable_interruptions=turns.enable_interruptions)
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


# --- the idle escalation ------------------------------------------------------
# Kept here, and pure, so it can be tested without pipecat, a socket or a clock.


@dataclass(frozen=True)
class IdleDecision:
    """What one ``on_user_turn_idle`` event should do.

    ``text`` is ``None`` when the agent says nothing; ``suppressed`` then names
    why, and goes on the call log so a post-mortem can tell a silence that was
    chosen from one that never happened.
    """

    count: int
    level: int
    text: str | None = None
    suppressed: str | None = None

    @property
    def speaks(self) -> bool:
        return self.text is not None


class IdlePolicy:
    """One caller's idle escalation. One instance per socket, never shared.

    The sequence, counting consecutive idle events with no caller speech
    between them:

    1. the short nudge (``prompt.idle_prompt_for``);
    2. the "take your time" line (``prompt.idle_patience_for``), and then
       silence for ``idle_mute_secs``;
    3. nothing, until the caller speaks or the mute window runs out.

    :meth:`on_user_speech` puts it back to step 1. It is wired to the
    aggregator's ``on_user_turn_started``, which fires the moment the caller
    starts talking — before the transcript exists — so a caller who answers is
    never charged for the pause that preceded the answer.

    In practice step 3 usually ends the nudging for that pause outright:
    pipecat re-arms the idle timer on ``BotStoppedSpeakingFrame``, so an idle
    event the policy answers with silence produces no bot speech and therefore
    no next timer. That is the intended shape — one re-prompt, then leave the
    line alone — and the mute window is what makes it true even if some other
    bot utterance re-arms the timer in between.
    """

    __slots__ = ("_clock", "_count", "_muted_until", "_spoke_at", "_turns")

    def __init__(
        self,
        settings: TurnSettings | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._turns = settings or default_turn_settings()
        self._clock = clock
        self._count = 0
        self._muted_until = float("-inf")
        self._spoke_at = float("-inf")

    @property
    def count(self) -> int:
        """Nudges spoken since the caller last said anything."""
        return self._count

    def on_user_speech(self) -> None:
        """The caller spoke. Forget the pause that came before it."""
        self._count = 0
        self._muted_until = float("-inf")

    def on_idle(self, language: str | None = None) -> IdleDecision:
        """Decide what this idle event says, and remember that it said it."""
        # Imported here, not at module scope: ``prompt`` reads this module's
        # ``DEFAULT_EXPOSED_TOOLS`` while it builds the system prompt, so a
        # top-level import back into it is a cycle.
        from vortex.conversation.prompt import idle_patience_for, idle_prompt_for

        now = self._clock()
        if now - self._spoke_at < self._turns.idle_bot_grace_secs:
            # Our own previous line is still going out. pipecat's controller
            # cancels the timer on BotStartedSpeakingFrame, but the frame we
            # queued may not have reached the transport yet.
            return IdleDecision(self._count, 0, suppressed="bot_speaking")
        if now < self._muted_until:
            return IdleDecision(self._count, 0, suppressed="muted")

        self._count += 1
        if self._count == 1:
            decision = IdleDecision(self._count, 1, idle_prompt_for(language))
        else:
            # Restating what we are waiting for would need the model, and the
            # idle handler runs outside the LLM turn. So: stop asking.
            decision = IdleDecision(self._count, 2, idle_patience_for(language))
            self._muted_until = now + self._turns.idle_mute_secs
        self._spoke_at = now
        return decision
