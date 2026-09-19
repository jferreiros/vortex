"""line/ - transport: the WebSocket server, the Twilio wire format, one
pipeline per connection, the call lifecycle and the submit client.

Owner: the line lane.

Modules:
- ``server.py``        FastAPI app, /health, /calls, and the /ws handler.
- ``twilio.py``        inbound/outbound message models for Media Streams.
- ``session.py``       ``CallSession``: per-call context, tool memory, submit,
                      close, and the action a silent call falls back on.
- ``submit.py``        POST /api/v1/submit/<action> with the 30 s window rules.
- ``stub_voice.py``    beeps-only pipeline for offline runs and tests.
- ``pipecat_voice.py`` the real STT -> LLM -> TTS pipeline.
- ``privacy.py``       outgoing TTS guard: block session national_id/phone.
- ``ulaw.py``          G.711 helpers for tones and silence.
"""
