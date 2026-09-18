"""Freeze the real clinic once a key exists, so the roster can be judged offline.

    uv run python -m evals.corpus.snapshot            # needs PLATFORM_API_KEY

Why this matters more than it looks. The other eval layers run against
``FakeClinicClient`` and invented patients, so they check the *shape* of an
answer and never its value. The published roster answers name real ids —
``P00001``, ``PR01``, ``centro``, ``review``, a slot to the minute — and those
can only be reproduced from the real clinic. One snapshot turns 73 published
answers into 73 offline assertions that mean something.

The clinic is read-only, generated once and identical for the whole event, so a
snapshot is valid for the weekend and costs one pull. It is deliberately not
committed: it is several megabytes of generated patient data and it belongs to
the organisers.

What it writes, under ``evals/corpus/world/`` (git-ignored):

    catalogue.json      providers, locations, specialties, types, plans,
                        restrictions, the bookable window
    patients.json       every patient the roster's answers name
    appointments.json   their upcoming and past diaries
    availability/       one file per (specialty, window) the roster needs
    manifest.json       when it was taken, against which base URL, and the
                        roster sha256 it was taken for
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from evals.corpus.catalogue import load
from vortex.clinic.client import ClinicApiError, ClinicClient
from vortex.settings import get_settings

WORLD_DIR = Path(__file__).resolve().parent / "world"

#: /availability rejects a span longer than 14 days, and the calendar itself
#: runs 7 September to 16 October 2026.
MAX_SPAN = timedelta(days=14)
CALENDAR_FROM = date(2026, 9, 7)
CALENDAR_TO = date(2026, 10, 16)


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
    # --out may point anywhere, so fall back to the name when it is not under the
    # default directory. A snapshot must never fail on its own progress line.
    try:
        shown: Path | str = path.relative_to(WORLD_DIR.parent)
    except ValueError:
        shown = path
    print(f"  {shown}  ({path.stat().st_size // 1024} KiB)")


def _named_patients() -> list[str]:
    """Every ``patient_id`` the published answers name."""
    return sorted(
        {
            action["patient_id"]
            for case in load().cases
            for alternative in case.acceptable
            for action in alternative
            if action.get("patient_id")
        }
    )


def _patient_specialty_pairs(
    provider_specialty: dict[str, str],
) -> set[tuple[str, str, str]]:
    """The (patient, specialty) pairs the published answers depend on.

    ``/availability`` names the one right ``appointment_type`` **for the patient
    and specialty it was asked about**, and every slot carries that type's id.
    Asked without a ``patient_id`` it answers ``first_visit`` for everyone, so a
    snapshot taken that way cannot reproduce a single review booking. Pull the
    pairs the roster needs, and no more.
    """
    pairs: set[tuple[str, str, str]] = set()
    for case in load().cases:
        for alternative in case.acceptable:
            for action in alternative:
                patient = action.get("patient_id")
                specialty = provider_specialty.get(action.get("provider_id", ""))
                if not (patient and specialty):
                    continue
                # Unqualified: what the plan on the record buys.
                pairs.add((patient, specialty, ""))
                # And named: problem 17's second plan is nowhere in the data, so
                # the only way to see its slots is to ask for it by name.
                if action.get("policy_id"):
                    pairs.add((patient, specialty, action["policy_id"]))
    return pairs


def _persona_lookups() -> list[dict[str, str]]:
    """The directory queries the personas themselves make possible.

    ``/directory`` takes name, national id, phone and date of birth — never a
    ``patient_id`` — so this is how a chart is reached from what a caller says,
    and it snapshots the exact lookup the identity lane will perform.
    """
    out: list[dict[str, str]] = []
    for case in load().cases:
        data = case.persona.get("data") or {}
        query = {
            key: str(data[key])
            for key in ("national_id", "phone", "date_of_birth")
            if data.get(key)
        }
        if data.get("full_name"):
            query["name"] = str(data["full_name"])
        if query:
            out.append({"case_id": case.id, **query})
    return out


async def take(out_dir: Path = WORLD_DIR) -> int:
    settings = get_settings()
    if not settings.clinic_is_live:
        print(
            "The clinic is not live. The desk issues PLATFORM_API_KEY once; put it and\n"
            "PLATFORM_API_BASE_URL in .env. VORTEX_CLINIC_MODE=fake also forces this.\n"
            "Without a live clinic this script cannot run; nothing else in evals needs it.",
            file=sys.stderr,
        )
        return 2

    roster = load()
    client = ClinicClient(settings.platform_api_base_url, settings.platform_api_key)
    manifest: dict[str, Any] = {
        "taken_at": datetime.now(UTC).isoformat(),
        "base_url": settings.platform_api_base_url,
        "roster_sha256": roster.sha256,
        "roster_cases": len(roster.cases),
    }
    try:
        if not await client.health():
            print("the clinic reports unhealthy; snapshot aborted", file=sys.stderr)
            return 2

        print("catalogue")
        catalogue = await client.catalogue()
        _dump(out_dir / "catalogue.json", catalogue.model_dump(mode="json"))

        lookups = _persona_lookups()
        print(f"directory ({len(lookups)} persona lookups)")
        charts: dict[str, Any] = {}
        for query in lookups:
            case_id = query.pop("case_id")
            dob = query.pop("date_of_birth", None)
            try:
                found = await client.directory(
                    name=query.get("name"),
                    national_id=query.get("national_id"),
                    phone=query.get("phone"),
                    date_of_birth=date.fromisoformat(dob) if dob else None,
                )
            except ClinicApiError as error:
                charts[case_id] = {"query": query, "error": str(error)}
                continue
            charts[case_id] = {
                "query": query,
                "patients": [p.model_dump(mode="json") for p in found],
            }
        _dump(out_dir / "patients.json", charts)

        patients = _named_patients()
        print(f"appointments ({len(patients)} patients named by the answers)")
        diaries: dict[str, Any] = {}
        for patient_id in patients:
            for when in ("upcoming", "past"):
                try:
                    diary = await client.appointments(patient_id, when=when)
                except ClinicApiError as error:
                    diaries.setdefault(patient_id, {})[when] = {"error": str(error)}
                    continue
                diaries.setdefault(patient_id, {})[when] = [
                    a.model_dump(mode="json") for a in diary
                ]
        _dump(out_dir / "appointments.json", diaries)

        specialties = sorted(
            {
                s.specialty_id
                for s in getattr(catalogue, "specialties", [])
                if getattr(s, "specialty_id", None)
            }
        )
        print(f"availability ({len(specialties)} specialties x the bookable calendar)")
        for specialty in specialties:
            start = CALENDAR_FROM
            windows = []
            while start <= CALENDAR_TO:
                end = min(start + MAX_SPAN - timedelta(days=1), CALENDAR_TO)
                try:
                    response = await client.availability(
                        date_from=start, date_to=end, specialty_id=specialty
                    )
                except ClinicApiError as error:
                    windows.append({"from": str(start), "to": str(end), "error": str(error)})
                else:
                    windows.append(
                        {
                            "from": str(start),
                            "to": str(end),
                            "response": response.model_dump(mode="json"),
                        }
                    )
                start = end + timedelta(days=1)
            _dump(out_dir / "availability" / f"{specialty}.json", windows)

        provider_specialty = {
            p.provider_id: p.specialty_id
            for p in getattr(catalogue, "providers", [])
            if getattr(p, "provider_id", None) and getattr(p, "specialty_id", None)
        }
        pairs = sorted(_patient_specialty_pairs(provider_specialty))
        print(
            f"availability per patient ({len(pairs)} patient/specialty/plan keys "
            "the answers need)"
        )
        per_patient: dict[str, Any] = {}
        for patient_id, specialty, policy in pairs:
            start = CALENDAR_FROM
            windows = []
            while start <= CALENDAR_TO:
                end = min(start + MAX_SPAN - timedelta(days=1), CALENDAR_TO)
                try:
                    response = await client.availability(
                        date_from=start,
                        date_to=end,
                        specialty_id=specialty,
                        patient_id=patient_id,
                        insurer=[policy] if policy else None,
                    )
                except ClinicApiError as error:
                    windows.append({"from": str(start), "to": str(end), "error": str(error)})
                else:
                    windows.append(
                        {
                            "from": str(start),
                            "to": str(end),
                            "response": response.model_dump(mode="json"),
                        }
                    )
                start = end + timedelta(days=1)
            per_patient[f"{patient_id}:{specialty}:{policy}"] = windows
        _dump(out_dir / "availability-per-patient.json", per_patient)

        manifest["specialties"] = specialties
        manifest["patients"] = patients
        manifest["patient_specialty_pairs"] = [f"{p}:{s}:{c}" for p, s, c in pairs]
        _dump(out_dir / "manifest.json", manifest)
    finally:
        await client.aclose()

    print(f"\nsnapshot complete: {out_dir}")
    print("the roster's answers can now be judged offline; re-take it if the desk")
    print("announces a clinic correction.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.corpus.snapshot", description=__doc__)
    parser.add_argument("--out", type=Path, default=WORLD_DIR)
    args = parser.parse_args(argv)
    return asyncio.run(take(args.out))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
