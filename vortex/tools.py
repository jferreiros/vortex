"""Tool registry: binds each frozen signature to the lane that implements it.

``vortex/contract.py`` says what a tool receives and returns. This file says
which function answers to which name, and turns the registry into:

- LLM function schemas (``function_schemas()``), for the voice pipeline.
- A single dispatcher (``call_tool()``), which validates input, runs the lane's
  function, validates output, and logs both to the call log.

Lanes never edit this file to change behaviour; they edit ``vortex/<lane>/tools.py``.
Only add a row here when the contract grows a new tool.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from vortex import contract
from vortex.contract import ToolContext
from vortex.diary import tools as diary
from vortex.identity import tools as identity
from vortex.line import submit as line_submit
from vortex.observability.tracing import observe_tool, redact
from vortex.rules import tools as rules

ToolFn = Callable[[ToolContext, Any], Awaitable[BaseModel]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    lane: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    fn: ToolFn


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        # ---- identity ---------------------------------------------------
        ToolSpec(
            "find_patient",
            "identity",
            "Look the caller (or the patient they call for) up in the clinic directory. "
            "Pass only what was said. Returns found, ambiguous (with the field to ask "
            "for next) or not_found.",
            contract.FindPatientInput,
            contract.FindPatientResult,
            identity.find_patient,
        ),
        ToolSpec(
            "validate_national_id",
            "identity",
            "Normalise a spoken DNI/NIE and check its control letter.",
            contract.ValidateNationalIdInput,
            contract.NationalIdCheck,
            identity.validate_national_id,
        ),
        ToolSpec(
            "build_registration",
            "identity",
            "Prepare the registration of a caller the directory does not know. "
            "Nothing is booked for a new patient.",
            contract.BuildRegistrationInput,
            contract.RegistrationResult,
            identity.build_registration,
        ),
        # ---- diary ------------------------------------------------------
        ToolSpec(
            "resolve_date",
            "diary",
            "Turn a phrase like 'next Thursday' or 'in a fortnight' into a date window, "
            "relative to the moment the call connected, in Europe/Madrid.",
            contract.ResolveDateInput,
            contract.ResolvedWindow,
            diary.resolve_date,
        ),
        ToolSpec(
            "find_slots",
            "diary",
            "Real availability for a specialty or provider in a date window. Returns "
            "slots, blocked providers with the rule that blocked them, and the one "
            "appointment type that fits the patient.",
            contract.FindSlotsInput,
            contract.AvailabilityResult,
            diary.find_slots,
        ),
        ToolSpec(
            "list_appointments",
            "diary",
            "The patient's upcoming or past appointments. The only source of an appointment_id.",
            contract.ListAppointmentsInput,
            contract.AppointmentList,
            diary.list_appointments,
        ),
        ToolSpec(
            "prepare_booking",
            "diary",
            "Build the booking action for a chosen slot. Call submit_action afterwards.",
            contract.PrepareBookingInput,
            contract.BookingResult,
            diary.prepare_booking,
        ),
        ToolSpec(
            "prepare_reschedule",
            "diary",
            "Build the reschedule action for an existing appointment and a new slot.",
            contract.PrepareRescheduleInput,
            contract.RescheduleResult,
            diary.prepare_reschedule,
        ),
        ToolSpec(
            "prepare_cancel",
            "diary",
            "Build the cancel action for an existing upcoming appointment.",
            contract.PrepareCancelInput,
            contract.CancelResult,
            diary.prepare_cancel,
        ),
        # ---- rules ------------------------------------------------------
        ToolSpec(
            "check_eligibility",
            "rules",
            "Check age, referral and insurance rules before offering a slot. Returns "
            "allowed, or the rule that forbids it and any provider to redirect to.",
            contract.CheckEligibilityInput,
            contract.EligibilityVerdict,
            rules.check_eligibility,
        ),
        ToolSpec(
            "triage",
            "rules",
            "Route a symptom to a specialty, or flag a medical emergency.",
            contract.TriageInput,
            contract.TriageResult,
            rules.triage,
        ),
        ToolSpec(
            "nearest_location",
            "rules",
            "The closest clinic site to a street address that can serve the specialty.",
            contract.NearestLocationInput,
            contract.NearestLocationResult,
            rules.nearest_location,
        ),
        ToolSpec(
            "find_provider",
            "rules",
            "Match a spoken doctor name to a provider. Reports ambiguity, leave, or not found.",
            contract.FindProviderInput,
            contract.ProviderMatch,
            rules.find_provider,
        ),
        ToolSpec(
            "clinic_facts",
            "rules",
            "Answer a question about the clinic from its catalogue: which sites open on a "
            "day, who consults at a site, whether there is a site in a town. Never answer "
            "these from memory; the caller books on what you say.",
            contract.ClinicFactsInput,
            contract.ClinicFacts,
            rules.clinic_facts,
        ),
        # ---- line -------------------------------------------------------
        ToolSpec(
            "submit_action",
            "line",
            "Send one prepared action to the platform. Call it once per thing done: "
            "one booking, one cancellation, one registration, one refusal.",
            contract.SubmitInput,
            contract.SubmitResult,
            line_submit.submit_action,
        ),
    )
}


class ToolError(Exception):
    """Raised when a tool name is unknown or its input does not validate."""


def _json_shapes(annotation: Any) -> frozenset[type]:
    """Which JSON container shapes — ``dict``, ``list`` — this annotation accepts.

    Unions are walked, so ``Action`` (six models) reports ``{dict}``; so does a
    nested model, a ``dict[...]`` and an optional one. Everything else — ``str``,
    ints, enums, literals — reports nothing and is never rewritten.
    """
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return frozenset[type]().union(*(_json_shapes(arg) for arg in get_args(annotation)))
    if origin is not None:
        annotation = origin
    if not isinstance(annotation, type) or issubclass(annotation, (str, bytes)):
        return frozenset()
    if issubclass(annotation, (BaseModel, Mapping)):
        return frozenset({dict})
    if issubclass(annotation, (list, tuple, set, frozenset)):
        return frozenset({list})
    return frozenset()


def _parse_stringified(model: type[BaseModel], raw_args: dict[str, Any]) -> dict[str, Any]:
    """Parse a nested argument the model sent as a JSON *string*.

    Small tool-calling models fill a nested schema with the right content in the
    wrong type. qwen3.6 does it on both nested inputs in the contract —
    ``prepare_booking.slot`` (a ``Slot``) and the ``submit_action.action``
    union::

        {"patient_id": "P00042", "slot": "{\\"start\\": \\"2026-09-19T09:30...\\"}"}

    Pydantic rejects that, the model is told "validation error", and it retries
    the identical shape until the call runs out of turns — measured on a text
    rehearsal, it never submits a BOOK at all. Since the flat calls succeed, the
    failure looks like a prompt problem and is not one.

    A value is rewritten only when the declared field is a model, mapping or
    sequence *and* the string parses as JSON of that same shape, so a name, a
    national id or a date phrase is never touched — nor is a string field that
    happens to hold JSON. Anything that does not parse is passed through for the
    validation below to reject with its real error.
    """
    out = dict(raw_args)
    for name, value in raw_args.items():
        field = model.model_fields.get(name)
        if not isinstance(value, str) or field is None:
            continue
        shapes = _json_shapes(field.annotation)
        if not shapes:
            continue
        try:
            parsed = json.loads(value)
        except ValueError:  # covers JSONDecodeError; never raise on a plain string
            continue
        if type(parsed) in shapes:
            out[name] = parsed
    return out


async def call_tool(name: str, ctx: ToolContext, raw_args: dict[str, Any]) -> BaseModel:
    """Validate, run, validate, log. The one path every tool call goes through."""
    with observe_tool(name, raw_args) as observation:
        result = await _run_tool(name, ctx, raw_args)
        if observation is not None:
            observation.update(output=redact(result.model_dump(mode="json")))
        return result


async def _run_tool(name: str, ctx: ToolContext, raw_args: dict[str, Any]) -> BaseModel:
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError(f"unknown tool: {name}")
    try:
        args = spec.input_model.model_validate(_parse_stringified(spec.input_model, raw_args))
    except ValidationError as exc:
        ctx.log.tool_failed(name, f"invalid input: {exc.errors()}")
        raise ToolError(f"invalid input for {name}: {exc}") from exc

    ctx.log.tool_called(name, args)
    started = time.monotonic()
    try:
        result = await spec.fn(ctx, args)
    except Exception as exc:
        ctx.log.tool_failed(name, f"{type(exc).__name__}: {exc}")
        raise
    if not isinstance(result, spec.output_model):
        result = spec.output_model.model_validate(result)
    ctx.log.tool_returned(name, result, (time.monotonic() - started) * 1000)

    if name == "prepare_booking" and isinstance(result, contract.BookingResult) and result.action:
        identity.note_target_patient(ctx, result.action.patient_id)
    elif name == "prepare_cancel" and isinstance(result, contract.CancelResult) and result.action:
        identity.note_target_patient(ctx, args.patient_id)

    return result


def function_schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    """OpenAI-style function definitions built from the input models.

    ``names`` restricts the set (the conversation lane decides what the model sees).
    """
    out = []
    for spec in TOOLS.values():
        if names is not None and spec.name not in names:
            continue
        schema = spec.input_model.model_json_schema()
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                    "$defs": schema.get("$defs", {}),
                },
            }
        )
    return out
