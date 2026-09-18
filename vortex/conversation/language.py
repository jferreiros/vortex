"""Language handling: detect, switch mid-call, constrain the provider.

Owner: the conversation lane.

The board checks the right language was used; the jury checks it was used
well. Every provider speaks Spanish; only four speak Catalan (problem 11).

Soniox ``stt-rt-v5`` tags every token with the language it heard when
``enable_language_identification`` is on, so the ``TranscriptionFrame.language``
attribute is the signal we trust. The word list below is only a fallback for
the frames that arrive untagged.

TODO(conversation):
- Pass the language into ``find_slots(language=...)`` only when the caller
  asks for a doctor they can talk to; elsewhere any provider is fine.
- Widen the fallback markers once we hear real callers (gl, eu).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for the annotation
    from pipecat.transcriptions.language import Language

    from vortex.settings import Settings

SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "ca", "en", "gl", "eu")

DEFAULT_LANGUAGE = "es"

# Words that are common in the language and rare in Spanish. Lowercase, no
# accents stripped: the STT writes them accented.
_MARKERS: dict[str, tuple[str, ...]] = {
    "ca": ("bon dia", "vull", "si us plau", "gràcies", "amb", "hora", "això", "però", "nosaltres"),
    "en": ("hello", "good morning", "appointment", "please", "thank you", "i would like"),
    "gl": ("bos días", "grazas", "quero", "moitas grazas"),
    "eu": ("egun on", "eskerrik asko", "mesedez", "nahi dut"),
}


def normalise_language(code: object) -> str | None:
    """Fold any language code (``Language.ES_ES``, ``"es-ES"``, ``"es"``) to ours."""
    if code is None:
        return None
    try:
        text = str(getattr(code, "value", code)).strip().lower()
    except Exception:  # never let a stray object break a live call
        return None
    if not text:
        return None
    base = text.replace("_", "-").split("-", 1)[0]
    return base if base in SUPPORTED_LANGUAGES else None


def detect_language(transcript: str, hint: object | None = None) -> str:
    """Return an ISO-639-1 code from ``SUPPORTED_LANGUAGES``.

    ``hint`` is the per-token language Soniox reports on the transcription
    frame. When it is present and supported it wins; otherwise a short marker
    list decides, and Spanish is the default. Never raises.
    """
    from_hint = normalise_language(hint)
    if from_hint:
        return from_hint
    try:
        text = (transcript or "").lower()
    except Exception:
        return DEFAULT_LANGUAGE
    if not text:
        return DEFAULT_LANGUAGE
    for code, markers in _MARKERS.items():
        if any(marker in text for marker in markers):
            return code
    return DEFAULT_LANGUAGE


def tts_voice_for(language: str, settings: Settings | Any) -> tuple[str, Language]:
    """The voice and the pipecat ``Language`` for a detected language.

    Per provider, because the co-official languages are not evenly covered:

    - google   es / ca / gl / eu  (Chirp 3 HD for Spanish, Standard for the rest)
    - azure    es / ca
    - deepgram es only

    Anything the active provider cannot say falls back to Spanish, the one
    language the whole clinic speaks. Never raises: a failed lookup during a
    live call must not end the call.
    """
    from pipecat.transcriptions.language import Language

    google = {
        "es": (getattr(settings, "google_tts_voice_es", ""), Language.ES_ES),
        "ca": (getattr(settings, "google_tts_voice_ca", ""), Language.CA_ES),
        "gl": (getattr(settings, "google_tts_voice_gl", ""), Language.GL_ES),
        "eu": (getattr(settings, "google_tts_voice_eu", ""), Language.EU_ES),
    }
    azure = {
        "es": (getattr(settings, "azure_tts_voice_es", ""), Language.ES_ES),
        "ca": (getattr(settings, "azure_tts_voice_ca", ""), Language.CA_ES),
    }
    deepgram = {"es": (getattr(settings, "deepgram_tts_model", ""), Language.ES_ES)}

    provider = str(getattr(settings, "tts_provider", "google") or "google").lower()
    voices = {"google": google, "azure": azure, "deepgram": deepgram}.get(provider, google)

    code = normalise_language(language) or DEFAULT_LANGUAGE
    return voices.get(code) or voices[DEFAULT_LANGUAGE]
