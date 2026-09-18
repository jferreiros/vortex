"""``call_tool`` takes the arguments a small model actually emits.

The contract has two nested inputs — ``prepare_booking.slot`` and the
``submit_action.action`` union — and qwen3.6 fills both with the right content
in the wrong type: a JSON *string* where the schema says object. Measured on
``scripts/rehearse_text.py``, a call that hits either one never recovers; the
model is told "validation error" and retries the identical shape until the
turns run out, so no BOOK is ever submitted.

These tests pin the coercion, and pin the things it must not touch: the rewrite
is driven by the *declared* field, so a name, a phrase or a national id stays a
string even when it looks like JSON, and a genuinely broken argument still
fails with its own error rather than being quietly swallowed.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from evals.common.context import make_context, submitted_actions
from vortex import tools as registry
from vortex.contract import MADRID, PrepareBookingInput, SubmitInput
from vortex.tools import ToolError, _parse_stringified

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)

SLOT = {
    "start": "2026-09-19T09:30:00+02:00",
    "provider_id": "PR01",
    "location_id": "centro",
    "appointment_type_id": "review",
}


class Listy(BaseModel):
    """A list-valued input. The contract has none today; the coercion is generic."""

    xs: list[str]


def test_a_stringified_object_is_parsed() -> None:
    args = _parse_stringified(
        PrepareBookingInput, {"patient_id": "P00042", "slot": json.dumps(SLOT)}
    )
    assert args["slot"] == SLOT
    assert args["patient_id"] == "P00042"


def test_a_stringified_union_member_is_parsed() -> None:
    """``submit_action.action`` is a union of six models, not one."""
    action = {"kind": "no-action", "reason": "out_of_scope"}
    assert _parse_stringified(SubmitInput, {"action": json.dumps(action)})["action"] == action


def test_a_stringified_list_is_parsed() -> None:
    assert _parse_stringified(Listy, {"xs": '["a", "b"]'})["xs"] == ["a", "b"]


def test_an_object_that_was_already_an_object_is_untouched() -> None:
    assert _parse_stringified(PrepareBookingInput, {"slot": SLOT})["slot"] == SLOT


@pytest.mark.parametrize(
    "value",
    [
        "Marta Ruiz López",  # a name
        "12345678Z",  # a national id
        "next Thursday",  # a date phrase
        "",  # nothing said
        '{"start": "2026-09-19T09:30:00+02:00"}',  # valid JSON, but a str field
    ],
)
def test_a_string_field_is_left_alone(value: str) -> None:
    """The field is declared ``str``, so nothing about the value can change it."""
    assert _parse_stringified(PrepareBookingInput, {"patient_id": value})["patient_id"] == value


@pytest.mark.parametrize("value", ["{not json at all", "[1, 2", "review", "42"])
def test_a_nested_field_that_is_not_json_of_that_shape_is_left_alone(value: str) -> None:
    """Never raise here: pydantic below produces the real validation error."""
    assert _parse_stringified(PrepareBookingInput, {"slot": value})["slot"] == value


def test_an_argument_the_model_does_not_declare_is_left_alone() -> None:
    assert _parse_stringified(PrepareBookingInput, {"nope": "{}"})["nope"] == "{}"


async def test_prepare_booking_accepts_a_stringified_slot(tmp_path: Path) -> None:
    ctx = make_context(call_id="args-book", now=NOW.isoformat(), log_dir=tmp_path)
    found = await registry.call_tool(
        "find_patient", ctx, {"name": "Marta Ruiz López", "date_of_birth": "1985-03-12"}
    )
    assert found.patient is not None
    slots = await registry.call_tool(
        "find_slots",
        ctx,
        {
            "patient_id": found.patient.patient_id,
            "specialty_id": "general_practice",
            "date_from": "2026-09-19",
            "date_to": "2026-10-02",
            "insurer": "sanitas",
        },
    )
    assert slots.slots, "the fake clinic should have general practice slots"
    slot = slots.slots[0].model_dump(mode="json")

    # Exactly what the model sends: the slot as a string.
    result = await registry.call_tool(
        "prepare_booking",
        ctx,
        {
            "patient_id": found.patient.patient_id,
            "slot": json.dumps(slot, default=str),
            "policy_id": "sanitas",
        },
    )
    assert result.rejection is None, result.rejection
    assert result.action is not None
    assert result.action.provider_id == slot["provider_id"]
    assert result.action.appointment_type_id == slot["appointment_type_id"]


async def test_submit_action_accepts_a_stringified_action(tmp_path: Path) -> None:
    ctx = make_context(call_id="args-submit", now=NOW.isoformat(), log_dir=tmp_path)
    action = {"kind": "no-action", "reason": "out_of_scope"}
    result = await registry.call_tool("submit_action", ctx, {"action": json.dumps(action)})
    assert result.status == "dry_run"
    assert submitted_actions(ctx) == [{"kind": "no-action", "reason": "out_of_scope"}]


async def test_a_genuinely_bad_argument_still_fails(tmp_path: Path) -> None:
    """The coercion must not turn a real error into a silent pass."""
    ctx = make_context(call_id="args-bad", now=NOW.isoformat(), log_dir=tmp_path)
    with pytest.raises(ToolError):
        await registry.call_tool("prepare_booking", ctx, {"patient_id": "P00042"})
    with pytest.raises(ToolError):
        await registry.call_tool("submit_action", ctx, {"action": '{"kind": "not-a-verb"}'})
