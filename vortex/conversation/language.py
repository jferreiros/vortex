"""Language handling: detect, switch mid-call, constrain the provider.

Owner: the conversation lane.

The board checks the right language was used; the jury checks it was used
well. Every provider speaks Spanish; only four speak Catalan (problem 11).

TODO(conversation):
- Detect the caller's language from the first transcript (es, ca, en, gl, eu).
- Switch the TTS voice/instructions without restarting the pipeline.
- Pass the language into ``find_slots(language=...)`` only when the caller
  asks for a doctor they can talk to; elsewhere any provider is fine.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "ca", "en", "gl", "eu")


def detect_language(transcript: str) -> str:
    """Return an ISO-639-1 code. Placeholder: always Spanish.

    TODO(conversation): implement. Deepgram nova-3 "multi" also reports a
    language per utterance; that signal may be enough.
    """
    return "es"
