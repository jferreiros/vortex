---
name: clinic-rules
description: Use when you decide what to book or refuse — resolving a spoken date to a slot, checking site hours and closures, picking the appointment type, matching a provider by name, applying insurance or age rules, routing a symptom, or choosing the nearest site.
---

# Clinic rules — the facts no schema states

The catalogue tells you dermatology needs a referral. It does not tell you this
caller has none. Noticing that a rule applies to the person on the line is the
job. These are the published facts and traps, by lane.

## Time and dates (La Agenda)

- Resolve dates against the moment the call connects, in Europe/Madrid. Not the
  machine clock. Not a fixed anchor.
- Nothing is booked same-day. "Earliest" starts the day after the call.
  `/availability` still lists today's free slots. Never submit one.
- "Morning" is before 14:00. "Afternoon" is from 14:00.
- A weekday phrase is the first such weekday strictly after the day of the call.
- Fixed vocabulary for problem 5: `tomorrow`, `the day after tomorrow`, `a week
  from today`, `in a fortnight`, `on Saturday morning`, `first thing on Monday the
  twelfth of October`, `this coming <day>`, `first thing <day>`, `<day> afternoon`.
- Closed day: move to the earliest slot on the next open day that keeps the rest
  of the request (same site, same part of the day).
- Public cases anchor to 09:00 Europe/Madrid on the day dialled.

## Sites and hours (La Agenda)

- Three sites: Centro, Norte, Sur.
- Sur shuts Friday lunchtime. Only Centro opens Saturday. Nothing opens Sunday.
- Monday 12 October 2026 is Fiesta Nacional: the whole network is shut. It is the
  one published closure day, and "first thing Monday" lands on it.
- Nearest site (problem 15): smallest straight-line distance from the caller's
  address to the coordinates published in `/availability`'s location data, among
  the sites that can serve the request. If the closest has nobody for the
  specialty, pick the closest one that does. Not a refusal.

## Appointment type (Las Reglas / La Agenda)

- Eleven types. Exactly one is right for any booking. It follows from two facts on
  the record, never from the conversation: the specialty booked, and the patient's
  `has_visited_before`.
- A specialty's own types win over the two universal ones (`first_visit`, `review`).
  Gynaecology has its own review only, so a new gynaecology patient books the
  universal `first_visit`.
- Two specialty pairs run the same minutes as the universal ones. Only the id
  separates `review` from `dermatology_review`. Hard-coding `review` fails a case
  the agent understood perfectly.
- `/availability` returns the right type as `appointment_type`, and each slot
  carries its id. Submit that id.

## Providers (Identidad / La Agenda)

- Twelve providers, six specialties.
- Dr. Requena is on sick leave 14–30 September, the whole event. A caller who asks
  for him must be moved (`provider_on_leave`, or a redirected BOOK).
- Two near-miss pairs, each in a different specialty: Sáez (general practice) /
  Sáenz (paediatrics), and Iglesias (dermatology) / Iglesia (orthopaedics). Ask which.
- D. Álvaro Cid is a physiotherapist, not a doctor. "D.", not "Dr." The title is
  part of the name.
- Language constrains a booking only in problem 11. Every provider speaks
  Spanish; four speak Catalan.
- Diaries run 40% to 72% full, provider by provider. The one gynaecologist has full
  days. The one physiotherapist has room. Spread the load when the caller has no
  preference, but the caller's ask comes first.

## Age (Las Reglas)

- The 14th birthday is the boundary, in months, no gap, no overlap. Every age has
  exactly one correct specialty for a general complaint (paediatrics vs general
  practice). Held referrals are on the directory record.

## Insurance (Las Reglas)

- Ten plans. Patients hold one or two. Only the first is on the directory record.
  The second exists only if you ask on the call.
- ASISA covers physiotherapy only at Centro and Norte. The only physiotherapist
  sits at Sur. An ASISA patient can never book physio.
- Adeslas covers no gynaecology. There is one gynaecologist. Nowhere to redirect.
- Dra. Iglesias does not take DKV. Dr. Vilar does. A DKV patient asking for her
  by name is a redirect, not a refusal. Every other provider takes all ten plans.
- `privado` is self-pay, a plan a patient holds or does not. Not a fallback. An
  uncovered patient is refused.
- Five refusal shapes (problem 6): plan refuses the specialty
  (`specialty_not_covered`), plan refuses the site (`location_not_covered`),
  provider refuses the plan (`provider_not_in_network`), plan demands its own
  referral (`insurer_referral_required`), plan out of visits this year
  (`allowance_exhausted`). Take the exact reason from `blocked`.
- Visit history is deliberately older than this year, so it never disagrees with
  a capped plan's spend.

## Triage (Las Reglas)

- Routing is a lookup on the published symptom table, not clinical judgement. The
  full table and the five red flags are in
  `.claude/skills/the-challenge/problems.md`, section 10.
- Red flags -> `ESCALATE(medical_emergency)`. Book nothing.
- Referral-required specialties are kept out of triage cases.

## Identity (Identidad)

- Register before you book. A caller not in the directory has no `patient_id`.
- DNI/NIE check letter is computed from the digits. Never trust the letter as heard.
- The email has no check. It is dictated. Confirm it back.
- Third party: the caller often gives their own details first. Book for the patient.
- A chart with nothing on it under a name the caller says is a regular is a signal
  you have the wrong person.

## Privacy (La Conversación)

- Never read a patient's `national_id` or `phone` aloud, in full or digit by
  digit, on our turns. Problem 14 runs a substring check after normalization.
  The name is not protected.
- Do not read data of a patient the caller has not been identified as, or
  authorised for.
