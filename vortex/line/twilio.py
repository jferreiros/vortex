"""Twilio Media Streams wire format, as the platform speaks it (call contract §1).

Inbound, in order: ``connected`` -> ``start`` -> ``media``* -> ``stop``.
Outbound from us: ``media`` (our voice), optionally ``mark`` and ``clear``.

Quirks the contract warns about:
- ``sequenceNumber``, ``chunk`` and ``timestamp`` are strings on the wire.
- Every key is camelCase. (Only the submit JSON is snake_case.)
- ``start.callSid`` is the ``call_id`` we submit. ``start.customParameters``
  carries ``call_id`` again and ``from_number`` (absent when withheld).

The stub voice pipeline and the smoke test use these models directly. The
pipecat pipeline uses pipecat's own ``TwilioFrameSerializer`` after the
handshake, which this module parses for both paths.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Literal
from xml.sax.saxutils import quoteattr

from pydantic import BaseModel, ConfigDict, Field

FRAME_MS = 20
SAMPLE_RATE = 8000
BYTES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000  # 160 bytes of µ-law per 20 ms


class _Wire(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class StartPayload(_Wire):
    stream_sid: str = Field(alias="streamSid")
    call_sid: str = Field(alias="callSid")
    account_sid: str | None = Field(default=None, alias="accountSid")
    tracks: list[str] = Field(default_factory=list)
    custom_parameters: dict[str, Any] = Field(default_factory=dict, alias="customParameters")
    media_format: dict[str, Any] = Field(default_factory=dict, alias="mediaFormat")

    @property
    def call_id(self) -> str:
        # The contract says: call_id is exactly start.callSid. customParameters
        # repeats it for convenience; callSid is the source of truth.
        return self.call_sid

    @property
    def from_number(self) -> str | None:
        value = self.custom_parameters.get("from_number")
        return str(value) if value else None


class MediaPayload(_Wire):
    track: str | None = None
    chunk: str | None = None
    timestamp: str | None = None
    payload: str  # base64 µ-law, 160 bytes per 20 ms frame

    def audio_bytes(self) -> bytes:
        return base64.b64decode(self.payload)


class ConnectedMessage(_Wire):
    event: Literal["connected"]
    protocol: str | None = None
    version: str | None = None


class StartMessage(_Wire):
    event: Literal["start"]
    sequence_number: str | None = Field(default=None, alias="sequenceNumber")
    stream_sid: str | None = Field(default=None, alias="streamSid")
    start: StartPayload


class MediaMessage(_Wire):
    event: Literal["media"]
    sequence_number: str | None = Field(default=None, alias="sequenceNumber")
    stream_sid: str | None = Field(default=None, alias="streamSid")
    media: MediaPayload


class StopMessage(_Wire):
    event: Literal["stop"]
    sequence_number: str | None = Field(default=None, alias="sequenceNumber")
    stream_sid: str | None = Field(default=None, alias="streamSid")
    stop: dict[str, Any] = Field(default_factory=dict)


class MarkMessage(_Wire):
    event: Literal["mark"]
    stream_sid: str | None = Field(default=None, alias="streamSid")
    mark: dict[str, Any] = Field(default_factory=dict)


class DtmfMessage(_Wire):
    event: Literal["dtmf"]
    stream_sid: str | None = Field(default=None, alias="streamSid")
    dtmf: dict[str, Any] = Field(default_factory=dict)


class UnknownMessage(_Wire):
    event: str


InboundMessage = (
    ConnectedMessage
    | StartMessage
    | MediaMessage
    | StopMessage
    | MarkMessage
    | DtmfMessage
    | UnknownMessage
)

_BY_EVENT: dict[str, type[BaseModel]] = {
    "connected": ConnectedMessage,
    "start": StartMessage,
    "media": MediaMessage,
    "stop": StopMessage,
    "mark": MarkMessage,
    "dtmf": DtmfMessage,
}


def parse_inbound(text: str) -> InboundMessage:
    """Parse one text frame. Unknown events come back as ``UnknownMessage``."""
    data = json.loads(text)
    model = _BY_EVENT.get(str(data.get("event", "")), UnknownMessage)
    return model.model_validate(data)  # type: ignore[return-value]


# ---- outbound ---------------------------------------------------------------


def media_message(stream_sid: str, ulaw_frame: bytes) -> str:
    """One outbound 20 ms frame. ``ulaw_frame`` is raw µ-law bytes."""
    return json.dumps(
        {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(ulaw_frame).decode("ascii")},
        }
    )


def mark_message(stream_sid: str, name: str) -> str:
    return json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": name}})


def clear_message(stream_sid: str) -> str:
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def split_frames(ulaw: bytes, frame_bytes: int = BYTES_PER_FRAME) -> list[bytes]:
    """Cut a µ-law buffer into 20 ms frames. The last frame is padded with silence."""
    frames = [ulaw[i : i + frame_bytes] for i in range(0, len(ulaw), frame_bytes)]
    if frames and len(frames[-1]) < frame_bytes:
        frames[-1] = frames[-1] + b"\xff" * (frame_bytes - len(frames[-1]))
    return frames


# E.164 country codes we will search or buy. Never NANP / +1.
_EU_DIAL_PREFIXES = (
    "34",
    "49",
    "33",
    "39",
    "351",
    "353",
    "31",
    "32",
    "43",
    "48",
    "46",
    "45",
    "358",
    "30",
    "420",
    "36",
    "40",
    "421",
    "386",
    "385",
    "359",
    "370",
    "371",
    "372",
    "352",
    "357",
    "356",
)


def is_european_e164(phone: str) -> bool:
    """True when the number is in the EU list. United States (+1) is always false."""
    digits = re.sub(r"[^\d+]", "", phone or "")
    if not digits.startswith("+"):
        digits = "+" + digits.lstrip("0")
    if digits.startswith("+1"):
        return False
    rest = digits[1:]
    return any(rest.startswith(cc) for cc in sorted(_EU_DIAL_PREFIXES, key=len, reverse=True))


def public_ws_url(public_base_url: str, ws_path: str = "/ws") -> str:
    """The receptionist websocket behind a public https/http base."""
    base = public_base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    path = ws_path if ws_path.startswith("/") else f"/{ws_path}"
    return base + path


def twiml_connect_stream(ws_url: str, params: dict[str, str] | None = None) -> str:
    """Bridge a PSTN call into our Media Streams socket."""
    rendered = "".join(
        f"<Parameter name={quoteattr(k)} value={quoteattr(v)}/>"
        for k, v in (params or {}).items()
        if v
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f"<Stream url={quoteattr(ws_url)}>{rendered}</Stream>"
        "</Connect></Response>"
    )
