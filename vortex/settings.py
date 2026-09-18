"""Process-wide settings, read once from the environment.

Every value has a default that works with no key configured. When a key is
missing, the matching component runs in fake mode:

- no ``PLATFORM_API_KEY``  -> fake clinic data and a dry-run submit client
- no voice keys            -> the stub voice pipeline (beeps, no STT/LLM/TTS)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # Platform (the organisers' API: clinic reads + submit routes)
    platform_api_key: str = field(default_factory=lambda: _env("PLATFORM_API_KEY"))
    platform_api_base_url: str = field(
        default_factory=lambda: _env("PLATFORM_API_BASE_URL", "http://localhost:9999")
    )

    # Voice pipeline providers
    deepgram_api_key: str = field(default_factory=lambda: _env("DEEPGRAM_API_KEY"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_llm_model: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", "gpt-4.1"))
    openai_tts_model: str = field(
        default_factory=lambda: _env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    )
    openai_tts_voice: str = field(default_factory=lambda: _env("OPENAI_TTS_VOICE", "coral"))
    deepgram_stt_model: str = field(default_factory=lambda: _env("DEEPGRAM_STT_MODEL", "nova-3"))

    # Server
    host: str = field(default_factory=lambda: _env("VORTEX_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("VORTEX_PORT", "7860")))
    ws_path: str = field(default_factory=lambda: _env("VORTEX_WS_PATH", "/ws"))

    # Forced modes. "auto" derives the mode from the keys above.
    # VORTEX_VOICE_MODE: auto | stub | pipecat
    voice_mode: str = field(default_factory=lambda: _env("VORTEX_VOICE_MODE", "auto"))
    # VORTEX_CLINIC_MODE: auto | fake | live
    clinic_mode: str = field(default_factory=lambda: _env("VORTEX_CLINIC_MODE", "auto"))

    # Observability
    calls_log_path: Path = field(
        default_factory=lambda: Path(_env("VORTEX_CALLS_LOG", str(REPO_ROOT / "logs/calls.jsonl")))
    )

    # Submission window: the platform closes it 30 s after the socket closes.
    # We keep a margin so a late retry still lands inside it.
    submit_window_secs: float = 30.0
    submit_deadline_margin_secs: float = 5.0

    @property
    def clinic_is_live(self) -> bool:
        if self.clinic_mode == "live":
            return True
        if self.clinic_mode == "fake":
            return False
        return bool(self.platform_api_key)

    @property
    def voice_is_pipecat(self) -> bool:
        if self.voice_mode == "pipecat":
            return True
        if self.voice_mode == "stub":
            return False
        return bool(self.deepgram_api_key and self.openai_api_key)

    def describe(self) -> dict[str, object]:
        """A safe summary for logs and /health. Never includes key values."""
        return {
            "clinic": "live" if self.clinic_is_live else "fake",
            "voice": "pipecat" if self.voice_is_pipecat else "stub",
            "platform_api_base_url": self.platform_api_base_url,
            "has_platform_key": bool(self.platform_api_key),
            "has_deepgram_key": bool(self.deepgram_api_key),
            "has_openai_key": bool(self.openai_api_key),
            "ws_path": self.ws_path,
            "calls_log_path": str(self.calls_log_path),
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings. Tests call this after they change the environment."""
    global _settings
    _settings = None
