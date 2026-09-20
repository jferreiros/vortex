"""Read-only view of the outbound-call pathways, for the wall.

The demo narrative is "every event fires its call at the right client";
this endpoint is the proof on screen: the registered pathways, the call
job each one triggers, whether that job has its script registered, and
whether the subsystem is enabled end to end (settings + Twilio + public
URL), so a misconfiguration shows up here before it shows up on stage.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from vortex.line.confirmation_calls import CALL_JOBS
from vortex.line.pathways import PATHWAYS
from vortex.settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/pathways/status")
async def list_pathways() -> JSONResponse:
    """Every registered pathway with its live wiring status."""
    settings = get_settings()
    twilio_ready = bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_from_number
        and settings.public_base_url
    )
    return JSONResponse(
        {
            "ok": True,
            "enabled": bool(settings.confirmation_calls),
            "twilio_ready": twilio_ready,
            "pathways": [
                {
                    "name": pathway.name,
                    "job": pathway.job,
                    "motivo": pathway.motivo,
                    "summary": pathway.summary,
                    "job_registered": pathway.job in CALL_JOBS,
                }
                for pathway in PATHWAYS.values()
            ],
        }
    )
