"""The three stage interfaces and their results. Timings are milliseconds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class STTResult:
    text: str
    final_ms: float  # end of audio sent -> final transcript received
    audio_s: float  # seconds of audio billed
    supported: bool = True
    error: str | None = None


@dataclass
class TTSResult:
    pcm: bytes
    rate: int
    ttfb_ms: float  # request -> first audio byte
    total_ms: float
    chars: int
    supported: bool = True
    error: str | None = None


@dataclass
class LLMResult:
    text: str
    ttft_ms: float  # request -> first token
    total_ms: float
    tokens_in: int
    tokens_out: int
    error: str | None = None
    extra: dict = field(default_factory=dict)


class STTProvider(Protocol):
    key: str
    simulated: bool

    def supports(self, language: str) -> bool: ...

    async def transcribe(
        self, pcm: bytes, rate: int, language: str, *, hint: str = ""
    ) -> STTResult: ...


class TTSProvider(Protocol):
    key: str
    simulated: bool

    def supports(self, language: str) -> bool: ...

    async def synthesize(self, text: str, language: str) -> TTSResult: ...


class LLMProvider(Protocol):
    model: str
    simulated: bool

    async def reply(self, system: str, user: str) -> LLMResult: ...
