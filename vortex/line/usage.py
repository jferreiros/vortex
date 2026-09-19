"""What one call actually spent at the three providers, counted per socket.

The jury wall prices a call in euros, and a price needs quantities: seconds of
audio at Soniox, tokens at the LLM host, characters at Google TTS. Pipecat
already measures all three - it just keeps quiet about them unless
``PipelineParams(enable_usage_metrics=True)`` is set, which is what turns the
``start_*_usage_metrics`` hooks in ``FrameProcessor`` into ``MetricsFrame``s on
the wire. ``_CallLogObserver`` catches those frames and adds them up here.

One ``UsageTotals`` per ``CallSession``, like everything else on the line: ten
sockets at once must not share a counter. ``CallSession.close`` turns it into
the single ``call.usage`` line the dashboard reads.

Three details the numbers depend on:

- **STT arrives as deltas.** ``STTUsage.audio_seconds`` is the audio submitted
  *since the last report*, so the total is their sum, not the last one.
- **TTS bills per service.** Chirp 3 HD, Standard and Gemini-TTS have three
  different rates, so characters are bucketed by the service that spoke them
  (``MetricsData.processor``, which is ``"GoogleHttpTTSService#0"`` - class
  name, ``#``, instance counter) and by the model/voice it used.
- **Do not add the cache counts to ``prompt_tokens``.** OpenAI-compatible hosts
  report ``prompt_tokens`` gross of the cache, so the cache figure is carried
  alongside for information and never summed into the input bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The only STT on this line. There is no ``settings.stt_provider`` to read.
STT_PROVIDER = "soniox"


def service_class_name(processor: str) -> str:
    """``"GeminiTTSService#2"`` -> ``"GeminiTTSService"``.

    Pipecat names every processor ``f"{class}#{count}"``, and the counter is a
    per-process instance number: it would make the same service look like a
    different one on the second call of the process.
    """
    return processor.split("#", 1)[0]


@dataclass
class TtsLeg:
    """Characters spoken by one TTS service with one model/voice."""

    service: str
    model: str
    characters: int = 0
    requests: int = 0


@dataclass
class UsageTotals:
    """Everything one call consumed. Per socket, never module-level."""

    #: True once a lane has run with pipecat's usage emitters switched on. The
    #: stub and Gemini Live lanes leave it False, which is how the dashboard
    #: tells "this call cost nothing measured" from "this call cost nothing".
    metered: bool = False

    stt_audio_seconds: float = 0.0
    stt_requests: int = 0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_input_tokens: int = 0
    llm_requests: int = 0

    #: Keyed by (service class name, model as the frame reported it), so the
    #: order of the ``tts`` list is the order the services first spoke.
    tts_legs: dict[tuple[str, str], TtsLeg] = field(default_factory=dict)

    def add_stt(self, audio_seconds: float) -> None:
        """One STT usage report. The value is a delta, so it accumulates."""
        self.stt_audio_seconds += float(audio_seconds)
        self.stt_requests += 1

    def add_llm(self, tokens: Any) -> None:
        """One completion's token usage (``LLMTokenUsage``)."""
        self.prompt_tokens += int(tokens.prompt_tokens or 0)
        self.completion_tokens += int(tokens.completion_tokens or 0)
        self.reasoning_tokens += int(getattr(tokens, "reasoning_tokens", 0) or 0)
        self.cache_read_input_tokens += int(getattr(tokens, "cache_read_input_tokens", 0) or 0)
        self.llm_requests += 1

    def add_tts(self, processor: str, model: str | None, characters: int) -> None:
        """One synthesis request, billed to the service that spoke it."""
        service = service_class_name(processor)
        key = (service, model or "")
        leg = self.tts_legs.get(key)
        if leg is None:
            leg = TtsLeg(service=service, model=model or "")
            self.tts_legs[key] = leg
        leg.characters += int(characters)
        leg.requests += 1

    @property
    def tts_characters(self) -> int:
        return sum(leg.characters for leg in self.tts_legs.values())

    def payload(self, settings: Any) -> dict[str, Any]:
        """The ``call.usage`` body. Providers and models come from settings.

        The frame carries the processor that spoke and (sometimes) its model,
        never the account's configured id, so the names the dashboard prices on
        are read back off ``settings`` here.
        """
        return {
            "metered": self.metered,
            "stt": {
                "provider": STT_PROVIDER,
                "model": settings.soniox_stt_model,
                "audio_seconds": round(self.stt_audio_seconds, 3),
                "requests": self.stt_requests,
            },
            "llm": {
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "reasoning_tokens": self.reasoning_tokens,
                "cache_read_input_tokens": self.cache_read_input_tokens,
                "requests": self.llm_requests,
            },
            "tts": [_tts_entry(leg, settings) for leg in self.tts_legs.values()],
        }

    def summary_extras(self) -> dict[str, Any]:
        """The four headline numbers, for the ``call.summary`` line."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "stt_audio_seconds": round(self.stt_audio_seconds, 3),
            "tts_characters": self.tts_characters,
        }


def tts_provider_for(service: str, settings: Any) -> str:
    """Who bills these characters, read off the pipecat service class.

    ``settings.tts_provider`` names the *primary* service only, and the pair
    can be mixed (ElevenLabs Spanish + Google ca/gl/eu), so the class that
    actually spoke is the honest answer. Gemini-TTS is Google as well.
    """
    if service.startswith(("Google", "Gemini")):
        return "google"
    if service.startswith("ElevenLabs"):
        return "elevenlabs"
    return settings.tts_provider


def tts_model_for(service: str, model: str, settings: Any) -> str:
    """The name the dashboard prices on: ``Chirp3-HD``, ``Standard``, ``gemini-``, ``eleven_``.

    ``GoogleHttpTTSService`` is built with no ``model`` (a Google voice *is*
    the model), so its metrics carry an empty string and the configured voice
    id stands in for it. Under ``GOOGLE_TTS_STANDARD_FALLBACK`` that same
    service also speaks ca/gl/eu on Standard-* voices; the Spanish voice is
    what it opens every call with, so that is the one recorded.
    """
    if model:
        return model
    if service.startswith("Gemini"):
        return settings.google_tts_gemini_model
    if service.startswith("ElevenLabs"):
        return settings.elevenlabs_model
    return settings.google_tts_voice_es


def _tts_entry(leg: TtsLeg, settings: Any) -> dict[str, Any]:
    return {
        "provider": tts_provider_for(leg.service, settings),
        "service": leg.service,
        "model": tts_model_for(leg.service, leg.model, settings),
        "characters": leg.characters,
        "requests": leg.requests,
    }
