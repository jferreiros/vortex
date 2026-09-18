---
name: rehearse-and-measure
description: Use when you want to test the agent against the platform — deciding between a practice call and Run All, reading a verdict, planning Run All timing around cooldowns, or working towards the Sunday 06:00 scoring wall.
---

# Rehearse and measure

Two lanes on the dashboard's Problems page. Only one scores.

## Practice call (`Call` button, beside each public case)

- Dials one published case. Its answer is printed on the problem page.
- Free. Scores nothing. As often as you like, **30 seconds** between calls.
- Feedback right away on the submissions tab: transcript, recording, and which
  fields our record lost. Never what they should have been.
- This is the lane to debug in. A public case is the same case every time.
- Public cases anchor "the earliest" to 09:00 Europe/Madrid on the day dialled,
  so the expected slot changes only overnight.
- Organisers also place smoke calls at every endpoint. Those are practice too.

## `Run All` (top of the problems list)

- The only scored lane. Four private cases for every open scored problem,
  dialled **10 at a time**. We choose nothing about it.
- Private cases are generated per run. Answers never published. Nothing to hard-code.
- Grows as problems open: 2 problems = 8 calls, a couple of minutes;
  17 problems = 68 calls, about **18 minutes**.
- A private case tells us: passed or not, whose failure it was, and a signal such
  as `missing_record` or `record_mismatch`. No field, no transcript, no audio
  until the reveal (Monday 21 September, 00:00 Europe/Madrid).
- Cancelling a run is safe at any point.

## Clocks and slots

| Limit | Value |
| --- | --- |
| Between practice calls | 30 s |
| Cooldown after a `Run All` finishes | 15 min |
| One `Run All` duration (full roster) | ~18 min |
| Realistic `Run All` cadence | one every ~33 min |
| Queued or active runs per team, either lane | **one** — both buttons disabled while occupied |
| Per-call cap | 3 min |
| Scoring wall | **Sunday 20 September, 06:00 Europe/Madrid** |

- Only runs **completed** at or before the wall count. A run must finish, not
  start, before 06:00. Last useful launch is around 05:30.
- One person owns the `Run All` button. Two people pressing block each other.

## What the board keeps

- The leaderboard ranks each team's **best** `Run All`. Not latest, not
  cumulative. Experimenting late is free. Not launching is not.
- The board shows how many runs backed a score. Four cases per problem is a
  sample: more runs, more chances.
- Opening a new problem never changes the score of an earlier run. There is no
  denominator. Points only grow.
- A voided run (harness failure) contributes nothing and releases its cooldown.
  It never reruns on its own. Ask for a replacement run explicitly.
- Equal scores share a rank (1, 1, 3).

## Reading a failure

Attribution is deterministic. No LLM arbiter.

| Evidence | Attribution | Effect |
| --- | --- | --- |
| Matching record, no signals | none | Pass |
| Missing or mismatching record | `agent_issue` | Fail |
| Endpoint unreachable, malformed message, clean early hang-up | `agent_issue` | Fail |
| No audible audio for the silence window | `agent_issue` | Fail |
| Wall-clock limit, turn cap, unexplained disconnect, unidentified pipeline error | `inconclusive` | Fail; evidence kept |
| Identified harness STT/LLM/TTS error, or confirmed local socket defect | `harness_issue` | Run voided |
| Confirmed harness defect and agent failure | `mixed` | Run voided |

For a dispute give an organiser: team, run id, call ids, rules version, the rule
expected, what was observed.

## Local rehearsal, no platform

- `make smoke` runs the handshake in process. `make call N=10` dials the local
  server with fake callers. `make test` runs the suite. None need a key.
- Problem 2's public bursts (5, 10, 20 lines) are the honest concurrency test.
  `Run All` never dials them. Trigger them by hand, early.

## Checkpoints

- Checkpoint 1: Saturday 10:00. Checkpoint 2: Saturday 23:00. Prizes to whoever
  leads at that moment. The desk announces the exact windows.
- Jury: Sunday 11:00, live call plus demo.
