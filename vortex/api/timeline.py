"""``/api/wall/timeline/*`` — one call's chat-and-tool timeline.

The JSON route is a snapshot; the stream pushes the same payload as
Server-Sent Events whenever it changes. Both read ``call_events`` through
``callfeed``, so a live call fills in without a reload.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from vortex.api import _shared

router = APIRouter()


@router.get("/timeline/{call_id}")
def wall_timeline_api(call_id: str) -> JSONResponse:
    """The chat+tool timeline the live-call page reads."""
    return JSONResponse(_shared.timeline_payload(call_id))


@router.get("/timeline/{call_id}/stream")
async def wall_timeline_stream(
    request: Request, call_id: str, once: bool = False
) -> StreamingResponse:
    """Same payload as GET /timeline/{id}, pushed as Server-Sent Events."""
    return _shared.sse_response(request, lambda: _shared.timeline_payload(call_id), once=once)
