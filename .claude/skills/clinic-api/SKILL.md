---
name: clinic-api
description: Use when you call or mock the clinic's read-only API — directory lookup, availability, a patient's appointments, or the catalogue — and when a lookup returns nothing, too many people, or empty slots and you must decide why.
---

# The clinic API — Clínica Arenal

A read-only EHR, generated once, identical for every team and every call.
Cache the catalogue freely. Nothing here reserves anything. Another team
practising cannot take a slot from us.

Base URL: `PLATFORM_API_BASE_URL` (the host the desk gives). Every route except
`/api/v1/health` and the schema needs `X-Api-Key: <team key>`. Missing, invalid
or revoked key: `403 {"detail":"Invalid API key"}`.

Live schema: ReDoc at the API host, Swagger at `/api/docs`, raw OpenAPI at
`/api/openapi.json`. The docs' prose names the endpoints and the traps. The
schema names the fields. Align `vortex/clinic/client.py` against the schema
once a key exists.

## Per-caller endpoints

| Endpoint | Params | Use |
| --- | --- | --- |
| `GET /api/v1/directory` | `name`, `national_id`, `phone`, `date_of_birth` | Who is calling |
| `GET /api/v1/availability` | `date_from`, `date_to`, plus `provider_id` or `specialty_id`; optional `location_id`, `patient_id`, repeated `insurer` | What they may book and when |
| `GET /api/v1/patients/{patient_id}/appointments` | `when` = `upcoming` (default), `past`, `all` | The diary, earliest first. The only source of an `appointment_id` |

## Catalogue endpoints (no params, never change — pull once at start-up)

| Endpoint | Returns |
| --- | --- |
| `GET /api/v1/clinic` | Everything below in one call, plus the bookable window and the standing restrictions with the decline reason each carries |
| `GET /api/v1/providers` | Specialty, languages, types performed, where and when they sit, plans taken and refused, leave |
| `GET /api/v1/locations` | Three sites: address, opening hours, who sits there, which plans cover them |
| `GET /api/v1/specialties` | Age window, referral required, plans that cover it. The ids `specialty_id=` takes |
| `GET /api/v1/appointment-types` | Duration, specialty, which patient it is for |
| `GET /api/v1/insurance-plans` | What each plan covers, where, which providers take it |

## Traps the docs call out

1. **An exact field that does not match excludes the patient.** It filters, it
   does not downrank. Name plus `date_of_birth` separates two people with the same
   name. A misheard `national_id` usually returns nothing. Some ids differ from
   another patient's by one digit, so a confidently wrong id can return a
   confidently wrong person. Confirm on a second field.
2. **`phone` is folded to nine national digits** before comparison.
   `+34612345678`, `0034612345678` and `612345678` are one query. Pass
   `from_number` as it arrives. A hit is the owner of the line, not always the
   patient being booked for.
3. **Availability answers without being asked to book.** Restriction metadata
   comes back whether or not there are slots. `blocked` names the standing rule
   that stopped a provider. Read the `reason` from it. Never guess which rule bit.
4. **Empty `slots` with empty `blocked` is a full calendar.** That is
   `no_availability`. Empty slots with a non-empty `blocked` is a rule. Different
   answers.
5. **Submit the record's name and id, never what the caller said.** A nickname or
   a misheard surname can still find a patient. It is not a legal name.
6. **Naming a plan is the only way to be quoted against it.** Leave `insurer` out
   and the search prices against the single plan on the record. A second plan is
   nowhere in the data. Ask on the call (problem 17), then pass it as `insurer`.
7. **`/availability` names the one right `appointment_type`** for the patient and
   specialty asked about, and every slot carries that type's id. Submit that id.
8. **Every patient record carries a note and a chart.** The note is free text from
   a receptionist ("hard of hearing — speak slowly"). Not scored, but it is what
   the jury judges a personal call on. Read it before you ask.

## Calendar limits

- Slots run 7 September – 16 October 2026 in 15-minute steps.
- Availability outside that range is 422. A span longer than 14 days is 422.
- `when=past` returns visits from 2024 and 2025, up to eight. Readable, never
  bookable. A past `appointment_id` is never an answer to problem 8.
- `has_visited_before: false` means no past visits at all.

## Offline

Without `PLATFORM_API_KEY`, `FakeClinicClient` answers from
`vortex/clinic/fixtures.py`. It mirrors the documented traps. Add fixtures when
your lane needs a new shape.
