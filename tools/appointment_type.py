"""Pick the right appointment type for a specialty + patient.

Rule: a patient the clinic has never seen books the specialty's "new patient"
type (``new_patient_requirement: "new_only"``); anyone else books its
"review"/follow-up type (``"existing_only"``). A specialty with no type of its
own for that case falls back to the universal type (``specialty_id: null`` —
e.g. gynaecology has no first-visit type, so a new patient there books the
universal ``first_visit``).

    uv run python tools/appointment_type.py --specialty-id dermatology \
        --client '{"has_visited_before": false}'
    uv run python tools/appointment_type.py --specialty-id gynaecology \
        --client '{"has_visited_before": true}'

    # Reuse a snapshot from `make try-api` instead of hitting the live API:
    uv run python tools/appointment_type.py --specialty-id paediatrics \
        --client '{"has_visited_before": false}' \
        --appointment-types-file api_results/2026-09-18T193555Z/GET_api_v1_appointment-types.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from vortex.settings import get_settings  # noqa: E402


def pick_appointment_type(
    specialty_id: str, client: dict[str, Any], appointment_types: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The one type that fits: specialty-specific wins over universal.

    ``client`` is a patient record as the directory/availability endpoints
    shape it (needs ``has_visited_before``; missing/falsy means "never seen").
    """
    wants = "new_only" if not client.get("has_visited_before") else "existing_only"
    own = [t for t in appointment_types if t.get("specialty_id") == specialty_id]
    universal = [t for t in appointment_types if t.get("specialty_id") is None]
    for pool in (own, universal):
        for t in pool:
            if t.get("new_patient_requirement") == wants:
                return t
    return None


def fetch_appointment_types() -> list[dict[str, Any]]:
    """Live GET /api/v1/appointment-types, using the credentials in .env."""
    settings = get_settings()
    if not settings.platform_api_key:
        raise SystemExit("PLATFORM_API_KEY is not set in .env - nothing to call.")
    with httpx.Client(
        base_url=settings.platform_api_base_url.rstrip("/"),
        headers={"X-Api-Key": settings.platform_api_key},
        timeout=10.0,
    ) as client:
        response = client.get("/api/v1/appointment-types")
        response.raise_for_status()
        return response.json()["appointment_types"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specialty-id", required=True, help="e.g. dermatology")
    parser.add_argument(
        "--client", required=True, help="patient JSON, e.g. '{\"has_visited_before\": false}'"
    )
    parser.add_argument(
        "--appointment-types-file",
        help="path to a saved GET /api/v1/appointment-types response; default: fetch live",
    )
    args = parser.parse_args()

    client = json.loads(args.client)
    if args.appointment_types_file:
        appointment_types = json.loads(Path(args.appointment_types_file).read_text())[
            "appointment_types"
        ]
    else:
        appointment_types = fetch_appointment_types()

    result = pick_appointment_type(args.specialty_id, client, appointment_types)
    if result is None:
        print(f"no appointment type found for specialty '{args.specialty_id}'", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
