"""``/api/wall/*`` — the clinic SPA's only backend.

One ``APIRouter`` per topic, each one owning its own handlers, all mounted
under a single ``/api/wall`` prefix on the board's FastAPI app. The SPA is
served from the same origin (``vortex/observability/live.py``), so there is
no CORS and no second process.

Adding a route means adding it to its module's ``router``. Nothing here
enumerates handler names any more: the decorators are the route table.

``attach`` is called once, from ``live.py``, after the board app exists.
Import direction is strict — ``vortex.api`` never imports ``live``, so the
routers can be mounted on a bare FastAPI app in a test.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from vortex.api import (
    agenda,
    analytics,
    live_calls,
    pathways,
    patient_timeline,
    settings,
    timeline,
    voice,
)

#: Every module that contributes routes, in the order they are mounted.
MODULES = (
    timeline,
    live_calls,
    agenda,
    analytics,
    settings,
    patient_timeline,
    voice,
    pathways,
)


def build_router() -> APIRouter:
    """The whole ``/api/wall`` surface, ready to include on any app."""
    router = APIRouter(prefix="/api/wall", tags=["wall"])
    for module in MODULES:
        router.include_router(module.router)
    return router


def attach(app: FastAPI) -> None:
    """Bind ``/api/wall`` onto the board FastAPI app. Call once."""
    app.include_router(build_router())
