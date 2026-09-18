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
make board                  # http://localhost:8080/wall  Live (jury) · /  Calls (team) · /call/<id>
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
| any of `SONIOX_API_KEY`, the LLM key and base URL the active `LLM_PROVIDER` resolves to, or the credentials of `VORTEX_TTS_PROVIDER` (and of `VORTEX_TTS_PROVIDER_ALT` when it differs) | the stub voice pipeline: beeps out, counts frames in, submits a typed refusal at the end |

`GET /health` says which mode is active. `VORTEX_VOICE_MODE` and
`VORTEX_CLINIC_MODE` force a mode (see `.env.example`).

## Providers

Every provider is picked with an environment variable, so swapping one is a
`.env` edit and a restart — never a code change.

### LLM presets

`LLM_PROVIDER` names a preset that fills in the base URL, the key variable and
the model id. `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` override it
whenever they are set. Each preset reads its own key variable, so several can
live in one `.env` and the switch is one line. `ARBITER_PROVIDER` (default
`helmcode`, model `deepseek-v4-flash`) resolves the same way for the post-hangup
submission arbiter; nothing consumes it yet.

| `LLM_PROVIDER` | Base URL | Key | Default model |
| --- | --- | --- | --- |
| `custom` | `LLM_BASE_URL` | `LLM_API_KEY` | `Qwen/Qwen3-30B-A3B-Instruct-2507` |
| `helmcode` (default) | `HELMCODE_BASE_URL`, default `https://api.helmcode.com/v1` | `HELMCODE_API_KEY` | `qwen3.6` (also `deepseek-v4-flash`, `gemma4`, `glm5.3` add-on) |
| `cloudflare` | `https://api.cloudflare.com/client/v4/accounts/<CLOUDFLARE_ACCOUNT_ID>/ai/v1` | `CLOUDFLARE_API_TOKEN` | `@cf/qwen/qwen3-30b-a3b-fp8` (UNVERIFIED) |
| `vercel` | `https://ai-gateway.vercel.sh/v1` | `VERCEL_AI_GATEWAY_KEY` | `anthropic/claude-haiku-4.5` |

UNVERIFIED means nobody has called that URL or model id yet. `LLM_TEMPERATURE`,
`LLM_MAX_TOKENS`, `LLM_DISABLE_THINKING` and `LLM_REASONING_EFFORT` (default
`none`; Helmcode models reason by default otherwise) apply to every preset.

### TTS: a primary and an alternate

`VORTEX_TTS_PROVIDER` speaks Spanish. `VORTEX_TTS_PROVIDER_ALT` speaks any
language the primary cannot, and the pipeline routes each detected language to
whichever of the two can say it.

Both set to the same provider (the default, `google`/`google`) means one
service and the plain voice-swap path; `VORTEX_TTS_PROVIDER=elevenlabs` with
the default alternate gives ElevenLabs Spanish and Google ca/gl/eu.

| `VORTEX_TTS_PROVIDER` | Languages | Env vars |
| --- | --- | --- |
| `google` (default) | es / ca / gl / eu — the only one that covers all four. Chirp 3 HD for Spanish, Standard voices for ca/gl/eu | `GOOGLE_APPLICATION_CREDENTIALS` *or* `GOOGLE_TTS_CREDENTIALS_JSON`, `GOOGLE_TTS_VOICE_ES`, `GOOGLE_TTS_VOICE_CA`, `GOOGLE_TTS_VOICE_GL`, `GOOGLE_TTS_VOICE_EU` |
| `elevenlabs` | es | `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL`, `ELEVENLABS_VOICE_ID_ES` (no default — set it), `ELEVENLABS_BASE_URL` (optional gateway origin) |

STT is Soniox `stt-rt-v5` throughout: language identification on, clinic
vocabulary boosted, `SONIOX_API_KEY` and `SONIOX_STT_MODEL`.
## The console

`make board` serves the console. `/wall` is public: every call on the line,
the four stages it goes through, the transcript, each tool call in words, and
the outcome with the rule that applied. `/call/<id>` is one call, shareable.
`/`, `/evals` and `/bench` are for the team (`VORTEX_OPS_PASSWORD` in
production). The board reads calls from the line at `VORTEX_LINE_URL`.

## Design

Every screen (the jury wall, the ops board, the docs pages, `/mic`, the evals
report) follows one system: [`DESIGN.md`](DESIGN.md). White canvas, black
pills, hairline cards, system fonts, one dark surface per page, status as
traffic-light dots and nothing else in colour.

The tokens live in `vortex/observability/design.css`. Every front end loads
that file first. `docs/design.css` is a copy for GitHub Pages:

```bash
make design-sync            # refresh docs/design.css after you edit the tokens
make test                   # tests/test_design.py fails when the copy is stale
```

Before you add a colour, a font or a shadow, read `DESIGN.md`. The answer is no.

## Which model for which job — the bench

Every candidate model plays the same scripted calls through the real prompt
and the real tools; every run is kept; the page shows the routing the line
runs today next to what the numbers say.

**https://jferreiros.github.io/vortex/bench.html**

```bash
make bench                     # every default model with a key (evals/bench/models.yaml)
make bench K=3 ONLY=p4.        # pass^3 on one problem
make bench-publish             # keep it: push the run to the bench-results branch
make bench-discord             # tell the team
```

The routing is one variable per role: `LLM_PROVIDER`/`LLM_MODEL` for the
receptionist, `ARBITER_PROVIDER`/`ARBITER_MODEL` for the arbiter,
`LLM_<ROLE>_PROVIDER`/`LLM_<ROLE>_MODEL` for anything new. `vortex/models.py`
resolves them; the bench measures through the same resolver. Details in
`docs/evals.md`, "Layer 5".

## The board — what to do next

Every task is one GitHub issue. The priority order is published as a page:

**https://jferreiros.github.io/vortex/tasks.html**

It groups the 52 tasks into the blocks of the plan — what unblocks everything
tonight, then problem 1, problem 2, problem 3, then the problems as they open,
then the wall and the jury. Each task carries the condition that closes it.

Take a task by assigning its issue to yourself. One at a time, in your lane's
folder. The page reads the issues live, so the page and GitHub never disagree.

`docs/tasks.json` is the source. Edit a task there, then:

```bash
make tasks ARGS=--dry-run   # print what would change
make tasks                  # create what is missing, update what changed
```

It matches issues by the `[T14]` prefix, so running it twice is safe. It never
closes an issue and never touches an assignee: who took a task is decided in
GitHub, not in a file.

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
