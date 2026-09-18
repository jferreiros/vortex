# Practice cases — problems 1–6

Raw transcription of the first six problem screens from the Prosper dashboard
("Submissions" panel). Cross-referenced against `.claude/skills/the-challenge/problems.md`
for the canonical `problem_id` and weight. Case 01 of "The Rules" is missing its
expected outcome — the source screenshot cut off before it; see the note there.

## 1. The Simple Booking (`simple_booking`, weight 1)

> The baseline. A patient already on file wants the earliest appointment in one specialty.

| # | Patient | Case | Identifies by | Expected |
| - | --- | --- | --- | --- |
| 01 | Josefa Domínguez Navarro | Wants the earliest available General Practice appointment. | DNI/NIE | seen before -> review; `book` |
| 02 | Amelia Hughes White | Wants the earliest available General Practice appointment at Arenal Centro. | DNI/NIE | never seen -> first visit; `book` |
| 03 | Ignacio Vázquez Moreno | Wants the earliest available Orthopaedics appointment. | phone number | seen before -> review; `book` |
| 04 | Chloe Roberts Smith | Wants the earliest available General Practice appointment at Arenal Sur on a Monday in the morning. | DNI/NIE | seen before -> review; `book` |

## 2. The Switchboard (`switchboard`, no weight — not scored)

> The Simple Booking, five, ten or twenty times at once. Every call is a problem-1
> case; there is nothing new to book, only more of it. `Run All` does not dial
> this one — it is already parallel, so concurrency is under test on every
> scored call, and this earns no points. Trigger it yourself before your first
> scored run.

| # | Case | Detail |
| - | --- | --- |
| 01 | 5 calls at once | 5 problem-1 calls opened on the endpoint at the same moment, each its own patient and its own booking. |
| 02 | 10 calls at once | same, 10 concurrent |
| 03 | 20 calls at once | same, 20 concurrent |

## 3. The Doctor and the Site (`doctor_and_site`, weight 2)

> A named provider at a named site, including near-miss surnames, a provider
> on leave, and a provider who is not at that site that day.

| # | Patient | Case | Identifies by | Expected |
| - | --- | --- | --- | --- |
| 01 | Joaquín Ramírez Delgado | Wants an appointment with Dra. Ortiz Vidal at Arenal Centro. The doctor consults there, so their earliest slot at that site. | DNI/NIE | seen before -> review; `book` |
| 02 | Emilio Rubio Jiménez | Wants an appointment with Dr. Sáez, the GP. Not Dra. Sáenz, the paediatrician, who sounds the same. | DNI/NIE | seen before -> review; `book` |
| 03 | Andrés Rubio Vázquez | Wants an appointment with Dr. Requena at Arenal Norte. The doctor is on leave, so the earliest doctor of the same kind at that same site. | DNI/NIE | seen before -> review; `book` |
| 04 | Mario Gómez Blanco | Wants an appointment with Dr. Sáez at Arenal Centro on a Monday. The doctor is not at that site that day, so their earliest slot there on any day. | DNI/NIE | never seen -> first visit; `book` |

## 4. The New Patient (`the_new_patient`, weight 2)

> Register a caller who is not on file, and book nothing: two surnames, DNI or
> NIE with its check letter, date of birth, phone, email, insurer.

| # | Patient | Case | Identifies by | Insurer | Expected |
| - | --- | --- | --- | --- | --- |
| 01 | Joaquín González Ortega | Rings to register; not on file, books nothing. Dictates an email. | DNI | Cigna | `register` |
| 02 | Elizabeth Jones Evans | Rings to register; not on file, books nothing. Dictates an email. | NIE | AXA | `register` |
| 03 | Natalia Muñoz González | Rings to register; not on file, books nothing. Dictates an email. | DNI | Sanitas | `register` |
| 04 | Sergio Martínez Ramírez | Rings to register; not on file, books nothing. Dictates an email. | DNI | Mapfre Salud | `register` |

## 5. When Exactly (`when_exactly`, weight 2)

> Relative and colloquial dates, resolved the moment the call connects, against
> site hours and the published closure day.

| # | Patient | Case | Caller says | Confirm date | Expected |
| - | --- | --- | --- | --- | --- |
| 01 | Josefa Domínguez Navarro | Books a General Practice appointment (hay fever worse than usual this year). | "tomorrow" | Saturday 19 September 2026 | `book` |
| 02 | Ignacio Vázquez Moreno | Books an Orthopaedics appointment (hip clicks and aches getting out of a chair). | "this coming Thursday" | Thursday 24 September 2026 | `book` |
| 03 | Ignacio Vázquez Moreno | Books a General Practice appointment (cough hanging around three weeks). | "Saturday morning" | Saturday 19 September 2026 | `book` |
| 04 | Chloe Roberts Smith | Books a General Practice appointment at Arenal Centro (repeat prescription about to run out). | "this coming Sunday" | Sunday 20 September 2026 | `book` |
| 05 | Amelia Hughes White | Books a General Practice appointment at Arenal Centro (blood pressure reading high on the pharmacy machine). | "first thing on Monday the twelfth of October" | Monday 12 October 2026 | `book` |

Note: 12 October 2026 is the published network-wide closure day (Fiesta
Nacional) per `problems.md` §5 — case 05 is very likely the trap that
requires moving to the next open day/slot that still matches "first thing" /
same site, not a straight booking on the 12th. Flagged as an open question
below.

## 6. The Rules (`the_rules`, weight 3)

> Age limits, referral requirements and the insurance matrix: a plan can
> refuse a specialty, a site, or be refused by the provider. The right answer
> is often a refusal carrying the rule that bit.

| # | Patient | Case | Expected |
| - | --- | --- | --- |
| 01 | Sonia Álvarez Medina | Books the earliest available General Practice appointment because her daughter's routine check-up is due. | **unknown — see note** |
| 02 | Teresa López García | Books the earliest available Dermatology appointment (a mole on her back looks different from last year). | `no-action` · `referral_required` |
| 03 | Josefa Sánche[z]... | Books the earliest available Gynaecology appointment (yearly check-up due). | `no-action` · `specialty_not_covered` |
| 04 | Gloria González Blanco | Books an appointment with Dra. Iglesias (eczema flared up, usual cream not working). | `book` |
| 05 | Ignacio Vázquez Moreno | Books the earliest available Dermatology appointment (a rash on the arm keeps coming back). | `book` |

Note: case 01's expected outcome was cut off in the source screenshot. Given
`clinic-rules` SKILL.md's age rule ("every age has exactly one correct
specialty... paediatrics vs general practice") and that the caller is asking
on behalf of "her daughter", this smells like either (a) a third-party
booking where the daughter's age forces Paediatrics instead of General
Practice, or (b) a control case that books normally. Flagged as an open
question below.
