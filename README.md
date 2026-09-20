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
make supabase-migrate       # apply database/supabase/migrations/*.sql (needs SUPABASE_DB_URL)
make supabase-ping          # can the service-role key reach call_events?
make logs-discord           # redacted digest of the call log to Discord
make langfuse-check         # project URL + whether the live line has keys
```

`make smoke` and `make test` need no key and no network: the tests that want a
database skip themselves when Supabase is not configured.

## Day-before confirmation calls

With `VORTEX_CONFIRMATION_CALLS=true` plus the Twilio keys and
`VORTEX_PUBLIC_BASE_URL` (the tunnel host), an accepted booking also queues a
voice call for the day before the slot. `VORTEX_CONFIRMATION_CALLS` gates the
*whole* outbound-calling subsystem in `vortex/line/confirmation_calls.py`,
not just this one job: with it off, nothing is ever queued and the worker
never starts. The worker itself runs for the whole life of the server
process (`server.py`'s `_app_lifespan`, same place the day-before SMS
`ReminderWorker` starts) — it is not tied to any inbound `/ws` call, so a
scheduled row fires on its own poll even on a day the line takes no calls at
all. The worker dials the patient, this server's `/confirmation/*` routes
serve the TwiML, and `Gather input="speech"` captures the answer: confirmed /
not_coming / reschedule_requested. The question itself offers the move out
loud ("Si prefiere cambiarla, dígamelo y la movemos ahora mismo"), so the
caller learns the option exists without guessing (es, ca, gl, eu and en
scripts; the call inherits the language the caller used, Spanish by
default). No answer lands as `no_answer` or `unclear`. A reschedule answer does
not end the call: when the live voice pipeline runs behind the same server the
call hands the line to its colleague - "le paso con mi compañero, que es quien
le agenda las citas" - and `<Connect><Stream>` carries it back to `/ws` with the
appointment, the already-identified patient and the language on the start
message, so the booking agent's rebooking flow continues without re-asking any
data and the patient moves the appointment in the same call. Without the live
voice pipeline the stored callback promise stands. The Twilio-only segments
sound in the wall's own voice: when `ELEVENLABS_API_KEY` is set each line
(the question, the reprompt, the "le paso con mi compañero" bridge, the
fallback acknowledgements) is synthesised with the configured voice and rate
from `voiceconfig.db`, cached under
`logs/confirmation_audio/`, served by `GET /confirmation/audio/{name}` and
played with `<Play>`; without the key, or if synthesis fails, the TwiML
keeps Twilio's standard `<Say>` voice for that line. Every row lives in
`logs/confirmation_calls.json` — the hooks a waitlist filler or a retry/SMS
fallback would subscribe to. Try it: `uv run python scripts/try_confirmation_call.py`
(`--live --to <E.164> --base-url <tunnel>` to dial for real).

### `motivo`: why the call is happening

Every row also carries a `motivo` — a lighter, business-facing label than
`job` (which selects the TwiML/classification code; today only
`appointment_confirmation` exists). All five known values ride the *same*
job and the *same* yes/no flow; only the opening clause changes ("para
confirmar su cita" vs. "para recordarle su cita", ...). See
`vortex/line/confirmation_calls.py`'s `KNOWN_MOTIVOS` — it is a plain string,
not a closed enum, so a new value needs no code change to be accepted, only
an entry in `_MOTIVO_OPENING` to get its own opening line (it otherwise
opens with the `confirmacion` clause).

| `motivo` | When |
| --- | --- |
| `confirmacion` (default) | the day-before "will you come" call every accepted `BookAction` queues |
| `recordatorio` | a plain reminder, no explicit yes/no framing |
| `reprogramacion` | the clinic needs to move the appointment |
| `seguimiento` | a follow-up call about a past or upcoming visit |
| `call_now` | place it on the worker's very next poll — see below |

`uv run python scripts/try_confirmation_call.py --motivo recordatorio` prints
the reminder's opening line without dialling anything.

### Queuing a call by hand (for testing)

`logs/confirmation_calls.json` is a plain JSON list; the server rereads it on
every poll, so appending a row to it while the server is running is enough
to have the worker pick it up — no restart needed. A `call_now` row jumps
the 24h booking-gap rule and the lead-time schedule entirely: any row whose
`call_at` is already due (in the past, or `motivo: "call_now"` built through
`build_confirmation_call`, which forces `call_at` to "now") is claimed and
dialled on the worker's very next tick (`VORTEX_CONFIRMATION_POLL_SECS`,
30s by default).

```json
{
  "confirmation_id": "manual-test-0001",
  "to": "+34600000000",
  "appointment_at": "2026-09-25T10:00:00+02:00",
  "call_at": "2020-01-01T00:00:00+02:00",
  "language": "es",
  "provider_name": "Dra. Ortiz",
  "location_name": "Arenal Centro",
  "patient_id": "P00042",
  "job": "appointment_confirmation",
  "motivo": "call_now",
  "status": "pending",
  "detail": "",
  "twilio_call_sid": "",
  "transcript": "",
  "attempts": 0
}
```

Set `call_at` to a timestamp already in the past (or now) so `claim_due`
picks it up immediately regardless of `motivo`; `motivo: "call_now"` is what
makes the *intent* ("dial this immediately") legible in the row itself and
in the `calls` table once the outbound worker is wired to the database (see
`database/README.md`). Every unrecognised key in the JSON is ignored on
read, and any dataclass field left out — including `motivo` on a row
written before this feature — defaults to `"confirmacion"`, so older rows
keep working unmodified.

## Modes

The server always starts. Missing keys switch components to fake mode:

| Key(s) missing | What runs instead |
| --- | --- |
| `PLATFORM_API_KEY` | `FakeClinicClient` (fixtures in `vortex/clinic/fixtures.py`) and a dry-run submit client that logs instead of POSTing |
| any of `SONIOX_API_KEY`, `ELEVENLABS_API_KEY`, or the LLM key and base URL the active `LLM_PROVIDER` resolves to | the stub voice pipeline: beeps out, counts frames in, submits a typed refusal at the end |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | no store at all: calls are answered and submitted, nothing is persisted, every board screen reads zero |

There is one persistent store and it is Supabase/Postgres. No SQLite file, no
JSONL log, no dual write. Schema lives only in
`database/supabase/migrations/NNNN_*.sql` and is applied with
`make supabase-migrate`, which reads `SUPABASE_DB_URL` (the direct Postgres URI
from the dashboard, not the REST URL). The line and the board never use that
URI: they go through PostgREST with the service-role key, server-side only.

`GET /health` says which mode is active. `VORTEX_VOICE_MODE` (`auto`, `stub`,
`pipecat`) and `VORTEX_CLINIC_MODE` force a mode (see `.env.example`).

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
| `helmcode` (default) | `HELMCODE_BASE_URL`, default `https://api.helmcode.com/v1` | `HELMCODE_API_KEY` | `deepseek-v4-flash` (also `qwen3.6`, `gemma4`, `glm5.3` add-on) |
| `azure` | `<AZURE_OPENAI_ENDPOINT>/openai/v1` | `AZURE_OPENAI_API_KEY` (sent as a bearer token) | `AZURE_OPENAI_DEPLOYMENT`, default `gpt-4.1` |

Azure's OpenAI-compatible surface is the resource endpoint plus `/openai/v1`,
and the model id is the *deployment* name. `AZURE_OPENAI_API_VERSION` is only
needed on the older dated endpoints; on `/openai/v1` it is ignored.
`LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_DISABLE_THINKING` and
`LLM_REASONING_EFFORT` (default `none`; Helmcode models reason by default
otherwise) apply to both presets.

### TTS: ElevenLabs

One provider, one multilingual model, all five languages. A language switch is
a new voice id pushed at the running service, not a second service to route to.

| `VORTEX_TTS_PROVIDER` | Languages | Env vars |
| --- | --- | --- |
| `elevenlabs` (the only one) | en / es / ca / gl / eu | `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL` (default `eleven_flash_v2_5`), `ELEVENLABS_BASE_URL` (optional gateway origin) |

Which voice says which language, and which one the wall's female/male switch
picks, is a fixed preset in code — `conversation.language.VoicePreset` — not a
row of environment variables. `ELEVENLABS_VOICE_ID_DEFAULT` overrides its
female column for every language and `ELEVENLABS_VOICE_ID_ES` for Spanish
alone.

STT is Soniox `stt-rt-v5` throughout: language identification on, clinic
vocabulary boosted, `SONIOX_API_KEY` and `SONIOX_STT_MODEL`.
## The console

`make board` serves the clinic console. Team pages (`VORTEX_OPS_PASSWORD` in
production) sit behind a sidebar:

| Page | What it shows |
| --- | --- |
| `/` Overview | today's numbers, agents on duty, what needs a person, recent calls |
| `/agents`, `/agents/<slug>` | the Scheduling agent (real) and four roadmap agents marked Preview |
| `/calls`, `/calls/live` | every call with "why not booked", and the call in progress |
| `/patients` | everyone who called, with their last outcome |
| `/insights` | refusal reasons, handle times, tool latency, calls by hour |
| `/settings`, `/settings/rules`, `/settings/integrations`, `/settings/engineering` | sites, doctors, rules and the insurance matrix from the clinic API; providers; evals |

Public pages for the jury: `/wall` (the Live flow: the call in progress as
conversation, workflow and outcome, on a dark canvas made for a projector) and
`/call/<id>` (one call, shareable). Phone numbers are masked there. The board reads calls from
the line at `VORTEX_LINE_URL`. Every screen follows `DESIGN.md`.

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

## The explainer — one page for a jury or a new joiner

`docs/didactica.html` explains the whole system in plain Spanish: the vision, the
architecture end to end, one call step by step, the providers, the decisions and
what each one cost, security, resilience, the evals, where challenge 1 stands,
what is ready for challenge 2, the jury's published criteria, and the questions
we would rather not be asked, with answers. Every claim carries one of three
marks: fact, inference or pending.

It is **one file that opens with a double click** — no server, no build, no
network. The design tokens are inlined instead of linked:

```bash
make didactica              # re-inline design.css after you change the tokens
open docs/didactica.html    # or just double-click it
```

`make design-sync` calls it too, and `tests/test_didactica.py` fails when the
inlined copy is stale, when a nav link points at a missing section or when the
page grows a second dark surface. Published at
**https://docs.203.0.113.20.sslip.io/** (`deploy/compose.docs.yaml`).

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

## Research

`docs/research/` holds the September 2026 survey of the voice-agent market:
noise filters, STT vendors, turn detection, industry launches, structured-data
libraries and the TTS stack. Start at
[`docs/research/README.md`](docs/research/README.md): it ranks the moves by
points per hour and says what the repo already has.

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
| `vortex/api/` | shared | the FastAPI `/api/wall` router the clinic SPA calls |
| `vortex/observability/` | shared | call event writer and the live view for the jury |
| `database/supabase/migrations/` | shared | the only source of schema, `NNNN_*.sql` |

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
            observability/ public.call_events in Supabase (one row per event, tagged call_id)
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
- Live: set `PLATFORM_API_KEY` and `PLATFORM_API_BASE_URL`. `vortex/clinic/client.py`,
  `vortex/contract.py` and the fixtures follow `docs/api/openapi.json`, the
  platform's own spec. `make try-api` hits every read endpoint and saves each
  response under `api_results/` with the patient fields replaced by
  `[redacted]`, so a field-name drift shows up in minutes and no patient data
  lands on the disk.

## Tunnel and endpoint

```bash
make tunnel                 # ngrok http 7860; use a European region and a static domain
```

Endpoint for the dashboard (Settings → Integration): `wss://<your-host>/ws`.
The scheme is `wss://`, the path is `/ws`. Keep the tunnel up for the whole
run: a Run All holds ten sockets open at once.

## Observability

`public.call_events` in Supabase gets one row per event, every row tagged with
`call_id`: `call.started`, `turn.user`, `turn.assistant`, `tool.called`,
`tool.returned`, `submit.sent`, `submit.result`, `call.ended`, `call.summary`.
`GET /calls` returns the recent events grouped by call. With no Supabase keys
nothing is written and that endpoint is empty — the call itself is unaffected.

`make board` is the live view (NiceGUI, port 8080). `/wall` is public (jury).
`/` ops, `/evals` and `/bench` ask for `VORTEX_OPS_PASSWORD` when that env is
set (always in production). Play dials `scripts/fake_caller.py` against `:7860`.
The wall tails `GET /calls` when the line is up, and reads Supabase directly
otherwise.

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
