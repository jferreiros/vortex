"""One resolver for every model the agent or the evals talk to.

A ``ModelSpec`` is an OpenAI-compatible endpoint plus the request settings the
runtime sends: temperature, max tokens and the two "reasoning off" dialects.
``route(role)`` returns the spec the runtime uses for that role, built from the
same environment variables ``vortex/settings.py`` reads. An eval that goes
through ``route`` therefore measures exactly what the phone line runs.

Roles today:

    receptionist   the model on the call           LLM_PROVIDER / LLM_MODEL
    arbiter        the post-hangup judge           ARBITER_PROVIDER / ARBITER_MODEL
    <other>        LLM_<OTHER>_PROVIDER / LLM_<OTHER>_MODEL, else the receptionist

A spec is also addressable by id, ``provider/model``. That is the id the bench
prints and the one ``--models`` takes: ``helmcode/qwen3.6``,
``helmcode/deepseek-v4-flash``, ``azure/gpt-4.1``. The first slash
splits provider from model; the model part may carry more slashes.

``openai`` is the one provider that is not a settings preset. It reads
``OPENAI_API_KEY`` and talks to api.openai.com. It exists so the bench can put
a known reference model beside the hackathon endpoints.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from vortex.settings import LLM_PRESETS, Settings, get_settings

ROLE_RECEPTIONIST = "receptionist"
ROLE_ARBITER = "arbiter"
ROLES: tuple[str, ...] = (ROLE_RECEPTIONIST, ROLE_ARBITER)

OPENAI_PROVIDER = "openai"
OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"

PROVIDERS: tuple[str, ...] = (*LLM_PRESETS, OPENAI_PROVIDER)


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    base_url: str  # empty means the SDK default (api.openai.com)
    api_key: str
    temperature: float = 0.2
    max_tokens: int = 320
    # Request keyword arguments beyond the message list: ``reasoning_effort``,
    # ``extra_body``. Same shape pipecat spreads into ``chat.completions.create``.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.model}"

    @property
    def slug(self) -> str:
        """A file-system-safe name: ``helmcode--qwen3.6``."""
        return re.sub(r"[^A-Za-z0-9._-]+", "-", self.id.replace("/", "--"))

    @property
    def available(self) -> bool:
        """A key and an endpoint. ``openai`` needs only the key."""
        if self.provider == OPENAI_PROVIDER:
            return bool(self.api_key)
        return bool(self.api_key and self.base_url)

    def request_kwargs(self) -> dict[str, Any]:
        """Everything but ``messages`` and ``tools`` for ``chat.completions.create``."""
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **self.extra,
        }

    def client(self, timeout: float = 60.0, max_retries: int = 6) -> Any:
        """An ``AsyncOpenAI`` pointed at this endpoint. Imported lazily: the
        evals and the runtime both use it, the settings module must not.

        Six retries with the SDK's backoff: a bench saturates a tokens-per-
        minute limit within seconds, and a 429 is a wait, not a verdict.
        """
        from vortex.observability.tracing import async_openai_client

        return async_openai_client(
            api_key=self.api_key or "missing",
            base_url=self.base_url or None,
            timeout=timeout,
            max_retries=max_retries,
        )

    def describe(self) -> dict[str, Any]:
        """Safe for logs and reports: never the key."""
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "has_key": bool(self.api_key),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra": self.extra,
        }


def request_extras(settings: Settings | None = None) -> dict[str, Any]:
    """The reasoning-off dialects the runtime sends, from settings.

    Mirrors ``vortex.line.pipecat_voice._llm_extra_body``: ``extra_body`` with
    ``chat_template_kwargs`` (vLLM/SGLang) and ``reasoning_effort`` (Helmcode
    and other OpenAI-style hosts). Open-weight hosts ignore the one they do
    not know; api.openai.com rejects both, so the ``openai`` provider skips
    them (see :func:`resolve`).
    """
    settings = settings or get_settings()
    extra: dict[str, Any] = {}
    if settings.llm_disable_thinking:
        extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    if settings.llm_reasoning_effort:
        extra["reasoning_effort"] = settings.llm_reasoning_effort
    return extra


def split_id(spec_id: str) -> tuple[str, str]:
    """``provider/model`` -> (provider, model). A bare provider takes its default model."""
    spec_id = spec_id.strip()
    if "/" not in spec_id:
        return spec_id, ""
    provider, model = spec_id.split("/", 1)
    return provider, model


def resolve(spec_id: str, settings: Settings | None = None) -> ModelSpec:
    """The spec for an id, with the runtime's request settings.

    Unknown provider -> ``ValueError``. A missing key does not raise: the spec
    comes back with ``available == False`` so a bench can report it as skipped.
    """
    settings = settings or get_settings()
    provider, model = split_id(spec_id)
    if provider == OPENAI_PROVIDER:
        # api.openai.com rejects the reasoning-off dialects with a 400
        # ("Unrecognized request arguments"), and its chat models do not
        # reason unless asked, so the reference row sends none of them.
        return ModelSpec(
            provider=provider,
            model=model or OPENAI_DEFAULT_MODEL,
            base_url=os.environ.get("OPENAI_BASE_URL", "").strip(),
            api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            extra={},
        )
    if provider not in LLM_PRESETS:
        raise ValueError(f"unknown provider {provider!r}; known: {', '.join(PROVIDERS)}")
    if provider == "custom":
        base_url = settings.llm_base_url_env
    else:
        base_url = settings._preset_base_url(provider)
    return ModelSpec(
        provider=provider,
        model=model or LLM_PRESETS[provider].model,
        base_url=base_url,
        api_key=settings._preset_api_key(provider),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        extra=request_extras(settings),
    )


def _role_env(role: str, suffix: str) -> str:
    key = f"LLM_{re.sub(r'[^A-Za-z0-9]+', '_', role).upper()}_{suffix}"
    return os.environ.get(key, "").strip()


def route(role: str = ROLE_RECEPTIONIST, settings: Settings | None = None) -> ModelSpec:
    """The spec the runtime uses for ``role``.

    ``receptionist`` and ``arbiter`` read the settings blocks that already
    exist. Any other role reads ``LLM_<ROLE>_PROVIDER`` / ``LLM_<ROLE>_MODEL``
    and falls back to the receptionist, so a new role costs two variables and
    no code.
    """
    settings = settings or get_settings()
    extra = request_extras(settings)
    if role == ROLE_RECEPTIONIST:
        return ModelSpec(
            provider=settings.llm_provider,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            extra=extra,
        )
    if role == ROLE_ARBITER:
        return ModelSpec(
            provider=settings.arbiter_provider,
            model=settings.arbiter_model,
            base_url=settings.arbiter_base_url,
            api_key=settings.arbiter_api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            extra=extra,
        )
    base = route(ROLE_RECEPTIONIST, settings)
    provider = _role_env(role, "PROVIDER").lower() or base.provider
    model = _role_env(role, "MODEL")
    if not model and provider == base.provider:
        model = base.model
    return resolve(f"{provider}/{model}", settings)


def routing_table(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Every known role and the spec it resolves to. What the bench page shows
    as "current routing"."""
    settings = settings or get_settings()
    return {role: route(role, settings).describe() for role in ROLES}
