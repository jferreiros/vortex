"""``/api/wall`` voice card and personality picker.

The board reads and writes these itself. Both the voice card
(``public.voiceconfig``) and the personas (``public.personalities``) are rows
in the same Postgres the line uses, so there is nothing to proxy: an HTTP hop
to ``:7860`` would only add a second way for the same table to be unreachable.
A board that is up can always answer, and a line that is down changes nothing
about what the clinic sees or saves.

Writes raise ``RuntimeError`` when Supabase is not configured — the card and
the rail must never report a save that went nowhere — and that becomes a 503
``store_unavailable``, the same shape ``vortex/api/settings.py`` uses.

The preview MP3 is synthesised here too: it is the same
``voice_config.synthesize_preview`` the line calls, off the event loop
because the TTS client blocks.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from vortex.line import personalities, voice_config
from vortex.settings import get_settings

log = logging.getLogger("vortex.api")
router = APIRouter()

STORE_DOWN = {"error": "store_unavailable"}


def _first_error(exc: ValidationError) -> str:
    """The first complaint, as a sentence: the form shows one line, and the
    validators already say which field and why. Same wording the line's own
    routes answer with, so the rail reads one ``error`` field either way."""
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"]) or "payload"
    return f"{field}: {first['msg'].removeprefix('Value error, ')}"


def _no_such_personality(slug: str) -> JSONResponse:
    return JSONResponse({"error": f"no personality named {slug}"}, status_code=404)


# ---- "Voz del agente" -------------------------------------------------------


@router.get("/voice-config")
def wall_voice_config() -> JSONResponse:
    """The stored card, or the defaults. Never fails: a call must sound the
    same whether or not the store answered."""
    return JSONResponse(voice_config.load(get_settings()).to_dict())


@router.put("/voice-config")
async def wall_voice_config_put(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        return JSONResponse(voice_config.save(get_settings(), payload).to_dict())
    except RuntimeError:
        log.warning("voice config not saved: no store configured")
        return JSONResponse(STORE_DOWN, status_code=503)


@router.post("/voice-preview")
async def wall_voice_preview(request: Request) -> Response:
    """The Try button: one MP3 of the greeting with the card's current
    sliders, saved or not."""
    payload = await request.json()
    settings = get_settings()
    cfg = voice_config.preview_config(settings, payload)
    try:
        audio = await asyncio.to_thread(voice_config.synthesize_preview, settings, cfg)
    except Exception as exc:
        log.warning("voice preview unavailable: %s", exc)
        return JSONResponse({"error": "voice_preview_unavailable"}, status_code=503)
    return Response(content=audio, media_type="audio/mpeg")


# ---- "Personalidades" -------------------------------------------------------


@router.get("/personalities")
def wall_personalities() -> JSONResponse:
    """The rail: every persona, who is on the phone, and the picker's
    catalogue. Same payload as the line's ``GET /personalities`` — one
    builder, one table."""
    return JSONResponse(personalities.listing(get_settings()))


@router.post("/personalities")
async def wall_personality_create(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        return JSONResponse(
            personalities.create(get_settings(), payload).to_dict(), status_code=201
        )
    except RuntimeError:
        return JSONResponse(STORE_DOWN, status_code=503)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except ValidationError as exc:
        return JSONResponse({"error": _first_error(exc)}, status_code=422)


@router.get("/personalities/{slug}")
def wall_personality(slug: str) -> JSONResponse:
    person = personalities.get(get_settings(), slug)
    if person is None:
        return _no_such_personality(slug)
    return JSONResponse(person.to_dict())


@router.put("/personalities/{slug}")
async def wall_personality_put(slug: str, request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        return JSONResponse(personalities.update(get_settings(), slug, payload).to_dict())
    except KeyError:
        return _no_such_personality(slug)
    except RuntimeError:
        return JSONResponse(STORE_DOWN, status_code=503)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except ValidationError as exc:
        return JSONResponse({"error": _first_error(exc)}, status_code=422)


@router.post("/personalities/{slug}/activate")
def wall_personality_activate(slug: str) -> JSONResponse:
    try:
        return JSONResponse(personalities.activate(get_settings(), slug).to_dict())
    except KeyError:
        return _no_such_personality(slug)
    except RuntimeError:
        return JSONResponse(STORE_DOWN, status_code=503)
