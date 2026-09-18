"""The fake provider: deterministic, free, and honest about being fake.

It exists so the benchmark, the report and the cost model can be exercised
with no key. Its "transcripts" are the reference text with a language- and
noise-dependent corruption, its latencies are drawn from a seeded generator,
and every result carries ``simulated=True``. The report shouts SIMULATED.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re

from evals.voice.audio import synthetic_voice
from evals.voice.providers.base import LLMResult, STTResult, TTSResult

# Rough corruption rates so the fake WER table is not flat: Spanish clean is
# good, minority languages are worse, noise hurts everyone. Made up on purpose.
_BASE_WER = {"es": 0.06, "ca": 0.14, "gl": 0.22, "eu": 0.30}
_NOISE_PENALTY = 0.18


def _rng(*parts: object) -> random.Random:
    seed = int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _corrupt(text: str, rate: float, rng: random.Random) -> str:
    words = text.split()
    out = []
    for w in words:
        r = rng.random()
        if r < rate * 0.5:
            continue  # deletion
        if r < rate:
            out.append(w[::-1] if len(w) > 3 else w + "s")  # substitution
            continue
        out.append(w)
    return " ".join(out)


class FakeSTT:
    simulated = True

    def __init__(self, key: str):
        self.key = key
        self._langs = {"deepgram": {"es", "ca"}}.get(key.split("_")[0], {"es", "ca", "gl", "eu"})

    def supports(self, language: str) -> bool:
        return language in self._langs

    async def transcribe(
        self, pcm: bytes, rate: int, language: str, *, hint: str = ""
    ) -> STTResult:
        await asyncio.sleep(0)
        noisy = hint.startswith("[noisy]")
        reference = re.sub(r"^\[[a-z]+\]\s*", "", hint)
        rng = _rng(self.key, language, noisy, reference)
        rate_wer = _BASE_WER.get(language, 0.3) + (_NOISE_PENALTY if noisy else 0.0)
        if not self.supports(language):
            return STTResult(text="", final_ms=0.0, audio_s=len(pcm) / 2 / rate, supported=False)
        return STTResult(
            text=_corrupt(reference, rate_wer, rng),
            final_ms=rng.uniform(220, 480) + (120 if noisy else 0),
            audio_s=len(pcm) / 2 / rate,
        )


class FakeTTS:
    simulated = True

    def __init__(self, key: str):
        self.key = key
        self._langs = {"openai": {"es", "ca", "gl", "eu"}}.get(key.split("_")[0], {"es"})

    def supports(self, language: str) -> bool:
        return language in self._langs

    async def synthesize(self, text: str, language: str) -> TTSResult:
        await asyncio.sleep(0)
        rng = _rng(self.key, language, text)
        if not self.supports(language):
            return TTSResult(
                pcm=b"", rate=16000, ttfb_ms=0, total_ms=0, chars=len(text), supported=False
            )
        pcm = synthetic_voice(text)
        return TTSResult(
            pcm=pcm,
            rate=16000,
            ttfb_ms=rng.uniform(90, 320),
            total_ms=rng.uniform(600, 1400),
            chars=len(text),
        )


class FakeLLM:
    simulated = True

    def __init__(self, model: str):
        self.model = model

    async def reply(self, system: str, user: str) -> LLMResult:
        await asyncio.sleep(0)
        rng = _rng(self.model, user)
        return LLMResult(
            text=(
                "Le puedo ofrecer el lunes a las nueve y cuarto con el doctor Sáez "
                "en Arenal Norte. ¿Le viene bien?"
            ),
            ttft_ms=rng.uniform(350, 900),
            total_ms=rng.uniform(900, 1800),
            tokens_in=len(system.split()) + len(user.split()) + 40,
            tokens_out=28,
        )
