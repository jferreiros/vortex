"""Process-wide settings, read once from the environment.

Every value has a default that works with no key configured. When a key is
missing, the matching component runs in fake mode:

- no ``PLATFORM_API_KEY``  -> fake clinic data and a dry-run submit client
- no voice keys            -> the stub voice pipeline (beeps, no STT/LLM/TTS)

The voice pipeline is EU-first: Soniox for STT, any OpenAI-compatible endpoint
hosted in the EU for the LLM, and Azure Neural (or Deepgram Aura-2) for TTS.
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

    # --- STT: Soniox real-time ------------------------------------------------
    soniox_api_key: str = field(default_factory=lambda: _env("SONIOX_API_KEY"))
    soniox_stt_model: str = field(default_factory=lambda: _env("SONIOX_STT_MODEL", "stt-rt-v5"))

    # --- LLM: any OpenAI-compatible endpoint hosted in the EU -----------------
    # IONOS AI Model Hub, Nebius Token Factory, Groq EU ... all speak /v1/chat/completions.
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model: str = field(
        default_factory=lambda: _env("LLM_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")
    )
    llm_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2")))
    llm_max_tokens: int = field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "120")))
    # Qwen3 hybrid builds think by default; a phone call cannot wait for that.
    llm_disable_thinking: bool = field(
        default_factory=lambda: (
            _env("LLM_DISABLE_THINKING", "true").lower() not in ("0", "false", "no")
        )
    )

    # --- TTS: Azure Neural (default) or Deepgram Aura-2 -----------------------
    # VORTEX_TTS_PROVIDER: azure | deepgram
    tts_provider: str = field(default_factory=lambda: _env("VORTEX_TTS_PROVIDER", "azure").lower())
    azure_speech_key: str = field(default_factory=lambda: _env("AZURE_SPEECH_KEY"))
    azure_speech_region: str = field(
        default_factory=lambda: _env("AZURE_SPEECH_REGION", "westeurope")
    )
    azure_tts_voice_es: str = field(
        default_factory=lambda: _env("AZURE_TTS_VOICE_ES", "es-ES-ElviraNeural")
    )
    azure_tts_voice_ca: str = field(
        default_factory=lambda: _env("AZURE_TTS_VOICE_CA", "ca-ES-JoanaNeural")
    )
    deepgram_api_key: str = field(default_factory=lambda: _env("DEEPGRAM_API_KEY"))
    deepgram_tts_model: str = field(
        default_factory=lambda: _env("DEEPGRAM_TTS_MODEL", "aura-2-celeste-es")
    )
    deepgram_base_url: str = field(
        default_factory=lambda: _env("DEEPGRAM_BASE_URL", "https://api.eu.deepgram.com")
    )

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
    def tts_is_azure(self) -> bool:
        return self.tts_provider != "deepgram"

    @property
    def has_tts_key(self) -> bool:
        return bool(self.azure_speech_key if self.tts_is_azure else self.deepgram_api_key)

    @property
    def voice_is_pipecat(self) -> bool:
        if self.voice_mode == "pipecat":
            return True
        if self.voice_mode == "stub":
            return False
        return bool(
            self.soniox_api_key and self.llm_api_key and self.llm_base_url and self.has_tts_key
        )

    def describe(self) -> dict[str, object]:
        """A safe summary for logs and /health. Never includes key values."""
        return {
            "clinic": "live" if self.clinic_is_live else "fake",
            "voice": "pipecat" if self.voice_is_pipecat else "stub",
            "platform_api_base_url": self.platform_api_base_url,
            "has_platform_key": bool(self.platform_api_key),
            "has_soniox_key": bool(self.soniox_api_key),
            "has_llm_key": bool(self.llm_api_key),
            "has_azure_speech_key": bool(self.azure_speech_key),
            "has_deepgram_key": bool(self.deepgram_api_key),
            "stt_model": self.soniox_stt_model,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "tts_provider": "azure" if self.tts_is_azure else "deepgram",
            "tts_voice": self.azure_tts_voice_es if self.tts_is_azure else self.deepgram_tts_model,
            "azure_speech_region": self.azure_speech_region if self.tts_is_azure else "",
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
