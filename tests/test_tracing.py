"""Langfuse tracing stays off without keys and never writes phone numbers or ids.

It also fails open: a broken SDK never stops a call from reaching its submission.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from evals.common.context import make_context, submitted_actions
from vortex.line.session import CallSession
from vortex.line.twilio import StartPayload
from vortex.observability import tracing
from vortex.settings import Settings, reset_settings
from vortex.tools import call_tool

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
        "name": "Ana",
        "note": "call +34 600 111 222 about 12345678Z",
    }
    redacted = tracing.redact(payload)
    assert redacted["national_id"] == "***5678"
    assert redacted["name"] == "Ana"
    assert "12345678Z" not in redacted["note"]
    assert "600 111 222" not in redacted["note"]


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


class _FailingObservation:
    """An observation whose every write hits a dead exporter."""

    def update(self, **_fields: object) -> None:
        raise RuntimeError("langfuse update failed")


class _Manager:
    def __init__(self, observation: object) -> None:
        self.observation = observation

    def __enter__(self) -> object:
        return self.observation

    def __exit__(self, *_exc: object) -> bool:
        return False


class _DeadClient:
    """Langfuse is down: it cannot even open an observation."""

    def start_as_current_observation(self, **_kwargs: object) -> object:
        raise RuntimeError("langfuse start failed")

    def flush(self) -> None:
        raise RuntimeError("langfuse flush failed")


class _WriteFailsClient:
    """Observations open, but every update and the flush fail."""

    def __init__(self) -> None:
        self.observation = _FailingObservation()
        self.flushes = 0

    def start_as_current_observation(self, **_kwargs: object) -> object:
        return _Manager(self.observation)

    def flush(self) -> None:
        self.flushes += 1
        raise RuntimeError("langfuse flush failed")


def test_observe_tool_runs_the_body_when_the_sdk_cannot_start(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", _DeadClient)
    ran = False
    with tracing.observe_tool("find_patient", {"name": "Ana"}) as observation:
        assert observation is None
        ran = True
    assert ran is True


def test_observe_tool_re_raises_the_body_error_not_the_sdk_error(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", _WriteFailsClient)
    with pytest.raises(ValueError, match="tool blew up"):
        with tracing.observe_tool("submit_action", {"action": {}}):
            raise ValueError("tool blew up")


def test_observe_span_runs_the_body_when_the_sdk_cannot_start(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", _DeadClient)
    with tracing.observe_span("submit-fallback", input={"branch": "no_action"}) as span:
        assert span is None
        tracing.update_observation(span, output={"skipped": False})


def test_update_observation_swallows_a_failing_write(clean_langfuse) -> None:
    tracing.update_observation(None, output={"any": "thing"})
    tracing.update_observation(_FailingObservation(), output={"any": "thing"})


def test_flush_survives_a_broken_client(clean_langfuse) -> None:
    clean_langfuse.setattr(tracing, "_client", _DeadClient)
    tracing.flush()


def test_trace_call_keeps_the_body_when_update_and_flush_fail(clean_langfuse, tmp_path) -> None:
    client = _WriteFailsClient()
    clean_langfuse.setattr(tracing, "_client", lambda: client)
    start = StartPayload.model_validate(
        {
            "streamSid": "MZ-fail-open",
            "callSid": "CA-fail-open",
            "customParameters": {"from_number": "+34600111222"},
        }
    )
    session = CallSession.open(
        start, settings=Settings(calls_log_path=tmp_path / "calls.jsonl"), now=NOW
    )
    with tracing.trace_call(session) as observation:
        assert observation is client.observation
        session.end_reason = "pipeline_finished"
    assert client.flushes == 1


async def test_call_tool_returns_its_result_when_the_observation_write_fails(
    clean_langfuse, tmp_path
) -> None:
    """A write that fails after a submit must not hide the result from the session.

    The session records what came back; a swallowed result would leave it looking
    unsubmitted and let the fallback POST a second action.
    """
    clean_langfuse.setattr(tracing, "_client", _WriteFailsClient)
    ctx = make_context(call_id="trace-write-fails", now=NOW.isoformat(), log_dir=tmp_path)
    action = {"kind": "no-action", "reason": "out_of_scope"}
    result = await call_tool("submit_action", ctx, {"action": action})
    assert result.status == "dry_run"
    assert submitted_actions(ctx) == [action]
