"""Clinic-wall HTTP API.

Mounted on the board process (NiceGUI's FastAPI ``app``) under ``/api/wall``.
Same origin as the React SPA. Not a second server and not Edge Functions —
the line on ``:7860`` stays the scoring socket.

    from vortex.api.wall import attach
    attach(app)
"""
