"""Langfuse tracing stays off without keys and never writes phone numbers or ids."""

from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from vortex.contract import FAKE_PATIENT, FindPatientResult, RegisterAction
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload
from vortex.observability import tracing
from vortex.settings import Settings, reset_settings

NOW = datetime(2026, 9, 19, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))


@pytest.fixture
def clean_langfuse(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_TRACING_ENVIRONMENT",
        "LANGFUSE_TRACING_ENABLED",
        "LANGFUSE_TRACING_IN_TESTS",
        "VORTEX_ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_settings()
    yield monkeypatch
    reset_settings()


def test_tracing_is_off_without_keys(clean_langfuse) -> None:
    assert tracing.enabled() is False
    assert Settings().describe()["has_langfuse_keys"] is False


def test_tracing_stays_off_under_pytest_even_with_keys(clean_langfuse) -> None:
    clean_langfuse.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    clean_langfuse.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    reset_settings()
    assert tracing.enabled() is False


def test_mask_phone_keeps_only_the_last_four() -> None:
    assert tracing.mask_phone("+34600111222") == "***1222"
    assert tracing.mask_phone(None) == "unknown"


def test_pseudonym_replaces_an_identifier_and_stays_stable() -> None:
    first = tracing.pseudonym("CA-trace")
    assert first == tracing.pseudonym("CA-trace")
    assert first != tracing.pseudonym("CA-other")
    assert "CA-trace" not in first
    assert tracing.pseudonym(None) == "unknown"


def test_redact_exports_approved_fields_and_nothing_else() -> None:
    payload = {
        "patient_id": "P00042",
        "national_id": "12345678Z",
        "given_name": "Ana",
        "email": "ana@example.com",
        "note": "call +34 600 111 222 about 12345678Z",
        "specialty_id": "dermatology",
        "duration_minutes": 15,
    }
    redacted = tracing.redact(payload)
    assert redacted["specialty_id"] == "dermatology"
    assert redacted["duration_minutes"] == 15
    assert redacted["patient_id"] == tracing.pseudonym("P00042")
    for key in ("national_id", "given_name", "email", "note"):
        assert redacted[key] == tracing.REDACTED


def test_redact_keeps_no_patient_record_out_of_a_tool_result() -> None:
    result = FindPatientResult(status="found", patient=FAKE_PATIENT).model_dump(mode="json")
    redacted = tracing.redact(result)
    assert redacted["status"] == "found"
    assert redacted["patient"]["patient_id"] == tracing.pseudonym(FAKE_PATIENT.patient_id)
    assert redacted["patient"]["insurer"] == "sanitas"
    exported = json.dumps(redacted, ensure_ascii=False)
    for leak in ("Marta", "Ruiz", "12345678Z", "marta.ruiz@example.com", "612345678", "1985-03-12"):
        assert leak not in exported


def test_redact_drops_free_text_and_registration_fields() -> None:
    args = {"complaint": "me duele el pecho desde ayer", "provider_name": "Dra. Ortiz"}
    assert tracing.redact(args) == {
        "complaint": tracing.REDACTED,
        "provider_name": tracing.REDACTED,
    }
    action = RegisterAction(
        given_name="Ana",
        first_surname="Gil",
        second_surname="Mora",
        national_id="12345678Z",
        date_of_birth=date(1990, 5, 4),
        phone="+34600111222",
        email="ana@example.com",
        insurer="sanitas",
    )
    redacted = tracing.redact(action)
    assert redacted == {
        "kind": "register",
        "given_name": tracing.REDACTED,
        "first_surname": tracing.REDACTED,
        "second_surname": tracing.REDACTED,
        "national_id": tracing.REDACTED,
        "date_of_birth": tracing.REDACTED,
        "phone": tracing.REDACTED,
        "email": tracing.REDACTED,
        "insurer": "sanitas",
    }


def test_call_input_exports_no_number_and_no_raw_call_id(clean_langfuse, tmp_path) -> None:
    start = StartPayload.model_validate(
        {
            "streamSid": "MZ-trace",
            "callSid": "CA-trace",
            "customParameters": {"from_number": "+34600111222", "problem_id": "p1"},
        }
    )
    session = CallSession.open(
        start, settings=Settings(calls_log_path=tmp_path / "calls.jsonl"), now=NOW
    )
    payload = tracing._call_input(session)
    assert payload["call_id"] == tracing.pseudonym("CA-trace")
    assert payload["from_number"] == tracing.pseudonym("+34600111222")
    assert payload["custom_parameters"]["problem_id"] == "p1"
    assert "600111222" not in json.dumps(payload)


def test_lookups_are_retrievers_and_writes_are_tools() -> None:
    assert tracing.tool_observation_type("find_patient") == "retriever"
    assert tracing.tool_observation_type("find_slots") == "retriever"
    assert tracing.tool_observation_type("submit_action") == "tool"
    assert tracing.tool_observation_type("prepare_booking") == "tool"
    assert tracing.tool_observation_name("find_patient") == "find-patient"


def test_trace_call_is_a_noop_without_keys(clean_langfuse, tmp_path) -> None:
    start = StartPayload.model_validate(
        {
            "streamSid": "MZ-trace",
            "callSid": "CA-trace",
            "customParameters": {"from_number": "+34600111222"},
        }
    )
    session = CallSession.open(
        start, settings=Settings(calls_log_path=tmp_path / "calls.jsonl"), now=NOW
    )
    with tracing.trace_call(session) as observation:
        assert observation is None
        session.end_reason = "pipeline_finished"
    assert session.call_id == "CA-trace"


def test_async_openai_client_is_plain_openai_when_off(clean_langfuse) -> None:
    from openai import AsyncOpenAI

    client = tracing.async_openai_client(api_key="x", base_url="https://example.invalid/v1")
    assert type(client) is AsyncOpenAI
