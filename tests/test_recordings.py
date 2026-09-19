"""Call recordings: inbound µ-law in, one 8 kHz PCM WAV out at ``call.ended``.

The stub pipeline tees every inbound media frame into the session's buffer;
``close`` decodes it (``vortex.line.ulaw``, pure Python) and writes
``recordings/{call_id}.wav``, then ``GET /recordings/{call_id}`` serves it
as an attachment.
"""

from __future__ import annotations

import base64
import json
import wave
from pathlib import Path

from starlette.testclient import TestClient

from vortex.line import twilio, ulaw
from vortex.line.recording import safe_call_id, wav_path_for, write_wav
from vortex.line.server import create_app

CALL_SID = "CA-rec-0001"
STREAM_SID = "MZ-rec-0001"


def _media(seq: int, chunk: int) -> str:
    frame = ulaw.silence(twilio.FRAME_MS)
    return json.dumps(
        {
            "event": "media",
            "sequenceNumber": str(seq),
            "streamSid": STREAM_SID,
            "media": {
                "track": "inbound",
                "chunk": str(chunk),
                "timestamp": str(chunk * 20),
                "payload": base64.b64encode(frame).decode("ascii"),
            },
        }
    )


def _start() -> str:
    return json.dumps(
        {
            "event": "start",
            "sequenceNumber": "1",
            "streamSid": STREAM_SID,
            "start": {
                "streamSid": STREAM_SID,
                "callSid": CALL_SID,
                "accountSid": "AC-fake",
                "customParameters": {"call_id": CALL_SID, "from_number": "+34612345678"},
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            },
        }
    )


def test_write_wav_round_trips_the_header(tmp_path: Path) -> None:
    source = ulaw.tone(440, 100)  # 800 µ-law samples of a 440 Hz tone
    path, duration_ms, size = write_wav("CA-1", source, directory=tmp_path)

    assert path.name == "CA-1.wav"
    assert duration_ms == 100
    assert size == path.stat().st_size

    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 8000
        assert wav.getnframes() == 800
        pcm = wav.readframes(800)

    # Decode again: one µ-law round-trip is near-lossless.
    back = ulaw.pcm16_to_ulaw(pcm)
    assert back == source


def test_safe_call_id_strips_unsafe_characters() -> None:
    assert safe_call_id("CA-abc-123") == "CA-abc-123"
    assert safe_call_id("../etc/passwd") == "etc_passwd"
    assert safe_call_id("") == "call"


def test_wav_path_for_missing_call(tmp_path: Path) -> None:
    assert wav_path_for("CA-none", directory=tmp_path) is None


def test_call_records_and_serves_the_wav(
    offline_settings, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VORTEX_RECORDINGS_DIR", str(tmp_path / "recordings"))
    client = TestClient(create_app(offline_settings))

    with client.websocket_connect(offline_settings.ws_path) as ws:
        ws.send_text(_start())
        # Drain the greeting up to its mark.
        while True:
            if json.loads(ws.receive_text())["event"] == "mark":
                break
        for i in range(100):
            ws.send_text(_media(seq=i + 2, chunk=i + 1))
        json.loads(ws.receive_text())  # the stub's ack beep
        ws.send_text(
            json.dumps({"event": "stop", "streamSid": STREAM_SID, "stop": {"callSid": CALL_SID}})
        )

    # 100 frames of 20 ms: two seconds of audio on disk.
    wav_path = tmp_path / "recordings" / f"{CALL_SID}.wav"
    assert wav_path.is_file()
    with wave.open(str(wav_path), "rb") as wav:
        assert wav.getframerate() == 8000
        assert wav.getnframes() == 100 * twilio.BYTES_PER_FRAME

    # The log says where it landed and how long it runs.
    lines = [
        event
        for event in (
            json.loads(line)
            for line in Path(offline_settings.calls_log_path).read_text().splitlines()
        )
        if event["call_id"] == CALL_SID
    ]
    rec = next(line for line in lines if line["kind"] == "call.recording")
    assert rec["format"] == "wav"
    assert rec["duration_ms"] == 2000
    assert rec["bytes"] == wav_path.stat().st_size

    # And the line serves it back as a download.
    resp = client.get(f"/recordings/{CALL_SID}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert "attachment" in resp.headers["content-disposition"]
    assert f"{CALL_SID}.wav" in resp.headers["content-disposition"]

    missing = client.get("/recordings/CA-nothing")
    assert missing.status_code == 404
