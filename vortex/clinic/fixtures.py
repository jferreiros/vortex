"""Fake clinic data for offline work. Raw dicts, shaped like the API answers.

Ids and people here are invented. They mirror the traps the docs describe
(near-miss surnames, a provider on leave, a same-name pair) so the lanes can
rehearse against them before the key arrives. Keep the set small.

Owner: clinic/. Add fixtures here when a lane needs a new shape to test against.
"""

from __future__ import annotations

WEEKDAY_HOURS = [{"weekday": d, "opens": "09:00", "closes": "20:00"} for d in range(5)]  # Mon-Fri

LOCATIONS: list[dict] = [
    {
        "location_id": "centro",
        "name": "Arenal Centro",
        "address": "Calle del Arenal 1, Madrid",
        "latitude": 40.4170,
        "longitude": -3.7060,
        "hours": WEEKDAY_HOURS + [{"weekday": 5, "opens": "09:00", "closes": "14:00"}],
        "provider_ids": ["PR01", "PR03", "PR04"],
        "insurer_ids": ["sanitas", "adeslas", "asisa", "dkv", "privado"],
    },
    {
        "location_id": "norte",
        "name": "Arenal Norte",
        "address": "Paseo de la Castellana 200, Madrid",
        "latitude": 40.4700,
        "longitude": -3.6880,
        "hours": WEEKDAY_HOURS,
        "provider_ids": ["PR02", "PR07"],
        "insurer_ids": ["sanitas", "adeslas", "asisa", "dkv", "privado"],
    },
    {
        "location_id": "sur",
        "name": "Arenal Sur",
        "address": "Calle de Madrid 54, Getafe",
        "latitude": 40.3080,
        "longitude": -3.7320,
        # Sur shuts Friday lunchtime.
        "hours": [{"weekday": d, "opens": "09:00", "closes": "20:00"} for d in range(4)]
        + [{"weekday": 4, "opens": "09:00", "closes": "14:00"}],
        "provider_ids": ["PR05", "PR06"],
        "insurer_ids": ["sanitas", "adeslas", "dkv", "privado"],
    },
]

SPECIALTIES: list[dict] = [
    {
        "specialty_id": "general_practice",
        "name": "General practice",
        "min_age_months": 14 * 12,
        "referral_required": False,
        "insurer_ids": ["sanitas", "adeslas", "asisa", "dkv", "privado"],
    },
    {
        "specialty_id": "paediatrics",
        "name": "Paediatrics",
        "max_age_months": 14 * 12 - 1,
        "referral_required": False,
        "insurer_ids": ["sanitas", "adeslas", "asisa", "dkv", "privado"],
    },
    {
        "specialty_id": "dermatology",
        "name": "Dermatology",
        "referral_required": True,
        "insurer_ids": ["sanitas", "adeslas", "asisa", "dkv", "privado"],
    },
    {
        "specialty_id": "orthopaedics",
        "name": "Orthopaedics",
        "referral_required": False,
        "insurer_ids": ["sanitas", "adeslas", "asisa", "dkv", "privado"],
    },
    {
        "specialty_id": "gynaecology",
        "name": "Gynaecology",
        "referral_required": False,
        "insurer_ids": ["sanitas", "asisa", "dkv", "privado"],  # not adeslas
    },
    {
        "specialty_id": "physiotherapy",
        "name": "Physiotherapy",
        "referral_required": False,
        "insurer_ids": ["sanitas", "adeslas", "asisa", "dkv", "privado"],
    },
]

APPOINTMENT_TYPES: list[dict] = [
    {
        "appointment_type_id": "first_visit",
        "name": "First visit",
        "specialty_id": None,
        "duration_minutes": 30,
        "for_new_patients": True,
        "guidance": "A patient the clinic has never seen, in a specialty without its own.",
    },
    {
        "appointment_type_id": "review",
        "name": "Review",
        "specialty_id": None,
        "duration_minutes": 15,
        "for_new_patients": False,
        "guidance": "Any returning patient in a specialty without its own review type.",
    },
    {
        "appointment_type_id": "dermatology_first",
        "name": "Dermatology first visit",
        "specialty_id": "dermatology",
        "duration_minutes": 30,
        "for_new_patients": True,
        "guidance": "New dermatology patient.",
    },
    {
        "appointment_type_id": "dermatology_review",
        "name": "Dermatology review",
        "specialty_id": "dermatology",
        "duration_minutes": 15,
        "for_new_patients": False,
        "guidance": "Returning dermatology patient. Same minutes as review; different id.",
    },
    {
        "appointment_type_id": "gynaecology_review",
        "name": "Gynaecology review",
        "specialty_id": "gynaecology",
        "duration_minutes": 15,
        "for_new_patients": False,
        "guidance": "Returning gynaecology patient. New patients book first_visit.",
    },
]

ALL_PLANS = ["sanitas", "adeslas", "asisa", "dkv", "privado"]

PROVIDERS: list[dict] = [
    {
        "provider_id": "PR01",
        "name": "Dra. Ortiz",
        "specialty_id": "general_practice",
        "languages": ["es", "en"],
        "appointment_type_ids": ["first_visit", "review"],
        "location_ids": ["centro"],
        "insurer_ids_accepted": ALL_PLANS,
        "insurer_ids_refused": [],
        "leave": [],
    },
    {
        "provider_id": "PR02",
        "name": "Dr. Sáez",
        "specialty_id": "general_practice",
        "languages": ["es", "ca"],
        "appointment_type_ids": ["first_visit", "review"],
        "location_ids": ["norte"],
        "insurer_ids_accepted": ALL_PLANS,
        "insurer_ids_refused": [],
        "leave": [],
    },
    {
        "provider_id": "PR03",
        "name": "Dra. Sáenz",
        "specialty_id": "paediatrics",
        "languages": ["es"],
        "appointment_type_ids": ["first_visit", "review"],
        "location_ids": ["centro"],
        "insurer_ids_accepted": ALL_PLANS,
        "insurer_ids_refused": [],
        "leave": [],
    },
    {
        "provider_id": "PR04",
        "name": "Dra. Iglesias",
        "specialty_id": "dermatology",
        "languages": ["es", "en"],
        "appointment_type_ids": ["dermatology_first", "dermatology_review"],
        "location_ids": ["centro"],
        "insurer_ids_accepted": ["sanitas", "adeslas", "asisa", "privado"],
        "insurer_ids_refused": ["dkv"],
        "leave": [],
    },
    {
        "provider_id": "PR05",
        "name": "Dr. Iglesia",
        "specialty_id": "orthopaedics",
        "languages": ["es"],
        "appointment_type_ids": ["first_visit", "review"],
        "location_ids": ["sur"],
        "insurer_ids_accepted": ALL_PLANS,
        "insurer_ids_refused": [],
        "leave": [],
    },
    {
        "provider_id": "PR06",
        "name": "D. Álvaro Cid",
        "specialty_id": "physiotherapy",
        "languages": ["es", "ca"],
        "appointment_type_ids": ["first_visit", "review"],
        "location_ids": ["sur"],
        "insurer_ids_accepted": ALL_PLANS,
        "insurer_ids_refused": [],
        "leave": [],
    },
    {
        "provider_id": "PR07",
        "name": "Dr. Requena",
        "specialty_id": "general_practice",
        "languages": ["es"],
        "appointment_type_ids": ["first_visit", "review"],
        "location_ids": ["norte"],
        "insurer_ids_accepted": ALL_PLANS,
        "insurer_ids_refused": [],
        "leave": [{"date_from": "2026-09-14", "date_to": "2026-09-30", "reason": "sick leave"}],
    },
]

INSURANCE_PLANS: list[dict] = [
    {
        "insurer_id": "sanitas",
        "name": "Sanitas",
        "specialty_ids": [s["specialty_id"] for s in SPECIALTIES],
        "location_ids": ["centro", "norte", "sur"],
        "provider_ids": [p["provider_id"] for p in PROVIDERS],
    },
    {
        "insurer_id": "adeslas",
        "name": "Adeslas",
        "specialty_ids": [
            s["specialty_id"] for s in SPECIALTIES if s["specialty_id"] != "gynaecology"
        ],
        "location_ids": ["centro", "norte", "sur"],
        "provider_ids": [p["provider_id"] for p in PROVIDERS],
    },
    {
        "insurer_id": "asisa",
        "name": "ASISA",
        "specialty_ids": [s["specialty_id"] for s in SPECIALTIES],
        # ASISA covers physio only at Centro and Norte; the physio sits at Sur.
        "location_ids": ["centro", "norte"],
        "provider_ids": [p["provider_id"] for p in PROVIDERS],
    },
    {
        "insurer_id": "dkv",
        "name": "DKV",
        "specialty_ids": [s["specialty_id"] for s in SPECIALTIES],
        "location_ids": ["centro", "norte", "sur"],
        "provider_ids": [p["provider_id"] for p in PROVIDERS if p["provider_id"] != "PR04"],
    },
    {
        "insurer_id": "privado",
        "name": "Self-pay",
        "specialty_ids": [s["specialty_id"] for s in SPECIALTIES],
        "location_ids": ["centro", "norte", "sur"],
        "provider_ids": [p["provider_id"] for p in PROVIDERS],
    },
]

RESTRICTIONS: list[dict] = [
    {"rule_id": "age_window", "reason": "not_eligible_age", "description": "Specialty age window"},
    {
        "rule_id": "referral",
        "reason": "referral_required",
        "description": "Specialty needs a referral",
    },
    {
        "rule_id": "provider_plan",
        "reason": "provider_not_in_network",
        "description": "Provider refuses the plan",
    },
    {
        "rule_id": "plan_specialty",
        "reason": "specialty_not_covered",
        "description": "Plan does not cover the specialty",
    },
    {
        "rule_id": "plan_location",
        "reason": "location_not_covered",
        "description": "Plan does not cover the site",
    },
    {
        "rule_id": "plan_referral",
        "reason": "insurer_referral_required",
        "description": "Plan needs its own referral",
    },
    {
        "rule_id": "allowance",
        "reason": "allowance_exhausted",
        "description": "Yearly visits used up",
    },
    {"rule_id": "leave", "reason": "provider_on_leave", "description": "Provider on leave"},
    {"rule_id": "hours", "reason": "location_hours", "description": "Outside site hours"},
    {
        "rule_id": "type",
        "reason": "type_not_offered",
        "description": "Type not offered by the provider",
    },
    {
        "rule_id": "history",
        "reason": "patient_history",
        "description": "History forbids the booking",
    },
]

CLINIC: dict = {
    "locations": LOCATIONS,
    "providers": PROVIDERS,
    "specialties": SPECIALTIES,
    "appointment_types": APPOINTMENT_TYPES,
    "insurance_plans": INSURANCE_PLANS,
    "restrictions": RESTRICTIONS,
    "bookable_from": "2026-09-07",
    "bookable_to": "2026-10-16",
    "closure_days": ["2026-10-12"],
}

PATIENTS: list[dict] = [
    {
        "patient_id": "P00042",
        "given_name": "Marta",
        "first_surname": "Ruiz",
        "second_surname": "López",
        "national_id": "12345678Z",
        "date_of_birth": "1985-03-12",
        "phone": "+34612345678",
        "email": "marta.ruiz@example.com",
        "insurer": "sanitas",
        "has_visited_before": True,
        "note": "Fake record. Seen twice, both times by Dra. Ortiz at Arenal Centro.",
        "referrals": [],
    },
    {
        # Same name as P00042, different birth date: the ambiguity case.
        "patient_id": "P00043",
        "given_name": "Marta",
        "first_surname": "Ruiz",
        "second_surname": "García",
        "national_id": "87654321X",
        "date_of_birth": "1992-11-02",
        "phone": "+34699000111",
        "email": "m.ruiz.garcia@example.com",
        "insurer": "adeslas",
        "has_visited_before": False,
        "note": "Fake record. Never seen. Registered online.",
        "referrals": [],
    },
    {
        "patient_id": "P00107",
        "given_name": "Lucas",
        "first_surname": "Ruiz",
        "second_surname": "López",
        "national_id": "",
        "date_of_birth": "2018-06-20",
        "phone": "+34612345678",  # the mother's line (P00042)
        "email": "",
        "insurer": "sanitas",
        "has_visited_before": True,
        "note": "Fake record. Child. Mother (Marta Ruiz López) usually calls. Seen by Dra. Sáenz.",
        "referrals": [],
    },
    {
        "patient_id": "P00200",
        "given_name": "Antonio",
        "first_surname": "Pérez",
        "second_surname": "Martín",
        "national_id": "X1234567L",
        "date_of_birth": "1958-01-30",
        "phone": "+34655555555",
        "email": "antonio.perez@example.com",
        "insurer": "dkv",
        "has_visited_before": True,
        "note": "Fake record. Hard of hearing; speak slowly. Holds a dermatology referral.",
        "referrals": ["dermatology"],
    },
]

APPOINTMENTS: list[dict] = [
    {
        "appointment_id": "A0001",
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "review",
        "start": "2026-09-30T10:00:00+02:00",
        "status": "scheduled",
    },
    {
        "appointment_id": "A0002",
        "patient_id": "P00107",
        "provider_id": "PR03",
        "location_id": "centro",
        "appointment_type_id": "review",
        "start": "2026-10-02T17:15:00+02:00",
        "status": "scheduled",
    },
    {
        "appointment_id": "A9001",
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "review",
        "start": "2025-03-14T09:30:00+01:00",
        "status": "completed",
    },
    {
        "appointment_id": "A9002",
        "patient_id": "P00042",
        "provider_id": "PR01",
        "location_id": "centro",
        "appointment_type_id": "first_visit",
        "start": "2024-04-08T11:00:00+02:00",
        "status": "completed",
    },
]
