"""The conversation lane: language detection, the prompt's invariants, turn settings.

No keys, no network, no model. What a model would *do* with the prompt is
layer 2 of the evals (``--brain openai``); this pins what the lane hands the
pipeline: the right language, a prompt that names every rule the score
depends on, canned lines in every language, and turn strategies that build.
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from vortex.clinic import fixtures
from vortex.contract import MADRID
from vortex.conversation import prompt as prompt_module
from vortex.conversation.language import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    detect_language,
    language_name,
    language_scores,
    normalise_language,
)
from vortex.conversation.prompt import (
    GREETING,
    build_system_prompt,
    emergency_line_for,
    goodbye_for,
    greeting_for,
    idle_prompt_for,
    initial_messages,
    refusal_line_for,
)
from vortex.conversation.turns import (
    DEFAULT_EXPOSED_TOOLS,
    TurnSettings,
    default_turn_settings,
    user_turn_strategies,
)

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)  # Friday

# ---- language ----------------------------------------------------------------


def test_english_is_the_default() -> None:
    assert DEFAULT_LANGUAGE == "en"
    assert detect_language("") == "en"
    assert detect_language("   ") == "en"
    assert detect_language("xyzzy 123") == "en"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hi, I'd like the earliest General Practice appointment you have, please.", "en"),
        ("Good morning, my name is Josefa Domínguez Navarro.", "en"),
        ("Yes, that works. Thank you.", "en"),
        ("Hola, buenos días. Quería la primera cita libre de medicina general.", "es"),
        ("Soy Marta Ruiz López, nací el doce de marzo del ochenta y cinco.", "es"),
        ("Vale, esa me va bien. Gracias.", "es"),
        ("Bon dia. Voldria hora amb un metge de capçalera que parli català.", "ca"),
        ("Perfecte, la primera que tingui. Gràcies.", "ca"),
        ("Bos días, quero unha cita de medicina xeral, moitas grazas.", "gl"),
        ("Egun on, hitzordua nahi dut, eskerrik asko.", "eu"),
    ],
)
def test_detects_each_supported_language_from_the_words(text: str, expected: str) -> None:
    assert detect_language(text) == expected


def test_the_stt_hint_wins_over_the_words() -> None:
    pytest.importorskip("pipecat")
    from pipecat.transcriptions.language import Language

    assert detect_language("hello, I would like an appointment", hint=Language.ES_ES) == "es"
    assert detect_language("hola, quiero cita", hint="ca-ES") == "ca"
    assert detect_language("hola, quiero cita", hint=Language.EN_US) == "en"
    # An unsupported hint falls through to the words.
    assert detect_language("hola, quiero cita", hint="de") == "es"
    assert detect_language("hola, quiero cita", hint=object()) == "es"


def test_a_call_in_spanish_does_not_flip_to_english_on_an_ok() -> None:
    # "ok" carries no vote: keep the language the call is in.
    assert detect_language("ok", current="es") == "es"
    assert detect_language("ok") == "en"
    assert detect_language("", current="ca") == "ca"
    # A clear switch still switches.
    assert detect_language("Perdone, mejor en español. Quiero cita.", current="en") == "es"
    assert detect_language("Sorry, in English please. I need an appointment.", current="es") == "en"


def test_shared_words_do_not_decide_on_their_own() -> None:
    # "no" and "hola" are in several lists; alone they change nothing.
    assert detect_language("no", current="es") == "es"
    assert detect_language("no", current="en") == "en"
    scores = language_scores("el")
    assert scores["es"] == scores["ca"] == 1  # a tie, resolved by current/default


def test_normalise_language_folds_every_shape() -> None:
    assert normalise_language("es-ES") == "es"
    assert normalise_language("CA_es") == "ca"
    assert normalise_language("en") == "en"
    assert normalise_language("de") is None
    assert normalise_language(None) is None
    assert normalise_language("") is None
    assert language_name("ca") == "Catalan"
    assert language_name(None) == "English"
    assert set(SUPPORTED_LANGUAGES) == {"en", "es", "ca", "gl", "eu"}


# ---- prompt ------------------------------------------------------------------


def test_prompt_renders_the_call_clock_not_the_machine_clock() -> None:
    text = build_system_prompt(NOW)
    assert "09:00 on Friday 18 September 2026" in text
    assert "Tomorrow is Saturday 19 September 2026" in text
    assert "Answer in English" in text
    assert "Answer in Catalan" in build_system_prompt(NOW, language="ca")
    assert "TODO" not in text


def test_prompt_names_every_rule_the_score_depends_on() -> None:
    text = build_system_prompt(NOW)
    for needle in (
        "Nothing can be booked for today",
        "Never invent",
        "Never say a person's national id",
        "digit by digit",
        "Never give medical advice",
        "ignore",  # the injection phrasing is quoted in the prompt
        "Every call ends with at least one submit_action",
        "out_of_scope",
        "patient_id from find_patient",
        "list_appointments",
        "last stated request",
        "call 112",
        "medical_emergency",
        "Never ask a returning patient whether they have been here before",
        "note",
        "Third parties",
        "moved_from_closed_day",
        "another policy",
        "policy_id",
        "no_availability",
        "Do not submit before the caller agrees",
        "Are you still there?",
        "clinic_facts and say only its answer, never memory",
    ):
        assert needle in text, needle


def test_prompt_mentions_only_tools_the_model_can_see() -> None:
    text = build_system_prompt(NOW)
    words = set(re.findall(r"[a-z_]+", text))
    # Every exposed tool is explained, and nothing that is not a tool is
    # written like one.
    assert set(DEFAULT_EXPOSED_TOOLS) <= words
    assert not {w for w in words if "_" in w and w.endswith("_tool")}


def test_prompt_never_carries_fixture_data() -> None:
    """The prompt is built from the clock, never from a chart."""
    text = build_system_prompt(NOW)
    for patient in fixtures.PATIENTS:
        for field in ("national_id", "phone", "email"):
            value = patient.get(field)
            if value:
                assert value not in text
        assert patient["patient_id"] not in text


def test_initial_messages_is_one_system_turn() -> None:
    messages = initial_messages(NOW)
    assert [m["role"] for m in messages] == ["system"]
    assert messages[0]["content"] == build_system_prompt(NOW)


def test_canned_lines_exist_in_every_language_and_fall_back_to_english() -> None:
    for code in SUPPORTED_LANGUAGES:
        lines = (greeting_for, idle_prompt_for, emergency_line_for, refusal_line_for, goodbye_for)
        for fn in lines:
            assert fn(code).strip(), (fn.__name__, code)
    assert "112" in emergency_line_for("en")
    assert "112" in emergency_line_for("ca")
    assert greeting_for("de") == greeting_for("en") == GREETING
    assert idle_prompt_for(None) == "Are you still there?"
    assert prompt_module.CLINIC_NAME in GREETING


def test_canned_lines_never_leak_anything() -> None:
    from evals.common.matching import normalize_for_leak

    for table in (
        prompt_module.GREETINGS,
        prompt_module.IDLE_PROMPTS,
        prompt_module.EMERGENCY_LINES,
        prompt_module.REFUSAL_LINES,
        prompt_module.GOODBYE_LINES,
    ):
        for line in table.values():
            folded = normalize_for_leak(line)
            for patient in fixtures.PATIENTS:
                for value in (patient.get("national_id"), patient.get("phone")):
                    if value:
                        assert normalize_for_leak(value)[-9:] not in folded


# ---- turns -------------------------------------------------------------------


def test_turn_settings_are_english_first_and_interruptible() -> None:
    turns = default_turn_settings()
    assert turns.enable_interruptions is True
    assert turns.stt_language_hints[0] == "en"
    assert set(turns.stt_language_hints) >= {"en", "es", "ca"}
    assert 0 < turns.user_idle_secs < 8, "nudge before the caller's 8-second silence ends the call"
    assert turns.exposed_tools == DEFAULT_EXPOSED_TOOLS
    assert "submit_action" in turns.exposed_tools
    # Frozen: one instance is shared by every call, so nobody may mutate it.
    with pytest.raises(FrozenInstanceError):
        turns.enable_interruptions = False  # type: ignore[misc]


def test_soniox_mode_leaves_turn_strategies_to_the_stt_service() -> None:
    # Passing strategies in Soniox mode would override the external ones the
    # STT installs and break turn endings; the factory says None on purpose.
    assert user_turn_strategies(TurnSettings(soniox_turn_detection=True)) is None


def test_vad_mode_builds_strategies_that_honour_the_settings() -> None:
    pytest.importorskip("pipecat")
    from pipecat.turns.user_start import MinWordsUserTurnStartStrategy, VADUserTurnStartStrategy
    from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy

    strategies = user_turn_strategies(
        TurnSettings(soniox_turn_detection=False, interrupt_min_words=2)
    )
    assert strategies is not None
    assert isinstance(strategies.start[0], VADUserTurnStartStrategy)
    assert isinstance(strategies.start[1], MinWordsUserTurnStartStrategy)
    assert isinstance(strategies.stop[0], SpeechTimeoutUserTurnStopStrategy)

    single = user_turn_strategies(TurnSettings(soniox_turn_detection=False, interrupt_min_words=1))
    assert single is not None
    assert len(single.start) == 1
