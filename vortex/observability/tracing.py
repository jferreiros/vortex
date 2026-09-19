"""Langfuse traces for inbound calls. Off when the keys are missing.

One trace per socket (one agent run). Concurrent Run All calls stay isolated
because each WebSocket handler is its own asyncio task and Langfuse uses
contextvars. Phone numbers and national ids are masked; audio is never sent.

Prompts and completions never leave the process. The model calls go through the
uninstrumented OpenAI client and each one is recorded by hand as a generation
carrying only metadata (model, parameters, message and tool counts, tokens,
latency, errors). Tool calls nest as ``tool`` or ``retriever`` observations.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

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

_PII_KEYS = frozenset(
    {
        "national_id",
        "dni",
        "nie",
        "from_number",
        "phone",
        "phone_number",
        "document",
    }
)
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


def _client() -> Any | None:
    if not enabled():
        return None
    _sync_env()
    from langfuse import get_client

    return get_client()


def mask_phone(value: str | None) -> str:
    if not value:
        return "unknown"
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: mask_phone(str(item)) if key.lower() in _PII_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        text = _DNI_RE.sub("********X", value)
        text = _NIE_RE.sub("X*******X", text)
        return _PHONE_RE.sub(lambda match: mask_phone(match.group(0)), text)
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
        "call_id": session.call_id,
        "from_number": mask_phone(session.start.from_number),
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


@contextmanager
def trace_call(session: Any) -> Iterator[Any]:
    client = _client()
    if client is None:
        yield None
        return
    from langfuse import propagate_attributes

    tags = ["voice", session.settings.llm_provider]
    tags.append("pipecat" if session.settings.voice_is_pipecat else "stub")
    problem = _problem_id(session)
    if problem:
        tags.append(problem)
    metadata = {
        "call_id": session.call_id,
        "stream_sid": session.stream_sid,
        "llm_provider": session.settings.llm_provider,
        "llm_model": session.settings.llm_model,
        "voice": "pipecat" if session.settings.voice_is_pipecat else "stub",
        "clinic": "live" if session.settings.clinic_is_live else "fake",
    }
    with client.start_as_current_observation(
        as_type="agent",
        name="handle-inbound-call",
        input=_call_input(session),
        metadata=metadata,
    ) as observation:
        with propagate_attributes(
            session_id=session.call_id,
            user_id=mask_phone(session.start.from_number),
            tags=tags,
            metadata=metadata,
            environment=session.settings.langfuse_environment or None,
        ):
            try:
                yield observation
            finally:
                output = _call_output(session)
                level = "ERROR" if output.get("reason") == "crashed" else None
                update: dict[str, Any] = {"output": output}
                if level:
                    update["level"] = level
                observation.update(**update)
                client.flush()


@contextmanager
def observe_tool(name: str, raw_args: dict[str, Any]) -> Iterator[Any]:
    client = _client()
    if client is None:
        yield None
        return
    with client.start_as_current_observation(
        as_type=tool_observation_type(name),
        name=tool_observation_name(name),
        input=redact(raw_args),
        metadata={"tool": name},
    ) as observation:
        try:
            yield observation
        except Exception as exc:
            observation.update(
                output={"error": f"{type(exc).__name__}: {exc}"},
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
    with client.start_as_current_observation(
        as_type="span",
        name=name,
        input=redact(input) if input is not None else None,
        metadata=metadata or {},
    ) as observation:
        yield observation


def flush() -> None:
    client = _client()
    if client is not None:
        client.flush()
