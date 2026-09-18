"""Cartesia: Ink-Whisper STT and Sonic TTS over HTTPS.

UNTESTED against the real service: written from the public API reference on
2026-09-18 with no key at hand. Confirm ``Cartesia-Version`` and the voice id
before spending; start with one utterance and ``--max-eur 0.05``.
"""

from __future__ import annotations

import os
import time

import httpx

from evals.voice.audio import pcm_to_wav
from evals.voice.providers.base import STTResult, TTSResult

_VERSION = os.environ.get("CARTESIA_VERSION", "2025-04-16")
_STT_LANGS = {"es", "ca", "gl", "eu"}
_TTS_LANGS = {"es"}


def _key() -> str:
    key = os.environ.get("CARTESIA_API_KEY", "")
    if not key:
        raise RuntimeError("CARTESIA_API_KEY is not set")
    return key


class CartesiaSTT:
    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.model = os.environ.get("CARTESIA_STT_MODEL", "ink-whisper")

    def supports(self, language: str) -> bool:
        return language in _STT_LANGS

    async def transcribe(
        self, pcm: bytes, rate: int, language: str, *, hint: str = ""
    ) -> STTResult:
        audio_s = len(pcm) / 2 / rate
        if not self.supports(language):
            return STTResult(text="", final_ms=0.0, audio_s=audio_s, supported=False)
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                r = await http.post(
                    "https://api.cartesia.ai/stt",
                    headers={"X-API-Key": _key(), "Cartesia-Version": _VERSION},
                    data={"model": self.model, "language": language},
                    files={"file": ("utterance.wav", pcm_to_wav(pcm, rate), "audio/wav")},
                )
            elapsed = (time.monotonic() - started) * 1000
            if r.status_code != 200:
                return STTResult(
                    text="",
                    final_ms=elapsed,
                    audio_s=audio_s,
                    error=f"{r.status_code}: {r.text[:200]}",
                )
            return STTResult(text=r.json().get("text", ""), final_ms=elapsed, audio_s=audio_s)
        except (httpx.HTTPError, ValueError) as exc:
            return STTResult(
                text="",
                final_ms=(time.monotonic() - started) * 1000,
                audio_s=audio_s,
                error=str(exc),
            )


class CartesiaTTS:
    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.model = os.environ.get("CARTESIA_TTS_MODEL", "sonic-3")
        self.voice = os.environ.get("CARTESIA_VOICE_ID", "")

    def supports(self, language: str) -> bool:
        return language in _TTS_LANGS

    async def synthesize(self, text: str, language: str) -> TTSResult:
        if not self.supports(language):
            return TTSResult(
                pcm=b"", rate=16000, ttfb_ms=0, total_ms=0, chars=len(text), supported=False
            )
        if not self.voice:
            return TTSResult(
                pcm=b"",
                rate=16000,
                ttfb_ms=0,
                total_ms=0,
                chars=len(text),
                error="CARTESIA_VOICE_ID is not set",
            )
        body = {
            "model_id": self.model,
            "transcript": text,
            "voice": {"mode": "id", "id": self.voice},
            "language": language,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
        }
        started = time.monotonic()
        ttfb = 0.0
        chunks: list[bytes] = []
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                async with http.stream(
                    "POST",
                    "https://api.cartesia.ai/tts/bytes",
                    headers={
                        "X-API-Key": _key(),
                        "Cartesia-Version": _VERSION,
                        "Content-Type": "application/json",
                    },
                    json=body,
                ) as r:
                    if r.status_code != 200:
                        payload = await r.aread()
                        return TTSResult(
                            pcm=b"",
                            rate=16000,
                            ttfb_ms=0,
                            total_ms=0,
                            chars=len(text),
                            error=f"{r.status_code}: {payload[:200]!r}",
                        )
                    async for chunk in r.aiter_bytes():
                        if not ttfb and chunk:
                            ttfb = (time.monotonic() - started) * 1000
                        chunks.append(chunk)
        except httpx.HTTPError as exc:
            return TTSResult(
                pcm=b"", rate=16000, ttfb_ms=0, total_ms=0, chars=len(text), error=str(exc)
            )
        return TTSResult(
            pcm=b"".join(chunks),
            rate=16000,
            ttfb_ms=ttfb,
            total_ms=(time.monotonic() - started) * 1000,
            chars=len(text),
        )
