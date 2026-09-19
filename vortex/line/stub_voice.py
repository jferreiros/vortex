"""The no-keys voice pipeline. Beeps instead of talking.

It exercises the whole call lifecycle on the wire without STT, LLM or TTS:
greeting audio out, caller frames in, a beep back every few seconds, a fake
decision at the end, and the submission through the session's submit client.

Use it to prove the transport under load (``scripts/fake_caller.py``) and in
the smoke test. It never runs when the voice keys are set.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from vortex.contract import NoAction
from vortex.line import twilio, ulaw
from vortex.line.session import CallSession

log = logging.getLogger(__name__)

GREETING_TONE_MS = 400
ACK_EVERY_FRAMES = 100  # a short beep after every 2 s of caller audio


async def _send_ulaw(ws: WebSocket, session: CallSession, audio: bytes, *, paced: bool) -> None:
    """Send µ-law as 20 ms media frames. ``paced`` sleeps 20 ms between frames."""
    for frame in twilio.split_frames(audio):
        await ws.send_text(twilio.media_message(session.stream_sid, frame))
        session.media_frames_out += 1
        if paced:
            await asyncio.sleep(twilio.FRAME_MS / 1000)


async def run_stub_call(ws: WebSocket, session: CallSession) -> str:
    """Drive one call. Returns the reason the loop ended."""
    session.ctx.log.event("voice.mode", mode="stub")
    # The stub says nothing a prompt could use, but the lookup is what the real
    # pipelines do first and it is what the end-of-call fallback reads, so the
    # offline rehearsal opens the same way a scored call does.
    await session.resolve_caller_line()
    session.ctx.log.assistant_turn("[stub] greeting tone")
    await _send_ulaw(ws, session, ulaw.tone(660, GREETING_TONE_MS), paced=False)
    await ws.send_text(twilio.mark_message(session.stream_sid, "greeting"))

    reason = "stop"
    try:
        while True:
            text = await ws.receive_text()
            msg = twilio.parse_inbound(text)
            if isinstance(msg, twilio.MediaMessage):
                session.media_frames_in += 1
                session.record_frame(msg.media.audio_bytes())
                if session.media_frames_in % ACK_EVERY_FRAMES == 0:
                    session.ctx.log.user_turn(f"[stub] {session.media_frames_in} frames heard")
                    await _send_ulaw(ws, session, ulaw.tone(880, 120), paced=False)
            elif isinstance(msg, twilio.StopMessage):
                reason = "stop"
                break
            elif isinstance(msg, twilio.DtmfMessage):
                session.ctx.log.event("dtmf", digit=msg.dtmf.get("digit"))
            elif isinstance(msg, twilio.MarkMessage):
                session.ctx.log.event("mark.ack", name=msg.mark.get("name"))
    except WebSocketDisconnect:
        reason = "disconnect"

    # The stub "decides" a refusal so the submit path runs end to end.
    session.ctx.log.assistant_turn("[stub] no real conversation; submitting a typed refusal")
    await session.submit(NoAction(reason="out_of_scope"))
    return reason
