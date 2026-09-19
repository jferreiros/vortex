"""Ten calls at once over real sockets on localhost, no keys, no internet.

Starts uvicorn in a thread on a free port and dials it with ``websockets``.
Every call must get its own greeting, its own log lines and its own submission.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
import websockets

from vortex.line.server import create_app
from vortex.line.twilio import FRAME_MS
from vortex.line.ulaw import silence

CALLS = 10
FRAMES_PER_CALL = 100


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(offline_settings):
    port = _free_port()
    config = uvicorn.Config(
        create_app(offline_settings), host="127.0.0.1", port=port, log_level="warning"
    )
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"ws://127.0.0.1:{port}{offline_settings.ws_path}"
    srv.should_exit = True
    thread.join(timeout=5)


async def _one_call(url: str, n: int) -> tuple[str, int]:
    call_sid, stream_sid = f"CA-burst-{n:03d}", f"MZ-burst-{n:03d}"
    frame = silence(FRAME_MS)
    import base64

    payload = base64.b64encode(frame).decode("ascii")
    received = 0
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "streamSid": stream_sid,
                    "start": {
                        "streamSid": stream_sid,
                        "callSid": call_sid,
                        "customParameters": {"call_id": call_sid, "from_number": "+34600000000"},
                    },
                }
            )
        )

        async def reader() -> None:
            nonlocal received
            async for raw in ws:
                msg = json.loads(raw)
                if msg["event"] == "media":
                    assert msg["streamSid"] == stream_sid
                    received += 1

        task = asyncio.create_task(reader())
        for i in range(FRAMES_PER_CALL):
            await ws.send(
                json.dumps(
                    {
                        "event": "media",
                        "sequenceNumber": str(i + 2),
                        "streamSid": stream_sid,
                        "media": {
                            "chunk": str(i + 1),
                            "timestamp": str(i * 20),
                            "payload": payload,
                        },
                    }
                )
            )
            await asyncio.sleep(0.002)
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"event": "stop", "streamSid": stream_sid, "stop": {}}))
        try:
            await asyncio.wait_for(task, timeout=5)
        except (TimeoutError, websockets.ConnectionClosed):
            task.cancel()
    return call_sid, received


async def test_ten_concurrent_calls(server, offline_settings) -> None:
    results = await asyncio.gather(*(_one_call(server, n) for n in range(CALLS)))
    assert len(results) == CALLS
    for _, received in results:
        assert received >= 10, "every call must hear its own greeting"

    # Give close() a moment to write the summaries.
    log_path = Path(offline_settings.calls_log_path)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        lines = [json.loads(x) for x in log_path.read_text().splitlines()]
        summaries = [x for x in lines if x["kind"] == "call.summary"]
        if len(summaries) >= CALLS:
            break
        await asyncio.sleep(0.1)
    assert len(summaries) == CALLS

    call_ids = {x["call_id"] for x in summaries}
    assert call_ids == {call_sid for call_sid, _ in results}
    for s in summaries:
        # Offline dry_run never counts as accepted, so close() may retry the
        # same NO_ACTION once. Concurrency only cares that each call's actions
        # stay on that call_id.
        assert len(s["actions"]) >= 1
        assert all(a["payload"]["call_id"] == s["call_id"] for a in s["actions"])
    ended = {x["call_id"]: x for x in lines if x["kind"] == "call.ended"}
    assert all(e["media_frames_in"] == FRAMES_PER_CALL for e in ended.values())
