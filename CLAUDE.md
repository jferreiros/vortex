# Vortex — CLAUDE.md

Team Vortex, HackSpain 2026, track Prosper AI ("El Turno"). Five people, one weekend.

We build a WebSocket server that answers a clinic's inbound scheduling calls. The
organisers dial our socket in Twilio Media Streams format and play a patient. We
identify the caller, read the clinic's read-only EHR, and POST the action we
would have taken: `book`, `register`, `reschedule`, `cancel`, `no-action` or
`escalate`. A case passes only if our submitted actions match one the case
accepts. There is no partial credit. Full detail lives in `.claude/skills/`.

## Skills

Read the skill that matches your task before you write code:

| Skill | When |
| --- | --- |
| `setup` | Fresh clone: install, `.env`, smoke test, server, tunnel, endpoint, first practice call. Also `/setup` |
| `the-challenge` | What is scored, the 18 problems, weights, `problem_id`, which are open |
| `call-contract` | The WebSocket protocol, audio format, `call_id`, concurrency, time caps |
| `submit-action` | The six submit routes, exact fields, the 18 `reason` values, response codes |
| `clinic-api` | Read-only endpoints, auth header, matching and availability traps |
| `clinic-rules` | Dates, hours, closures, appointment type, provider/insurer traps, triage |
| `rehearse-and-measure` | Practice calls vs `Run All`, cooldowns, the scoring wall |

## Layout and lane ownership

One folder per lane. Work in your lane's folder. Ask before you touch another.

| Folder | Lane | What lives there |
| --- | --- | --- |
| `vortex/line/` | La Línea | WebSocket server, Twilio wire format, one pipeline per socket, µ-law audio, submit client with the 30 s window |
| `vortex/conversation/` | La Conversación | System prompt, turn-taking, interruptions, language, which tools the model sees |
| `vortex/identity/` | Identidad | Directory lookup, second-field confirmation, DNI/NIE check letter, new patient registration |
| `vortex/diary/` | La Agenda | Availability, relative dates to the exact minute in Europe/Madrid, site hours, reschedule and cancel |
| `vortex/rules/` | Las Reglas | Age limits, referrals, insurance matrix, provider matching, triage, nearest site, decline reasons |
| `vortex/clinic/` | shared | Read-only HTTP client for the clinic API and offline fixtures |
| `vortex/observability/` | shared | JSONL call log and the live view for the jury |

Shared files. Change them only with the whole team on the call:

- `vortex/contract.py` — the frozen tool contract. Read it first.
- `vortex/tools.py` — binds each contract signature to a lane function.
- `vortex/settings.py` — environment variables.

Each `vortex/<lane>/tools.py` starts by delegating to `contract.stub_*`. Replace the
stub call with real logic. Keep the signature.

## Install, run, test

Commands come from the `Makefile`. Python 3.12+, `uv` 0.9+.

```bash
uv sync --all-groups        # install (same as: make install)
cp .env.example .env        # every key is optional
make run                    # server on http://localhost:7860, socket at ws://localhost:7860/ws
make dev                    # same, with uvicorn --reload
make board                  # NiceGUI ops board / jury wall
make test                   # pytest, whole suite
make smoke                  # tests/test_smoke.py: connected/start/media/stop in process
make call N=10              # scripts/fake_caller.py dials the running server N times
make try-api                # scripts/api/try_api.py: hits every read-only clinic endpoint
                             #   live, dumps each raw JSON response under api_results/
make tunnel                 # ngrok http 7860
make tail                   # follow logs/calls.jsonl
make lint / make fmt        # ruff
```

`make test` and `make smoke` need no key and no network. Without `PLATFORM_API_KEY`
the server runs on `FakeClinicClient` fixtures and a dry-run submit client. Without
`DEEPGRAM_API_KEY` or `OPENAI_API_KEY` the stub voice pipeline runs. `GET /health`
reports the active mode. See `README.md` for the mode table.

## Hard rules

Each rule has a reason. The reason is the rule.

1. **Never submit nothing.** A call with no accepted record is an attempted, failed
   case. A call that cannot end in a booking still sends `NO_ACTION` with its
   `reason`. Otherwise a crashed agent and a correct refusal look the same.
2. **Identifiers come from the API, never from the caller or the model.**
   `patient_id` comes from `/directory`. `appointment_id` comes from
   `/patients/{id}/appointments`. `appointment_type_id` comes from `/availability`.
   Ids are compared exactly. A guessed id fails the case even when the slot is right.
3. **Everything is per socket. No shared state between calls.** `Run All` opens ten
   sockets at once and problem 2 opens twenty. Sharing a conversation, a session
   object or an in-flight `call_id` across sockets is the exact failure the challenge
   looks for. Build a fresh pipeline per connection.
4. **Do not change a contract signature without telling the team.** Five people
   program against `vortex/contract.py` at the same time. Adding an optional field
   is fine. Renaming or retyping is not. Say it on the call before you push.
5. **Work in your lane's folder.** The contract is the only shared surface. A push
   into another lane's folder is a merge conflict at 3 a.m.
6. **Tools return typed data or a typed `Rejection`. Never prose.** The model must
   not interpret a sentence to find a `reason`. The `reason` a tool returns is the
   `reason` we submit, and it names the rule that bit.
7. **The API key belongs to the team and is never committed.** It is shown once at
   the desk and is not stored anywhere readable. A leaked key is a rotation at the
   desk for all five of us. `.env` is git-ignored. Keep it that way.

## Other things every lane shares

- Time is Europe/Madrid, resolved against the moment the call connects, never the
  machine clock. `ToolContext.now` carries it.
- `slot` values carry an explicit offset and match the platform to the minute.
- Nothing is booked same-day. "The earliest" starts the day after the call.
- Every call is capped at three minutes. Get to a submission before the cap.
- Log every event with its `call_id` to `logs/calls.jsonl`. The live view builds on it.
- Write code, comments, docs and commit messages in English.
