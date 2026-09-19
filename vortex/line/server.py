"""The WebSocket server the platform dials.

Routes:
- ``GET  /health``              liveness + which modes are active (never the key values)
- ``GET  /calls``               recent call events grouped by call_id (feeds the live view)
- ``GET  /recordings/{call_id}`` the finished call's audio, as a WAV attachment
- ``WS   /ws``                  one call per connection, Twilio Media Streams format

Per connection: accept -> read ``connected`` and ``start`` -> open a
``CallSession`` -> run the voice pipeline (pipecat, Gemini Live demo, or
stub) -> close the session inside the 30-second submission window.

Owner: the line lane.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from vortex.line import twilio, voice_config
from vortex.line.recording import safe_call_id, wav_path_for
from vortex.line.session import CallSession
from vortex.line.sms_reminders import ReminderWorker, reminder_worker_status
from vortex.observability.calllog import group_by_call, read_calls, read_recent
from vortex.observability.discord_calls import enabled as discord_calls_on
from vortex.observability.discord_calls import notify_session
from vortex.observability.tracing import trace_call
from vortex.settings import Settings, get_settings

log = logging.getLogger("vortex.line")
DESIGN_CSS = Path(__file__).resolve().parent.parent / "observability" / "design.css"


class HandshakeError(RuntimeError):
    pass


async def _close_session(session: CallSession, reason: str) -> None:
    """Run ``session.close()`` to the end even if this task is cancelled.

    A socket dying must not take the end-of-call bookkeeping down with it:
    ``close`` writes the WAV, submits the fallback inside the 30-second
    window and logs ``call.summary``. Some hosts cancel the handler task the
    moment the socket closes (the test client does), and the first await
    that truly suspends - the WAV write's ``to_thread`` - would otherwise
    swallow the rest. Shielded and re-awaited, it finishes.
    """
    task = asyncio.ensure_future(session.close(reason=reason))
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()  # re-raise whatever close() itself raised


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



@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    """Start the day-before SMS worker while the server is up."""
    cfg: Settings = app.state.settings
    worker: ReminderWorker | None = None
    if cfg.sms_confirmations and cfg.sms_day_before_reminders:
        worker = ReminderWorker(cfg)
        worker.start()
    app.state.sms_reminder_worker = worker
    try:
        yield
    finally:
        if worker is not None:
            await worker.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    log.info(
        "langfuse %s · discord calls %s",
        "on" if settings.langfuse_public_key and settings.langfuse_secret_key else "off",
        "on" if discord_calls_on() else "off",
    )
    app = FastAPI(title="Vortex", version="0.1.0", lifespan=_app_lifespan)
    app.state.settings = settings

    @app.get("/health")
    async def health() -> dict[str, object]:
        worker = getattr(app.state, "sms_reminder_worker", None)
        return {
            "status": "ok",
            **settings.describe(),
            **reminder_worker_status(worker),
        }

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

    @app.get("/recordings/{call_id}")
    async def call_recording(call_id: str) -> FileResponse:
        """The finished call's audio: 8 kHz mono WAV, sent as an attachment.

        404 while the call still runs and when no recording was ever written -
        the WAV only exists once ``call.ended`` has flushed the buffer.
        """
        path = wav_path_for(call_id)
        if path is None:
            raise HTTPException(404, f"no recording for call {call_id}")
        return FileResponse(
            path, media_type="audio/wav", filename=f"{safe_call_id(call_id)}.wav"
        )

    @app.get("/mic", response_class=HTMLResponse)
    async def mic() -> str:
        """Talk to the agent from a browser: mic in, agent audio out, Twilio wire."""
        return (Path(__file__).parent / "mic.html").read_text(encoding="utf-8")

    @app.get("/design.css")
    async def design_css() -> PlainTextResponse:
        """The design tokens for /mic. One source: vortex/observability/design.css."""
        return PlainTextResponse(DESIGN_CSS.read_text(encoding="utf-8"), media_type="text/css")

    # ---- the wall's "Voz del agente" card ----------------------------------
    # The board proxies these three; the db file lives on this process's log
    # volume. Writes apply to calls opened after the PUT — a call in flight
    # keeps the voice it started with.

    @app.get("/voice-config")
    async def get_voice_config() -> dict[str, object]:
        return voice_config.load(settings).to_dict()

    @app.put("/voice-config")
    async def put_voice_config(
        payload: Annotated[dict | None, Body()] = None,
    ) -> dict[str, object]:
        return voice_config.save(settings, payload).to_dict()

    @app.post("/voice-preview")
    async def voice_preview(payload: Annotated[dict | None, Body()] = None) -> Response:
        """One MP3 of the greeting with the posted (or stored) settings, for
        the wall's Try button. Synthesised off the event loop — the Google
        client is blocking."""
        cfg = voice_config.preview_config(settings, payload)
        try:
            audio = await asyncio.to_thread(voice_config.synthesize_preview, settings, cfg)
        except Exception as exc:
            raise HTTPException(503, f"voice preview unavailable: {exc}") from exc
        return Response(content=audio, media_type="audio/mpeg")

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
                # closes. close() submits the fallback if nothing went out -
                # shielded, so a handler cancelled on disconnect cannot stop it.
                await _close_session(session, reason)
                log.info("call %s ended (%s)", session.call_id, reason)
                notify_session(session)

    return app


app = create_app()
