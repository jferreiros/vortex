"""ElevenLabs ``voice_settings``, one named preset per voice character.

These four numbers are the ElevenLabs ``voice_settings`` block: ``stability``
holds the delivery steady, ``similarity_boost`` keeps it close to the cloned
voice, ``style`` exaggerates its expression and ``use_speaker_boost``
sharpens the speaker resemblance. The last two cost latency — the ElevenLabs
docs say a ``style`` above 0 and speaker boost both add time to the first
byte, and on a phone call the first byte is the whole impression — so
``RECEPTIONIST`` keeps ``style`` at 0 and leaves speaker boost on, the same
values as the working Telnyx configuration for this voice. The preset is
deliberately *not* an environment variable: a voice character is a product
decision we review in a diff, not a knob to turn on a live call. To add
another character, add a member here and point the TTS builder at it — give it
values that differ from an existing member's, or ``Enum`` folds the two into
one alias.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class VoiceSettings(NamedTuple):
    """The ElevenLabs ``voice_settings`` block, field for field."""

    stability: float
    similarity_boost: float
    style: float
    use_speaker_boost: bool


class ElevenLabsVoicePreset(Enum):
    """Named ElevenLabs voice settings. ``RECEPTIONIST`` is the one we call with."""

    RECEPTIONIST = VoiceSettings(
        stability=0.5,
        similarity_boost=0.75,
        style=0.0,
        use_speaker_boost=True,
    )
