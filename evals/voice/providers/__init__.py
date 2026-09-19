"""Provider adapters. One small interface per stage; the runner never sees a vendor SDK."""

from __future__ import annotations

from evals.voice.providers.base import (
    LLMProvider,
    LLMResult,
    STTProvider,
    STTResult,
    TTSProvider,
    TTSResult,
)


def make_stt(key: str, *, real: bool) -> STTProvider:
    if not real:
        from evals.voice.providers.fake import FakeSTT

        return FakeSTT(key)
    if key.startswith("deepgram"):
        from evals.voice.providers.deepgram import DeepgramSTT

        return DeepgramSTT(key)
    if key.startswith("openai"):
        from evals.voice.providers.openai_audio import OpenAISTT

        return OpenAISTT(key)
    if key.startswith("cartesia"):
        from evals.voice.providers.cartesia import CartesiaSTT

        return CartesiaSTT(key)
    if key.startswith("soniox"):
        from evals.voice.providers.soniox import SonioxSTT

        return SonioxSTT(key)
    raise ValueError(f"no STT adapter for {key!r}")


def make_tts(key: str, *, real: bool) -> TTSProvider:
    if not real:
        from evals.voice.providers.fake import FakeTTS

        return FakeTTS(key)
    if key.startswith("deepgram"):
        from evals.voice.providers.deepgram import DeepgramTTS

        return DeepgramTTS(key)
    if key.startswith("openai"):
        from evals.voice.providers.openai_audio import OpenAITTS

        return OpenAITTS(key)
    if key.startswith("cartesia"):
        from evals.voice.providers.cartesia import CartesiaTTS

        return CartesiaTTS(key)
    raise ValueError(f"no TTS adapter for {key!r}")


def make_llm(model: str, *, real: bool) -> LLMProvider:
    if not real:
        from evals.voice.providers.fake import FakeLLM

        return FakeLLM(model)
    from evals.voice.providers.openai_audio import OpenAILLM

    return OpenAILLM(model)


__all__ = [
    "LLMProvider",
    "LLMResult",
    "STTProvider",
    "STTResult",
    "TTSProvider",
    "TTSResult",
    "make_llm",
    "make_stt",
    "make_tts",
]
