"""Fake clinic data for offline work.

These are **raw platform payloads**, not contract records: ``CLINIC`` is shaped
like ``GET /api/v1/clinic``'s ``ClinicResponse``, ``PATIENTS`` like
``/directory``'s ``PatientMatchOut`` and ``APPOINTMENTS`` like
``/patients/{id}/appointments``' ``AppointmentOut``, down to the en dash in
``"09:00–20:00"`` and the ten-plan insurer vocabulary. ``FakeClinicClient``
feeds them through the same ``_adapt_*`` functions a live response goes
through, so the offline suite tests the adapters too.

Ids and people here are invented. They mirror the traps the docs describe
(near-miss surnames, a provider on leave, a same-name pair) so the lanes can
rehearse against them. Keep the set small.

The published Problems-page cases live in ``synthetic-data/`` (same keys,
separate folder). ``FakeClinicClient()`` keeps this small set;
``FakeClinicClient(data_dir=...)`` reads the pack. Regenerate with
``make evals-hydrate``.

Owner: clinic/. Add fixtures here when a lane needs a new shape to test against.
"""

from __future__ import annotations

from typing import Any

#: The platform's ten plans, id -> display name. The ``insurer`` and
#: ``policy_id`` we submit must be one of these ids.
INSURER_NAMES: dict[str, str] = {
    "sanitas": "Sanitas",
    "adeslas": "Adeslas",
    "dkv": "DKV",
    "asisa": "ASISA",
    "mapfre": "Mapfre Salud",
    "caser": "Caser Salud",
    "cigna": "Cigna",
    "axa": "AXA",
    "nueva_mutua": "Nueva Mutua Sanitaria",
    "privado": "Privado",
}

ALL_PLANS: list[str] = list(INSURER_NAMES)


def insurer_refs(ids: list[str]) -> list[dict[str, str]]:
    """``ClinicInsurerRef``: the catalogue names a plan as ``{id, name}``."""
    return [{"id": i, "name": INSURER_NAMES[i]} for i in ids]


def days(intervals_by_weekday: dict[str, str]) -> list[dict[str, Any]]:
    """``ClinicDayResponse``: a named weekday and its ``"09:00–20:00"`` intervals."""
    return [{"weekday": d, "intervals": [iv]} for d, iv in intervals_by_weekday.items()]


WEEKDAYS_9_20 = {
    "monday": "09:00–20:00",
    "tuesday": "09:00–20:00",
    "wednesday": "09:00–20:00",
    "thursday": "09:00–20:00",
    "friday": "09:00–20:00",
}

LOCATIONS: list[dict[str, Any]] = [
    {
        "id": "centro",
        "name": "Arenal Centro",
        "address": "Calle del Arenal 1, Madrid",
        "latitude": 40.4170,
        "longitude": -3.7060,
        "hours": days(WEEKDAYS_9_20 | {"saturday": "09:00–14:00"}),
        "provider_names": ["Dra. Ortiz", "Dra. Sáenz", "Dra. Iglesias"],
        "covered_by": insurer_refs(ALL_PLANS),
        "not_covered_by": [],
    },
    {
        "id": "norte",
        "name": "Arenal Norte",
        "address": "Paseo de la Castellana 200, Madrid",
        "latitude": 40.4700,
        "longitude": -3.6880,
        "hours": days(WEEKDAYS_9_20),
        "provider_names": ["Dr. Sáez", "Dr. Requena"],
        "covered_by": insurer_refs(ALL_PLANS),
        "not_covered_by": [],
    },
    {
        "id": "sur",
        "name": "Arenal Sur",
        # Sur shuts Friday lunchtime.
        "address": "Calle de Madrid 54, Getafe",
        "latitude": 40.3080,
        "longitude": -3.7320,
        "hours": days(
            {
                "monday": "09:00–20:00",
                "tuesday": "09:00–20:00",
                "wednesday": "09:00–20:00",
                "thursday": "09:00–20:00",
                "friday": "09:00–14:00",
            }
        ),
        "provider_names": ["Dr. Iglesia", "D. Álvaro Cid"],
        # ASISA does not cover Sur; the physiotherapist sits there.
        "covered_by": insurer_refs([i for i in ALL_PLANS if i != "asisa"]),
        "not_covered_by": insurer_refs(["asisa"]),
    },
]

SPECIALTIES: list[dict[str, Any]] = [
    {
        "id": "general_practice",
        "name": "General practice",
        "min_age_months": 14 * 12,
        "max_age_months": None,
        "referral_required": False,
        "provider_names": ["Dra. Ortiz", "Dr. Sáez", "Dr. Requena"],
        "covered_by": insurer_refs(ALL_PLANS),
        "not_covered_by": [],
    },
    {
        "id": "paediatrics",
        "name": "Paediatrics",
        "min_age_months": 0,
        "max_age_months": 14 * 12 - 1,
        "referral_required": False,
        "provider_names": ["Dra. Sáenz"],
        "covered_by": insurer_refs(ALL_PLANS),
        "not_covered_by": [],
    },
    {
        "id": "dermatology",
        "name": "Dermatology",
        "min_age_months": 0,
        "max_age_months": None,
        "referral_required": True,
        "provider_names": ["Dra. Iglesias"],
        "covered_by": insurer_refs(ALL_PLANS),
        "not_covered_by": [],
    },
    {
        "id": "orthopaedics",
        "name": "Orthopaedics",
        "min_age_months": 0,
        "max_age_months": None,
        "referral_required": False,
        "provider_names": ["Dr. Iglesia"],
        "covered_by": insurer_refs(ALL_PLANS),
        "not_covered_by": [],
    },
    {
        # No age window on purpose: the rules must not invent one.
        "id": "gynaecology",
        "name": "Gynaecology",
        "min_age_months": 0,
        "max_age_months": None,
        "referral_required": False,
        "provider_names": [],
        # Adeslas does not cover gynaecology.
        "covered_by": insurer_refs([i for i in ALL_PLANS if i != "adeslas"]),
        "not_covered_by": insurer_refs(["adeslas"]),
    },
    {
        "id": "physiotherapy",
        "name": "Physiotherapy",
        "min_age_months": 0,
        "max_age_months": None,
        "referral_required": False,
        "provider_names": ["D. Álvaro Cid"],
        "covered_by": insurer_refs(ALL_PLANS),
        "not_covered_by": [],
    },
]

APPOINTMENT_TYPES: list[dict[str, Any]] = [
    {
        "id": "first_visit",
        "name": "First visit",
        "duration_minutes": 30,
        "new_patient_requirement": "new_only",
        "guidance": "A patient the clinic has never seen, in a specialty without its own.",
        "provider_names": ["Dra. Ortiz", "Dr. Sáez", "Dr. Requena", "Dr. Iglesia", "D. Álvaro Cid"],
        "specialty_id": None,
        "specialty_name": None,
    },
    {
        "id": "review",
        "name": "Review",
        "duration_minutes": 15,
        "new_patient_requirement": "existing_only",
        "guidance": "Any returning patient in a specialty without its own review type.",
        "provider_names": ["Dra. Ortiz", "Dr. Sáez", "Dr. Requena", "Dr. Iglesia", "D. Álvaro Cid"],
        "specialty_id": None,
        "specialty_name": None,
    },
    {
        "id": "dermatology_first",
        "name": "Dermatology first visit",
        "duration_minutes": 30,
        "new_patient_requirement": "new_only",
        "guidance": "New dermatology patient.",
        "provider_names": ["Dra. Iglesias"],
        "specialty_id": "dermatology",
        "specialty_name": "Dermatology",
    },
    {
        "id": "dermatology_review",
        "name": "Dermatology review",
        "duration_minutes": 15,
        "new_patient_requirement": "existing_only",
        "guidance": "Returning dermatology patient. Same minutes as review; different id.",
        "provider_names": ["Dra. Iglesias"],
        "specialty_id": "dermatology",
        "specialty_name": "Dermatology",
    },
    {
        "id": "gynaecology_review",
        "name": "Gynaecology review",
        "duration_minutes": 15,
        "new_patient_requirement": "existing_only",
        "guidance": "Returning gynaecology patient. New patients book first_visit.",
        "provider_names": [],
        "specialty_id": "gynaecology",
        "specialty_name": "Gynaecology",
    },
]


def schedule(location_id: str, location_name: str, hours: dict[str, str]) -> dict[str, Any]:
    """``ClinicScheduleResponse``: when one provider sits at one site."""
    return {"location_id": location_id, "location_name": location_name, "days": days(hours)}


CENTRO_HOURS = schedule("centro", "Arenal Centro", WEEKDAYS_9_20 | {"saturday": "09:00–14:00"})
NORTE_HOURS = schedule("norte", "Arenal Norte", WEEKDAYS_9_20)
SUR_HOURS = schedule("sur", "Arenal Sur", WEEKDAYS_9_20 | {"friday": "09:00–14:00"})

PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "PR01",
        "name": "Dra. Ortiz",
        "specialty_id": "general_practice",
        "specialty_name": "General practice",
        "languages": ["es", "en"],
        "appointment_type_names": ["First visit", "Review"],
        "location_names": ["Arenal Centro"],
        "schedules": [CENTRO_HOURS],
        "accepted_insurers": insurer_refs(ALL_PLANS),
        "refused_insurers": [],
        "leave": None,
    },
    {
        "id": "PR02",
        "name": "Dr. Sáez",
        "specialty_id": "general_practice",
        "specialty_name": "General practice",
        "languages": ["es", "ca"],
        "appointment_type_names": ["First visit", "Review"],
        "location_names": ["Arenal Norte"],
        "schedules": [NORTE_HOURS],
        "accepted_insurers": insurer_refs(ALL_PLANS),
        "refused_insurers": [],
        "leave": None,
    },
    {
        # One letter from PR02: "Sáenz" and "Sáez" are the near-miss pair.
        "id": "PR03",
        "name": "Dra. Sáenz",
        "specialty_id": "paediatrics",
        "specialty_name": "Paediatrics",
        "languages": ["es"],
        "appointment_type_names": ["First visit", "Review"],
        "location_names": ["Arenal Centro"],
        "schedules": [CENTRO_HOURS],
        "accepted_insurers": insurer_refs(ALL_PLANS),
        "refused_insurers": [],
        "leave": None,
    },
    {
        "id": "PR04",
        "name": "Dra. Iglesias",
        "specialty_id": "dermatology",
        "specialty_name": "Dermatology",
        "languages": ["es", "en"],
        "appointment_type_names": ["Dermatology first visit", "Dermatology review"],
        "location_names": ["Arenal Centro"],
        "schedules": [CENTRO_HOURS],
        # Refuses DKV: the provider_not_in_network case.
        "accepted_insurers": insurer_refs([i for i in ALL_PLANS if i != "dkv"]),
        "refused_insurers": insurer_refs(["dkv"]),
        "leave": None,
    },
    {
        # One letter from PR04.
        "id": "PR05",
        "name": "Dr. Iglesia",
        "specialty_id": "orthopaedics",
        "specialty_name": "Orthopaedics",
        "languages": ["es"],
        "appointment_type_names": ["First visit", "Review"],
        "location_names": ["Arenal Sur"],
        "schedules": [SUR_HOURS],
        "accepted_insurers": insurer_refs(ALL_PLANS),
        "refused_insurers": [],
        "leave": None,
    },
    {
        "id": "PR06",
        "name": "D. Álvaro Cid",
        "specialty_id": "physiotherapy",
        "specialty_name": "Physiotherapy",
        "languages": ["es", "ca"],
        "appointment_type_names": ["First visit", "Review"],
        "location_names": ["Arenal Sur"],
        "schedules": [SUR_HOURS],
        "accepted_insurers": insurer_refs(ALL_PLANS),
        "refused_insurers": [],
        "leave": None,
    },
    {
        "id": "PR07",
        "name": "Dr. Requena",
        "specialty_id": "general_practice",
        "specialty_name": "General practice",
        "languages": ["es"],
        "appointment_type_names": ["First visit", "Review"],
        "location_names": ["Arenal Norte"],
        "schedules": [NORTE_HOURS],
        "accepted_insurers": insurer_refs(ALL_PLANS),
        "refused_insurers": [],
        # The platform sends one leave period or null, never a list.
        "leave": {"start": "2026-09-14", "end": "2026-09-30", "reason": "sick leave"},
    },
]

SPECIALTY_NAMES = [s["name"] for s in SPECIALTIES]
LOCATION_NAMES = [loc["name"] for loc in LOCATIONS]
PROVIDER_NAMES = [p["name"] for p in PROVIDERS]

PLANS: list[dict[str, Any]] = [
    {
        "id": plan_id,
        "name": INSURER_NAMES[plan_id],
        "covered_specialty_names": [
            n for n in SPECIALTY_NAMES if not (plan_id == "adeslas" and n == "Gynaecology")
        ],
        "uncovered_specialty_names": ["Gynaecology"] if plan_id == "adeslas" else [],
        "covered_location_names": [
            n for n in LOCATION_NAMES if not (plan_id == "asisa" and n == "Arenal Sur")
        ],
        "uncovered_location_names": ["Arenal Sur"] if plan_id == "asisa" else [],
        "accepted_by": [
            n for n in PROVIDER_NAMES if not (plan_id == "dkv" and n == "Dra. Iglesias")
        ],
        "refused_by": ["Dra. Iglesias"] if plan_id == "dkv" else [],
        "holders": 100,
    }
    for plan_id in ALL_PLANS
]

#: A restriction's id *is* the decline reason it carries; ``/availability``'s
#: ``blocked[].restriction`` names one of these eleven.
RESTRICTIONS: list[dict[str, str]] = [
    {
        "id": "not_eligible_age",
        "title": "Not eligible by age",
        "explanation": "The patient is outside the specialty's age window.",
    },
    {
        "id": "referral_required",
        "title": "Referral required",
        "explanation": "The specialty needs a referral the patient does not hold.",
    },
    {
        "id": "provider_not_in_network",
        "title": "Provider not in network",
        "explanation": "The provider refuses the patient's plan.",
    },
    {
        "id": "specialty_not_covered",
        "title": "Specialty not covered",
        "explanation": "The plan does not cover the specialty.",
    },
    {
        "id": "location_not_covered",
        "title": "Location not covered",
        "explanation": "The plan does not cover the site.",
    },
    {
        "id": "insurer_referral_required",
        "title": "Insurer referral required",
        "explanation": "The plan needs its own referral.",
    },
    {
        "id": "allowance_exhausted",
        "title": "Allowance exhausted",
        "explanation": "The patient has used this year's visits.",
    },
    {
        "id": "provider_on_leave",
        "title": "Provider on leave",
        "explanation": "The provider is away for the whole window asked about.",
    },
    {
        "id": "location_hours",
        "title": "Outside site hours",
        "explanation": "The site is shut, or the provider does not sit there then.",
    },
    {
        "id": "type_not_offered",
        "title": "Type not offered",
        "explanation": "The provider does not perform that appointment type.",
    },
    {
        "id": "patient_history",
        "title": "Patient history",
        "explanation": "The record forbids this booking.",
    },
]

#: The two plan rules the catalogue cannot express. ``ClinicPlanResponse`` has
#: no referral or allowance field, so on a live call these reach us only as
#: ``/availability``'s ``blocked[].restriction``. The fake answers the same way:
#: a provider these tables stop is listed in ``blocked`` with the restriction
#: id, and none of their slots are offered.
#:
#: A plan that demands its own referral for a specialty, on top of anything the
#: specialty itself asks. Orthopaedics needs none, so here the plan's rule is
#: the only one that can bite. A referral on the record for that specialty
#: satisfies it.
PLAN_REFERRALS: list[dict[str, str]] = [
    {
        "insurer": "mapfre",
        "specialty_id": "orthopaedics",
        "restriction": "insurer_referral_required",
    },
]

#: A plan a patient has used up for the year. The visits that spent it are not
#: in ``APPOINTMENTS`` on purpose: the platform's history is older than this
#: year, so nothing we can read disagrees with the plan's own count.
EXHAUSTED_ALLOWANCES: list[dict[str, str]] = [
    {"patient_id": "P00301", "insurer": "caser", "restriction": "allowance_exhausted"},
]

CLINIC: dict[str, Any] = {
    "clinic_name": "Clínica Arenal (fixtures)",
    "patient_count": 6,
    "calendar": {
        "starts": "2026-09-07",
        "ends": "2026-10-16",
        "max_span_days": 14,
        "slot_minutes": 15,
        "closure_days": ["2026-10-12"],
        "appointment_count": 4,
    },
    "restrictions": RESTRICTIONS,
    "providers": PROVIDERS,
    "specialties": SPECIALTIES,
    "appointment_types": APPOINTMENT_TYPES,
    "locations": LOCATIONS,
    "plans": PLANS,
}

#: ``PatientMatchOut``. Note what is *not* here: the directory returns no email.
PATIENTS: list[dict[str, Any]] = [
    # The published problem 5 ("when exactly") personas, so a scenario can name
    # them and the agent can look them up. Identity is incidental here; the day
    # the caller says is the whole point of every one of these records.
    {
        "patient_id": "P00001",
        "given_name": "Josefa",
        "first_surname": "Domínguez",
        "second_surname": "Navarro",
        "national_id": "48064716Y",
        "date_of_birth": "2001-09-19",
        "phone": "711330529",
        "sex": "F",
        "has_visited_before": True,
        "insurer": "mapfre",
        "referrals": [],
        "note": "Fake record. Published case: general practice tomorrow.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00005",
        "given_name": "Ignacio",
        "first_surname": "Vázquez",
        "second_surname": "Moreno",
        "national_id": "65699248R",
        "date_of_birth": "1939-12-09",
        "phone": "731169716",
        "sex": "M",
        "has_visited_before": True,
        "insurer": "cigna",
        # Holds a dermatology referral: problem 6's control case, the referred
        # adult whose booking goes through with nothing to refuse.
        "referrals": ["dermatology"],
        "note": "Fake record. Published cases: orthopaedics Thursday, general practice Saturday.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00011",
        "given_name": "Chloe",
        "first_surname": "Roberts",
        "second_surname": "Smith",
        "national_id": "Z4237244M",
        "date_of_birth": "1996-09-01",
        "phone": "708729566",
        "sex": "F",
        "has_visited_before": True,
        "insurer": "mapfre",
        "referrals": [],
        "note": "Fake record. Published case: general practice at Centro this coming Sunday.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        # Never seen: the published answer for her is a first_visit, not a review.
        "patient_id": "P00012",
        "given_name": "Amelia",
        "first_surname": "Hughes",
        "second_surname": "White",
        "national_id": "13309713G",
        "date_of_birth": "1981-04-08",
        "phone": "712676131",
        "sex": "F",
        "has_visited_before": False,
        "insurer": "sanitas",
        "referrals": [],
        "note": "Fake record. Published case: first thing Monday the twelfth of October.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00042",
        "given_name": "Marta",
        "first_surname": "Ruiz",
        "second_surname": "López",
        "national_id": "12345678Z",
        "date_of_birth": "1985-03-12",
        "phone": "612345678",
        "sex": "F",
        "has_visited_before": True,
        "insurer": "sanitas",
        "referrals": [],
        "note": "Fake record. Seen twice, both times by Dra. Ortiz at Arenal Centro.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        # Same name as P00042, different birth date: the ambiguity case.
        "patient_id": "P00043",
        "given_name": "Marta",
        "first_surname": "Ruiz",
        "second_surname": "García",
        "national_id": "87654321X",
        "date_of_birth": "1992-11-02",
        "phone": "699000111",
        "sex": "F",
        "has_visited_before": False,
        "insurer": "adeslas",
        "referrals": [],
        "note": "Fake record. Never seen. Registered online.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00107",
        "given_name": "Lucas",
        "first_surname": "Ruiz",
        "second_surname": "López",
        "national_id": "",
        "date_of_birth": "2018-06-20",
        "phone": "612345678",  # the mother's line (P00042)
        "sex": "M",
        "has_visited_before": True,
        "insurer": "sanitas",
        "referrals": [],
        "note": "Fake record. Child. Mother (Marta Ruiz López) usually calls. Seen by Dra. Sáenz.",
        "match_score": 1.0,
        "matched_fields": ["phone"],
    },
    {
        "patient_id": "P00200",
        "given_name": "Antonio",
        "first_surname": "Pérez",
        "second_surname": "Martín",
        "national_id": "X1234567L",
        "date_of_birth": "1958-01-30",
        "phone": "655555555",
        "sex": "M",
        "has_visited_before": True,
        "insurer": "dkv",
        "referrals": ["dermatology"],
        "note": "Fake record. Hard of hearing; speak slowly. Holds a dermatology referral.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        # Her plan demands its own referral for orthopaedics (PLAN_REFERRALS).
        "patient_id": "P00300",
        "given_name": "Carmen",
        "first_surname": "Delgado",
        "second_surname": "Soto",
        "national_id": "45678912S",
        "date_of_birth": "1970-05-05",
        "phone": "611222333",
        "sex": "F",
        "has_visited_before": True,
        "insurer": "mapfre",
        "referrals": [],
        "note": "Fake record. Seen once by Dra. Ortiz at Arenal Norte.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        # His plan is out of visits for the year (EXHAUSTED_ALLOWANCES).
        "patient_id": "P00301",
        "given_name": "Rafael",
        "first_surname": "Moreno",
        "second_surname": "Vidal",
        "national_id": "78912345N",
        "date_of_birth": "1966-08-14",
        "phone": "622333444",
        "sex": "M",
        "has_visited_before": True,
        "insurer": "caser",
        "referrals": [],
        "note": "Fake record. Regular at Arenal Centro. Prefers mornings.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        # Problem 17 (second policy): ASISA never covers Sur, the physiotherapist's
        # only site. The API carries one plan per patient; a second one exists only
        # if the caller names it, which is what this fixture is here to exercise.
        "patient_id": "P00250",
        "given_name": "Elena",
        "first_surname": "Molina",
        "second_surname": "Torres",
        "national_id": "23456789D",
        "date_of_birth": "1979-05-04",
        "phone": "677111222",
        "sex": "F",
        "has_visited_before": True,
        "insurer": "asisa",
        "referrals": [],
        "note": "Fake record. On ASISA only on file; holds Sanitas too but never volunteers it.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00201",
        "given_name": "Laura",
        "first_surname": "Gómez",
        "second_surname": "Herrera",
        "national_id": "55667788Z",
        "date_of_birth": "1990-05-14",
        "phone": "699112233",
        "sex": "F",
        "has_visited_before": True,
        "insurer": "asisa",
        "referrals": [],
        "note": "Fake record. Seen once before, by D. Álvaro Cid.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00202",
        "given_name": "Manuel",
        "first_surname": "Torres",
        "second_surname": "Domínguez",
        "national_id": "66778899D",
        "date_of_birth": "1979-11-02",
        "phone": "688223344",
        "sex": "M",
        "has_visited_before": False,
        "insurer": "asisa",
        "referrals": [],
        "note": "Fake record. Never seen.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00203",
        "given_name": "Elvira",
        "first_surname": "Castro",
        "second_surname": "Molina",
        "national_id": "77889900D",
        "date_of_birth": "1995-02-20",
        "phone": "677334455",
        "sex": "F",
        "has_visited_before": False,
        "insurer": "nueva_mutua",
        "referrals": [],
        "note": "Fake record. Never seen.",
        "match_score": 1.0,
        "matched_fields": ["name"],
    },
    {
        "patient_id": "P00204",
        "given_name": "Sofía",
        "first_surname": "Pérez",
        "second_surname": "Ruiz",
        "national_id": "",
        "date_of_birth": "2012-05-14",
        "phone": "",
        "sex": "F",
        "has_visited_before": True,
        "insurer": "dkv",
        "referrals": [],
        "note": "Fake record. Child. Father (Antonio Pérez Martín) usually calls. Seen by Iglesia.",
        "match_score": 1.0,
        "matched_fields": ["phone"],
    },
]

#: ``AppointmentOut``. The platform sends no status: ``when=upcoming`` is the
#: only thing that can be cancelled or moved.
APPOINTMENTS: list[dict[str, Any]] = [
    {
        "appointment_id": "A0001",
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "review",
        "start_time": "2026-09-30T10:00:00+02:00",
        "duration_minutes": 15,
    },
    {
        "appointment_id": "A0002",
        "patient_id": "P00107",
        "provider_id": "PR03",
        "location_id": "centro",
        "appointment_type_id": "review",
        "start_time": "2026-10-02T17:15:00+02:00",
        "duration_minutes": 15,
    },
    {
        "appointment_id": "A9001",
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "review",
        "start_time": "2025-03-14T09:30:00+01:00",
        "duration_minutes": 15,
    },
    {
        "appointment_id": "A9002",
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "first_visit",
        "start_time": "2024-04-08T11:00:00+02:00",
        "duration_minutes": 30,
    },
    {
        "appointment_id": "A0003",
        "patient_id": "P00204",
        "provider_id": "PR05",
        "location_id": "sur",
        "appointment_type_id": "review",
        "start_time": "2026-09-22T11:15:00+02:00",
        "duration_minutes": 15,
    },
]
