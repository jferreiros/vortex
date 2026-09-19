"""Langfuse traces for inbound calls. Off when the keys are missing.

One trace per socket (one agent run). Concurrent Run All calls stay isolated
because each WebSocket handler is its own asyncio task and Langfuse uses
contextvars.

Only the fields on the allowlist below leave the process: clinic ids, enums,
counts, dates and times. Patient records, free text and audio never do, and the
identifiers we still need to follow a call travel as keyed pseudonyms.

Prompts and completions never leave the process. The model calls go through the
uninstrumented OpenAI client and each one is recorded by hand as a generation
carrying only metadata (model, parameters, message and tool counts, tokens,
latency, errors). Tool calls nest as ``tool`` or ``retriever`` observations.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

RETRIEVER_TOOLS = frozenset(
    {
        "find_patient",
        "list_appointments",
        "find_slots",
        "resolve_date",
        "nearest_site",
        "validate_national_id",
    }
)

REDACTED = "[redacted]"

#: The only field names whose value is exported. Everything else becomes
#: ``REDACTED``, so a field added to the contract later stays private until
#: somebody puts it here on purpose. Names, national ids, dates of birth,
#: phones, emails, addresses and every free-text field are absent by design:
#: nothing on this list describes a person.
_ALLOWED_KEYS = frozenset(
    {
        # What the call did: outcome, shape and counts.
        "action",
        "actions",
        "allowed",
        "appointment",
        "appointment_type",
        "appointments",
        "ask_digit_positions",
        "ask_for",
        "blocked",
        "branch",
        "candidates",
        "emergency",
        "kind",
        "level",
        "looked_up",
        "match_score",
        "matched_fields",
        "moved_from_closed_day",
        "patient",
        "payload",
        "provider",
        "providers",
        "reason",
        "rejection",
        "restriction",
        "restrictions",
        "result",
        "retrying",
        "route",
        "rule_id",
        "sites",
        "skipped",
        "skipped_checks",
        "slots",
        "status",
        "submitted",
        "tool",
        "tool_calls",
        "user_turns",
        "valid",
        "widened",
        # Ids of the clinic's own entities. None of them names a patient.
        "appointment_type_id",
        "appointment_type_ids",
        "case_id",
        "http_status",
        "insurer",
        "insurer_id",
        "insurer_ids",
        "insurer_ids_accepted",
        "insurer_ids_excluded",
        "insurer_ids_refused",
        "language",
        "languages",
        "location_id",
        "location_ids",
        "location_ids_excluded",
        "payable_with",
        "policy_id",
        "problem_id",
        "provider_id",
        "provider_ids",
        "provider_ids_refused",
        "specialty_id",
        "specialty_ids",
        "specialty_ids_excluded",
        # When, for how long, how many.
        "bookable_from",
        "bookable_to",
        "closes",
        "closure_days",
        "date_from",
        "date_to",
        "distance_km",
        "duration_minutes",
        "for_new_patients",
        "hours",
        "leave",
        "max_span_days",
        "new_patient_requirement",
        "on_leave_until",
        "open_days",
        "opens",
        "part_of_day",
        "patient_count",
        "schedules",
        "slot",
        "slot_minutes",
        "start",
        "time_from",
        "time_to",
        "weekday",
        "when",
        "widen_days",
    }
)

#: Identifiers a trace still has to correlate on. They leave as a keyed
#: pseudonym, never as themselves.
_PSEUDONYM_KEYS = frozenset(
    {
        "appointment_id",
        "call_id",
        "call_sid",
        "from_number",
        "patient_id",
        "stream_sid",
    }
)

#: Per process and never written down: a pseudonym can be followed across the
#: events of one run of the server and is a dead end anywhere else.
_PSEUDONYM_KEY = secrets.token_bytes(32)

GENERATION_NAME = "generate-response"
GENERATION_PARAMETER_KEYS = (
    "temperature",
    "max_tokens",
    "top_p",
    "stream",
    "reasoning_effort",
)

_DNI_RE = re.compile(r"\b\d{8}[A-Za-z]\b")
_NIE_RE = re.compile(r"\b[XYZxyz]\d{7}[A-Za-z]\b")
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{7,}\d")
_TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        and os.environ.get("LANGFUSE_TRACING_IN_TESTS", "").strip().lower() not in _TRUE
    ):
        return False
    if os.environ.get("LANGFUSE_TRACING_ENABLED", "true").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    from vortex.settings import get_settings

    settings = get_settings()
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def _sync_env() -> None:
    from vortex.settings import get_settings

    settings = get_settings()
    if settings.langfuse_public_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    if settings.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    if settings.langfuse_base_url:
        os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_base_url)
    if settings.langfuse_environment:
        os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", settings.langfuse_environment)
    os.environ.setdefault("OTEL_SERVICE_NAME", "vortex")


def _quiet(what: str, call: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run one Langfuse call. A trace we lose is never a call we lose."""
    try:
        return call(*args, **kwargs)
    except Exception:
        log.debug("langfuse %s failed", what, exc_info=True)
        return None


class _SafeObservation:
    """An observation whose ``update`` cannot break the code that traces itself.

    ``vortex.tools.call_tool`` updates the observation after the tool has already
    run, and ``submit_action`` reaches the platform inside that tool. An update
    that raised there would lose the submission the session must remember.
    """

    __slots__ = ("_observation",)

    def __init__(self, observation: Any) -> None:
        self._observation = observation

    def update(self, **fields: Any) -> None:
        _quiet("observation update", self._observation.update, **fields)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._observation, name)


@contextmanager
def _entered(manager: Any) -> Iterator[Any]:
    """Enter a Langfuse context manager. Yields ``None`` when it fails to start.

    Exceptions raised by the body are handed to ``__exit__`` and then re-raised:
    the application keeps its own errors, Langfuse never adds one.
    """
    if manager is None:
        yield None
        return
    try:
        value = manager.__enter__()
    except Exception:
        log.debug("langfuse context start failed", exc_info=True)
        yield None
        return
    try:
        yield value
    except BaseException:
        _quiet("context exit", manager.__exit__, *sys.exc_info())
        raise
    _quiet("context exit", manager.__exit__, None, None, None)


@contextmanager
def _observation(client: Any, **kwargs: Any) -> Iterator[Any]:
    manager = _quiet("observation start", client.start_as_current_observation, **kwargs)
    with _entered(manager) as observation:
        yield None if observation is None else _SafeObservation(observation)


def _client() -> Any | None:
    try:
        if not enabled():
            return None
        _sync_env()
        from langfuse import get_client

        return get_client()
    except Exception:
        log.debug("langfuse client unavailable", exc_info=True)
        return None


def mask_phone(value: str | None) -> str:
    if not value:
        return "unknown"
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def pseudonym(value: Any) -> str:
    """A stable, one-way name for an identifier, good for this run only."""
    text = str(value or "")
    if not text:
        return "unknown"
    digest = hmac.new(_PSEUDONYM_KEY, text.encode("utf-8"), hashlib.sha256)
    return f"px-{digest.hexdigest()[:16]}"


def _scrub(text: str) -> str:
    """Last line of defence on an approved value: mask an id or a phone in it."""
    masked = _DNI_RE.sub("********X", text)
    masked = _NIE_RE.sub("X*******X", masked)
    return _PHONE_RE.sub(lambda match: mask_phone(match.group(0)), masked)


def _approved_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, list):
        return [_approved_value(item) for item in value]
    if isinstance(value, str):
        return _scrub(value)
    if hasattr(value, "model_dump"):
        return redact(value.model_dump(mode="json"))
    return value


def _field(key: Any, value: Any) -> Any:
    name = str(key).lower()
    if name in _PSEUDONYM_KEYS:
        return pseudonym(value)
    if name in _ALLOWED_KEYS:
        return _approved_value(value)
    return REDACTED


def redact(value: Any) -> Any:
    """Keep the approved diagnostic fields, replace every other value.

    An allowlist, not a mask: a patient record reaching this function comes out
    as its pseudonymous id plus the clinic ids and enums around it, and a string
    that arrived under no key at all is free text, so it does not come out.
    """
    if isinstance(value, dict):
        return {key: _field(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return REDACTED
    if hasattr(value, "model_dump"):
        return redact(value.model_dump(mode="json"))
    return value


def tool_observation_type(name: str) -> str:
    return "retriever" if name in RETRIEVER_TOOLS else "tool"


def tool_observation_name(name: str) -> str:
    return name.replace("_", "-")


def _generation_model_parameters(create_kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: create_kwargs[key]
        for key in GENERATION_PARAMETER_KEYS
        if create_kwargs.get(key) is not None
    }


def _generation_metadata(create_kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_count": len(create_kwargs.get("messages") or []),
        "tool_count": len(create_kwargs.get("tools") or []),
    }


def _usage_details(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    counted = {
        "input": getattr(usage, "prompt_tokens", None),
        "output": getattr(usage, "completion_tokens", None),
        "total": getattr(usage, "total_tokens", None),
    }
    return {key: value for key, value in counted.items() if isinstance(value, int)}


def content_free_create(original: Any) -> Any:
    """``chat.completions.create`` wrapped in a generation that carries no content.

    The messages hold names, national ids, phone numbers, insurers and clinical
    reasons, and the completion repeats them, so neither is ever passed to
    Langfuse as ``input`` or ``output``. Only the shape of the request survives.
    """

    async def create(*args: Any, **create_kwargs: Any) -> Any:
        client = _client()
        if client is None:
            return await original(*args, **create_kwargs)
        with client.start_as_current_observation(
            as_type="generation",
            name=GENERATION_NAME,
            model=create_kwargs.get("model"),
            model_parameters=_generation_model_parameters(create_kwargs),
            metadata=_generation_metadata(create_kwargs),
        ) as generation:
            try:
                response = await original(*args, **create_kwargs)
            except Exception as exc:
                generation.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
                raise
            usage = _usage_details(response)
            if usage:
                generation.update(usage_details=usage)
            return response

    return create


def async_openai_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    organization: str | None = None,
    project: str | None = None,
    default_headers: Any = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "api_key": api_key or "missing",
        "base_url": base_url or None,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    if organization is not None:
        kwargs["organization"] = organization
    if project is not None:
        kwargs["project"] = project
    if default_headers is not None:
        kwargs["default_headers"] = default_headers
    from openai import AsyncOpenAI

    client = AsyncOpenAI(**kwargs)
    if enabled():
        client.chat.completions.create = content_free_create(  # type: ignore[method-assign]
            client.chat.completions.create
        )
    return client


def traced_openai_llm_service(service_cls: type, **kwargs: Any) -> Any:
    if not enabled():
        return service_cls(**kwargs)

    class TracedOpenAILLMService(service_cls):  # type: ignore[misc, valid-type]
        def create_client(
            self,
            api_key: Any = None,
            base_url: Any = None,
            organization: Any = None,
            project: Any = None,
            default_headers: Any = None,
            **_ignored: Any,
        ) -> Any:
            return async_openai_client(
                api_key=api_key,
                base_url=base_url,
                organization=organization,
                project=project,
                default_headers=default_headers,
            )

    return TracedOpenAILLMService(**kwargs)


def _problem_id(session: Any) -> str:
    params = getattr(session.start, "custom_parameters", {}) or {}
    for key in ("problem_id", "problemId", "case_id", "caseId"):
        value = params.get(key)
        if value:
            return str(value)
    return ""


def _call_input(session: Any) -> dict[str, Any]:
    return {
        "call_id": pseudonym(session.call_id),
        "from_number": pseudonym(session.start.from_number),
        "custom_parameters": redact(dict(session.start.custom_parameters or {})),
    }


def _call_output(session: Any) -> dict[str, Any]:
    submitted = []
    for result in session.submitted:
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
        submitted.append(redact(payload))
    return {
        "reason": getattr(session, "end_reason", ""),
        "submitted": submitted,
        "user_turns": session.ctx.log.user_turns,
        "tool_calls": session.ctx.log.tool_calls,
        "actions": redact(list(session.ctx.log.actions)),
    }


def _call_tags(session: Any) -> list[str]:
    tags = ["voice", session.settings.llm_provider]
    tags.append("pipecat" if session.settings.voice_is_pipecat else "stub")
    problem = _problem_id(session)
    if problem:
        tags.append(problem)
    return tags


def _call_metadata(session: Any) -> dict[str, Any]:
    return {
        "call_id": pseudonym(session.call_id),
        "stream_sid": pseudonym(session.stream_sid),
        "llm_provider": session.settings.llm_provider,
        "llm_model": session.settings.llm_model,
        "voice": "pipecat" if session.settings.voice_is_pipecat else "stub",
        "clinic": "live" if session.settings.clinic_is_live else "fake",
    }


def _propagation(session: Any, metadata: dict[str, Any]) -> Any:
    from langfuse import propagate_attributes

    return propagate_attributes(
        session_id=pseudonym(session.call_id),
        user_id=pseudonym(session.start.from_number),
        tags=_call_tags(session),
        metadata=metadata,
        environment=session.settings.langfuse_environment or None,
    )


def _flush(client: Any) -> None:
    client.flush()


def _record_call_output(observation: Any, session: Any) -> None:
    output = _call_output(session)
    update: dict[str, Any] = {"output": output}
    if output.get("reason") == "crashed":
        update["level"] = "ERROR"
    if observation is not None:
        observation.update(**update)


@contextmanager
def trace_call(session: Any) -> Iterator[Any]:
    client = _client()
    if client is None:
        yield None
        return
    metadata = _quiet("call metadata", _call_metadata, session) or {}
    with _observation(
        client,
        as_type="agent",
        name="handle-inbound-call",
        input=_quiet("call input", _call_input, session),
        metadata=metadata,
    ) as observation:
        with _entered(_quiet("propagate attributes", _propagation, session, metadata)):
            try:
                yield observation
            finally:
                _quiet("call output", _record_call_output, observation, session)
                _quiet("flush", _flush, client)


@contextmanager
def observe_tool(name: str, raw_args: dict[str, Any]) -> Iterator[Any]:
    client = _client()
    if client is None:
        yield None
        return
    with _observation(
        client,
        as_type=tool_observation_type(name),
        name=tool_observation_name(name),
        input=_quiet("redact input", redact, raw_args),
        metadata={"tool": name},
    ) as observation:
        try:
            yield observation
        except Exception as exc:
            if observation is not None:
                observation.update(
                    output={"error": type(exc).__name__},
                    level="ERROR",
                )
            raise


@contextmanager
def observe_span(
    name: str, *, input: Any = None, metadata: dict[str, Any] | None = None
) -> Iterator[Any]:
    client = _client()
    if client is None:
        yield None
        return
    with _observation(
        client,
        as_type="span",
        name=name,
        input=_quiet("redact input", redact, input) if input is not None else None,
        metadata=metadata or {},
    ) as observation:
        yield observation


def flush() -> None:
    client = _client()
    if client is not None:
        _quiet("flush", _flush, client)
