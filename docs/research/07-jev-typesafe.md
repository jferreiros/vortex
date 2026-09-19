# Research 07 — Jev (TypeSafe AI) on the Vortex line

Date: 2026-09-19. Target: remaining contest window (Saturday afternoon → Sunday 11:00 jury).
Sources fetched the same day. Claims without a primary page are tagged `UNVERIFIED`.

The model Joaquín called "Shape JV" / "Chef" is **Jev**, TypeSafe AI's first
System One model, launched 14–15 September 2026. The Knowledge Hub already
has it: item `4783`, tweet of Diogo Almeida (`@CompleteSkeptic`), analysed
15 September. The vault's own line: *Jev = decisiones estructuradas
calibradas, 40–400× más barato que un LLM, sin generación de texto libre.*

This note answers one question: **where Jev can raise the 196-point score or
the Sunday jury score, and where it would waste the weekend.**

## What Jev is

Jev is not a chat model. You send `state` (string / JSON / array of text)
plus a map of typed questions. Every question is answered in one parallel
pass. The three primitives:

| Primitive | Asks | Returns |
| --- | --- | --- |
| `choice` | pick one of N options (≤ 255) | `choice`, `probabilities`, `confidence` |
| `score` | position on an ordered rubric (2–10 levels) | weighted mean + distribution |
| `noul` | is this statement true? | probability in `[0, 1]` |

It cannot write a reply, a summary, code, or an explanation. It does not
see images or audio. Schema violations are impossible by construction; a
wrong *valid* answer is still possible. "Cannot hallucinate" means "cannot
leave the schema", not "cannot pick the wrong specialty".

Official numbers (vendor, West-Coast laptops): 70–500 ms end to end, most
calls ~100 ms; `$0.042` per million input tokens; output free. From Madrid
add RTT. Context: ~32k tokens for `state` + longest question, ~64k for the
whole request. Rate limits on `jev-1.13`: 250k tokens/s, 1,200 req/min
(moving without notice).

Endpoint: `POST https://api.typesafe.ai/v1/systemone`. Python SDK:
`typesafe-sdk`. Also on Vercel AI Gateway as `typesafe-ai/jev` via
`evaluate`. Pin `jev-1.13.0`; `jev-latest` will move.

## What Jev is bad at (the limit they mentioned)

The "large comparisons" warning is real and documented.

- A `choice` has a hard cap of **255 options**. Above that TypeSafe runs a
  two-stage score-then-choose path and calls out the slowdown. Do not hand
  Jev the availability list, the patient directory, or every provider.
- Accuracy falls as `state` fills with material the question does not need.
  Retrieve in code first.
- It is not a calculator. Counting, hex colours, and "how many slots" fail.
  Dates are text: which of two dates comes first, whether one falls in a
  window, relative phrases — all unreliable. That work already lives in
  `vortex/diary/`.
- It reads literally. Negations and implied conditions land at face value.
- Near-miss medical language is a trap for us: "bleeding between periods"
  must not become haemorrhage. The published table already encodes that.
- Independent accuracy evidence is thin (launch week). TypeSafe's own
  workflow dashboard has Jev at 67.8% agreement with a GPT-6 Astra +
  Claude Fable 5.1 consensus, level with Sonnet 5, behind Sol / Opus 5.
  Speed and cost win; raw accuracy does not.

## What Vortex already decided, without Jev

The line is a cascade: Soniox → text LLM (tool calls) → TTS. The bench
already splits two roles:

| Role | Env | Status |
| --- | --- | --- |
| receptionist | `LLM_PROVIDER` / `LLM_MODEL` | live, generates speech + tools |
| arbiter | `ARBITER_PROVIDER` / `ARBITER_MODEL` | **wired, unused** |

`docs/research/04-industry-2025-2026.md` item 10 already names the Hamming
post-call judge: deterministic checks first, then a grader with confidence.
Triage is a **lookup** on the published 15 + 5 table (`vortex/rules/triage.py`),
not clinical judgement. Dates, hours, insurance, nearest site, DNI check
letter are code. The overnight loop already showed that inventing a
specialty id (`general_medicine`) loses problem 1.

The leaderboard does not score model, cost, or latency. The jury does:
engineering rigour, named failure modes, cost per call, "why did it say
that?", safety.

## Fit map — every problem, one line

| # | Problem | pts | Jev? | Why |
| --- | --- | --- | --- | --- |
| 1 | Simple booking | 4 | no | specialty enum + tools; Jev cannot pick a slot |
| 2 | Switchboard | — | no | concurrency, not judgement |
| 3 | Doctor and site | 8 | no | catalogue + leave; code |
| 4 | New patient | 8 | no | DNI/email/phone are deterministic |
| 5 | When exactly | 8 | **never** | dates are Jev's documented failure |
| 6 | The rules | 12 | no | read `blocked`; do not guess |
| 7 | No slot free | 8 | no | empty window is arithmetic |
| 8 | Change / cancel | 8 | maybe | last-intent only, post-hangup |
| 9 | Third party | 12 | maybe | noul: is the patient the caller? |
| 10 | Triage | 12 | **fallback only** | table first; Jev on unmatched paraphrase |
| 11 | Languages | 12 | no | Soniox LID + provider language field |
| 12 | Noise | 12 | no | STT / VAD; Jev does not hear |
| 13 | Difficult caller | 16 | **yes, post-hangup** | "final stated request" is a typed choice |
| 14 | Adversarial | 16 | **yes, post-hangup** | jailbreak / out_of_scope is TypeSafe's home turf |
| 15 | Nearest site | 12 | **never** | haversine; Jev cannot compare coordinates |
| 16 | The questions | 12 | no | facts from the catalogue |
| 17 | Second policy | 16 | no | ask, then submit the `policy_id` the slot used |
| 18 | The real call | 20 | yes, as 8+9+13 | last intent + who is the patient |

## The two places that are actually worth it

### A. The unused arbiter, after hangup (recommended spike)

The submit window is 30 s. Jev at ~100–400 ms from Madrid fits inside it
without touching the voice path. The receptionist keeps talking; Jev only
sees the finished transcript + the tool trace + the action the model was
about to POST.

One call, many questions (fan-out, TypeSafe's cheap pattern):

- `choice action` — `book` / `register` / `cancel` / `reschedule` / `no_action` / `escalate`
- `choice specialty` — the six real ids plus `none` (kills `general_medicine`)
- `noul final_request` — does this action match the **last** stated ask?
- `noul out_of_scope` — injection, other patient's data, medical advice, sales
- `noul red_flag` — one of the five published emergencies
- `noul patient_is_caller` — problem 9

Code still owns the slot, the `policy_id`, the site, and the refusal
reason from `blocked`. Jev may **veto or relabel**; it may not invent a
time. If confidence is below a threshold we keep the receptionist's
action (or the last `blocked` reason). That is TypeSafe's own
confidence-gated routing pattern.

This is the Hamming arbiter the research already asked for, with a model
that returns a number the wall can show. Jury line: *the LLM talks, a
System One model judges, code books.*

Points it can save: 13 (16), 14 (16), 9 (12), the specialty-id miss on 1,
wrong hangup `out_of_scope` (F3 in `OPUS-P0-BRIEF`). It cannot save
turn-taking or STT.

### B. Triage fallback, never triage replacement (optional, after A)

Problem 10 is a published table. Replacing it with Jev is how you fail the
near-misses (sore throat + fever stays GP; bleeding between periods is not
haemorrhage). The table already encodes those.

Use Jev only when `triage_table.score(complaint)` is empty **and** no
named specialty / named doctor resolved. Choice of six specialties +
`emergency` + `unknown`. If `unknown` or low confidence, keep
`general_practice` (the published residue).

Do not send the whole catalogue as options. Do not send the availability
list. Do not run this on the hot path of every turn: the table is free
and already tested.

## Do not put Jev here

- On the live turn. The line is already 3.6–7.7 s after end of speech.
  Another 100–400 ms plus a Spain RTT does not win problem 12 or 13.
- Picking a slot, a provider from a long list, or "the nearest site".
- Resolving "this coming Thursday" or Saturday hours.
- Generating the agent's spoken reply.
- Replacing `check_eligibility` or `blocked`.
- Scoring the 73-case replay as a judge of *our* judge. The platform
  scorer is deterministic and already cloned.

## Recommended weekend sequence

A 90-minute **offline** spike, no voice path, no deploy:

1. One script: `evals/jev/spike.py`. Reads the published triage rows +
   the five red flags + the three near-misses already in
   `evals/results/logic/calls/triage.nearmiss.*`. Asks the A and B
   question sets above. Writes a JSON table: expected vs Jev vs
   confidence.
2. Pass gate for wiring A: on the public triage set, red flags fire,
   near-misses do not, and specialty agreement ≥ the table. On a handful
   of problem-13 / problem-14 shaped transcripts (from
   `evals/corpus/cases/public-cases.json` where they exist), last-intent
   and `out_of_scope` are right at high confidence.
3. Fail gate: if Jev escalates a near-miss or invents a specialty, stop.
   The table and the unused DeepSeek arbiter stay. Cite Jev to the jury
   as something we evaluated and rejected with numbers.
4. Only then: `ARBITER_PROVIDER=typesafe`, a thin client next to
   `vortex/models.py`, hangup hook in `vortex/line/session.py`. Env
   `TYPESAFE_API_KEY`. Never in git.

This is cheaper than swapping the receptionist model and cheaper than
another prompt-loop night. It is more expensive than the three
points-per-hour moves already ranked 1–3 in `docs/research/README.md`
(dead interruption gate, Soniox entity CER, read-back). **Those still
go first.** Jev is the next model-shaped bet after the audio floor
stops leaking.

## Knowledge Hub, applied

Item 4783 already said the first trial should be a high-volume
classify / score / route task where a chat LLM is overkill. Vortex's
arbiter is that task: one decision per call, closed label set, code
around it. Flipr chollos and a Buildylab client pipeline stay valid
and are out of scope this weekend.

The vault's open question (`@svpino`, `@omarsar0`) is whether
calibration holds on *our* labels. The spike is that test. If the
probabilities are not honest on the near-misses, we do not automate
against them.

## Key handling

The early-access key was pasted into a chat. Put it only in the VPS
`deploy/.env` as `TYPESAFE_API_KEY`. Rotate if that chat is retained.
Do not commit it. Do not put it in Discord.

## Sources

- TypeSafe launch post, 14 Sep 2026: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- Docs: https://docs.typesafe.ai/introduction.md, https://docs.typesafe.ai/concepts/system-one.md
- Intent routing / confidence routing / use-case map: https://docs.typesafe.ai/patterns/intent-routing.md, https://docs.typesafe.ai/patterns/confidence-routing.md, https://docs.typesafe.ai/concepts/use-case-map.md
- Vercel AI Gateway, 16 Sep 2026: https://vercel.com/changelog/typesafe-ais-jev-now-available-on-ai-gateway
- Practical guide (limits, jaggedness, batching): https://dev.to/valyuai/how-to-use-jev-a-practical-guide-to-typesafes-system-one-model-g5e
- Flavio Copes deep dive, 17 Sep 2026: https://flaviocopes.com/jev/
- Business Wire, 15 Sep 2026 ($40M, DCVC): https://www.businesswire.com/news/home/20260915525333/en/TypeSafe-AI-Emerges-From-Stealth-With-%2440M-in-Funding-With-New-Model-for-Composable-AI
- Knowledge Hub item 4783 (`data.sqlite`), actions 101397–101399
- Repo: `vortex/rules/triage.py`, `vortex/models.py`, `vortex/settings.py` arbiter block, `docs/NEXT-STEPS.md`, `docs/research/04-industry-2025-2026.md` §10, `.claude/skills/the-challenge/problems.md`
