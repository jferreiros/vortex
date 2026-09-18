"""``vortex.models``: one resolver, and it says the same thing the runtime does."""

from __future__ import annotations

import pytest

from vortex import models
from vortex.settings import LLM_PRESETS, Settings, reset_settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """A clean LLM environment. Yields monkeypatch; settings are rebuilt on exit."""
    for var in (
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "ARBITER_PROVIDER",
        "ARBITER_MODEL",
        "ARBITER_BASE_URL",
        "ARBITER_API_KEY",
        "HELMCODE_API_KEY",
        "VERCEL_AI_GATEWAY_KEY",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "LLM_SUMMARY_PROVIDER",
        "LLM_SUMMARY_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_settings()
    yield monkeypatch
    reset_settings()


def test_resolve_reads_the_preset_and_its_key(env: pytest.MonkeyPatch) -> None:
    env.setenv("HELMCODE_API_KEY", "hk")
    spec = models.resolve("helmcode/qwen3.6", Settings())
    assert spec.id == "helmcode/qwen3.6"
    assert spec.base_url == "https://api.helmcode.com/v1"
    assert spec.api_key == "hk"
    assert spec.available
    assert spec.slug == "helmcode--qwen3.6"


def test_model_part_may_carry_slashes(env: pytest.MonkeyPatch) -> None:
    env.setenv("VERCEL_AI_GATEWAY_KEY", "vk")
    spec = models.resolve("vercel/anthropic/claude-haiku-4.5", Settings())
    assert spec.provider == "vercel" and spec.model == "anthropic/claude-haiku-4.5"
    assert spec.available


def test_bare_provider_takes_the_preset_default(env: pytest.MonkeyPatch) -> None:
    spec = models.resolve("helmcode", Settings())
    # Read the default off the preset. Naming the model here makes the test
    # fail every time someone picks a better one, which is not what it checks.
    assert spec.model == LLM_PRESETS["helmcode"].model
    assert not spec.available  # no key


def test_openai_is_its_own_provider(env: pytest.MonkeyPatch) -> None:
    env.setenv("OPENAI_API_KEY", "ok")
    spec = models.resolve("openai/gpt-4.1-mini", Settings())
    assert spec.base_url == "" and spec.api_key == "ok" and spec.available
    assert models.resolve("openai", Settings()).model == models.OPENAI_DEFAULT_MODEL


def test_openai_sends_no_reasoning_dialect(env: pytest.MonkeyPatch) -> None:
    """api.openai.com answers 400 to chat_template_kwargs and reasoning_effort."""
    env.setenv("OPENAI_API_KEY", "ok")
    kwargs = models.resolve("openai/gpt-4.1-mini", Settings()).request_kwargs()
    assert "reasoning_effort" not in kwargs and "extra_body" not in kwargs
    assert kwargs["max_tokens"] == Settings().llm_max_tokens


def test_unknown_provider_raises(env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        models.resolve("nowhere/model", Settings())


def test_request_kwargs_carry_the_runtime_settings(env: pytest.MonkeyPatch) -> None:
    env.setenv("HELMCODE_API_KEY", "hk")
    env.setenv("LLM_TEMPERATURE", "0.7")
    env.setenv("LLM_MAX_TOKENS", "64")
    kwargs = models.resolve("helmcode/qwen3.6", Settings()).request_kwargs()
    assert kwargs["model"] == "qwen3.6"
    assert kwargs["temperature"] == 0.7 and kwargs["max_tokens"] == 64
    assert kwargs["reasoning_effort"] == "none"
    assert kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_reasoning_switches_follow_settings(env: pytest.MonkeyPatch) -> None:
    env.setenv("LLM_DISABLE_THINKING", "false")
    env.setenv("LLM_REASONING_EFFORT", "")
    extras = models.request_extras(Settings())
    assert extras == {}


def test_route_receptionist_matches_what_pipecat_reads(env: pytest.MonkeyPatch) -> None:
    """The bench measures the receptionist through ``route``; pipecat builds its
    service from ``settings.llm_*``. They must never disagree."""
    env.setenv("LLM_PROVIDER", "helmcode")
    env.setenv("LLM_MODEL", "glm5.3-flash")
    env.setenv("HELMCODE_API_KEY", "hk")
    settings = Settings()
    spec = models.route("receptionist", settings)
    assert (spec.model, spec.base_url, spec.api_key) == (
        settings.llm_model,
        settings.llm_base_url,
        settings.llm_api_key,
    )
    assert spec.id == "helmcode/glm5.3-flash"
    from vortex.line.pipecat_voice import _llm_extra_body

    assert spec.extra == _llm_extra_body(settings)


def test_route_arbiter_has_its_own_block(env: pytest.MonkeyPatch) -> None:
    env.setenv("HELMCODE_API_KEY", "hk")
    env.setenv("ARBITER_MODEL", "deepseek-v4-flash")
    spec = models.route("arbiter", Settings())
    assert spec.id == "helmcode/deepseek-v4-flash"
    assert spec.available


def test_new_role_costs_two_variables(env: pytest.MonkeyPatch) -> None:
    env.setenv("HELMCODE_API_KEY", "hk")
    env.setenv("VERCEL_AI_GATEWAY_KEY", "vk")
    settings = Settings()
    # Unset: the receptionist.
    assert models.route("summary", settings).id == models.route("receptionist", settings).id
    # A model on the same provider.
    env.setenv("LLM_SUMMARY_MODEL", "gemma4")
    assert models.route("summary", Settings()).id == "helmcode/gemma4"
    # Another provider, with its default model.
    env.setenv("LLM_SUMMARY_PROVIDER", "vercel")
    env.delenv("LLM_SUMMARY_MODEL")
    spec = models.route("summary", Settings())
    assert spec.id == "vercel/anthropic/claude-haiku-4.5" and spec.available


def test_routing_table_never_leaks_the_key(env: pytest.MonkeyPatch) -> None:
    env.setenv("HELMCODE_API_KEY", "super-secret")
    table = models.routing_table(Settings())
    assert set(table) == {"receptionist", "arbiter"}
    assert "super-secret" not in repr(table)
    assert table["receptionist"]["has_key"] is True
