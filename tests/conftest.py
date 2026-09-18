"""Shared fixtures. Every test runs with no key and no network."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vortex import settings as settings_module


@pytest.fixture
def offline_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> settings_module.Settings:
    """Settings with every key blank and the call log in a temp dir."""
    for key in (
        "PLATFORM_API_KEY",
        "SONIOX_API_KEY",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "AZURE_SPEECH_KEY",
        "DEEPGRAM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VORTEX_VOICE_MODE", "stub")
    monkeypatch.setenv("VORTEX_CLINIC_MODE", "fake")
    monkeypatch.setenv("VORTEX_CALLS_LOG", str(tmp_path / "calls.jsonl"))
    settings_module.reset_settings()
    yield settings_module.get_settings()
    settings_module.reset_settings()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _unset_dotenv_keys() -> None:
    # A developer's .env must not leak into the tests.
    for key in (
        "PLATFORM_API_KEY",
        "SONIOX_API_KEY",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "AZURE_SPEECH_KEY",
        "DEEPGRAM_API_KEY",
    ):
        os.environ.pop(key, None)


_unset_dotenv_keys()
