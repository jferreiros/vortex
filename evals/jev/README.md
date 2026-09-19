# Jev spike

Offline TypeSafe Jev run against the published triage table and the public
cases for problems 9, 10, 13 and 14. The live line does not call this.

```bash
make evals-jev
```

Needs `TYPESAFE_API_KEY` in `.env`. Pins `jev-1.13.0`. Writes
`evals/jev/results/report.md` and `latest.json`.

Exit `0` after a finished run, even when the verdict is `REJECT`.
Exit `2` only if the API key is missing or TypeSafe errors.

## Verdict

| Verdict | Meaning |
| --- | --- |
| `WIRE_ARBITER` | Red flags, near-misses, last-intent and adversarial hold. Hangup judge is worth wiring. |
| `WIRE_TRIAGE_FALLBACK` | The published table and public triage complaints match. Use only when the regex table scores nothing. |
| `WIRE_ARBITER_AND_TRIAGE_FALLBACK` | Both. |
| `REJECT` | A near-miss escalated, or Jev invented a specialty id. Leave the line as it is. |
