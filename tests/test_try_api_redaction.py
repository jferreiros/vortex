"""``scripts/api/try_api``: what lands in ``api_results/`` carries no patient data.

The script dumps live bodies so a field-name drift shows up fast. `/directory`,
a patient's appointments and `/submissions` answer with real people, so every
patient field is replaced before the file is written and only the field names
survive.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("try_api", ROOT / "scripts" / "api" / "try_api.py")
assert SPEC and SPEC.loader
try_api = importlib.util.module_from_spec(SPEC)
sys.modules["try_api"] = try_api
SPEC.loader.exec_module(try_api)

DIRECTORY = {
    "matches": [
        {
            "patient_id": "P00042",
            "given_name": "Marta",
            "first_surname": "Ruiz",
            "second_surname": "Gomez",
            "national_id": "X8148593S",
            "date_of_birth": "1990-01-01",
            "phone": "+34607034486",
            "sex": "F",
            "has_visited_before": True,
            "insurer": "DKV",
            "referrals": ["cardiology"],
            "note": "hard of hearing - speak slowly",
            "match_score": 1.0,
            "matched_fields": ["name", "phone"],
        }
    ]
}


def test_every_patient_field_is_replaced() -> None:
    (match,) = try_api.redact(DIRECTORY)["matches"]
    for field in try_api.PATIENT_FIELDS & set(DIRECTORY["matches"][0]):
        assert match[field] == try_api.REDACTED
    assert "Marta" not in str(match)
    assert "X8148593S" not in str(match)
    assert "607034486" not in str(match)


def test_the_field_names_and_the_non_patient_values_survive() -> None:
    (match,) = try_api.redact(DIRECTORY)["matches"]
    assert set(match) == set(DIRECTORY["matches"][0])
    assert match["patient_id"] == "P00042"
    assert match["insurer"] == "DKV"
    assert match["matched_fields"] == ["name", "phone"]


def test_a_register_record_nested_in_submissions_is_redacted_too() -> None:
    submissions = {
        "submissions": [
            {
                "call_id": "CA1",
                "record": {
                    "actions": [
                        {
                            "action": "register",
                            "new_patient": {
                                "given_name": "Luis",
                                "national_id": "12345678Z",
                                "phone": "612345678",
                                "email": "luis@example.com",
                                "insurer": "Adeslas",
                            },
                        }
                    ]
                },
            }
        ]
    }
    dumped = try_api.redact(submissions)
    new_patient = dumped["submissions"][0]["record"]["actions"][0]["new_patient"]
    assert new_patient["given_name"] == try_api.REDACTED
    assert new_patient["email"] == try_api.REDACTED
    assert new_patient["insurer"] == "Adeslas"


def test_a_catalogue_body_is_untouched() -> None:
    catalogue = {
        "providers": [
            {
                "id": "PR1",
                "name": "Dra. Elena Marin",
                "languages": ["es", "en"],
                "on_leave_until": None,
            }
        ],
        "slots": [{"start_time": "2026-09-08T10:00:00+02:00", "duration_minutes": 30}],
    }
    assert try_api.redact(catalogue) == catalogue
