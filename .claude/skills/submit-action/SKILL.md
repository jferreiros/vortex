---
name: submit-action
description: Use when you build or debug the POST that reports a call's outcome — choosing the action verb, filling its exact fields, picking a reason value, handling the 30-second window, or interpreting a 404, 409, 410 or 422 from /api/v1/submit.
---

# Submitting the action

The clinic is read-only. We do not book anything. We report the write we would
have made, one POST per action, to `POST /api/v1/submit/<action>` with the
team key in `X-Api-Key`. Body is plain snake_case JSON. Attribution comes from
the registered call session, never from a team id in the body.

## The six routes

Every body carries `call_id` (exactly `start.callSid`) plus:

| Route | Body besides `call_id` |
| --- | --- |
| `POST /api/v1/submit/register` | `given_name`, `first_surname`, `second_surname`, `national_id`, `date_of_birth`, `phone`, `email`, `insurer` |
| `POST /api/v1/submit/book` | `patient_id`, `provider_id`, `location_id`, `appointment_type_id`, `slot`, `policy_id` |
| `POST /api/v1/submit/reschedule` | `appointment_id`, `provider_id`, `location_id`, `slot`, `policy_id` |
| `POST /api/v1/submit/cancel` | `appointment_id` |
| `POST /api/v1/submit/no-action` | `reason` |
| `POST /api/v1/submit/escalate` | `reason` |

Example:

```json
POST /api/v1/submit/book
{
  "call_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "patient_id": "P00042",
  "provider_id": "PR05",
  "location_id": "sur",
  "appointment_type_id": "review",
  "slot": "2026-09-24T16:30:00+02:00",
  "policy_id": "sanitas"
}
```

## Field rules

- `register`: for a caller the directory does not know. Nothing is booked. Every
  field is scored after normalization. `national_id` re-derives its check letter;
  a letter that does not match its digits is a 422.
- `book`: `patient_id` comes from `/directory`, never from what the caller said.
- `appointment_type_id`: take it from `/availability`'s `appointment_type` (the
  slot carries the id). Same slot under the wrong type fails.
- `policy_id`: which of the patient's plans the appointment is billed against. A
  patient may hold two. Naming it is part of the answer.
- `appointment_id`: from `/patients/{patient_id}/appointments`. No other source.
- `slot`: explicit timezone offset. It converts to Europe/Madrid and must match to
  the exact minute.
- Ids are compared exactly. Nothing to normalize about `PR05`.

## `reason` — closed vocabulary, 18 values

The first eleven mirror the clinic's restrictions one-for-one, so a rule that bit
can always be named. Read them from `/availability`'s `blocked`.

```
not_eligible_age
referral_required
provider_not_in_network
specialty_not_covered
location_not_covered
insurer_referral_required
allowance_exhausted
provider_on_leave
location_hours
type_not_offered
patient_history
```

The other seven cover endings that are not a clinic rule:

```
no_availability
clinic_closed
patient_not_found
provider_not_found
caller_not_authorised
out_of_scope
medical_emergency
```

Known pairings from the problem set: red flags -> `escalate` with
`medical_emergency`; adversarial calls -> `no-action` with `out_of_scope`; full
calendar -> `no-action` with `no_availability`.

## The 30-second window

The window opens when they open the call and closes **30 s after their socket to
us closes**. Early is never a rejection reason. Only late is. Submit as soon as
the outcome is decided; do not wait for `stop`.

| Situation | Response |
| --- | --- |
| `call_id` was never ours, or is another team's | 404 |
| Call still open, or closed at most 30 s ago | 200 — accepted |
| Call closed more than 30 s ago | 410 — window closed |
| An identical action was already accepted for this call | 409 |
| Malformed body | 422, nothing recorded |

- 200 acknowledges receipt, not a pass. Response:
  `{"call_id": "…", "received_at": "…", "record": {"actions": [...]}}` — every
  action accepted so far, with verbs `REGISTER`, `BOOK`, `RESCHEDULE`, `CANCEL`,
  `NO_ACTION`, `ESCALATE`. A `REGISTER` nests its fields under `new_patient`.
- 409 is a retry of the same action. Expected, not a bug. Treat it as success.
- After the window every route returns 410. The deadline is checked before anything else.
- A call's record is every action accepted inside its window. Most calls submit
  one. "Cancel mine and my son's" submits two, one request each.
- Missing, invalid and revoked keys return `403 {"detail":"Invalid API key"}`.

## Reading our own records

`GET /api/v1/submissions?limit=50` with `X-Api-Key` returns our records. Useful
for a health check or the live view.
