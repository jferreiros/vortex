"""Deepgram: Nova-3 STT and Aura-2 TTS over plain HTTPS.

UNTESTED against the real service: written from the public API reference on
2026-09-18 with no key at hand. The first real run should be a single
utterance with ``--max-eur 0.05``. Batch ``/v1/listen`` is used, not the
streaming socket, so ``final_ms`` here is a round trip, an upper bound on the
streaming finalisation the line lane will see.
"""

from __future__ import annotations

import os
import time

import httpx

from evals.voice.audio import pcm_to_wav
from evals.voice.providers.base import STTResult, TTSResult

_STT_LANGS = {"es", "ca"}
_TTS_LANGS = {"es"}
_LANG_PARAM = {"es": "es", "ca": "ca", "gl": "gl", "eu": "eu"}


def _key() -> str:
    key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set")
    return key


class DeepgramSTT:
    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.model = os.environ.get("DEEPGRAM_STT_MODEL", "nova-3")

    def supports(self, language: str) -> bool:
        return language in _STT_LANGS

    async def transcribe(
        self, pcm: bytes, rate: int, language: str, *, hint: str = ""
    ) -> STTResult:
        audio_s = len(pcm) / 2 / rate
        if not self.supports(language):
            return STTResult(text="", final_ms=0.0, audio_s=audio_s, supported=False)
        params = {"model": self.model, "language": _LANG_PARAM[language], "smart_format": "true"}
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.post(
                    "https://api.deepgram.com/v1/listen",
                    params=params,
                    headers={"Authorization": f"Token {_key()}", "Content-Type": "audio/wav"},
                    content=pcm_to_wav(pcm, rate),
                )
            elapsed = (time.monotonic() - started) * 1000
            if r.status_code != 200:
                return STTResult(
                    text="",
                    final_ms=elapsed,
                    audio_s=audio_s,
                    error=f"{r.status_code}: {r.text[:200]}",
                )
            data = r.json()
            text = data["results"]["channels"][0]["alternatives"][0]["transcript"]
            return STTResult(text=text, final_ms=elapsed, audio_s=audio_s)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return STTResult(
                text="",
                final_ms=(time.monotonic() - started) * 1000,
                audio_s=audio_s,
                error=str(exc),
            )


class DeepgramTTS:
    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.model = os.environ.get("DEEPGRAM_TTS_MODEL", "aura-2-celeste-es")

    def supports(self, language: str) -> bool:
        return language in _TTS_LANGS

    async def synthesize(self, text: str, language: str) -> TTSResult:
        if not self.supports(language):
            return TTSResult(
                pcm=b"", rate=16000, ttfb_ms=0, total_ms=0, chars=len(text), supported=False
            )
        started = time.monotonic()
        ttfb = 0.0
        chunks: list[bytes] = []
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                async with http.stream(
                    "POST",
                    "https://api.deepgram.com/v1/speak",
                    params={
                        "model": self.model,
                        "encoding": "linear16",
                        "sample_rate": "16000",
                        "container": "none",
                    },
                    headers={
                        "Authorization": f"Token {_key()}",
                        "Content-Type": "application/json",
                    },
                    json={"text": text},
                ) as r:
                    if r.status_code != 200:
                        body = await r.aread()
                        return TTSResult(
                            pcm=b"",
                            rate=16000,
                            ttfb_ms=0,
                            total_ms=0,
                            chars=len(text),
                            error=f"{r.status_code}: {body[:200]!r}",
                        )
                    async for chunk in r.aiter_bytes():
                        if not ttfb and chunk:
                            ttfb = (time.monotonic() - started) * 1000
                        chunks.append(chunk)
        except httpx.HTTPError as exc:
            return TTSResult(
                pcm=b"", rate=16000, ttfb_ms=0, total_ms=0, chars=len(text), error=str(exc)
            )
        total = (time.monotonic() - started) * 1000
        return TTSResult(
            pcm=b"".join(chunks), rate=16000, ttfb_ms=ttfb, total_ms=total, chars=len(text)
        )
