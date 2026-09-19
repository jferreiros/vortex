"""Per-call audio capture: µ-law frames in, one PCM WAV out at ``call.ended``.

Every inbound media frame is appended to the session's recording buffer in
the µ-law it arrived in. When the call ends, the buffer is decoded
(``vortex.line.ulaw`` - the codec the stub and the fake caller already use,
no ``audioop`` needed) and written as an 8 kHz mono PCM WAV to
``recordings/{call_id}.wav``, so the Calls table can play and download it.

The directory is ``recordings/`` at the repo root; ``VORTEX_RECORDINGS_DIR``
overrides it. Everything is per call: the buffer lives on the session and
the serializer's tee closes over one socket's session.
"""

from __future__ import annotations

import base64
import json
import os
import re
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vortex.line import ulaw
from vortex.settings import REPO_ROOT

if TYPE_CHECKING:
    from vortex.line.session import CallSession

#: Inbound audio is µ-law at 8 kHz mono - the wire format never changes.
SAMPLE_RATE = 8000

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def recordings_dir() -> Path:
    """Where WAVs land. Read at write time so a test's env always wins."""
    override = os.environ.get("VORTEX_RECORDINGS_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "recordings"


def safe_call_id(call_id: str) -> str:
    """A ``call_id`` that is safe as a file name and a URL segment."""
    safe = _UNSAFE.sub("_", call_id).strip("._")
    return safe or "call"


def write_wav(
    call_id: str, ulaw_bytes: bytes, *, directory: Path | None = None
) -> tuple[Path, int, int]:
    """Decode the buffered µ-law and write one 8 kHz mono PCM WAV.

    Returns ``(path, duration_ms, size_bytes)`` for the ``call.recording``
    event. One µ-law byte is one sample, so the duration falls straight out
    of the buffer length.
    """
    directory = directory or recordings_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_call_id(call_id)}.wav"
    pcm = ulaw.ulaw_to_pcm16(ulaw_bytes)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    duration_ms = round(len(ulaw_bytes) / SAMPLE_RATE * 1000)
    return path, duration_ms, path.stat().st_size


def wav_path_for(call_id: str, *, directory: Path | None = None) -> Path | None:
    """The WAV of a finished call, or ``None`` when none was written."""
    path = (directory or recordings_dir()) / f"{safe_call_id(call_id)}.wav"
    return path if path.is_file() else None


def recording_serializer(session: CallSession) -> Any:
    """The Twilio serializer plus a tee on inbound media.

    Every ``media`` message's µ-law payload is appended to this call's
    recording buffer before it is decoded for the pipeline, so the WAV holds
    exactly what the platform sent. The closure captures this socket's
    session - one per connection, like everything else on the line.
    """
    from pipecat.frames.frames import Frame
    from pipecat.serializers.twilio import TwilioFrameSerializer

    class _Serializer(TwilioFrameSerializer):
        async def deserialize(self, data: str | bytes) -> Frame | None:
            try:
                message = json.loads(data)
                if message.get("event") == "media":
                    payload = message.get("media", {}).get("payload")
                    if payload:
                        session.record_frame(base64.b64decode(payload))
            except (ValueError, TypeError):
                pass  # a malformed frame is the base class's to reject
            return await super().deserialize(data)

    return _Serializer(
        stream_sid=session.stream_sid,
        call_sid=session.call_id,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
