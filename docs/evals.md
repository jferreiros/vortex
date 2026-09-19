# Evals — how we know the agent works

The platform scores a `Run All` every ~33 minutes and never says which field
we lost. Measuring there is slow and blind. `evals/` measures here: in
seconds, against the fake clinic, with a diff against the last run. Three
layers, each runnable on its own.

| Layer | What it drives | Needs | Cost | Runs on |
| --- | --- | --- | --- | --- |
| 1 `evals/logic` | one tool, or a flow of tools, through `vortex/tools.py` | nothing | 0 | every PR |
| 2 `evals/conversation` | a scripted caller, turn by turn, as text | nothing (`rules` brain); `OPENAI_API_KEY` for the model | cents | every PR |
| 3 `evals/voice` | real STT/LLM/TTS providers on the same utterances | provider keys, `--real` | real money | by hand |
| 5 `evals/bench` | every candidate model on the layer-2 scenarios, one matrix | one provider key per model | perk models 0; the OpenAI reference ~1 € | schedule, by hand, and on prompt changes |

Every run writes `evals/results/<layer>/latest.json`, then rebuilds
`evals/results/summary.md` (for CI) and `evals/results/report.html` (for a
screen). The report leads with the verdict, then what broke and what got
fixed against the previous run and against the accepted baseline.

## The one command for CI

```bash
make evals            # == uv run python -m evals ci
```

What it does: layer 1, then layer 2 with the `auto` brain, then the report.
Exit code 1 if either layer has a `fail` or `error`. It needs:

- `uv sync --all-groups` (Python 3.12+; `.python-version` pins 3.14)
- no network, no key. With `OPENAI_API_KEY` set, layer 2 uses the real model
  in text mode and costs about 0.01 € per scenario. Without it, layer 2 uses
  the `rules` brain and says so in the report.
- write access to `evals/results/` (git-ignored)

What to publish from a CI job: `evals/results/summary.md` (paste it into the
job summary or the PR comment) and `evals/results/report.html` as an artifact.
`evals/results/summary.json` has the per-layer verdict and the broke/fixed
lists for a status check.

**Layer 3 is not part of `make evals` on purpose.** It spends money on every
run. Run it by hand (`make evals-voice REAL=1`) and it refuses to start above
`--max-eur` (default 0.50 €); every real run is appended to
`evals/results/voice/spend.json` so the total against the 100 € is one file
away. A nightly job could call it with a hard cap, but never a PR job.

## Reading the board

| Mark | Meaning |
| --- | --- |
| `pass` | the tool/flow/scenario produced the accepted result |
| `hollow` | passed, but every tool it touched is still a `contract.stub_*`. Green that proves nothing. Shrinks as lanes land. |
| `fail` | ran, result did not match. The detail names the field: `$.actions[0].slot: expected …, got …` |
| `error` | the tool raised, or the case is malformed (template typo, unknown tool) |
| `unverified` | the harness could not check it. Today: a `replay` run whose cassette no longer matches the prompt |
| `skipped` | out of scope for this run (a language the provider does not claim, the budget brake) |

A run's verdict is `FAIL` on any fail or error, `UNVERIFIED` if nothing
could be checked, else `PASS`. `hollow` never turns a board green on its own:
the count is shown beside `pass`, and the jury should read them apart.

## Layer 1 — logic (`evals/logic/cases/*.yaml`)

A case calls one tool through the registry (input validated, output
validated, logged) and matches the typed output; or runs a flow of tools,
threading results with `{{step.path}}`, and matches the actions that would
have been POSTed.

```yaml
- id: identity.dni.wrong_letter_is_invalid
  problem: 4
  tool: validate_national_id
  args: {value: "12345678A"}
  expect: {kind: dni, valid: false, expected_letter: "Z"}
```

Matching is *subset*: named keys must match, unnamed keys are ignored.
Timestamps compare as instants. Operators: `$in`, `$one_of`, `$not`,
`$absent`, `$present`, `$len`, `$min_len`, `$contains`, `$all`, `$regex`,
`$date` (see `evals/common/matching.py`). Expected slots are never typed by
hand: `{$earliest_slot: {specialty_id: general_practice}}` asks the fake
availability for the answer, the way the platform computes its own.

Files: `identity.yaml`, `diary.yaml`, `rules.yaml`, `triage.yaml` (every row
of the published routing table and every red flag), `flows.yaml` (one flow per
problem shape). Add a case by adding a list item; ids must be unique. The
call clock is Friday 18 September 2026 09:00 Madrid unless the case says
otherwise, so the answers do not drift.

## Layer 2 — conversation (`evals/conversation/scenarios/*.yaml`)

A scenario is what the caller says, turn by turn, and what the call must end
in. Corrections, interruptions (`interrupt_after_words`), silence
(`silence_secs`), third parties, injections.

```yaml
- id: p13.correction_final_request_wins
  problem: 13
  caller:
    - says: "…el martes por la tarde."
      means: {identify: {name: "Marta Ruiz", date_of_birth: "1985-03-12"},
              request: {intent: book, specialty_id: general_practice,
                        when: "this coming Tuesday", part_of_day: afternoon}}
    - says: "No, mejor el miércoles por la mañana."
      means: {request: {when: "this coming Wednesday", part_of_day: morning}}
    - says: "Vale, la primera."
      means: {accept: true}
  expect:
    actions: [{kind: book, patient_id: P00042,
               slot: {$earliest_slot: {specialty_id: general_practice, on: "2026-09-23", part_of_day: morning}}}]
    must_not_call: [prepare_cancel]
    privacy_of: [P00042]
```

Checks, in order of weight: the submitted **actions** (final state, exactly
what the leaderboard scores), the **trajectory** (`trajectory_contains` as an
ordered subsequence, `must_not_call`, `max_tool_calls`), and the
**transcript** (`privacy_of` forbids those patients' `national_id` and `phone`
on our turns after the platform's normalisation; `transcript_must_contain` /
`must_not_contain`). A scenario that ends without a submission gets the
session's fallback (`no-action/out_of_scope`) and the report says so.

Three brains play the receptionist:

- **`rules`** (default with no key). A deterministic reference receptionist
  that reads the `means:` annotations, never the words, and threads the
  tools the way the system prompt tells the model to. It proves the harness,
  the tools and the state threading. It says nothing about the model, and
  the report banner says exactly that.
- **`model`** (`--brain model`). The real model in text mode: the lane's
  system prompt, the lane's exposed tools, the caller's words, the runtime's
  request settings. Same tool registry, same fake clinic. Without `--model`
  it plays the receptionist the environment routes (`LLM_PROVIDER`), so it
  measures what the phone line runs; `--model provider/model` plays any
  other (`helmcode/deepseek-v4-flash`, `openai/gpt-4.1`). `--record` saves
  every answer under `evals/conversation/cassettes/<model slug>/`.
  `--repeat k` runs each scenario k times and reports pass^k (τ-bench's
  reliability metric): a scenario passes only if all k runs pass.
- **`openai`** (`--brain openai`, needs `OPENAI_API_KEY`). The same brain
  pinned to api.openai.com; what `auto` picks when that key is set.
- **`replay`** (`--brain replay`). Answers from the cassette, never calls the
  API, deterministic. If the prompt, the tools or the script changed since
  the recording, the scenario is `unverified`, never a silent pass. This is
  how a PR can check the model's decisions without a key.

Recommended loop: record cassettes once with `make evals-conversation
BRAIN=openai` plus `--record`, commit them, let CI replay; re-record when the
prompt changes.

## Layer 3 — voice (`evals/voice`)

Same utterances (Spanish, Catalan, Galician, Basque; names, a DNI read digit
by digit, a date, a site) through every stack in `evals/voice/pricing.yaml`,
clean and at 5 dB SNR (problem 12's spec), after an 8 kHz telephone round
trip. Per stack:

| Metric | How |
| --- | --- |
| STT final | end of caller audio → final transcript |
| LLM TTFT | request → first token of the reply |
| TTS TTFB | request → first audio byte |
| **perceived** | the sum: what the caller waits before we start to speak. p50 and p95 |
| WER | word error rate per language, clean vs noisy, after accent/punctuation/number normalisation |
| €/call, €/68 calls, €/weekend | list prices × the call profile in `pricing.yaml` (3 min on the wire, 1.5 min each way, 1,300 chars, 12k/600 tokens) |

Without keys it runs the **fake provider**: synthetic audio, invented
latencies and corruptions, real list prices. The report says SIMULATED in the
verdict and in a banner. The real adapters (`providers/deepgram.py`,
`cartesia.py`, `openai_audio.py`) are written from the vendors' references on
2026-09-18 and **have not been run against the real services**. First real
run: one stack, one language, `--max-eur 0.05`.

```bash
make evals-voice                                  # fake, free
make evals-voice REAL=1 MAX_EUR=0.10 STACKS=dg-41mini-oai
```

## Layer 5 — the model bench (`evals/bench`)

The question this layer answers: **which model for which job**, with a
number, so the routing in `.env` is a decision and not a habit.

```bash
make bench                                   # every default model with a key
make bench MODELS=helmcode/qwen3.6,helmcode/deepseek-v4-flash K=3 ONLY=p4.
make bench-publish                           # keep it: push to the bench-results branch
make bench-discord                           # tell the team
```

Every candidate in `evals/bench/models.yaml` plays the layer-2 scenarios
through the model brain: the lane's real system prompt, the lane's exposed
tools, the fake clinic, and the **runtime's request settings** (temperature,
token cap, reasoning off) from `vortex.models`. Scoring is layer 2's, by
final state. The bench adds the comparison, per model:

| Column | Meaning |
| --- | --- |
| pass | scenarios passed / played |
| weighted | pass rate with each scenario weighted by its problem's points (`evals/corpus/catalogue.py`) |
| p50 / p95 | LLM round trip per model call, request to complete reply. Not TTFT: the runtime streams, so the caller hears the first sentence earlier |
| tokens in / scenario | prompt tokens per scenario; the system prompt plus tools is ~18k per round |
| no submit | scenarios where the model hung up with nothing submitted (the session fallback fired) |
| cut | replies the `LLM_MAX_TOKENS` cap truncated |
| €/call (list) | one scored call at list price from the call profile; `perk` when the hackathon allowance pays, `n/a` when nobody verified a price |

Per problem and per scenario group the same counts are kept, so a model
that wins overall and loses problem 4 shows it.

**Routing.** `vortex/models.py` resolves one `ModelSpec` per role from the
environment: `receptionist` from `LLM_PROVIDER`/`LLM_MODEL`, `arbiter` from
`ARBITER_PROVIDER`/`ARBITER_MODEL`, any new role from
`LLM_<ROLE>_PROVIDER`/`LLM_<ROLE>_MODEL` with the receptionist as fallback.
The bench prints that routing next to its recommendation:

- receptionist: highest weighted pass rate among models whose LLM p95 stays
  under 4 s; ties go to the lower p50, then the lower list price.
- arbiter: highest weighted pass rate, latency ignored.

A recommendation is a number to argue with. The routing itself stays in
`.env`; nothing changes it for you.

**Persistence.** `evals/results/` is git-ignored, so `make bench-publish`
(`python -m evals publish`) pushes the latest run of every layer to the
`bench-results` branch: `runs/<layer>/<stamp>-<sha>.json` in full,
`latest/<layer>.json`, and `index.json` with the headline numbers. It builds
the commit with git plumbing, never touches your working tree, and retries
when someone else published first. The page at
**https://jferreiros.github.io/vortex/bench.html** reads that branch: routing,
matrix, per-problem table, trend across runs, per-scenario drill-down, and
every run ever published with a link to its JSON.

**GitHub and Discord.** The `bench` workflow runs on a schedule, by hand
(`workflow_dispatch` with models/repeat/only/max-eur), and when `main`
changes the prompt, the tools or the bench. It writes the matrix to the job
summary, uploads the report, publishes to the branch, and tries Discord.
Discord has refused Actions runner IPs before; `make bench-discord` from a
laptop or the VPS always works. The workflow needs the provider keys as
repository secrets (`HELMCODE_API_KEY` at least); without them every model
is skipped and the run says so.

**The brake.** `--max-eur` (default 1 €) refuses a run whose list-price
estimate is above it, at 90k input tokens per scenario. Perk models estimate
0. The OpenAI reference row costs about 1 € for 38 scenarios.

**Cassettes per model.** `--record` saves answers under
`evals/conversation/cassettes/<model slug>/`, so `--brain replay` can check
one model's decisions without a key.

## Baselines and diffs

Every saved run records the prompt it ran under: `mode.prompt_version` and
`mode.prompt_sha256`, beside `mode.model`. The prompt text itself is a
versioned file, `vortex/conversation/prompts/<version>.md`
(`<version>` = `v<N>-<slug>`); `vortex/conversation/prompt.py` loads the one
named by `VORTEX_PROMPT_VERSION`, or the latest on disk when the variable is
unset. A version file is never edited in place — a change is a new version,
the old one stays for the diff — so a run's score belongs to a
`(prompt_version, model)` pair, and a hypothesis is one pair compared
against another, not "the prompt" against a model.

`evals/baselines/<layer>.json` is the accepted reference, committed. Every run
is diffed against the previous run (`broke`, `fixed`, `new`, `gone`) and
against the baseline. `make evals-accept LAYER=logic` promotes the latest run:
for a run that carries the pair, the baseline file is keyed by it
(`<layer>__<prompt_version>__<model>.json`) and later runs diff against the
baseline of their own pair, falling back to the layer-wide file until one is
accepted. Accept after a lane lands and the board moved for a reason you can
name.

## Selftest

`make evals-selftest` runs `evals/selftest/`: matching operators, templates,
the diff, the leak check, the fallback, WER, the noise mixer. It tests the
harness, not the agent: a green board has to be a real green.

## What the numbers mean for the jury

- Score by final state, like the platform: the POST payload, not the transcript.
- Trajectory as a subset match, tolerant of extra calls, strict on forbidden ones.
- Deterministic checks first; no LLM judge on the PR path. A judge is worth
  adding only for the transcript's tone, and from a different model family.
- pass^k, not pass@1: a 70% scenario is a failing scenario at 68 calls.
- Perceived latency is measured where the caller is: end of speech to first
  audio, per stage, p50/p95. Vendors' self-reported numbers read about half a
  second early.
- Cost per call at list price, with the weekend total, so a provider choice is
  a number, not a feeling.

## Things the harness cannot do yet

- Drive the real voice pipeline (`vortex/line/pipecat_voice.py`) with audio.
  Pipecat ships an eval harness (`pipecat eval`) whose scripted scenarios look
  like ours, but it needs the bot on its RTVI eval transport (`-t eval`); the
  line lane would have to expose that beside the Twilio socket. Worth doing
  after the first real call works.
- Turn-taking metrics (false interruptions, missed end of turn) need audio
  through the VAD. Layer 3 measures the providers, not our VAD settings.
- Geocoding for `nearest_location` needs a network; those cases stay red offline.
