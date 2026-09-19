"""Gemini Live demo wiring builds offline. Nothing dials Google.

Pins the constructor, tool schema shape and register_function options that
the jury demo path needs, without a GOOGLE_API_KEY and without a network.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from vortex import settings as settings_module
from vortex.contract import MADRID
from vortex.conversation.prompt import GREETING, build_system_prompt
from vortex.conversation.turns import default_turn_settings
from vortex.line import gemini_live_voice as gemini_mod


@pytest.fixture
def gemini_settings(monkeypatch: pytest.MonkeyPatch):
    """Settings with Gemini Live forced on and a throwaway API key."""

    def build(**env: str) -> settings_module.Settings:
        for key in (
            "GOOGLE_API_KEY",
            "GEMINI_LIVE_MODEL",
            "GEMINI_LIVE_VOICE",
            "VORTEX_VOICE_MODE",
            "SONIOX_API_KEY",
            "HELMCODE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_TTS_CREDENTIALS_JSON",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        settings_module.reset_settings()
        return settings_module.get_settings()

    yield build
    settings_module.reset_settings()


def _fake_session(settings: settings_module.Settings):
    """Minimal CallSession stand-in: build_gemini_live_service only needs call_tool."""

    class Session:
        def __init__(self) -> None:
            self.settings = settings
            self.calls: list[tuple[str, dict]] = []

        async def call_tool(self, name: str, arguments: dict) -> object:
            from vortex.contract import Rejection

            self.calls.append((name, arguments))
            return Rejection(reason="out_of_scope", message="offline test")

    return Session()


def test_gemini_live_modules_import() -> None:
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import LLMRunFrame  # noqa: F401
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

    assert GeminiLiveLLMService is not None


def test_tool_schemas_cover_exposed_tools() -> None:
    pytest.importorskip("pipecat")
    schemas = gemini_mod.tool_schemas_for(default_turn_settings().exposed_tools)
    names = {s.name for s in schemas}
    assert "find_patient" in names
    assert "submit_action" in names
    assert "prepare_booking" in names
    # Nested Slot / Action defs travel inside properties for Gemini.
    nested = next(s for s in schemas if s.name == "prepare_booking")
    assert "$defs" in nested.properties


def test_build_gemini_live_service_registers_vortex_tools(gemini_settings) -> None:
    """Constructor + register_function with a fake key. Never connects."""
    pytest.importorskip("pipecat")
    settings = gemini_settings(
        VORTEX_VOICE_MODE="gemini-live",
        GOOGLE_API_KEY="test-gemini-key-not-real",
    )
    session = _fake_session(settings)
    schemas = gemini_mod.tool_schemas_for(default_turn_settings().exposed_tools)
    llm = gemini_mod.build_gemini_live_service(
        api_key=settings.google_api_key,
        model=settings.gemini_live_model,
        voice=settings.gemini_live_voice,
        system_instruction=build_system_prompt(datetime.now(MADRID)),
        schemas=schemas,
        session=session,
    )
    assert settings.gemini_live_model == gemini_mod.DEFAULT_GEMINI_LIVE_MODEL
    assert settings.gemini_live_voice == gemini_mod.DEFAULT_GEMINI_LIVE_VOICE
    for schema in schemas:
        assert llm.has_function(schema.name)


def test_greeting_constant_is_what_the_kickoff_uses() -> None:
    """The Live kick-off quotes GREETING; keep that string non-empty."""
    assert GREETING
    assert "Clínica" in GREETING or "Arenal" in GREETING


def test_gemini_live_mode_is_opt_in_only(gemini_settings) -> None:
    """auto never selects gemini-live even when GOOGLE_API_KEY is set."""
    s = gemini_settings(GOOGLE_API_KEY="test-key")
    assert s.voice_is_gemini_live is False
    assert s.voice_label == "stub"

    s = gemini_settings(VORTEX_VOICE_MODE="gemini-live", GOOGLE_API_KEY="test-key")
    assert s.voice_is_gemini_live is True
    assert s.voice_is_pipecat is False
    assert s.voice_label == "gemini-live"
    assert s.describe()["voice"] == "gemini-live"
    assert s.describe()["has_google_api_key"] is True
    assert s.describe()["gemini_live_model"] == "models/gemini-3.8-live"


def test_gemini_live_model_and_voice_overrides(gemini_settings) -> None:
    s = gemini_settings(
        VORTEX_VOICE_MODE="gemini-live",
        GOOGLE_API_KEY="test-key",
        GEMINI_LIVE_MODEL="models/gemini-3.8-live-extended-thinking",
        GEMINI_LIVE_VOICE="Kore",
    )
    assert s.gemini_live_model == "models/gemini-3.8-live-extended-thinking"
    assert s.gemini_live_voice == "Kore"
    assert s.describe()["gemini_live_voice"] == "Kore"
