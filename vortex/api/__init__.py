"""Clinic-wall HTTP API.

Mounted on the board process (NiceGUI's FastAPI ``app``) under ``/api/wall``.
Same origin as the React SPA. Not a second server and not Edge Functions —
the line on ``:7860`` stays the scoring socket.

    from vortex.api.wall import attach
    attach(app)

One module per topic, each exporting a ``router``:

===================== ===================================================
``timeline``          one call's chat + tool timeline, JSON and SSE
``live_calls``        the calls in progress, JSON and SSE
``agenda``            diary dropdowns, the month grid, the two cancels
``analytics``         Insights, Analytics, Home overview, occupancy
``settings``          clinic settings, pathways, patterns
``patient_timeline``  one patient's visits + calls, and rejections
``voice``             the voice card and the personality picker
===================== ===================================================

``_shared`` holds what the routers and the board's own NiceGUI pages both
need: the call feed, the card cache, the diary catalogue, the SSE envelope.
Nothing here may import ``vortex.observability.live`` — the import goes the
other way, and a cycle stops the board from starting.
"""
