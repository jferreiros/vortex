# Outbound-call pathways

A **pathway** is the wiring from something that happened to a call placed to
the person that event concerns. It is not the script itself.

```
clinic event -> trigger site -> PathwayEvent -> fire_pathway
                                          |-> CallJob (script + answer classifier)
                                          |-> ConfirmationStore (dedup + queue)
                                          |-> ConfirmationWorker -> Twilio
                                          |-> result webhooks -> status + handoff
```

## Building blocks

- `Pathway`: names the event, the registered `CallJob`, and whether it is an
  immediate (`call_now`) or scheduled (`programada`) call.
- `PathwayEvent`: the event's record-resolved target and appointment context.
  A trigger must use the phone of the patient the event is about, not the
  inbound caller or an operator/test number.
- `fire_pathway`: the single entrance. It applies number normalisation,
  subsystem/empty-target guards, loop prevention, dedup, persistence and
  queueing through the existing `confirmation_calls` implementation.
- `CallJob`: already present in main. It owns the prompt, answer classifier,
  acknowledgement and optional live-agent handoff.
- `GET /api/wall/pathways/status`: read-only demo/ops proof of every runtime
  pathway, its job wiring and live readiness. It deliberately does not replace
  the existing `/api/wall/pathways` admin document endpoint.

## Included pathways

| Event | Trigger sites | Target | Job | Timing |
|---|---|---|---|---|
| `appointment_cancelled` | single/range wall cancel; phone `CancelAction` | patient on cancelled visit | `cancellation_rebooking` | immediately |
| `appointment_booked` | phone `BookAction` | patient on new visit | `appointment_confirmation` | day before |

For synthetic demo visits with no record phone,
`VORTEX_CANCEL_CALL_FALLBACK_TO` can name a stand-in recipient. It is never
used when a record phone exists and it is empty by default.

## Add another pathway

1. Reuse a `CallJob` if the call says the same thing, otherwise implement and
   `register_job` a new one in `confirmation_calls.py`.
2. `register_pathway(Pathway(...))` in `vortex/line/pathways.py`.
3. At the point where the event has *successfully committed*, resolve the
   affected patient's record phone and call `fire_pathway(settings, name,
   PathwayEvent(...), now=...)`. Catch failures at that boundary so a failed
   call queue cannot roll back the clinic event.
4. Test that the target is the event's patient, E.164 normalisation, the empty
   target guard, dedup and the loop guard. Never place a real call in tests.

The registry is deliberately small. It does not introduce a second worker,
webhook implementation, persistence layer or call script framework; those are
already in main, and duplicating them would create competing call paths.
