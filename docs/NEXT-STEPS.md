# Next steps — evals, prompt versioning, hypothesis worktrees

Written Saturday 19 September 2026, 01:40 Europe/Madrid. State of `main` at
`5ff7514`. Read this before you touch the evals or the prompt.

## 1. Where we are

- The agent speaks. `voice: pipecat` on the public endpoint since 01:05
  (Google TTS credential deployed to `/home/factory/personal/vortex/deploy/.env`).
- Endpoint: `wss://line.167.233.80.47.sslip.io/ws`. Verified by dialling it.
- Overnight a self-improving loop against `Run All` took us to first place.
  Then the agent regressed and we can no longer match that score. **The loop
  optimised against four private cases per problem with no local gate.** That
  is a noisy signal and a regression has nowhere to be caught before it ships.
- Branch `feat/voice-loop` (4 commits) is **not merged**. Sections 2 and 3
  depend on it: the roster verification, the call-log judge, the discovery
  sweep. Merge it first.

## 2. How good are the evals — the honest answer

The question that matters: **if the agent passes our evals, does it pass the
platform's?** Today: **no, not yet.** Our evals check necessary conditions.
None of them checks the sufficient one. Here is why, layer by layer.

| Layer | What it runs | Clinic | Verdict |
| --- | --- | --- | --- |
| 1 `logic` | tools in isolation, 132 cases | **fake**, invented patients | shape only |
| 2 `conversation` | text transcript → LLM → tools → action, 57 scenarios | **fake**, invented patients | shape only; blind to audio and turn-taking |
| 3 `voice` | STT/TTS provider bench | — | never run against real providers |
| 4 `corpus` | judge + probes + roster reproduction | **real snapshot** | the only layer with ground truth |
| 5 `bench` | layer 2 across 18 models | **fake** | compares models on non-predictive cases |

**What is solid.** Layer 4's judge is a verified replica of the platform
scorer: all 73 official answers pass it, and all 130 published BOOK answers
reproduce against the real clinic (`make evals-verify`). If the judge says
pass on a record, the platform says pass on that record. The clinic snapshot
in `evals/corpus/world/` is the real catalogue, real patients, real slots.

**What is missing.** Nothing runs the **73 official cases through the agent**
and judges the result. Layers 1, 2 and 5 use `FakeClinicClient` and patients
like `P00042 / Marta Ruiz` that do not exist. So a scenario passing in layer 2
tells you the prompt can drive the tools — it does not tell you the agent
would book `P00001` at `PR01` on the slot the case accepts.

Concrete proof from tonight, one real call on the deployed agent:

```
find_patient  {'name': 'Josefa Domínguez Navarro', 'national_id': '48064716Y'}  → P00001 ✓
find_slots    {'patient_id': 'P00001', 'specialty_id': 'general_medicine'}      → nothing
submit        no_availability                                                   ✗ (answer was BOOK)
```

`general_medicine` does not exist. The real ids are `general_practice`,
`paediatrics`, `dermatology`, `orthopaedics`, `gynaecology`, `physiotherapy`.
The model invents the id, gets nothing, and fails problem 1. Layer 2 reported
this as "expected book, got no-action" on two different models — it could see
the symptom, not the cause, because its fake clinic does not have the real
catalogue either.

So: **the evals are valuable as a judge and as ground truth. They are not yet
a predictor.** One step turns them into one.

## 3. Step 0 — the replay runner (do this before anything else)

Build `make evals-replay`: play each of the 73 official cases through the
agent in text mode, against the **real snapshot**, and judge the record with
the platform judge. Every piece exists; none is wired together.

| Piece | Where | Status |
| --- | --- | --- |
| The 73 cases with `caller_prompt` + `persona` | `evals/corpus/cases/public-cases.json` | done |
| A scripted caller that plays a persona | `evals/conversation/brains/rules.py` | done, needs the persona as input |
| The agent in text mode with the real prompt and tools | `evals/conversation/brains/openai_brain.py` | done |
| A `ToolContext` on the real clinic | `evals/common/context.py` | **uses `FakeClinicClient`; needs a `SnapshotClinicClient`** |
| The judge | `evals/corpus/judge.py` | done |
| Per-problem points | `evals/corpus/catalogue.py` | done |

The one new class is `SnapshotClinicClient`: same interface as
`FakeClinicClient`, answers from `evals/corpus/world/`. Directory lookups from
`patients.json`, diaries from `appointments.json`, availability from
`availability-per-patient.json`. About 150 lines.

Output: **a score out of 196, offline, in a minute, on the deployed prompt and
model.** That number is the local proxy for the leaderboard. Its trend is what
the loop optimises. Its baseline is what a PR must not lower.

Acceptance: run it on the current prompt. It should fail problem 1 for the
`general_medicine` reason above. Fix the prompt (add the six specialty ids the
way it already lists the three sites). Problem 1 turns green. That is the
first commit that a predictor caught.

## 4. Prompt versioning

The prompt is `vortex/conversation/prompt.py`, one file, no version. A run
records its model (`mode.model`) but not its prompt, so two runs cannot be
compared with confidence.

1. Move the system prompt text to `vortex/conversation/prompts/<version>.md`,
   `<version>` = `v<N>-<slug>` (`v3-specialty-ids`). `prompt.py` loads the one
   named by `VORTEX_PROMPT_VERSION`, default = latest.
2. Record `prompt_version` and its sha256 in every `RunResult.mode`, beside
   `model`. `evals/common/results.py`.
3. Baselines keyed by `(prompt_version, model)`, not by layer alone.
   `make evals-accept` promotes a pair.
4. Never edit a prompt file in place. A change is a new version. The old one
   stays for the diff.

## 5. Hypothesis worktrees

One worktree per hypothesis. A hypothesis is a `(prompt_version, model)` pair
and a sentence saying why it should score higher.

```bash
git worktree add ../wt-h7 -b hyp/7-qwen-terse-prompt
cd ../wt-h7
# write vortex/conversation/prompts/v7-terse.md; set VORTEX_PROMPT_VERSION=v7-terse
LLM_PROVIDER=helmcode LLM_MODEL=qwen3.6 make evals-replay      # the 196-point number
make evals-bench MODELS=helmcode/qwen3.6 K=3                     # pass^3 stability
make bench-publish                                              # to bench-results
```

The bench already compares 18 models on the layer-2 scenarios and publishes a
page. Point it at the replay runner once Step 0 exists, and the same page
compares hypotheses on the predictive number.

Rule for the matrix: **a model is not bad until it has a prompt written for
it.** `deepseek-v4-flash` and `qwen3.6` do not read the same prompt the same
way. Run every model with at least two prompt versions before ranking.

Merging: take the winner's prompt as the next version. Cherry-pick sentences
from the runners-up only with a replay run that shows the gain.

## 6. The local loop, and the gate

The overnight loop worked, then regressed, because its only signal was
`Run All`. Move the loop to `make evals-replay` and add one gate:

```
1. change the prompt (new version)
2. make evals-replay              → score S, per-problem table
3. if S < baseline: discard, log why, next
4. if S ≥ baseline: make evals-bench K=3 on the deployed model
5. if pass^3 holds: promote → deploy → ONE Run All
6. if Run All ≥ best: accept as baseline. Else revert.
```

`Run All` is the last step, not the first. It runs once per ~33 minutes and
tells you nothing about which field lost. `evals-replay` runs in a minute and
names the field.

**Do not skip the K=3 step.** A scenario at 70% pass is a scenario that fails
in 68 calls. That is the regression you saw.

## 7. Open defects that are worth points now

| Points | Defect | Where | Evidence |
| --- | --- | --- | --- |
| 4+ | prompt invents `general_medicine` | `vortex/conversation/prompt.py` | section 2 |
| 16 + 20 | turn-taking: 2 of 4 caller turns answered, 3.6–7.7 s after end of speech | `vortex/line/`, VAD settings | `/home/factory/voicecall.py` on the VPS |
| 12 | 4 of 11 refusal reasons never reached: `allowance_exhausted`, `location_hours`, `type_not_offered`, `patient_history` | `make evals-discover` | `evals/corpus/world/blocked-samples.json` |
| 8 | `blocked` reports a rule only when it stops the whole window; a wide `find_slots` hides `provider_on_leave` | `vortex/diary/` | `docs/evals-corpus.md` |
| all | roster anchored to Friday; from Saturday every "earliest" answer moved | `make evals-fetch` each morning | runner warns |

## 8. Commands

```bash
make evals                 # layers 1 + 2 + 4, CI gate, no keys
make evals-verify          # 130 published answers vs the real clinic
make evals-corpus LOG=logs/calls.jsonl CASE=<id>   # judge a practice call
make evals-snapshot        # re-take the clinic (needs PLATFORM_API_KEY)
make evals-discover        # find a real caller per refusal reason
make evals-bench MODELS=a,b K=3 MAX_EUR=1.00
make evals-replay          # ← does not exist yet. Step 0.
```

## 9. Things that cost us tonight, so you do not pay them again

- `make evals ci` with `--brain auto` billed a real OpenAI key from a shell
  environment. Fixed on `main`: the brain reads `LLM_PROVIDER`. Never put a
  paid key in a CI environment.
- `/availability` without `patient_id` returns `first_visit` for everyone.
  Without `insurer` it prices against the plan on file. Both are in the docs;
  both had to be hit to be believed.
- The platform rejects a `call_id` that is not a UUID with 422. A self-test
  must use a UUID or expect the 422.
- A synthetic caller must stream silence between utterances. A dead line is
  read as a barge-in and cancels the pending reply.
- `Run All` dials nothing about which case it is. `from_number` identifies 26
  of 73 personas; the rest need `--case`.
