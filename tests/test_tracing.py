"""Langfuse tracing stays off without keys and exports only what the allowlist names."""

from __future__ import annotations

from contextlib import contextmanager
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


def _open_session(tmp_path) -> CallSession:
    start = StartPayload.model_validate(
        {
            "streamSid": "MZ-trace",
            "callSid": "CA-trace",
            "customParameters": {"from_number": "+34600111222"},
        }
    )
    return CallSession.open(
        start, settings=Settings(calls_log_path=tmp_path / "calls.jsonl"), now=NOW
    )


def test_trace_call_is_a_noop_without_keys(clean_langfuse, tmp_path) -> None:
    session = _open_session(tmp_path)
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


def test_the_exported_call_metadata_carries_no_raw_identifier(clean_langfuse, tmp_path) -> None:
    session = _open_session(tmp_path)
    metadata = tracing._call_metadata(session)
    assert metadata["call_id"] == tracing.pseudonym("CA-trace")
    assert metadata["stream_sid"] == tracing.pseudonym("MZ-trace")
    assert "CA-trace" not in metadata["call_id"]
    assert "MZ-trace" not in metadata["stream_sid"]


class _FakeObservation:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **fields) -> None:
        self.updates.append(fields)


class _FakeClient:
    def __init__(self, observation: _FakeObservation) -> None:
        self.observation = observation

    @contextmanager
    def start_as_current_observation(self, **_kwargs):
        yield self.observation


def test_a_failed_tool_records_the_error_type_and_not_its_text(clean_langfuse) -> None:
    observation = _FakeObservation()
    clean_langfuse.setattr(tracing, "_client", lambda: _FakeClient(observation))

    with pytest.raises(ValueError), tracing.observe_tool("find_patient", {}):
        raise ValueError("invalid input for find_patient: 12345678Z +34600111222")

    assert observation.updates == [{"output": {"error": "ValueError"}, "level": "ERROR"}]


class _BrokenObservation:
    def update(self, **_fields) -> None:
        raise RuntimeError("langfuse is down")


class _BrokenClient:
    def start_as_current_observation(self, **_kwargs):
        raise RuntimeError("langfuse is down")

    def flush(self) -> None:
        raise RuntimeError("langfuse is down")


class _UnflushableClient(_FakeClient):
    def flush(self) -> None:
        raise RuntimeError("langfuse is down")


def test_a_tracer_that_cannot_start_yields_no_observation(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", lambda: _BrokenClient())

    with tracing.observe_tool("submit_action", {}) as observation:
        assert observation is None
    with tracing.observe_span("submit-fallback", input={"branch": "silence"}) as span:
        assert span is None


def test_a_failed_update_never_reaches_the_tool_that_already_submitted(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", lambda: _FakeClient(_BrokenObservation()))

    with tracing.observe_tool("submit_action", {}) as observation:
        observation.update(output={"status": "accepted"})


def test_the_tool_error_still_propagates_when_the_tracer_is_broken(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", lambda: _FakeClient(_BrokenObservation()))

    with pytest.raises(ValueError), tracing.observe_tool("find_patient", {}):
        raise ValueError("invalid input for find_patient")


def test_trace_call_closes_the_call_when_the_update_and_flush_fail(
    clean_langfuse, tmp_path
) -> None:
    clean_langfuse.setattr(tracing, "_client", lambda: _UnflushableClient(_BrokenObservation()))
    session = _open_session(tmp_path)

    with tracing.trace_call(session):
        session.end_reason = "pipeline_finished"

    assert session.end_reason == "pipeline_finished"


def test_trace_call_keeps_the_crash_that_the_server_must_see(clean_langfuse, tmp_path) -> None:
    clean_langfuse.setattr(tracing, "_client", lambda: _BrokenClient())
    session = _open_session(tmp_path)

    with pytest.raises(RuntimeError, match="pipeline"), tracing.trace_call(session):
        raise RuntimeError("pipeline crashed")


def test_flush_is_quiet_when_langfuse_is_down(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", lambda: _BrokenClient())

    tracing.flush()


def test_async_openai_client_is_plain_openai_when_off(clean_langfuse) -> None:
    from openai import AsyncOpenAI

    client = tracing.async_openai_client(api_key="x", base_url="https://example.invalid/v1")
    assert type(client) is AsyncOpenAI


def test_async_openai_client_stays_uninstrumented_when_tracing_is_on(
    clean_langfuse, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openai import AsyncOpenAI

    monkeypatch.setattr(tracing, "enabled", lambda: True)
    client = tracing.async_openai_client(api_key="x", base_url="https://example.invalid/v1")
    assert type(client) is AsyncOpenAI
    assert client.chat.completions.create.__qualname__.startswith("content_free_create")


class _RecordingObservation:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class _RecordingLangfuseClient:
    def __init__(self) -> None:
        self.observations: list[dict] = []
        self.last: _RecordingObservation | None = None

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.observations.append(kwargs)
        self.last = _RecordingObservation()
        yield self.last


class _Usage:
    prompt_tokens = 700
    completion_tokens = 20
    total_tokens = 720


class _Response:
    usage = _Usage()


async def test_generation_records_metadata_but_never_prompts_or_completions(
    clean_langfuse, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RecordingLangfuseClient()
    monkeypatch.setattr(tracing, "_client", lambda: recorder)

    async def original(**kwargs):
        return _Response()

    create = tracing.content_free_create(original)
    response = await create(
        model="qwen3.6",
        messages=[{"role": "system", "content": "DNI 12345678Z, +34600111222"}],
        tools=[{"type": "function", "function": {"name": "find_patient"}}],
        temperature=0.2,
        stream=False,
    )

    assert response is not None
    observation = recorder.observations[0]
    assert observation["as_type"] == "generation"
    assert observation["name"] == "generate-response"
    assert observation["model"] == "qwen3.6"
    assert observation["model_parameters"] == {"temperature": 0.2, "stream": False}
    assert observation["metadata"] == {"message_count": 1, "tool_count": 1}
    assert "input" not in observation
    assert "output" not in observation
    assert recorder.last is not None
    assert recorder.last.updates == [{"usage_details": {"input": 700, "output": 20, "total": 720}}]


async def test_generation_marks_an_error_without_the_request_body(
    clean_langfuse, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RecordingLangfuseClient()
    monkeypatch.setattr(tracing, "_client", lambda: recorder)

    async def original(**kwargs):
        raise RuntimeError("provider said no")

    create = tracing.content_free_create(original)
    with pytest.raises(RuntimeError):
        await create(model="qwen3.6", messages=[{"role": "user", "content": "12345678Z"}])

    assert recorder.last is not None
    assert recorder.last.updates == [
        {"level": "ERROR", "status_message": "RuntimeError: provider said no"}
    ]


async def test_generation_is_skipped_when_tracing_is_off(clean_langfuse) -> None:
    seen: list[dict] = []

    async def original(**kwargs):
        seen.append(kwargs)
        return _Response()

    create = tracing.content_free_create(original)
    await create(model="qwen3.6", messages=[{"role": "user", "content": "hello"}])
    assert seen == [{"model": "qwen3.6", "messages": [{"role": "user", "content": "hello"}]}]
