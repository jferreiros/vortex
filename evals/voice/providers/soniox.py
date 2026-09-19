"""Soniox stt-rt-v5 over the real-time WebSocket API.

UNTESTED against the real service: written from the public WebSocket reference
on 2026-09-19 with no key at hand. Matches the production model
(``SONIOX_STT_MODEL``, default ``stt-rt-v5``). ``final_ms`` is measured from
the end of the audio send to the server's ``finished`` frame — the same
finalisation wait the line lane sees after a turn ends.
"""

from __future__ import annotations

import json
import os
import time

import websockets

from evals.voice.providers.base import STTResult

_STT_LANGS = {"es", "ca", "gl", "eu", "en"}
_WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
_CHUNK_BYTES = 3200  # 100 ms of 16 kHz PCM16 mono


def _key() -> str:
    key = os.environ.get("SONIOX_API_KEY", "")
    if not key:
        raise RuntimeError("SONIOX_API_KEY is not set")
    return key


class SonioxSTT:
    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.model = os.environ.get("SONIOX_STT_MODEL", "stt-rt-v5")

    def supports(self, language: str) -> bool:
        return language in _STT_LANGS

    async def transcribe(
        self, pcm: bytes, rate: int, language: str, *, hint: str = ""
    ) -> STTResult:
        audio_s = len(pcm) / 2 / rate
        if not self.supports(language):
            return STTResult(text="", final_ms=0.0, audio_s=audio_s, supported=False)
        finals: list[str] = []
        started = time.monotonic()
        audio_done_at: float | None = None
        try:
            config = {
                "api_key": _key(),
                "model": self.model,
                "audio_format": "pcm_s16le",
                "sample_rate": rate,
                "num_channels": 1,
                "language_hints": [language],
                "enable_endpoint_detection": True,
            }
            async with websockets.connect(_WS_URL, max_size=8 * 1024 * 1024) as ws:
                await ws.send(json.dumps(config))
                for i in range(0, len(pcm), _CHUNK_BYTES):
                    await ws.send(pcm[i : i + _CHUNK_BYTES])
                await ws.send(json.dumps({"type": "finalize"}))
                await ws.send(b"")
                audio_done_at = time.monotonic()
                while True:
                    raw = await ws.recv()
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    if data.get("error_code") or data.get("error_type"):
                        msg = data.get("error_message") or data.get("error_type") or "soniox error"
                        return STTResult(
                            text="",
                            final_ms=(time.monotonic() - started) * 1000,
                            audio_s=audio_s,
                            error=str(msg),
                        )
                    for token in data.get("tokens") or []:
                        if token.get("is_final") and token.get("text"):
                            finals.append(token["text"])
                    if data.get("finished"):
                        break
        except (
            OSError,
            RuntimeError,
            websockets.WebSocketException,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            return STTResult(
                text="",
                final_ms=(time.monotonic() - started) * 1000,
                audio_s=audio_s,
                error=str(exc),
            )
        final_ms = (time.monotonic() - (audio_done_at or started)) * 1000
        return STTResult(text="".join(finals).strip(), final_ms=final_ms, audio_s=audio_s)
