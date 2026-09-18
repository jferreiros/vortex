"""OpenAI: transcription, chat (streamed, for TTFT) and gpt-4o-mini-tts.

UNTESTED against the real service in this repo: written from the SDK
reference on 2026-09-18 with no key at hand. Uses the ``openai`` package the
project already depends on.
"""

from __future__ import annotations

import io
import os
import time

from evals.voice.audio import pcm_to_wav
from evals.voice.providers.base import LLMResult, STTResult, TTSResult

_LANGS = {"es", "ca", "gl", "eu"}


def _client():
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import AsyncOpenAI

    return AsyncOpenAI()


class OpenAISTT:
    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.model = (
            "gpt-4o-transcribe" if key.endswith("gpt4o_transcribe") else "gpt-4o-mini-transcribe"
        )

    def supports(self, language: str) -> bool:
        return language in _LANGS

    async def transcribe(
        self, pcm: bytes, rate: int, language: str, *, hint: str = ""
    ) -> STTResult:
        audio_s = len(pcm) / 2 / rate
        started = time.monotonic()
        try:
            wav = io.BytesIO(pcm_to_wav(pcm, rate))
            wav.name = "utterance.wav"
            res = await _client().audio.transcriptions.create(
                model=self.model, file=wav, language=language
            )
            return STTResult(
                text=getattr(res, "text", ""),
                final_ms=(time.monotonic() - started) * 1000,
                audio_s=audio_s,
            )
        except Exception as exc:  # any SDK/network failure is a measured failure, not a crash
            return STTResult(
                text="",
                final_ms=(time.monotonic() - started) * 1000,
                audio_s=audio_s,
                error=str(exc),
            )


class OpenAITTS:
    simulated = False

    def __init__(self, key: str):
        self.key = key
        self.model = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.voice = os.environ.get("OPENAI_TTS_VOICE", "coral")

    def supports(self, language: str) -> bool:
        return language in _LANGS

    async def synthesize(self, text: str, language: str) -> TTSResult:
        started = time.monotonic()
        ttfb = 0.0
        chunks: list[bytes] = []
        try:
            client = _client()
            async with client.audio.speech.with_streaming_response.create(
                model=self.model, voice=self.voice, input=text, response_format="pcm"
            ) as response:
                async for chunk in response.iter_bytes():
                    if not ttfb and chunk:
                        ttfb = (time.monotonic() - started) * 1000
                    chunks.append(chunk)
        except Exception as exc:
            return TTSResult(
                pcm=b"", rate=24000, ttfb_ms=0, total_ms=0, chars=len(text), error=str(exc)
            )
        return TTSResult(
            pcm=b"".join(chunks),
            rate=24000,
            ttfb_ms=ttfb,
            total_ms=(time.monotonic() - started) * 1000,
            chars=len(text),
        )


class OpenAILLM:
    simulated = False

    def __init__(self, model: str):
        self.model = model

    async def reply(self, system: str, user: str) -> LLMResult:
        started = time.monotonic()
        ttft = 0.0
        text: list[str] = []
        tokens_in = tokens_out = 0
        try:
            stream = await _client().chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                stream=True,
                stream_options={"include_usage": True},
                temperature=0,
            )
            async for event in stream:
                if event.usage:
                    tokens_in = event.usage.prompt_tokens or 0
                    tokens_out = event.usage.completion_tokens or 0
                if event.choices and event.choices[0].delta and event.choices[0].delta.content:
                    if not ttft:
                        ttft = (time.monotonic() - started) * 1000
                    text.append(event.choices[0].delta.content)
        except Exception as exc:
            return LLMResult(
                text="",
                ttft_ms=0,
                total_ms=(time.monotonic() - started) * 1000,
                tokens_in=0,
                tokens_out=0,
                error=str(exc),
            )
        return LLMResult(
            text="".join(text),
            ttft_ms=ttft,
            total_ms=(time.monotonic() - started) * 1000,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
