# Layer 4 — the organisers' own cases

`docs/evals.md` covers layers 1 to 3, which were written from the prose in
`.claude/skills/`. This layer is different: it runs on the organisers' published
case roster, and it replicates their scorer.

```bash
make evals-coverage    # where the 196 points are, and what the roster never shows
make evals-corpus      # roster integrity + the probes, no keys, ~40 ms
make evals-corpus LOG=logs/calls.jsonl   # score real practice calls
make evals-fetch       # refresh the roster (each morning of the event)
make evals-snapshot    # freeze the real clinic; needs PLATFORM_API_KEY
make evals-hydrate     # rebuild synthetic-data/ from the roster (LIVE=1 hits the API)
```

`make evals` runs layers 1, 2 and 4 and is still the CI entry point.

## What the roster is

The Problems page links `public-cases.json`. It holds 73 published cases, and
each one carries:

| Field | What it gives us |
| --- | --- |
| `persona` + `caller_prompt` | the exact script the organisers feed their own caller |
| `expected.acceptable` | **the set of action lists the case accepts** |
| `audio` | the noise bed and its SNR, for problems 12 and 18 |
| `protected` | the fields problem 14 reads our transcript for |
| `reference_time` | the anchor the answer was computed against |

It is the only published ground truth in the challenge. A copy lives at
`evals/corpus/cases/public-cases.json`, with its sha256 printed on every run.

**Re-fetch it each morning.** The roster is fixed — one seed builds it for every
process — but "the earliest appointment" is anchored to 09:00 Europe/Madrid on
the day it is dialled, so a booking answer changes overnight. A stale roster
judges yesterday's call correctly and today's wrong.

## The judge

`evals/corpus/judge.py` reimplements the automatic scorer:

- A case passes if the submitted action list matches **one** the case accepts,
  after normalization. Binary, no partial credit, membership not similarity.
- `evals/corpus/normalize.py` is the published normalization table, field by
  field. Ids compare exactly; only the `REGISTER` demographics and the moment of
  the appointment have any tolerance. Every example on that table is a test.
- Problem 14 also reads our turns for the targeted patient's national id and
  phone. A perfect refusal after reading an id aloud still fails.

`test_every_published_answer_passes_our_own_judge` runs the organisers' own
answer to each of the 73 cases through this judge. If that test ever fails, the
replica has drifted from the real scorer and nothing below it can be trusted.

### Why it earns its place

`Run All` is the only scored lane: one run per ~33 minutes, and a failed private
case tells you *that* it failed, not which field lost. A practice call answers
in 30 seconds and is free. Point this judge at `logs/calls.jsonl` and every
practice call gives the verdict the leaderboard would give, plus the field:

```
fail  judged.doctor_and_site-d5b4f04886c5   record_mismatch
      action 1 · provider_id: expected 'PR07', got 'PR02'
```

For that to work, log the public case id on `call.started`. The runner says how
many calls it could not join.

## The probes — beyond the 73

Private cases are generated per run "from the same template" as the public ones.
Four published cases per problem is a sample of that template space, so passing
all four proves little. The probes enumerate the parts of the space the docs
publish **in full**, and assert a property of the answer rather than a value —
the answer key is private, the rules are not.

| Family | Probes | What it covers |
| --- | --- | --- |
| `dates` | 135 | all 27 published phrases x the days a scored call can connect on |
| `triage` | 20 | all 15 symptom rows and all 5 red flags. The roster shows 5 |
| `ids` | 36 | the DNI/NIE check letter, which is arithmetic: roster ids, generated ids, wrong letters, dictated forms |

The date probes are deliberately site-blind. `resolve_date` takes no
`location_id`, so it can only apply the closures that shut the whole network —
Sunday and Fiesta Nacional. "Sur shuts Friday lunchtime" and "only Centro opens
on a Saturday" move a booking too, but they belong to `find_slots`; asserting
them against `resolve_date` would fail a correct implementation. They are
reported as skipped, with that reason, rather than left out.

Twenty more situations the docs state and no public case exercises are listed
as skipped with the reason, including the nine refusal reasons the roster never
reaches. A board that omits what it could not test is a board that lies.

## The isolated pack (`synthetic-data/`)

`make evals-hydrate` writes patients, already-booked appointments and one
CallLog JSONL per problem into `synthetic-data/` at the repo root — same payload
shape as `vortex/clinic/fixtures.py`, different folder. It does not touch the
fixtures, `logs/calls.jsonl`, or the gitignored `evals/corpus/world/` snapshot.

`FakeClinicClient()` still reads the small invented fixtures. Pass
`data_dir=Path("synthetic-data")` to look up the published ids (`P00001`,
`A001101`, …) offline. `LIVE=1` enriches charts and diaries from the clinic API
when a key is set.

## What is still blocked

The roster's answers name real ids — `P00001`, `PR01`, `centro`, `review`, a
slot to the minute. Layers 1 and 2 run against `FakeClinicClient` and invented
patients, so they check the shape of an answer and never its value.

`make evals-snapshot` fixes that in one pull, once the desk issues
`PLATFORM_API_KEY`. It writes the catalogue, the directory lookups each persona
makes possible, the diaries of every patient the answers name, and availability
across the whole bookable calendar into `evals/corpus/world/` (git-ignored — it
is the organisers' generated patient data). After that, all 73 published answers
become 73 offline assertions that mean something, and the nine unreached refusal
shapes become buildable cases.

**Run the snapshot the moment the key lands.** It is the difference between an
eval suite that checks we produce a well-formed answer and one that checks we
produce the right one.

## Judging real calls

A practice call is free, repeatable every 30 seconds, and the organisers play
real audio through real speech recognition at our socket. It is the highest
fidelity voice eval available and it costs nothing:

```bash
make evals-corpus LOG=logs/calls.jsonl CASE=simple_booking-14a8720daa02
```

Nothing names the case for us. `start.customParameters` carries `call_id` and
`from_number` and nothing else, and the submissions readback carries `call_id`,
`record` and `received_at`. So the join is ours: `from_number` names the
persona, but the organisers reuse a persona across problems, so it identifies
only **26 of the 73** cases on its own. The joiner uses the number when it is
unambiguous, refuses to guess when it is not, and `CASE=` says which.

**Watch the anchor.** The roster file is the export at Friday's anchor. "The
earliest appointment" means the earliest from the day after the call, so from
Saturday onward every "earliest" answer in the file has moved while the problem
page shows today's. The runner compares the roster's anchor with today and says
so; a slot mismatch on such a case is the anchor, not the agent.

## Finding a caller for a rule nobody publishes

`make evals-discover` sweeps the live API by plan, by patient and by provider,
and records in `world/blocked-samples.json` a real query that triggers each
decline reason. The published roster reaches two of the eleven rule reasons.
The sweep reaches seven, including `provider_on_leave`, `not_eligible_age` and
`insurer_referral_required`, each as a concrete patient and specialty a lane can
build a caller around.

**The window decides whether a rule is visible at all.** `blocked` reports a
rule only when it stops the whole window asked for:

| Query | Result |
| --- | --- |
| `provider_id=PR02`, 21–30 September (inside his leave) | 0 slots, `blocked: provider_on_leave` |
| `provider_id=PR02`, 21 September – 4 October | 50 slots in October, `blocked: []` |

One day past the end of the leave and the rule disappears — Dr. Requena simply
looks available. An agent that widens its search until it finds something never
learns why the caller cannot have what they asked for, and problem 3 turns on
exactly that.

Four reasons the sweep does not reach — `allowance_exhausted`, `location_hours`,
`type_not_offered` and `patient_history` — need a patient outside the roster's
own 24, a site's closing time, or a specialty that does not offer a type. They
are listed as unreached rather than quietly dropped.
