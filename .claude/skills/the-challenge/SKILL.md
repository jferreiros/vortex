---
name: the-challenge
description: Use when you need to know what the leaderboard scores, what a given problem asks for, its weight, its problem_id, or whether it is open yet — before you plan work on any problem.
---

# The challenge — El Turno (Prosper AI, HackSpain 2026)

## What is built

A voice agent that answers inbound scheduling calls for Clínica Arenal, a
read-only EHR. The organisers dial our WebSocket, play a persona, and check what
we POST at the end of the call. There is no starter kit and no phone number on
our side. Only a socket.

## How the score works

- Two parts: the automatic leaderboard, and the jury's "final boss" on Sunday.
- The leaderboard is **binary per case**. The list of actions we submit matches one
  of the outcomes the case accepts, or the case fails. No credit for a field, for
  most of a name, or for an id one character out.
- A case can accept several outcomes. Three GPs free at the same minute are three
  right answers. Membership, not partial credit.
- Expected answers are computed through the same availability endpoint we call. A
  case never expects a slot the API would not offer.
- `points = sum over problems of (passed cases x weight)`. Every private case you
  pass is worth its problem's whole weight. There is no fraction and no denominator.
- Each scored problem has four private cases per run. Full roster: **196 points**.
  The Real Call puts up to 20 on the board where The Simple Booking puts up to 4.
- Problem 2 carries no weight and `Run All` never dials it.
- A sum, not a percentage, because the set opens across the weekend: a score from
  Friday means the same thing on Sunday, and points only grow.
- A problem nobody attempted scores the same as one that failed. Silence is never
  cheaper than a wrong answer.
- Not scored: voice quality, politeness, number of questions or tool calls, model,
  cost, speed. One exception: problem 14 checks the transcript for leaked data.
- What the scorer forgives is published at `/leaderboard/docs/scoring`, a page the
  nav does not link. Ids compare exactly. Only the REGISTER demographics and the
  slot have any tolerance. `evals/corpus/normalize.py` implements that table.
- A call our side spoiled is **redialled once** under a new call id before it is
  judged, and only that second call is scored. Attributed harness failures void the
  case; a run is voided only when every one of its calls was.

## The jury (final boss, Sunday 11:00)

Not automated. Same panel for every team. They call us live and judge: patient
experience, how personal it feels (use the chart note and history before you ask),
the platform around the agent (live console, "why did it say that?"), safety and
boundaries, language handling, engineering rigour (evaluation harness, variance,
named failure modes, cost per call), and discretion. Demo what you built. A
criterion the jury cannot observe is not scored.

## The 18 problems

Open status is the docs snapshot from Friday 18 September, 21:00. Check the
Problems page for today. Problems open in order as each is verified end to end.
Public case counts are the roster's own; `evals/corpus/` holds the roster itself.

| # | Problem | `problem_id` | Weight | Public cases | Open (Fri) | Answer |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | The Simple Booking | `simple_booking` | 1 | 4 | yes | BOOK |
| 2 | The Switchboard | `switchboard` | — | 3 bursts (5, 10, 20) | yes | Problem 1, on every line |
| 3 | The Doctor and the Site | `doctor_and_site` | 2 | 5 | yes | BOOK exact provider and location, or NO_ACTION |
| 4 | The New Patient | `the_new_patient` | 2 | 4 | yes | REGISTER only. A BOOK beside it fails |
| 5 | When Exactly | `when_exactly` | 2 | 5 | yes | BOOK at the exact slot |
| 6 | The Rules | `the_rules` | 3 | 5 | yes | NO_ACTION with the rule that bit, or a redirected BOOK |
| 7 | No Slot Free | `no_slot_free` | 2 | 4 | not yet | BOOK from the acceptable set, or NO_ACTION(no_availability) |
| 8 | Change and Cancel | `change_and_cancel` | 2 | 4 | not yet | CANCEL or RESCHEDULE; two CANCELs in one call is possible |
| 9 | The Third Party | `third_party` | 3 | 4 | not yet | BOOK for the patient, never for the caller |
| 10 | Triage | `triage` | 3 | 5 | not yet | BOOK in the right specialty, or ESCALATE(medical_emergency) |
| 11 | Languages | `languages` | 3 | 4 | not yet | BOOK with the language constraint applied |
| 12 | Noise | `noise` | 3 | 4 | not yet | BOOK |
| 13 | The Difficult Caller | `difficult_caller` | 4 | 5 | not yet | BOOK the final stated request |
| 14 | Adversarial and Privacy | `adversarial` | 4 | 4 | not yet | NO_ACTION(out_of_scope) and a clean transcript |
| 15 | The Nearest Site | `nearest_site` | 3 | 4 | not yet | BOOK at the correct site |
| 16 | The Questions | `the_questions` | 3 | 5 | not yet | BOOK; a wrong fact on the call breaks the booking |
| 17 | The Second Policy | `second_policy` | 4 | 4 | not yet | BOOK naming the `policy_id` it is billed against |
| 18 | The Real Call | `the_real_call` | 5 | 3 | not yet | Multi-action list, all correct |

Per-problem detail, traps and the triage table: see `problems.md` in this folder.

## Public vs private cases

- Public cases are published with their answers in `public-cases.json` and on each
  problem page. They are for practice and earn nothing. The file is committed at
  `evals/corpus/cases/public-cases.json`; `make evals-fetch` refreshes it.
- Public cases anchor "the earliest" to 09:00 Europe/Madrid on the day dialled, so
  the answer changes only overnight.
- Private cases are generated per run from a seed only the organisers hold. Their
  answers are never published. Problem 11's private pool draws Catalan far more
  often than its public cases.

## Lane map (from the team plan)

- La Línea: 2, and every case indirectly.
- La Conversación: 11, 12, 13, 14.
- Identidad: 1 (with La Agenda), 4, 9.
- La Agenda: 3, 5, 7, 8, 15.
- Las Reglas: 6, 10, 16, 17.
- Everyone: 18.
