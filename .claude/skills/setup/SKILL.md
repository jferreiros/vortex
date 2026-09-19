---
name: setup
description: Use when someone has just cloned the repo, or the local server, tests or tunnel do not run — walks from clone to a practice call with the exact commands, no key required.
---

# Setup — from clone to a practice call

Every command below was run on 18 September against this repo. Python 3.12+
and `uv` 0.9+ are the only prerequisites. `.python-version` pins 3.14; `uv`
downloads it if missing.

## 1. Clone and install

```bash
git clone git@github.com:jferreiros/vortex.git
cd vortex
uv sync --all-groups        # same as: make install
```

`uv sync` creates `.venv/` and installs runtime and dev groups (pytest, ruff).
Every `make` target runs through `uv run`, so you never activate the venv.

## 2. Create `.env`

```bash
cp .env.example .env
```

Every value is optional. **The server starts and every test passes with an empty
`.env`.** Without keys the server runs against fake clinic data and a dry-run
submit client. Build your lane against that first.

| Variable | Meaning | Without it |
| --- | --- | --- |
| `PLATFORM_API_KEY` | The team's `pk-…` key. One per team, handed out at the desk. **Not in the repo. Ask on WhatsApp. Never commit it.** | `FakeClinicClient` fixtures + submit logs instead of POSTing |
| `PLATFORM_API_BASE_URL` | The API host the desk gives | Fake data; nothing is called |
| `DEEPGRAM_API_KEY` | Speech to text (nova-3) | Stub voice pipeline: beeps out, counts frames in |
| `OPENAI_API_KEY` | LLM and TTS | Stub voice pipeline |
| `OPENAI_LLM_MODEL`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE`, `DEEPGRAM_STT_MODEL` | Model overrides | Defaults from `.env.example` |
| `VORTEX_HOST`, `VORTEX_PORT`, `VORTEX_WS_PATH` | Bind address, port, socket path | `0.0.0.0`, `7860`, `/ws` |
| `VORTEX_VOICE_MODE` | `auto`, `stub`, `pipecat`, `gemini-live` | `auto`: pipecat only if both voice keys exist; `gemini-live` is jury demo only |
| `VORTEX_CLINIC_MODE` | `auto`, `fake`, `live` | `auto`: live only if the platform key exists |
| `VORTEX_CALLS_LOG` | JSONL event log path | `logs/calls.jsonl` |

`.env` and `.env.*` are git-ignored, except `.env.example`.

## 3. Run the smoke test

Do this before you start the server. It needs no key and no network.

```bash
make smoke                  # tests/test_smoke.py: connected/start/media/stop in process
make test                   # whole suite (24 tests on 18 Sep), ~2 s
make lint                   # ruff
```

If `make smoke` passes, the install is good.

## 4. Start the server

```bash
make run                    # uv run python -m vortex -> http://localhost:7860
# or
make dev                    # uvicorn --reload on the same port
```

Check it in a second terminal:

```bash
curl -s http://localhost:7860/health
```

Expected: `{"status":"ok","clinic":"fake","voice":"stub",...}` plus which keys
are set (never their values). `clinic` and `voice` tell you which mode runs.

Dial it locally the way the platform does:

```bash
make call                   # 1 fake call, Twilio format, 3 s of silence
make call N=10              # 10 concurrent fake calls
```

Each line prints frames sent and received. `GET /calls` and `make tail`
(`logs/calls.jsonl`) show the events per `call_id`.

## 5. Open the tunnel and build the endpoint URL

`ngrok` is not part of `uv sync`. Install it from ngrok.com and sign in.

```bash
make tunnel                                         # ngrok http 7860
# better, with a static domain claimed on your ngrok account:
ngrok http --url=<your-name>.ngrok-free.app 7860
```

Build the endpoint from the tunnel host:

- ngrok shows `https://a1b2c3d4.ngrok-free.app`.
- The endpoint is `wss://a1b2c3d4.ngrok-free.app/ws`.
- Scheme `wss://`, not `https://`. Path `/ws` (or your `VORTEX_WS_PATH`).
  **Forgetting the path is the most common mistake in the docs.**

Check it before you hand it over. `wscat -c wss://a1b2c3d4.ngrok-free.app/ws`
if you have `wscat`, or `make call` with the public URL:

```bash
uv run python scripts/fake_caller.py --url wss://a1b2c3d4.ngrok-free.app/ws --calls 1
```

## 6. Tell the platform where to call

Dashboard -> **Settings -> Integration**. Two fields:

| Field | Value |
| --- | --- |
| Endpoint | `wss://a1b2c3d4.ngrok-free.app/ws` — scheme and path included |
| Headers | Optional, one per line, e.g. `Authorization: Bearer …`. Values are write-only |

Saving replaces the whole configuration. The new endpoint applies to the **next**
run: a run snapshots its endpoint when admitted, so a run already queued dials
where it was queued. Only `wss://` or `ws://` endpoints are accepted.

## 7. Launch a practice call

1. Dashboard -> Problems -> pick a problem -> Statement tab.
2. Press **Call** beside a public case. The expected answer is printed beside it.
3. Wait for the call to end. 30 seconds between practice calls.
4. Open the **submissions** tab: transcript, recording, and which fields our
   record lost. Compare with the printed answer.
5. Locally, `make tail` shows the same call by `call_id`: `call.started`,
   `tool.called`, `submit.sent`, `submit.result`, `call.ended`.

Practice calls are free and score nothing. `Run All` is the scored lane; see
the `rehearse-and-measure` skill before you press it.

## Frequent problems

- **The ngrok URL changed.** A free ngrok URL changes on every restart and the
  dashboard still points at the old one. Claim a static domain
  (`ngrok http --url=<name>.ngrok-free.app 7860`) and set it once.
- **Audio lags or the call is cut for silence.** Pick a European ngrok region.
  Audio is real-time 20 ms frames; a tunnel through another continent adds delay
  to every one of them.
- **A call failed during a run.** If the tunnel or the server drops mid-run, that
  call is a failed case. The other calls in the wave continue. Keep the tunnel
  and the server up for the whole run. `Run All` holds ten sockets open at once.
- **`403 {"detail":"Invalid API key"}`.** The key is missing, mistyped, or was
  rotated at the desk. Ask the team for the current one.
- **`/health` says `clinic: fake` but you set the key.** The server reads `.env`
  at start. Restart it.
- **Tests fail because of your `.env`.** They should not: `tests/conftest.py`
  unsets the keys and forces stub and fake modes. If they still fail, run
  `uv sync --all-groups` again.
