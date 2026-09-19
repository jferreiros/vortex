"""The idle policy: when the agent nudges a quiet caller, and what it says.

Post-mortem of the scored run of 2026-09-18, 20 calls: 147 "Are you still
there?" nudges, a mean of 7 per call and 13 in the worst one, with 14 of the 20
calls running into the harness's 3-minute cut. The harness caller answers in a
median of 4.5 s, p90 10 s, max 22 s after the agent stops speaking, so a 6 s
timer fired while the caller was still thinking; the nudge then made them
restart their sentence, at about 10 s a time.

Two fixes, both tested here: the timer starts at 10 s, and a second
consecutive idle escalates to a "take your time" line and then silence,
instead of asking the same question again.

Everything below is pure — no pipecat, no socket, no wall clock.
"""

from __future__ import annotations

import pytest

from vortex import settings as settings_module
from vortex.conversation.prompt import idle_patience_for, idle_prompt_for
from vortex.conversation.turns import (
    IdlePolicy,
    TurnSettings,
    default_turn_settings,
)


class FakeClock:
    """A monotonic clock that only moves when the test says so."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def policy(clock: FakeClock, **overrides: object) -> IdlePolicy:
    return IdlePolicy(TurnSettings(**overrides), clock=clock)  # type: ignore[arg-type]


# ---- (a) defaults ------------------------------------------------------------


def test_the_first_nudge_waits_ten_seconds() -> None:
    """Past the caller's p90 answer time, well short of the 3-minute cap."""
    assert default_turn_settings().user_idle_secs == 10.0


def test_the_mute_window_and_the_bot_grace_have_defaults() -> None:
    turns = default_turn_settings()
    assert turns.idle_mute_secs == 20.0
    assert turns.idle_bot_grace_secs == 2.0


# ---- (b) the env override ----------------------------------------------------


def test_vortex_user_idle_secs_moves_the_first_nudge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORTEX_USER_IDLE_SECS", "4.5")
    settings_module.reset_settings()
    try:
        assert settings_module.get_settings().user_idle_secs == 4.5
        assert TurnSettings().user_idle_secs == 4.5
    finally:
        settings_module.reset_settings()


def test_the_idle_nudge_can_be_switched_off_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    # pipecat reads 0 as "no idle detection at all".
    monkeypatch.setenv("VORTEX_USER_IDLE_SECS", "0")
    settings_module.reset_settings()
    try:
        assert TurnSettings().user_idle_secs == 0.0
    finally:
        settings_module.reset_settings()


def test_the_idle_seconds_are_reported_by_describe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORTEX_USER_IDLE_SECS", "12")
    settings_module.reset_settings()
    try:
        assert settings_module.get_settings().describe()["user_idle_secs"] == 12.0
    finally:
        settings_module.reset_settings()


# ---- (c) the escalation state machine ---------------------------------------


def test_the_first_idle_speaks_the_short_nudge() -> None:
    clock = FakeClock()
    first = policy(clock).on_idle("en")
    assert first.count == 1
    assert first.level == 1
    assert first.text == idle_prompt_for("en")
    assert first.speaks is True
    assert first.suppressed is None


def test_the_second_idle_stops_asking_and_gives_the_caller_room() -> None:
    """Asking twice makes the caller restart the sentence. Say the other line."""
    clock = FakeClock()
    idle = policy(clock)
    idle.on_idle("en")
    clock.advance(10.0)
    second = idle.on_idle("en")
    assert second.count == 2
    assert second.level == 2
    assert second.text == idle_patience_for("en")
    assert second.text != idle_prompt_for("en")


def test_after_the_second_nudge_the_agent_says_nothing_for_the_mute_window() -> None:
    clock = FakeClock()
    idle = policy(clock)
    idle.on_idle("en")
    clock.advance(10.0)
    idle.on_idle("en")

    for step in (5.0, 5.0, 5.0):  # 5, 10, 15 s into a 20 s window
        clock.advance(step)
        muted = idle.on_idle("en")
        assert muted.speaks is False
        assert muted.suppressed == "muted"
        assert muted.count == 2, "a silence is not a nudge and must not count as one"

    clock.advance(10.0)  # 25 s: the window has run out
    assert idle.on_idle("en").speaks is True


def test_a_nudge_never_lands_on_top_of_the_agents_own_last_line() -> None:
    """pipecat cancels the timer on BotStartedSpeaking; this is the floor under it.

    ``UserIdleController`` arms the timer on ``BotStoppedSpeakingFrame`` and
    cancels it on ``BotStartedSpeakingFrame``, so a nudge cannot fire while the
    bot has the floor. What it cannot see is the ``TTSSpeakFrame`` we queued a
    moment ago and that has not reached the transport yet.
    """
    clock = FakeClock()
    idle = policy(clock)
    idle.on_idle("en")

    clock.advance(1.0)  # inside idle_bot_grace_secs
    blocked = idle.on_idle("en")
    assert blocked.speaks is False
    assert blocked.suppressed == "bot_speaking"
    assert blocked.count == 1

    clock.advance(2.0)
    assert idle.on_idle("en").level == 2


def test_the_caller_speaking_puts_the_escalation_back_to_the_start() -> None:
    clock = FakeClock()
    idle = policy(clock)
    idle.on_idle("en")
    clock.advance(10.0)
    idle.on_idle("en")
    assert idle.count == 2

    idle.on_user_speech()
    assert idle.count == 0

    clock.advance(10.0)
    again = idle.on_idle("en")
    assert again.count == 1
    assert again.text == idle_prompt_for("en"), "a caller who answered starts clean"


def test_speech_clears_the_mute_window_too() -> None:
    clock = FakeClock()
    idle = policy(clock)
    idle.on_idle("en")
    clock.advance(10.0)
    idle.on_idle("en")  # opens a 20 s mute window

    clock.advance(3.0)
    idle.on_user_speech()
    assert idle.on_idle("en").speaks is True


def test_the_lines_follow_the_language_of_the_call() -> None:
    clock = FakeClock()
    idle = policy(clock)
    assert idle.on_idle("ca").text == idle_prompt_for("ca")
    clock.advance(10.0)
    assert idle.on_idle("eu").text == idle_patience_for("eu")


def test_both_idle_lines_exist_in_every_language_we_can_detect() -> None:
    from vortex.conversation.language import SUPPORTED_LANGUAGES

    for code in SUPPORTED_LANGUAGES:
        assert idle_prompt_for(code).strip(), code
        assert idle_patience_for(code).strip(), code
        assert idle_patience_for(code) != idle_prompt_for(code), code


def test_two_calls_never_share_an_escalation() -> None:
    """Run All opens ten sockets at once; problem 2 opens twenty."""
    clock = FakeClock()
    one, two = policy(clock), policy(clock)
    one.on_idle("en")
    clock.advance(10.0)
    one.on_idle("en")
    assert one.count == 2
    assert two.count == 0
    assert two.on_idle("en").level == 1


def test_the_settings_drive_the_windows() -> None:
    clock = FakeClock()
    idle = policy(clock, idle_mute_secs=60.0, idle_bot_grace_secs=0.5)
    idle.on_idle("en")
    clock.advance(0.6)
    assert idle.on_idle("en").level == 2
    clock.advance(30.0)
    assert idle.on_idle("en").suppressed == "muted"
    clock.advance(31.0)
    assert idle.on_idle("en").speaks is True
