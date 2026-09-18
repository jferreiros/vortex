"""Dial the server like the platform does. N concurrent calls, Twilio format.

    uv run python scripts/fake_caller.py --url ws://localhost:7860/ws --calls 10 --seconds 3
    uv run python scripts/fake_caller.py --wav caller.wav        # 8 kHz mono 16-bit PCM

With no WAV it streams silence. Prints per-call frames sent and received.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets  # noqa: E402

from vortex.line.twilio import BYTES_PER_FRAME, FRAME_MS  # noqa: E402
from vortex.line.ulaw import pcm16_to_ulaw, silence  # noqa: E402


def load_audio(wav: str | None, seconds: float) -> list[bytes]:
    if wav:
        with wave.open(wav, "rb") as fh:
            assert fh.getnchannels() == 1 and fh.getframerate() == 8000 and fh.getsampwidth() == 2
            pcm = fh.readframes(fh.getnframes())
        ulaw = pcm16_to_ulaw(pcm)
    else:
        ulaw = silence(int(seconds * 1000))
    frames = [ulaw[i : i + BYTES_PER_FRAME] for i in range(0, len(ulaw), BYTES_PER_FRAME)]
    return [f for f in frames if len(f) == BYTES_PER_FRAME]


async def one_call(url: str, n: int, frames: list[bytes], from_number: str) -> None:
    call_sid = f"CA-fake-{int(time.time())}-{n:02d}"
    stream_sid = f"MZ-fake-{n:02d}"
    received = 0
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "sequenceNumber": "1",
                    "streamSid": stream_sid,
                    "start": {
                        "streamSid": stream_sid,
                        "callSid": call_sid,
                        "tracks": ["inbound"],
                        "customParameters": {"call_id": call_sid, "from_number": from_number},
                        "mediaFormat": {
                            "encoding": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "channels": 1,
                        },
                    },
                }
            )
        )

        async def reader() -> None:
            nonlocal received
            async for raw in ws:
                if json.loads(raw).get("event") == "media":
                    received += 1

        task = asyncio.create_task(reader())
        started = time.monotonic()
        for i, frame in enumerate(frames):
            await ws.send(
                json.dumps(
                    {
                        "event": "media",
                        "sequenceNumber": str(i + 2),
                        "streamSid": stream_sid,
                        "media": {
                            "track": "inbound",
                            "chunk": str(i + 1),
                            "timestamp": str(i * FRAME_MS),
                            "payload": base64.b64encode(frame).decode("ascii"),
                        },
                    }
                )
            )
            # Real time: one frame every 20 ms.
            target = started + (i + 1) * FRAME_MS / 1000
            await asyncio.sleep(max(0.0, target - time.monotonic()))
        await ws.send(json.dumps({"event": "stop", "streamSid": stream_sid, "stop": {}}))
        try:
            await asyncio.wait_for(task, timeout=3)
        except (TimeoutError, websockets.ConnectionClosed):
            task.cancel()
    print(f"{call_sid}: sent {len(frames)} frames, received {received}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:7860/ws")
    parser.add_argument("--calls", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=3.0, help="silence length without --wav")
    parser.add_argument("--wav", default=None, help="8 kHz mono 16-bit PCM WAV to stream")
    parser.add_argument("--from-number", default="+34612345678")
    args = parser.parse_args()
    frames = load_audio(args.wav, args.seconds)
    await asyncio.gather(
        *(one_call(args.url, n, frames, args.from_number) for n in range(args.calls))
    )


if __name__ == "__main__":
    asyncio.run(main())
