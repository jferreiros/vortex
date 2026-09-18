# Public jury board

Run `make board` and open `http://localhost:8080/wall`. Each card links to
`/wall/call?call_id=...`, a live-updating identity/status header with a placeholder
for the future live-call screen. The private operations board remains at `/`.

The public board polls once per second and requests the full retained history
with `GET /calls?limit=0`; the existing JSONL reader treats zero as all events.
If Line is unavailable, it reads the full local `VORTEX_CALLS_LOG` instead.
An offline indicator means the last events cannot establish current connectivity.
History is only as complete as the source log: this is not a separate database.

## State projection

The ten columns are CONNECTED, IDENTIFYING, REGISTERING, ROUTING, SEARCHING,
OFFERING, MODIFYING, EMERGENCY, SUBMITTING and FINISHED. Existing tool events
provide an **estimated** display state, clearly labelled in the UI. For example,
`find_patient` starts IDENTIFYING, a unique result moves to ROUTING, and slots
returned by `find_slots` move to OFFERING. A submission does not close a call;
`call.ended` or `call.summary` does. Missing opening events are not counted as
active calls.

The conversation owner can emit an authoritative state through the existing
`ctx.log.event` method, without changing a contract signature:

```python
ctx.log.event("call.state", state="REGISTERING")
ctx.log.event("language.detected", language="ca")
```

After an explicit state arrives, tool events no longer override it. A closing
event always wins. Language can also be attached as `language` to `call.started`,
`turn.user` or `call.summary`. Provider-language preferences are not evidence of
the caller's detected language.

## Historical metrics

Only finished calls enter the historical aggregates. Results count accepted,
duplicate-acknowledged or dry-run submissions, not merely prepared actions.
Dry runs are labelled as simulations. Multiple different actions in one call
appear in each applicable result category; retries do not inflate counts.

**An accepted submission is not a passed evaluation.** Until evaluation results
are imported, the pass rate is unknown. The evaluation integration can log:

```python
log.event("call.verdict", passed=True)  # only a real Prosper evaluation verdict
```

The rate is passed / evaluated finished calls, and the UI shows coverage. There
is currently no automatic verdict importer. Missing languages remain unknown;
they are not guessed from text or assigned Spanish by default.
