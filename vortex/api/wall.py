"""``/api/wall/*`` as a FastAPI router.

Handlers still live next to the board helpers in ``observability.live``
(they share catalogue cache, SSE, product DB). This module is the public
HTTP surface: one ``APIRouter``, one prefix, included once at board import.
"""

from __future__ import annotations

from fastapi import APIRouter

# path (under /api/wall), live.py attribute, methods
_ROUTES: tuple[tuple[str, str, list[str]], ...] = (
    ("/timeline/{call_id}", "wall_timeline_api", ["GET"]),
    ("/timeline/{call_id}/stream", "wall_timeline_stream", ["GET"]),
    ("/business-insights", "wall_business_insights_api", ["GET"]),
    ("/analytics", "wall_analytics_api", ["GET"]),
    ("/agenda-options", "wall_agenda_options_api", ["GET"]),
    ("/doctor-suggest", "wall_doctor_suggest_api", ["GET"]),
    ("/doctor-agenda", "wall_doctor_agenda_api", ["GET"]),
    ("/clinic-settings", "wall_clinic_settings_get", ["GET"]),
    ("/clinic-settings", "wall_clinic_settings_put", ["PUT"]),
    ("/pathways", "wall_pathways_get", ["GET"]),
    ("/pathways", "wall_pathways_put", ["PUT"]),
    ("/patterns", "wall_patterns_get", ["GET"]),
    ("/patterns", "wall_patterns_put", ["PUT"]),
    ("/patient-timeline/{patient_id}", "wall_patient_timeline", ["GET"]),
    ("/patient-timeline/{patient_id}/reject", "wall_patient_timeline_reject", ["POST"]),
    ("/agenda/cancel-preview", "wall_cancel_preview_api", ["POST"]),
    ("/agenda/cancel", "wall_cancel_range_api", ["POST"]),
    ("/appointments/cancel", "wall_cancel_visit_api", ["POST"]),
    ("/home-overview", "wall_home_overview_api", ["GET"]),
    ("/live-calls", "wall_live_calls_api", ["GET"]),
    ("/live-calls/stream", "wall_live_calls_stream", ["GET"]),
    ("/occupancy", "wall_occupancy_api", ["GET"]),
    ("/voice-config", "wall_voice_config", ["GET"]),
    ("/voice-config", "wall_voice_config_put", ["PUT"]),
    ("/voice-preview", "wall_voice_preview", ["POST"]),
    ("/personalities", "wall_personalities", ["GET"]),
    ("/personalities", "wall_personality_create", ["POST"]),
    ("/personalities/{slug}", "wall_personality", ["GET"]),
    ("/personalities/{slug}", "wall_personality_put", ["PUT"]),
    ("/personalities/{slug}/activate", "wall_personality_activate", ["POST"]),
)


def attach(app) -> None:
    """Bind ``/api/wall`` onto the board FastAPI app. Call once, after live helpers exist."""
    from vortex.observability import live as board

    router = APIRouter(prefix="/api/wall", tags=["wall"])
    for path, name, methods in _ROUTES:
        router.add_api_route(path, getattr(board, name), methods=methods)
    app.include_router(router)
