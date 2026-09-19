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

**Never return ``None`` from :func:`user_turn_strategies`.** ``None`` looks
free but is not: ``LLMUserContextAggregator.__init__`` does
``self._params.user_turn_strategies or UserTurnStrategies()``, and
``UserTurnStrategies.__post_init__`` fills an empty ``stop`` from
``default_user_turn_stop_strategies()``, which constructs
``LocalSmartTurnAnalyzerV3()`` — an ``onnxruntime.InferenceSession`` over
``smart-turn-v3.2-cpu.onnx``, built eagerly in ``__init__``. In Soniox mode
that model is then replaced by the strategies the STT service recommends and
never used, so every socket loaded and threw away an ONNX session. Both
branches below pass an explicit ``start`` *and* ``stop``, so the fallback never
runs and the analyzer is built only where ``use_smart_turn`` asks for it.

The offline A/B of VAD+Smart Turn vs Soniox endpointing lives in
``vortex/line/smart_turn_ab.py``.

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

**The single confirmation.** :class:`ConfirmationPolicy` reads one thing off the
transcript: the caller has just said yes to the plan we read back. On the scored
runs the agent sometimes answered that yes by reading the whole plan back again,
and the call ran out of wall clock with nothing submitted. The prompt says to
submit on the first yes; this policy is the part that does not depend on the
model obeying it, and ``CallSession.confirm_prepared`` is what it feeds.
"""

from __future__ import annotations

import re
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

    Never ``None``: both branches pass an explicit ``start`` and ``stop``, so
    the aggregator never falls back to ``UserTurnStrategies()`` and its
    smart-turn default. The analyzer is built only when ``use_smart_turn`` is
    on, which is VAD mode only.

    Imports pipecat lazily so the module imports without it.
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


# --- the single confirmation --------------------------------------------------
# Pure, like the idle escalation: two string tests and a two-slot state machine,
# so the rule can be read and tested without pipecat, a socket or a model.

# A yes is short. Anything longer is a sentence with a yes somewhere in it, and
# a sentence can carry a correction ("yes, but make it Friday afternoon").
AFFIRMATION_MAX_WORDS = 6

# What a caller says instead of "yes", in the five languages we answer in.
AFFIRMATION_WORDS: frozenset[str] = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
        "correct",
        "perfect",
        "exactly",
        "confirm",
        "confirmed",
        "si",
        "sí",
        "vale",
        "dale",
        "claro",
        "correcto",
        "perfecto",
        "adelante",
        "d'acord",
        "dacord",
        "correcte",
        "perfecte",
        "endavant",
        "bai",
        "ados",
    }
)

AFFIRMATION_PHRASES: tuple[str, ...] = (
    "book it",
    "book that",
    "go ahead",
    "that works",
    "that's right",
    "sounds good",
    "de acuerdo",
    "así es",
    "asi es",
    "me va bien",
    "está bien",
    "esta bien",
)

# A yes that is taking something back is not a yes. ``NEGATIONS`` are matched
# whole ("no", "not"); the stems are matched anywhere, so "cambi" covers
# "cambia", "cambiar" and "cambio".
NEGATIONS: frozenset[str] = frozenset({"no", "not", "nope", "dont", "don't", "nada", "ez", "ezetz"})

CORRECTION_STEMS: tuple[str, ...] = (
    "instead",
    "actually",
    "rather",
    "wait",
    "change",
    "en lugar",
    "mejor",
    "espera",
    "cambi",
    "prefer",
)

# Words that make an agent question a read-back rather than any other question.
# Deliberately narrow: a missed read-back costs one avoidable turn, a false one
# would send an action the caller never agreed to.
CONFIRMATION_CUES: tuple[str, ...] = (
    "book",
    "confirm",
    "appointment",
    "cit",
    "hora",
    "reserv",
    "anul",
    "cancel",
    "hitzordu",
)

_WORDS = re.compile(r"[\w'’]+")


def _words(text: str) -> list[str]:
    return _WORDS.findall(text.casefold().replace("’", "'"))


def is_affirmation(text: str) -> bool:
    """Is this caller turn a plain yes, and nothing else?

    Short, carrying one of the yes words or phrases, and free of any negation or
    correction. "yes" and "dale" pass; "yes, but Friday instead" does not.
    """
    words = _words(text)
    if not words or len(words) > AFFIRMATION_MAX_WORDS:
        return False
    if any(word in NEGATIONS for word in words):
        return False
    joined = " ".join(words)
    if any(stem in joined for stem in CORRECTION_STEMS):
        return False
    if any(word in AFFIRMATION_WORDS for word in words):
        return True
    return any(phrase in joined for phrase in AFFIRMATION_PHRASES)


def looks_like_confirmation_question(text: str, *, prepared: bool = False) -> bool:
    """Was the agent's last turn a read-back waiting for a yes?

    A question mark is required either way. ``prepared`` says a tool has already
    drawn an action up on this call, which is itself the closing step, so the
    cue words are only needed before that.
    """
    if "?" not in text:
        return False
    if prepared:
        return True
    lowered = text.casefold()
    return any(cue in lowered for cue in CONFIRMATION_CUES)


@dataclass(frozen=True)
class ConfirmDecision:
    """What one caller turn means for the plan the agent read back."""

    confirmed: bool
    why: str = ""


class ConfirmationPolicy:
    """One caller's confirmations. One instance per socket, never shared.

    The agent's turn arrives as TTS fragments, so :meth:`on_assistant_text` is
    fed every piece and joins them; :meth:`on_user_text` judges the caller's
    reply against that joined turn. The agent's turn is kept until the agent
    speaks again, so a caller whose yes reaches the STT as two transcripts
    ("well ..." then "yes") is still heard the second time.

    ``confirmed`` means exactly one thing: submit what is prepared now, and do
    not read the plan back a second time.
    """

    __slots__ = ("_answered", "_assistant")

    def __init__(self) -> None:
        self._assistant: list[str] = []
        self._answered = False

    @property
    def last_assistant_turn(self) -> str:
        return " ".join(self._assistant)

    def on_assistant_text(self, text: str) -> None:
        """Collect one fragment of what the agent is saying."""
        if not text or not text.strip():
            return
        if self._answered:
            self._assistant.clear()
            self._answered = False
        self._assistant.append(text.strip())

    def on_user_text(self, text: str, *, prepared: bool = False) -> ConfirmDecision:
        """Judge one caller turn against the agent's last question."""
        question = self.last_assistant_turn
        self._answered = True
        if not is_affirmation(text):
            return ConfirmDecision(False, "not a plain yes")
        if not looks_like_confirmation_question(question, prepared=prepared):
            return ConfirmDecision(False, "no read-back to agree to")
        return ConfirmDecision(True, f"caller affirmed: {text.strip()}")
