"""Per-call office bed mixed into the Twilio output, with optional typing on top.

``SoundfileMixer`` plays *one* file at a time, so switching to ``typing`` used
to mute the room. This mixer always adds the office loop, and only then the
keyboard file, so a lookup never kills the bed. Files are resampled to the
transport rate on start so a mismatch cannot drop the room silently.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Any

import numpy as np
from pipecat.audio.mixers.base_audio_mixer import BaseAudioMixer

log = logging.getLogger(__name__)

SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"
OFFICE_SOUND = "office"
TYPING_SOUND = "typing"
# Audible under speech, not a second voice. 0.42 was a debug level after the
# bed had been failing to mix at all.
OFFICE_VOLUME = 0.09
TYPING_VOLUME = 0.22
REQUIRED_RATE = 8000


def _wav_is_transport_ready(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as handle:
            return (
                handle.getnchannels() == 1
                and handle.getsampwidth() == 2
                and handle.getframerate() == REQUIRED_RATE
                and handle.getnframes() > 0
            )
    except Exception as exc:
        log.warning("ambience file unreadable %s: %s", path, exc)
        return False


def _load_mono(path: Path, sample_rate: int) -> np.ndarray:
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    data = np.asarray(data, dtype=np.float64)
    if rate != sample_rate and len(data) > 1:
        n = max(1, int(round(len(data) * sample_rate / rate)))
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return np.clip(np.round(data * 32767.0), -32768, 32767).astype(np.int16)


def _take_loop(sound: np.ndarray, pos: int, n: int) -> tuple[np.ndarray, int]:
    if len(sound) == 0 or n <= 0:
        return np.zeros(n, dtype=np.int16), 0
    pos %= len(sound)
    end = pos + n
    if end <= len(sound):
        return sound[pos:end], end % len(sound)
    head = sound[pos:]
    tail = sound[: n - len(head)]
    return np.concatenate([head, tail]), n - len(head)


class _AmbienceMixer(BaseAudioMixer):
    """Always mix office; add keyboard clicks when ``sound`` is ``typing``."""

    def __init__(self, office_path: Path, typing_path: Path, *, volume: float = OFFICE_VOLUME):
        self._paths = {OFFICE_SOUND: office_path, TYPING_SOUND: typing_path}
        # Names the SoundfileMixer API uses, so existing tests keep working.
        self._sound_files = {OFFICE_SOUND: str(office_path), TYPING_SOUND: str(typing_path)}
        self._volume = float(volume)
        self._typing = False
        self._mixing = True
        self._office = np.zeros(0, dtype=np.int16)
        self._clicks = np.zeros(0, dtype=np.int16)
        self._office_pos = 0
        self._click_pos = 0

    async def start(self, sample_rate: int) -> None:
        try:
            self._office = _load_mono(self._paths[OFFICE_SOUND], sample_rate)
            self._clicks = _load_mono(self._paths[TYPING_SOUND], sample_rate)
        except Exception as exc:
            log.warning("ambience mixer failed to load wavs: %s", exc)
            self._office = np.zeros(0, dtype=np.int16)
            self._clicks = np.zeros(0, dtype=np.int16)
        self._office_pos = 0
        self._click_pos = 0
        log.info(
            "ambience mixer ready office=%s clicks=%s rate=%s",
            len(self._office),
            len(self._clicks),
            sample_rate,
        )

    async def stop(self) -> None:
        return None

    async def process_frame(self, frame: Any) -> None:
        from pipecat.frames.frames import MixerEnableFrame, MixerUpdateSettingsFrame

        if isinstance(frame, MixerEnableFrame):
            self._mixing = bool(frame.enable)
            return
        if not isinstance(frame, MixerUpdateSettingsFrame):
            return
        for key, value in frame.settings.items():
            if key == "sound":
                self._typing = value == TYPING_SOUND
            elif key == "volume":
                self._volume = float(value)

    async def mix(self, audio: bytes) -> bytes:
        if not self._mixing or len(self._office) == 0:
            return audio
        voice = np.frombuffer(audio, dtype=np.int16)
        n = len(voice)
        room, self._office_pos = _take_loop(self._office, self._office_pos, n)
        mixed = voice.astype(np.float64) + room.astype(np.float64) * self._volume
        if self._typing and len(self._clicks):
            clicks, self._click_pos = _take_loop(self._clicks, self._click_pos, n)
            mixed += clicks.astype(np.float64) * TYPING_VOLUME
        return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()


def _make_ambience_mixer() -> Any | None:
    """Build the looping mixer, or ``None`` if the beds cannot load."""
    office = SOUNDS_DIR / "office.wav"
    typing = SOUNDS_DIR / "typing.wav"
    missing = [str(path) for path in (office, typing) if not path.is_file()]
    if missing:
        log.warning("ambience mixer skipped; missing %s", ", ".join(missing))
        return None
    if not _wav_is_transport_ready(office) or not _wav_is_transport_ready(typing):
        log.warning("ambience mixer skipped; wavs are not 8 kHz mono int16")
        return None
    try:
        return _AmbienceMixer(office, typing, volume=OFFICE_VOLUME)
    except Exception as exc:
        log.warning("ambience mixer skipped: %s", exc)
        return None
