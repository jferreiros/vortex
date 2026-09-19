"""The WebSocket server the platform dials.

Routes:
- ``GET  /health``   liveness + which modes are active (never the key values)
- ``GET  /calls``    recent call events grouped by call_id (feeds the live view)
- ``WS   /ws``       one call per connection, Twilio Media Streams format

Per connection: accept -> read ``connected`` and ``start`` -> open a
``CallSession`` -> run the voice pipeline (pipecat, Gemini Live demo, or
stub) -> close the session inside the 30-second submission window.

Owner: the line lane.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse

from vortex.line import twilio
from vortex.line.session import CallSession
from vortex.observability.calllog import group_by_call, read_calls, read_recent
from vortex.observability.discord_calls import enabled as discord_calls_on
from vortex.observability.discord_calls import notify_session
from vortex.observability.tracing import trace_call
from vortex.settings import Settings, get_settings

log = logging.getLogger("vortex.line")
DESIGN_CSS = Path(__file__).resolve().parent.parent / "observability" / "design.css"


class HandshakeError(RuntimeError):
    pass


async def read_handshake(ws: WebSocket, *, max_messages: int = 5) -> twilio.StartPayload:
    """Read until the ``start`` message. ``connected`` may or may not come first."""
    for _ in range(max_messages):
        msg = twilio.parse_inbound(await ws.receive_text())
        if isinstance(msg, twilio.StartMessage):
            return msg.start
        if isinstance(msg, twilio.ConnectedMessage):
            continue
        if isinstance(msg, twilio.StopMessage):
            raise HandshakeError("stop before start")
    raise HandshakeError("no start message in the first frames")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    log.info(
        "langfuse %s · discord calls %s",
        "on" if settings.langfuse_public_key and settings.langfuse_secret_key else "off",
        "on" if discord_calls_on() else "off",
    )
    app = FastAPI(title="Vortex", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", **settings.describe()}

    @app.get("/calls")
    async def calls(limit: int = 500, calls: int = 0, since: str = "") -> dict[str, object]:
        """Recent call events grouped by ``call_id`` — what the board reads.

        ``limit`` alone keeps the legacy behaviour: the last N *events*.

        ``calls`` and ``since`` bound by calls instead of events, which is the
        difference that matters: every group returned carries its
        ``call.started``, so a date-filtered reader never silently drops the
        call that straddled the tail. ``calls=60`` returns the newest sixty
        complete calls; ``since=<ISO-8601>`` returns every call started at or
        after the timestamp. Both run in a worker thread — parsing the log
        must not stall the loop that streams live call audio.
        """
        if calls or since:
            stamp = None
            if since:
                try:
                    stamp = datetime.fromisoformat(since)
                except ValueError:
                    raise HTTPException(400, f"invalid since: {since!r}") from None
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=UTC)
            grouped, meta = await asyncio.to_thread(
                read_calls,
                settings.calls_log_path,
                max_calls=calls or None,
                since=stamp,
            )
            return {"calls": grouped, "meta": meta}
        events = await asyncio.to_thread(read_recent, settings.calls_log_path, limit)
        return {"calls": group_by_call(events)}

    @app.get("/mic", response_class=HTMLResponse)
    async def mic() -> str:
        """Talk to the agent from a browser: mic in, agent audio out, Twilio wire."""
        return (Path(__file__).parent / "mic.html").read_text(encoding="utf-8")

    @app.get("/design.css")
    async def design_css() -> PlainTextResponse:
        """The design tokens for /mic. One source: vortex/observability/design.css."""
        return PlainTextResponse(DESIGN_CSS.read_text(encoding="utf-8"), media_type="text/css")

    @app.websocket(settings.ws_path)
    async def call_socket(ws: WebSocket) -> None:
        await ws.accept()
        connected_at = datetime.now(tz=__import__("zoneinfo").ZoneInfo("Europe/Madrid"))
        try:
            start = await read_handshake(ws)
        except (HandshakeError, WebSocketDisconnect, ValueError) as exc:
            log.warning("handshake failed: %s", exc)
            return

        session = CallSession.open(start, settings=settings, now=connected_at)
        log.info("call %s started (stream %s)", session.call_id, session.stream_sid)
        reason = "error"
        with trace_call(session):
            try:
                if settings.voice_is_gemini_live:
                    from vortex.line.gemini_live_voice import run_gemini_live_call

                    reason = await run_gemini_live_call(ws, session)
                elif settings.voice_is_pipecat:
                    from vortex.line.pipecat_voice import run_pipecat_call

                    reason = await run_pipecat_call(ws, session)
                else:
                    from vortex.line.stub_voice import run_stub_call

                    reason = await run_stub_call(ws, session)
            except WebSocketDisconnect:
                reason = "disconnect"
            except Exception:
                log.exception("call %s crashed", session.call_id)
                session.ctx.log.event("call.crashed")
                reason = "crashed"
            finally:
                # The submission window is still open for 30 s after the socket
                # closes. close() submits the fallback if nothing went out.
                await session.close(reason=reason)
                log.info("call %s ended (%s)", session.call_id, reason)
                notify_session(session)

    return app


app = create_app()
