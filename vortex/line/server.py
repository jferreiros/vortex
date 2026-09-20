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
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import ValidationError

from vortex.line import confirmation_calls as confirmations
from vortex.line import personalities, twilio, voice_config
from vortex.line.confirmation_calls import ConfirmationWorker, confirmation_worker_status
from vortex.line.session import CallSession
from vortex.line.sms_reminders import ReminderWorker, reminder_worker_status
from vortex.observability import supabase_log
from vortex.observability.calllog import group_by_call
from vortex.observability.discord_calls import enabled as discord_calls_on
from vortex.observability.discord_calls import notify_session
from vortex.observability.tracing import trace_call
from vortex.settings import Settings, get_settings

log = logging.getLogger("vortex.line")
DESIGN_CSS = Path(__file__).resolve().parent.parent / "observability" / "design.css"


class HandshakeError(RuntimeError):
    pass


def _no_such_personality(slug: str) -> JSONResponse:
    """Same body shape as a validation failure, so the page reads one field."""
    return JSONResponse({"error": f"no personality named {slug}"}, status_code=404)


def _first_error(exc: ValidationError) -> str:
    """The first complaint, as a sentence: the form shows one line, and the
    validators already say which field and why."""
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"]) or "payload"
    return f"{field}: {first['msg'].removeprefix('Value error, ')}"


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
    """Start the day-before SMS worker and the outbound-call worker while the
    server is up.

    Both run for the app's whole lifetime, independent of any inbound
    ``/ws`` connection: a call queues a row (``session.py``'s
    ``_queue_confirmation_call``), it never has to drive the worker's next
    poll. So a scheduled row — confirmación, recordatorio, reprogramación,
    seguimiento, or a ``call_now`` row someone queued by hand — fires on its
    own schedule even if the line takes no inbound calls at all today.
    """
    cfg: Settings = app.state.settings
    worker: ReminderWorker | None = None
    if cfg.sms_confirmations and cfg.sms_day_before_reminders:
        worker = ReminderWorker(cfg)
        worker.start()
    app.state.sms_reminder_worker = worker
    call_worker: ConfirmationWorker | None = None
    if cfg.confirmation_calls:
        call_worker = ConfirmationWorker(cfg)
        call_worker.start()
    app.state.confirmation_call_worker = call_worker
    try:
        yield
    finally:
        if worker is not None:
            await worker.stop()
        if call_worker is not None:
            await call_worker.stop()


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
        call_worker = getattr(app.state, "confirmation_call_worker", None)
        return {
            "status": "ok",
            "store": settings.store,
            **settings.describe(),
            **reminder_worker_status(worker),
            **confirmation_worker_status(call_worker),
        }

    @app.get("/calls")
    async def calls(limit: int = 500, calls: int = 0, since: str = "") -> dict[str, object]:
        """Call events grouped by ``call_id``, read from ``public.call_events``.

        ``limit`` alone keeps the legacy behaviour: the last N *events*.

        ``calls`` and ``since`` bound by calls instead of events, which is the
        difference that matters: every group returned carries its
        ``call.started``, so a date-filtered reader never silently drops the
        call that straddled the tail. ``calls=60`` returns the newest sixty
        complete calls; ``since=<ISO-8601>`` returns every call started at or
        after the timestamp. Both run in a worker thread — a PostgREST round
        trip must not stall the loop that streams live call audio.
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
                supabase_log.fetch_calls, calls or None, stamp
            )
            return {"calls": grouped, "meta": meta}
        events = await asyncio.to_thread(supabase_log.fetch_recent, limit)
        return {"calls": group_by_call(events or [])}

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
        try:
            return voice_config.save(settings, payload).to_dict()
        except RuntimeError as exc:
            # No store: the card must not report a save that went nowhere.
            raise HTTPException(503, str(exc)) from exc

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

    # ---- the Clinic View's "Personalidades" picker --------------------------
    # Same shape as the voice card above: the board proxies these four and the
    # rows live in ``public.personalities``. Foundation only — activating a
    # persona stores the choice; reading it on the call (prompt tone,
    # greeting, TTS voice) is a separate change.

    @app.get("/personalities")
    async def get_personalities() -> dict[str, object]:
        people = personalities.list_all(settings)
        return {
            "items": [person.to_dict() for person in people],
            "active": next((p.slug for p in people if p.active), None),
            **personalities.catalog(),
        }

    @app.post("/personalities")
    async def post_personality(
        payload: Annotated[dict | None, Body()] = None,
    ) -> Response:
        try:
            return JSONResponse(personalities.create(settings, payload).to_dict(), status_code=201)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        except ValidationError as exc:
            return JSONResponse({"error": _first_error(exc)}, status_code=422)

    @app.get("/personalities/{slug}")
    async def get_personality(slug: str) -> Response:
        person = personalities.get(settings, slug)
        if person is None:
            return _no_such_personality(slug)
        return JSONResponse(person.to_dict())

    @app.put("/personalities/{slug}")
    async def put_personality(
        slug: str,
        payload: Annotated[dict | None, Body()] = None,
    ) -> Response:
        try:
            return JSONResponse(personalities.update(settings, slug, payload).to_dict())
        except KeyError:
            return _no_such_personality(slug)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        except ValidationError as exc:
            # One sentence the form can show, not pydantic's whole report.
            return JSONResponse({"error": _first_error(exc)}, status_code=422)

    @app.post("/personalities/{slug}/activate")
    async def activate_personality(slug: str) -> Response:
        try:
            return JSONResponse(personalities.activate(settings, slug).to_dict())
        except KeyError:
            return _no_such_personality(slug)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)

    # ---- outbound confirmation calls (Twilio fetches these) -----------------
    # Twilio posts application/x-www-form-urlencoded; parsed by hand so the app
    # keeps its no-python-multipart dependency footprint.

    async def _form(request: Request) -> dict[str, str]:
        from urllib.parse import parse_qsl

        body = (await request.body()).decode("utf-8", errors="replace")
        return dict(parse_qsl(body))

    def _call_store() -> confirmations.ConfirmationStore:
        return confirmations.confirmation_store_from_settings(settings)

    async def _audio_url(text: str, language: str) -> str | None:
        """A public <Play> URL for one line in the wall's voice, or None for <Say>."""
        name = await confirmations.ensure_confirmation_audio(settings, text, language)
        if name is None:
            return None
        base = settings.public_base_url.rstrip("/")
        return f"{base}/confirmation/audio/{name}"

    @app.get("/confirmation/audio/{name}")
    async def confirmation_audio(name: str) -> Response:
        """One synthesised confirmation-call line, for Twilio's <Play>."""
        if not confirmations.valid_audio_name(name):
            return Response(status_code=404)
        path = confirmations.confirmation_audio_dir(settings) / name
        if not path.is_file():
            return Response(status_code=404)
        return Response(content=path.read_bytes(), media_type="audio/mpeg")

    @app.api_route("/confirmation/twiml", methods=["GET", "POST"])
    async def confirmation_twiml(cid: str = "") -> Response:
        """The TwiML for one queued confirmation call: the question + Gather."""
        call = await _call_store().get(cid) if cid else None
        if call is None:
            return Response(status_code=404)
        base = settings.public_base_url.rstrip("/")
        job = confirmations.job_for(call.job)
        audio_url = await _audio_url(job.ask_words(call, reprompt=False), call.language)
        return Response(
            content=job.ask_twiml(call, base, attempt=1, reprompt=False, audio_url=audio_url),
            media_type="application/xml",
        )

    @app.post("/confirmation/result")
    async def confirmation_result(request: Request, cid: str = "", attempt: int = 1) -> Response:
        """Gather's action: classify the spoken answer and store the outcome."""
        store = _call_store()
        call = await store.get(cid) if cid else None
        if call is None:
            return Response(status_code=404)
        form = await _form(request)
        transcript = (form.get("SpeechResult") or "").strip()
        job = confirmations.job_for(call.job)
        outcome = job.classify(transcript, call.language)
        if outcome == "unknown" and attempt < 2:
            base = settings.public_base_url.rstrip("/")
            audio_url = await _audio_url(job.ask_words(call, reprompt=True), call.language)
            xml = job.ask_twiml(call, base, attempt=attempt + 1, reprompt=True, audio_url=audio_url)
            return Response(content=xml, media_type="application/xml")
        status: confirmations.ConfirmationStatus = outcome if outcome != "unknown" else "unclear"
        detail = "answered" if outcome != "unknown" else "unclear_response"
        # A patient who wants to move the appointment moves it in the same
        # call: the confirmation call hands the line to its colleague, the
        # booking agent, and its existing rebooking conversation takes over.
        # Without the live voice pipeline there is no colleague to hand the
        # line to, so the stored callback promise stands.
        handoff_xml: str | None = None
        if outcome == "reschedule_requested" and (
            settings.voice_is_pipecat or settings.voice_is_gemini_live
        ):
            bridge = confirmations.handoff_bridge_text(call.language)
            audio_url = await _audio_url(bridge, call.language)
            handoff_xml = confirmations.twiml_handoff_to_agent(
                call, confirmations.handoff_ws_url(settings.public_base_url), audio_url=audio_url
            )
            detail = "handoff_to_voice_agent"
        await store.update(
            call.confirmation_id,
            status=status,
            detail=detail,
            transcript=transcript,
            attempts=attempt,
        )
        confirmations.sync_call_now_outcome_to_db(
            confirmation_id=call.confirmation_id,
            motivo=call.motivo,
            settings=settings,
            status=status,
            transcript=transcript,
            detail=detail,
        )
        log.info("confirmation %s -> %s (%r)", call.confirmation_id, status, transcript[:80])
        if handoff_xml is not None:
            return Response(content=handoff_xml, media_type="application/xml")
        text = (
            job.ack(outcome, call.language)
            if outcome != "unknown"
            else job.final_unclear(call.language)
        )
        audio_url = await _audio_url(text, call.language)
        return Response(
            content=confirmations.twiml_say(text, call.language, audio_url=audio_url),
            media_type="application/xml",
        )

    @app.post("/confirmation/noresult")
    async def confirmation_noresult(cid: str = "") -> Response:
        """The Gather timed out with no speech: the call connected, nobody spoke."""
        store = _call_store()
        call = await store.get(cid) if cid else None
        if call is None:
            return Response(status_code=404)
        await store.update(
            call.confirmation_id,
            status="unclear",
            detail="no_speech",
        )
        confirmations.sync_call_now_outcome_to_db(
            confirmation_id=call.confirmation_id,
            motivo=call.motivo,
            settings=settings,
            status="unclear",
            detail="no_speech",
        )
        text = confirmations.job_for(call.job).no_speech(call.language)
        audio_url = await _audio_url(text, call.language)
        return Response(
            content=confirmations.twiml_say(text, call.language, audio_url=audio_url),
            media_type="application/xml",
        )

    @app.post("/confirmation/status")
    async def confirmation_status(request: Request, cid: str = "") -> Response:
        """Twilio's terminal call statuses: catch the calls that never answered.

        The result webhook owns the answered outcomes; this only fills the rows
        still ``calling`` when the call ends, so a hangup mid-question and a
        phone that never picked up both land somewhere countable.
        """
        store = _call_store()
        call = await store.get(cid) if cid else None
        if call is None:
            return Response(status_code=404)
        form = await _form(request)
        call_status = (form.get("CallStatus") or "").strip()
        call_sid = (form.get("CallSid") or "").strip()
        if call.status == "calling":
            terminal_status: confirmations.ConfirmationStatus | None = None
            terminal_detail = call_status
            if call_status in ("no-answer", "busy"):
                terminal_status = "no_answer"
            elif call_status in ("failed", "canceled"):
                terminal_status = "failed"
            elif call_status == "completed":
                terminal_status = "unclear"
                terminal_detail = "hangup_before_answer"
            if terminal_status is not None:
                await store.update(
                    call.confirmation_id,
                    status=terminal_status,
                    detail=terminal_detail,
                    twilio_call_sid=call_sid or call.twilio_call_sid,
                )
                confirmations.sync_call_now_outcome_to_db(
                    confirmation_id=call.confirmation_id,
                    motivo=call.motivo,
                    settings=settings,
                    status=terminal_status,
                    detail=terminal_detail,
                )
        return Response(status_code=204)

    # ---- live Twilio Voice: inbound ring + outbound "call me" ---------------
    # Twilio fetches these as TwiML. Both bridge the PSTN leg into /ws so the
    # receptionist pipeline (same Media Streams socket the platform uses) talks.

    def _voice_stream_twiml(form: dict[str, str]) -> Response:
        base = settings.public_base_url.strip()
        if not base:
            return Response(
                content="VORTEX_PUBLIC_BASE_URL is unset",
                status_code=400,
                media_type="text/plain",
            )
        ws_url = twilio.public_ws_url(base, settings.ws_path)
        params = {
            "call_id": (form.get("CallSid") or "").strip(),
            "from_number": (form.get("From") or form.get("To") or "").strip(),
        }
        return Response(
            content=twilio.twiml_connect_stream(ws_url, params),
            media_type="application/xml",
        )

    @app.api_route("/voice/incoming", methods=["GET", "POST"])
    async def voice_incoming(request: Request) -> Response:
        """A real number rang us: connect the caller into the receptionist."""
        form = await _form(request) if request.method == "POST" else dict(request.query_params)
        return _voice_stream_twiml(form)

    @app.api_route("/voice/outbound", methods=["GET", "POST"])
    async def voice_outbound(request: Request) -> Response:
        """We dialled a phone: connect the answered party into the receptionist."""
        form = await _form(request) if request.method == "POST" else dict(request.query_params)
        return _voice_stream_twiml(form)

    @app.api_route("/voice/status", methods=["GET", "POST"])
    async def voice_status() -> Response:
        """Twilio terminal statuses for live PSTN calls. We log, we do not score."""
        return Response(status_code=204)

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
