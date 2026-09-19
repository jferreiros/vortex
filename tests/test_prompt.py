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

The version tests pin the loader: the env var names the version, unset means
the latest on disk, a version is a file that is never edited in place, and
the sha256 is of the exact bytes the run recorded.

``tests/test_conversation_lane.py`` owns the *content* of the prompt (the
rules the score depends on). This file owns its shape.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vortex.contract import MADRID
from vortex.conversation import prompt as prompt_module
from vortex.conversation.prompt import (
    CLINIC_NAME,
    PROMPTS_DIR,
    SITES_BRIEF,
    SPECIALTIES_BRIEF,
    TOOL_GUIDE,
    TOOL_LINES,
    active_prompt_version,
    build_system_prompt,
    caller_note_for,
    initial_messages,
    latest_prompt_version,
    list_prompt_versions,
    load_prompt_template,
    prompt_sha256,
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


# ---- versions ----------------------------------------------------------------


def test_env_unset_loads_the_latest_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORTEX_PROMPT_VERSION", raising=False)
    assert active_prompt_version() == latest_prompt_version() == "v4-nearest-offer"
    assert build_system_prompt(NOW) == load_prompt_template("v4-nearest-offer").format(
        clinic_name=CLINIC_NAME,
        now_human="09:00 on Friday 18 September 2026",
        tomorrow="Saturday 19 September 2026",
        language="English",
        sites_brief=SITES_BRIEF,
        specialties_brief=SPECIALTIES_BRIEF,
        caller_note=caller_note_for(None),
        tool_guide=TOOL_GUIDE,
    )


def test_the_env_var_names_the_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "v4-test.md").write_text("Pinned: {language}.", encoding="utf-8")
    monkeypatch.setenv("VORTEX_PROMPT_VERSION", "v4-test")
    assert active_prompt_version(tmp_path) == "v4-test"
    assert load_prompt_template(directory=tmp_path) == "Pinned: {language}."
    # build_system_prompt resolves the env at call time, not at import.
    monkeypatch.setattr(prompt_module, "PROMPTS_DIR", tmp_path)
    assert build_system_prompt(NOW) == "Pinned: English."


def test_an_unknown_or_malformed_version_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="unknown prompt version 'v9-nope'"):
        load_prompt_template("v9-nope")
    with pytest.raises(ValueError, match="not a v<N>-<slug> name"):
        load_prompt_template("../escape")
    monkeypatch.setenv("VORTEX_PROMPT_VERSION", "v9-nope")
    with pytest.raises(ValueError, match="v3-specialty-ids"):
        build_system_prompt(NOW)


def test_a_second_version_can_be_added_without_editing_the_first(
    tmp_path: Path,
) -> None:
    first = load_prompt_template("v3-specialty-ids")
    (tmp_path / "v3-specialty-ids.md").write_text(first, encoding="utf-8")
    (tmp_path / "v4-terse.md").write_text("Terse. {tool_guide}", encoding="utf-8")
    assert list_prompt_versions(tmp_path) == ["v3-specialty-ids", "v4-terse"]
    assert latest_prompt_version(tmp_path) == "v4-terse"
    # The first version still loads, byte for byte, from the same directory.
    assert load_prompt_template("v3-specialty-ids", tmp_path) == first
    assert prompt_sha256("v3-specialty-ids", tmp_path) == prompt_sha256("v3-specialty-ids")


def test_prompt_sha256_is_the_file_s_bytes() -> None:
    assert (
        prompt_sha256("v3-specialty-ids")
        == hashlib.sha256((PROMPTS_DIR / "v3-specialty-ids.md").read_bytes()).hexdigest()
    )
