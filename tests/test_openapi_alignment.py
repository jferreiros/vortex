"""Our submit models against the platform's published schema.

Schema only: this reads ``docs/platform/openapi.json`` and touches no network.
It is the test that fails when the organisers rename a field, instead of the
first live call failing on it.

Regenerate the spec with the command in ``docs/platform/README.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vortex import contract
from vortex.clinic.client import APPOINTMENT_WINDOWS
from vortex.identity.tools import KNOWN_INSURERS

SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "platform" / "openapi.json"
SPEC: dict[str, Any] = json.loads(SPEC_PATH.read_text())
SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]

#: Our action model -> the request schema its route accepts.
ACTION_SCHEMAS: dict[str, tuple[type, str]] = {
    "book": (contract.BookAction, "BookRequest"),
    "register": (contract.RegisterAction, "RegisterRequest"),
    "reschedule": (contract.RescheduleAction, "RescheduleRequest"),
    "cancel": (contract.CancelAction, "CancelRequest"),
    "no-action": (contract.NoAction, "NoActionRequest"),
    "escalate": (contract.EscalateAction, "EscalateRequest"),
}

#: ``kind`` is ours, for the union discriminator; ``action_payload`` strips it.
#: ``call_id`` is the platform's, and ``action_payload`` adds it.
OURS_ONLY = {"kind"}
THEIRS_ONLY = {"call_id"}


def our_fields(model: type) -> set[str]:
    return set(model.model_fields) - OURS_ONLY


def spec_properties(schema: str) -> set[str]:
    return set(SCHEMAS[schema]["properties"])


def spec_required(schema: str) -> set[str]:
    return set(SCHEMAS[schema].get("required", []))


def enum_of(schema: str) -> set[str]:
    return set(SCHEMAS[schema]["enum"])


@pytest.mark.parametrize("kind", sorted(ACTION_SCHEMAS))
def test_no_field_the_route_does_not_accept(kind: str) -> None:
    model, schema = ACTION_SCHEMAS[kind]
    unknown = our_fields(model) - spec_properties(schema)
    assert not unknown, f"{model.__name__} sends {sorted(unknown)}, which {schema} does not accept"


@pytest.mark.parametrize("kind", sorted(ACTION_SCHEMAS))
def test_every_required_field_is_on_the_model(kind: str) -> None:
    model, schema = ACTION_SCHEMAS[kind]
    missing = spec_required(schema) - THEIRS_ONLY - our_fields(model)
    assert not missing, f"{schema} requires {sorted(missing)}, which {model.__name__} never sends"


@pytest.mark.parametrize("kind", sorted(ACTION_SCHEMAS))
def test_every_field_we_send_is_required_by_the_route(kind: str) -> None:
    """These requests have no optional fields: anything we treat as optional
    would be a 422 we could have caught here."""
    model, schema = ACTION_SCHEMAS[kind]
    optional = our_fields(model) - spec_required(schema)
    assert not optional, f"{sorted(optional)} is optional for us but required by {schema}"


def test_routes_exist_in_the_spec() -> None:
    for kind, route in contract.ACTION_ROUTES.items():
        assert route in SPEC["paths"], f"{route} is not a path the platform publishes"
        assert "post" in SPEC["paths"][route], f"{route} is not a POST"
        body = SPEC["paths"][route]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert body["$ref"].rsplit("/", 1)[-1] == ACTION_SCHEMAS[kind][1]


def test_decline_reasons_are_a_subset_of_the_platform_vocabulary() -> None:
    spec_reasons = enum_of("OutcomeReason")
    ours = set(contract.ALL_REASONS)
    assert not ours - spec_reasons, f"we would submit {sorted(ours - spec_reasons)}, a 422"
    # Not a subset check: a reason we cannot name is an outcome we cannot report.
    assert not spec_reasons - ours, f"the platform accepts {sorted(spec_reasons - ours)}, we do not"


def test_insurer_vocabulary_matches() -> None:
    spec_insurers = enum_of("Insurer")
    assert set(contract.INSURERS) == spec_insurers
    assert set(KNOWN_INSURERS) == spec_insurers


def test_the_key_goes_in_the_header_the_spec_names() -> None:
    scheme = SPEC["components"]["securitySchemes"]["TeamApiKey"]
    assert (scheme["type"], scheme["in"], scheme["name"]) == ("apiKey", "header", "X-Api-Key")


def test_submit_response_shape_we_map() -> None:
    """``SubmitClient`` reads the status code, and the log keeps the body; the
    body's own keys are asserted here so a rename shows up as a test."""
    assert spec_required("SubmitResponse") == {"call_id", "received_at", "record"}
    assert spec_required("SubmittedOutcome") == {"actions"}
    actions = SCHEMAS["SubmittedOutcome"]["properties"]["actions"]
    verbs = actions["items"]["discriminator"]["mapping"]
    assert set(verbs) == {"REGISTER", "BOOK", "RESCHEDULE", "CANCEL", "NO_ACTION", "ESCALATE"}
    assert set(verbs) == {k.replace("-", "_").upper() for k in contract.ACTION_ROUTES}


def test_read_route_query_parameters() -> None:
    """The names, and which of them the platform insists on."""

    def params(path: str) -> dict[str, bool]:
        declared = SPEC["paths"][path]["get"]["parameters"]
        return {p["name"]: p.get("required", False) for p in declared}

    assert params("/api/v1/directory") == {
        "name": False,
        "national_id": False,
        "phone": False,
        "date_of_birth": False,
    }
    assert params("/api/v1/availability") == {
        "date_from": True,
        "date_to": True,
        "provider_id": False,
        "specialty_id": False,
        "location_id": False,
        "patient_id": False,
        "insurer": False,
    }
    assert params("/api/v1/patients/{patient_id}/appointments") == {
        "patient_id": True,
        "when": False,
    }
    assert set(APPOINTMENT_WINDOWS) == enum_of("AppointmentWindow")


def test_slot_and_date_formats() -> None:
    """``slot`` is a date-time with an offset; the availability window is dates."""
    for schema in ("BookRequest", "RescheduleRequest"):
        assert SCHEMAS[schema]["properties"]["slot"]["format"] == "date-time"
    assert SCHEMAS["RegisterRequest"]["properties"]["date_of_birth"]["format"] == "date"
    declared = SPEC["paths"]["/api/v1/availability"]["get"]["parameters"]
    for name in ("date_from", "date_to"):
        param = next(p for p in declared if p["name"] == name)
        assert param["schema"]["format"] == "date"
