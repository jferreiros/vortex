# `provider_on_leave` never wins. Book the substitute.

Cycle 5, 2026-09-19. Diagnosed, measured, **not shipped** — the fix needs the real
model in the loop and there was no time to verify it before the scoring wall. This
is the note to act on with budget in hand.

## What the board says

Across 292 live calls, `NO_ACTION` with reason `provider_on_leave` was submitted
five times. Three were judged. **All three scored 0.** No call that submitted it has
ever passed.

| call | redirect offered | verdict |
| --- | --- | --- |
| `68cd1f8d` | not recorded | failed 0.0/2.0 |
| `d0ff6da5` | three substitutes | failed 0.0/2.0 |
| `df26b9b3` | not recorded | failed 0.0/2.0 |

The other side of the same rule, a redirected `BOOK`, went **three passed, one
failed** — and that one failure was `8c8a7c54`, which lost to the stale-plan double
booking fixed in #256, not to the redirect.

| call | submitted | verdict |
| --- | --- | --- |
| `12986188` | BOOK the substitute | passed 2.0/2.0 |
| `657ac814` | BOOK the substitute | passed 2.0/2.0 |
| `a929faac` | BOOK the substitute | passed 2.0/2.0 |
| `8c8a7c54` | BOOK, twice | failed — the stale plan, since fixed |

`docs/rules.md` allows either ending: "Requena out 14-30 Sep → redirect or NO_ACTION
provider_on_leave". The board has answered which one the cases accept.

## Why the refusal is always available and always wrong

Dr. Requena is general practice, and general practice carries PR01, PR02 and PR07.
A substitute therefore *always* exists when this rule fires. There is no state of
this clinic in which Requena is away and nobody can take the patient, so there is
no case for which the bare refusal is the best answer we can give.

## Two calls, and neither is a close judgement call

`d0ff6da5` — the agent handled the leave perfectly and then contradicted itself:

```
 64.9  AGENT  Dr. Requena is on sick leave, so he can't take your checkup.
 65.5  AGENT  I can offer you another doctor: Dra. Carmen Ortiz Vidal at Centro,
              or Dr. Martín Sáez. Would either suit you?
 87.9  USER   Oh, okay. That's fine.
 89.8  SUBMIT NO_ACTION provider_on_leave
```

The caller **accepted the substitute** and we filed "we could not help".

`df26b9b3` — the submission raced the conversation:

```
 20.0  USER   I need to see Dr. Requena. About a cough that's been hanging around 3 weeks.
 21.8  RET    find_provider -> status on_leave
 27.5  SUBMIT NO_ACTION provider_on_leave
 28.8  AGENT  Would you like me to look for the earliest appointment with another
              doctor in General Practice?
```

We refused at 27.5s and offered the alternative at 28.8s. The case was decided
before the caller was asked.

## The shape of the fix, and why it was not shipped

The guard is narrow and cannot regress a passing case: no passing call submits this
action, so intercepting it only touches a path that has lost every time. Refuse
`NO_ACTION(provider_on_leave)` at submit time while the call still holds a
substitute, and hand the model a typed rejection naming the doctors who can serve.

What stopped it:

- `submit_action` returns a `SubmitResult`, not a `Rejection`. A tool that declines
  to submit has no precedent in this codebase and the return shape wants designing,
  not improvising at 07:00.
- The fix only pays off if the model *recovers* — offers the substitute and books it.
  The offline evals run against the rules brain, not the runtime model, so the one
  thing this change depends on is the one thing they cannot show. Two of the three
  calls also never ran `find_slots`, so the end-of-call fallback would reach
  `cold_booking`, which is a guess.

Blocked and flailing is still worth more than a certain zero, so the expected value
is positive. But it is an untested behavioural change, and the run that carried it
would have been the last before the wall.

## How to verify it when there is time

Run the conversation layer against the real model, not the rules brain:

```bash
make evals-conversation BRAIN=model K=3
```

Add a case where the caller asks for Requena and accepts the substitute, and assert
the run ends on `BOOK` with the redirect provider — never on `NO_ACTION`. Then a
Run All to confirm on the board.
