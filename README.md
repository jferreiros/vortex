# Vortex — HackSpain 2026

Team **Vortex**. Track: **Prosper AI** (`prosper-ai`).

A voice agent that answers a clinic's inbound scheduling calls. The platform
dials our WebSocket in Twilio Media Streams format, plays a patient, and we
POST back the action we would have taken: book, register, reschedule, cancel,
no-action or escalate. Full brief: https://hackspain.app/tracks/prosper-ai

## Quick start

```bash
uv sync --all-groups        # Python 3.12+, uv 0.9+
cp .env.example .env        # every key is optional; see "Modes" below
make run                    # http://localhost:7860  (ws://localhost:7860/ws)
make board                  # http://localhost:8080  ops ·  http://localhost:8080/wall  jury
make smoke                  # in-process WebSocket test: connected/start/media/stop
make call                   # dial the running server with 1 fake call
make call N=10              # ... with 10 concurrent fake calls
make tunnel                 # ngrok http 7860 -> wss://<host>/ws for the dashboard
make test                   # the whole test suite
make tail                   # follow logs/calls.jsonl
```

`make smoke` and `make test` need no key and no network.

## Modes

The server always starts. Missing keys switch components to fake mode:

| Key(s) missing | What runs instead |
| --- | --- |
| `PLATFORM_API_KEY` | `FakeClinicClient` (fixtures in `vortex/clinic/fixtures.py`) and a dry-run submit client that logs instead of POSTing |
| `DEEPGRAM_API_KEY` or `OPENAI_API_KEY` | the stub voice pipeline: beeps out, counts frames in, submits a typed refusal at the end |

`GET /health` says which mode is active. `VORTEX_VOICE_MODE` and
`VORTEX_CLINIC_MODE` force a mode (see `.env.example`).

## Who touches what

One folder per person. Touch your folder; ask before you touch another.

| Folder | Owner | What lives there |
| --- | --- | --- |
| `vortex/line/` | transport | WebSocket server, Twilio wire format, one pipeline per socket, call lifecycle, submit client with the 30 s window |
| `vortex/conversation/` | dialogue | system prompt, turn-taking settings, interruptions, language, which tools the model sees |
| `vortex/identity/` | who calls | directory lookup, second-field confirmation, DNI/NIE check letter, new patient registration |
| `vortex/diary/` | the agenda | availability, relative dates to the exact minute in Europe/Madrid, site hours, reschedule and cancel |
| `vortex/rules/` | what the clinic refuses | age limits, referrals, insurance matrix, provider matching, triage, nearest site, closed reason vocabulary |
| `vortex/clinic/` | shared | read-only HTTP client for the clinic API + offline fixtures |
| `vortex/observability/` | shared | JSONL call log and the live view for the jury |

Shared files, change only with the whole team on the call:

- **`vortex/contract.py`** — the frozen tool contract. Every tool's input,
  output and signature, the six submission actions, the decline reasons,
  and a stub for every tool. Read it first.
- `vortex/tools.py` — binds each contract signature to the lane function.
- `vortex/settings.py` — environment variables.

## How the lanes plug together

```
platform ──ws──> line/server.py ── CallSession (per socket)
                      │                 ├─ ToolContext: call_id, now (Madrid), clinic, log, submitter
                      │                 └─ voice pipeline: stub or pipecat
                      ▼
            conversation/ prompt + turn settings
                      ▼
            tools.py ── call_tool(name, ctx, args) ──> identity/ diary/ rules/ tools.py
                                                          │
                                                   clinic/ (read-only API)
                      ▼
            line/submit.py ── POST /api/v1/submit/<action> ── within 30 s of socket close
                      ▼
            observability/ logs/calls.jsonl (one JSON line per event, tagged call_id)
```

Every lane function has this shape and is `async`:

```python
async def find_patient(ctx: ToolContext, args: FindPatientInput) -> FindPatientResult: ...
```

Each `vortex/<lane>/tools.py` starts by delegating to `contract.stub_*`.
Replace the stub call with real logic; keep the signature. The stub is the
reference shape, so a lane can run against fake data before the key arrives
and the transport can run a whole call tonight.

## Working offline vs. live

- Offline: `FakeClinicClient` answers from `vortex/clinic/fixtures.py`. It
  mirrors the traps in the docs (near-miss surnames, a provider on leave, two
  patients with the same name). Add fixtures when your lane needs a new shape.
- Live: set `PLATFORM_API_KEY` and `PLATFORM_API_BASE_URL`. `vortex/clinic/client.py`
  has a `TODO(clinic)` to align field names with `/api/openapi.json` once a
  key exists; the docs' prose is the only source today.

## Tunnel and endpoint

```bash
make tunnel                 # ngrok http 7860; use a European region and a static domain
```

Endpoint for the dashboard (Settings → Integration): `wss://<your-host>/ws`.
The scheme is `wss://`, the path is `/ws`. Keep the tunnel up for the whole
run: a Run All holds ten sockets open at once.

## Observability

`logs/calls.jsonl` gets one JSON line per event, every line tagged with
`call_id`: `call.started`, `turn.user`, `turn.assistant`, `tool.called`,
`tool.returned`, `submit.sent`, `submit.result`, `call.ended`, `call.summary`.
`GET /calls` returns the recent events grouped by call.

`make board` is the live view (NiceGUI, port 8080). `/wall` is public (jury).
`/` ops, `/evals` and `/bench` ask for `VORTEX_OPS_PASSWORD` when that env is
set (always in production). Play dials `scripts/fake_caller.py` against `:7860`.
Replay writes a scripted book/refuse into the JSONL. The wall tails `GET /calls`
when line is up, otherwise the JSONL file.

Production: `https://vortex.203.0.113.20.sslip.io/wall` (público) and
`https://vortex.203.0.113.20.sslip.io/` (equipo). That hostname is the VPS
IP, not a personal domain. Deploy: `deploy/compose.yml` on the VPS,
Traefik/Let's Encrypt. Never put the ops password in git.

## Team

| Member | Role |
| --- | --- |
| Ricardo Andrés Méndez Cavalieri | owner |
| Joaquín Ferreiros | member |
| Marta Sierra Obea | member |
| Cristina Caballero Rivas | member |
| Francisco Jimeno Fernández | member |
