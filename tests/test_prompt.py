"""The system prompt: it builds, it carries this call's clock, and it fits.

The prompt is resent on every turn of a three-minute call, so its size is a
running cost, not a one-off. ``TOKEN_BUDGET`` is the ceiling the conversation
lane agreed to; the approximation (four characters to a token) is deliberately
crude and deliberately pessimistic for English prose, so a prompt that passes
here has room on any tokeniser.

The other three tests are the invariants the voice pipeline depends on: a
prompt that names a tool the model was never given is an invitation to
hallucinate a call, and a tool the model was given but the prompt never
mentions is one it will not reach for.

``tests/test_conversation_lane.py`` owns the *content* of the prompt (the
rules the score depends on). This file owns its shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

from vortex.contract import MADRID
from vortex.conversation.prompt import (
    TOOL_LINES,
    build_system_prompt,
    initial_messages,
    tool_guide,
)
from vortex.conversation.turns import DEFAULT_EXPOSED_TOOLS

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)  # Friday, the public-case anchor

# Characters per token, and the ceiling. Kept here rather than in the module
# so the budget is a test the lane has to argue with, not a constant it can
# quietly raise while editing the prompt. 1400 until issue 298: listing the
# six specialty ids next to SITES_BRIEF cost ~25 tokens on a prompt that was
# already at the wall. The next claim on this budget buys its tokens out of
# the existing text.
CHARS_PER_TOKEN = 4
TOKEN_BUDGET = 1430


def test_the_prompt_builds() -> None:
    text = build_system_prompt(NOW)
    assert text.strip()
    # A template hole that never got filled renders as a literal brace.
    assert "{" not in text and "}" not in text


def test_the_prompt_carries_this_call_s_madrid_clock() -> None:
    """The clock is the call's, in Madrid, and tomorrow is spelled out for it."""
    text = build_system_prompt(NOW)
    assert "09:00 on Friday 18 September 2026 in Madrid" in text
    assert "Tomorrow is Saturday 19 September 2026" in text

    # A caller who dials at 23:30 UTC is already on the next day in Madrid:
    # the prompt must say the Madrid day, never the wire's.

    late = datetime(2026, 9, 18, 23, 30, tzinfo=UTC)  # 01:30 on the 19th, Madrid
    assert "01:30 on Saturday 19 September 2026" in build_system_prompt(late)


def test_the_prompt_mentions_every_tool_the_model_is_given() -> None:
    text = build_system_prompt(NOW)
    missing = [name for name in DEFAULT_EXPOSED_TOOLS if name not in text]
    assert not missing, f"exposed but never explained: {missing}"


def test_the_tool_guide_cannot_drift_from_the_exposed_list() -> None:
    """A tool added to one list and not the other is the failure this catches."""
    assert set(TOOL_LINES) == set(DEFAULT_EXPOSED_TOOLS)
    guide = tool_guide()
    for name in DEFAULT_EXPOSED_TOOLS:
        assert f"\n{name}: " in guide, name
    # One line per tool, plus the header.
    assert len(guide.splitlines()) == len(DEFAULT_EXPOSED_TOOLS) + 1


def test_the_prompt_fits_the_turn_budget() -> None:
    """Sent every turn: an over-budget prompt is paid for on every reply."""
    text = build_system_prompt(NOW)
    approx_tokens = len(text) // CHARS_PER_TOKEN
    assert approx_tokens <= TOKEN_BUDGET, (
        f"system prompt is ~{approx_tokens} tokens, budget is {TOKEN_BUDGET} "
        f"({len(text)} characters; the ceiling is {TOKEN_BUDGET * CHARS_PER_TOKEN})"
    )


def test_every_language_variant_fits_too() -> None:
    """A longer language name must not be what pushes the prompt over."""
    for code in ("en", "es", "ca", "gl", "eu"):
        text = build_system_prompt(NOW, language=code)
        assert len(text) // CHARS_PER_TOKEN <= TOKEN_BUDGET, code


def test_initial_messages_carries_the_whole_prompt() -> None:
    messages = initial_messages(NOW)
    assert [m["role"] for m in messages] == ["system"]
    content = messages[0]["content"]
    assert content == build_system_prompt(NOW)
    assert "submit_action" in content
