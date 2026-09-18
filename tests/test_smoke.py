"""Smoke test: one call over the wire, no keys, no network.

Opens a WebSocket against the app in-process, sends the Twilio Media Streams
sequence connected / start / media* / stop, and checks that the server answers
with media of its own, does not crash, and writes the call to the JSONL log.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from starlette.testclient import TestClient

from vortex.line import twilio, ulaw
from vortex.line.server import create_app

CALL_SID = "CA-smoke-0001"
STREAM_SID = "MZ-smoke-0001"


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


def test_one_call_over_the_wire(offline_settings) -> None:
    app = create_app(offline_settings)
    client = TestClient(app)

    with client.websocket_connect(offline_settings.ws_path) as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "sequenceNumber": "1",
                    "streamSid": STREAM_SID,
                    "start": {
                        "streamSid": STREAM_SID,
                        "callSid": CALL_SID,
                        "accountSid": "AC-fake",
                        "tracks": ["inbound"],
                        "customParameters": {"call_id": CALL_SID, "from_number": "+34612345678"},
                        "mediaFormat": {
                            "encoding": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "channels": 1,
                        },
                    },
                }
            )
        )

        # The greeting: at least one media frame back, tagged with our streamSid.
        first = json.loads(ws.receive_text())
        assert first["event"] == "media"
        assert first["streamSid"] == STREAM_SID
        payload = base64.b64decode(first["media"]["payload"])
        assert len(payload) == twilio.BYTES_PER_FRAME

        # Drain the rest of the greeting up to the mark.
        received = 1
        while True:
            msg = json.loads(ws.receive_text())
            if msg["event"] == "mark":
                assert msg["mark"]["name"] == "greeting"
                break
            assert msg["event"] == "media"
            received += 1
        assert received >= 10

        # Two seconds of caller audio (100 frames of 20 ms).
        for i in range(100):
            ws.send_text(_media(seq=i + 2, chunk=i + 1))

        # The stub acknowledges every 100 frames with a short beep.
        ack = json.loads(ws.receive_text())
        assert ack["event"] == "media"

        ws.send_text(
            json.dumps(
                {
                    "event": "stop",
                    "sequenceNumber": "200",
                    "streamSid": STREAM_SID,
                    "stop": {"accountSid": "AC-fake", "callSid": CALL_SID},
                }
            )
        )

    # The call log tells the whole story, tagged with the call_id.
    log_path = Path(offline_settings.calls_log_path)
    lines = [json.loads(line) for line in log_path.read_text().splitlines()]
    kinds = [line["kind"] for line in lines if line["call_id"] == CALL_SID]
    assert kinds[0] == "call.started"
    assert "submit.result" in kinds
    assert kinds[-1] == "call.summary"

    submitted = next(line for line in lines if line["kind"] == "submit.result")
    assert submitted["route"] == "/api/v1/submit/no-action"
    assert submitted["payload"]["call_id"] == CALL_SID
    assert submitted["result"]["status"] == "dry_run"

    summary = lines[-1]
    assert summary["actions"][0]["payload"]["reason"] == "out_of_scope"

    ended = next(line for line in lines if line["kind"] == "call.ended")
    assert ended["media_frames_in"] == 100
    assert ended["media_frames_out"] >= 10


def test_health_reports_modes(offline_settings) -> None:
    client = TestClient(create_app(offline_settings))
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["voice"] == "stub"
    assert body["clinic"] == "fake"
    assert body["has_platform_key"] is False


def test_start_without_connected_still_works(offline_settings) -> None:
    """The platform sends connected first, but the handshake tolerates its absence."""
    client = TestClient(create_app(offline_settings))
    with client.websocket_connect(offline_settings.ws_path) as ws:
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "streamSid": "MZ-2",
                    "start": {"streamSid": "MZ-2", "callSid": "CA-2", "customParameters": {}},
                }
            )
        )
        first = json.loads(ws.receive_text())
        assert first["event"] == "media"
        ws.send_text(json.dumps({"event": "stop", "streamSid": "MZ-2", "stop": {}}))
