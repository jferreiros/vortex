"""``/api/wall`` voice card and personality picker.

Both of these are proxied to the line rather than read here. The line is the
process that speaks: it owns the TTS credentials and the voice stack, and it
is the one that has to pick a change up on its next call. The board asks it
for the current card and hands writes straight through, so there is exactly
one reader of that state and no second copy to disagree.

A line that does not answer must not blank the page: the GETs fall back to
the seed defaults — personalities flagged ``offline`` so the page can say so
and grey out its buttons instead of pretending a write will land — and the
writes answer 502.

(These handlers moved here from ``vortex/observability/live.py`` unchanged;
the wire shape is exactly what the SPA already reads.)
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from vortex.line import personalities, voice_config
from vortex.observability import callfeed

log = logging.getLogger("vortex.api")
router = APIRouter()


@router.get("/voice-config")
async def wall_voice_config() -> JSONResponse:
    try:
        r = httpx.get(f"{callfeed.LINE_URL}/voice-config", timeout=callfeed.LINE_HEALTH_TIMEOUT_S)
        if r.status_code == 200:
            return JSONResponse(r.json())
    except Exception as exc:
        log.warning("voice-config fetch failed: %s", exc)
    return JSONResponse(voice_config.DEFAULTS)


@router.put("/voice-config")
async def wall_voice_config_put(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        r = httpx.put(f"{callfeed.LINE_URL}/voice-config", json=payload, timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@router.post("/voice-preview")
async def wall_voice_preview(request: Request) -> Response:
    """The Try button: streams back the line's MP3 of the greeting."""
    payload = await request.json()
    try:
        r = httpx.post(f"{callfeed.LINE_URL}/voice-preview", json=payload, timeout=20)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)
    if r.status_code == 200:
        return Response(content=r.content, media_type="audio/mpeg")
    try:
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception:
        return JSONResponse({"error": r.text}, status_code=r.status_code)


@router.get("/personalities")
async def wall_personalities() -> JSONResponse:
    try:
        r = httpx.get(f"{callfeed.LINE_URL}/personalities", timeout=callfeed.LINE_HEALTH_TIMEOUT_S)
        if r.status_code == 200:
            return JSONResponse(r.json())
    except Exception as exc:
        log.warning("personalities fetch failed: %s", exc)
    return JSONResponse(
        {
            "items": personalities.DEFAULTS,
            "active": personalities.DEFAULTS[0]["slug"],
            "offline": True,
            **personalities.catalog(),
        }
    )


@router.post("/personalities")
async def wall_personality_create(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        r = httpx.post(f"{callfeed.LINE_URL}/personalities", json=payload, timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@router.get("/personalities/{slug}")
async def wall_personality(slug: str) -> JSONResponse:
    try:
        r = httpx.get(
            f"{callfeed.LINE_URL}/personalities/{slug}", timeout=callfeed.LINE_HEALTH_TIMEOUT_S
        )
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@router.put("/personalities/{slug}")
async def wall_personality_put(slug: str, request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        r = httpx.put(f"{callfeed.LINE_URL}/personalities/{slug}", json=payload, timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@router.post("/personalities/{slug}/activate")
async def wall_personality_activate(slug: str) -> JSONResponse:
    try:
        r = httpx.post(f"{callfeed.LINE_URL}/personalities/{slug}/activate", timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)
