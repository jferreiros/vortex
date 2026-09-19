"""Langfuse tracing stays off without keys and exports only what the allowlist names."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

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


def test_redact_masks_national_ids_and_phones() -> None:
    payload = {
        "national_id": "12345678Z",
        "phone": "+34600111222",
        "status": "call +34 600 111 222 about 12345678Z",
    }
    redacted = tracing.redact(payload)
    assert redacted["national_id"] == "***5678"
    assert redacted["phone"] == "***1222"
    assert "12345678Z" not in redacted["status"]
    assert "600 111 222" not in redacted["status"]


def test_redact_drops_every_field_the_allowlist_does_not_name() -> None:
    payload = {
        "given_name": "Ana",
        "first_surname": "Ruiz",
        "email": "ana@example.com",
        "address": "Calle Mayor 1, Madrid",
        "date_of_birth": "1990-01-01",
        "note": "recurring migraines since March",
        "complaint": "me duele el pecho",
    }
    redacted = tracing.redact(payload)
    assert set(redacted) == set(payload)
    assert set(redacted.values()) == {"[redacted]"}


def test_redact_keeps_the_shape_of_a_record_without_its_content() -> None:
    result = {
        "status": "found",
        "patient": {
            "patient_id": "P00042",
            "given_name": "Marta",
            "email": "marta@example.com",
            "insurer": "DKV",
            "has_visited_before": True,
        },
        "ask_for": "",
    }
    redacted = tracing.redact(result)
    assert redacted["status"] == "found"
    assert redacted["patient"]["insurer"] == "DKV"
    assert redacted["patient"]["has_visited_before"] is True
    assert redacted["patient"]["given_name"] == "[redacted]"
    assert redacted["patient"]["email"] == "[redacted]"
    assert redacted["patient"]["patient_id"].startswith("anon-")


def test_correlation_identifiers_become_stable_pseudonyms() -> None:
    first = tracing.redact({"call_id": "CA-1", "appointment_id": "A-7"})
    second = tracing.redact({"call_id": "CA-1", "appointment_id": "A-8"})
    assert first["call_id"] == second["call_id"]
    assert "CA-1" not in first["call_id"]
    assert first["appointment_id"] != second["appointment_id"]
    assert tracing.pseudonym("") == "unknown"


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


def test_the_exported_call_input_carries_no_raw_identifier(clean_langfuse, tmp_path) -> None:
    start = StartPayload.model_validate(
        {
            "streamSid": "MZ-trace",
            "callSid": "CA-trace",
            "customParameters": {"from_number": "+34600111222", "problem_id": "P3"},
        }
    )
    session = CallSession.open(
        start, settings=Settings(calls_log_path=tmp_path / "calls.jsonl"), now=NOW
    )
    exported = tracing._call_input(session)
    assert exported["call_id"] == tracing.pseudonym("CA-trace")
    assert "CA-trace" not in exported["call_id"]
    assert exported["from_number"] == "***1222"
    assert exported["custom_parameters"]["problem_id"] == "P3"
    assert exported["custom_parameters"]["from_number"] == "***1222"


def test_async_openai_client_is_plain_openai_when_off(clean_langfuse) -> None:
    from openai import AsyncOpenAI

    client = tracing.async_openai_client(api_key="x", base_url="https://example.invalid/v1")
    assert type(client) is AsyncOpenAI
