"""Find a real caller for each decline reason the public roster never shows.

    uv run python -m evals.corpus.discover     # needs PLATFORM_API_KEY

Problem 6 is worth 12 points and has five shapes of refusal. The published
roster reaches two of them, so an agent can pass every public case and still
have never produced `allowance_exhausted` or `not_eligible_age`. The reasons
are not guessable — the contract says to read them from `/availability`'s
`blocked` and never to invent one — so the only honest way to build a case for
a reason is to find a patient the real clinic actually refuses for it.

This sweeps the live API three ways and records what it finds in
``world/blocked-samples.json``: by plan and specialty, by patient and
specialty, and by provider. Each sample is a concrete, reproducible query, so a
lane can build a caller around it.

**The window matters more than anything else here.** ``blocked`` reports a rule
only when it stops the whole window asked for. Ask for Dr. Requena from 21 to
30 September, inside his leave, and you get zero slots and
``provider_on_leave``. Ask from 21 September to 4 October, one day past the end
of it, and you get fifty slots in October and no ``blocked`` at all — the rule
vanishes and he looks available. An agent that widens its search to "find
something, anything" will never learn why the caller cannot have what they
asked for, and problem 3 turns on exactly that.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from evals.corpus.catalogue import RULE_REASONS, load
from evals.corpus.world import WORLD_DIR
from vortex.clinic.client import ClinicApiError, ClinicClient
from vortex.settings import get_settings

#: A fortnight inside the event, which is the longest span /availability takes.
FROM = date(2026, 9, 21)
TO = date(2026, 10, 4)

#: Deliberately narrow, and entirely inside Requena's 14–30 September leave.
#: A window that runs past the end of a rule does not report the rule.
NARROW_FROM = date(2026, 9, 21)
NARROW_TO = date(2026, 9, 30)

MAX_SAMPLES = 3


def _catalogue(world_dir: Path) -> dict[str, Any]:
    path = world_dir / "catalogue.json"
    if not path.exists():
        raise FileNotFoundError(f"no snapshot at {world_dir}. Run: make evals-snapshot")
    return json.loads(path.read_text())


def _roster_patients() -> list[str]:
    return sorted(
        {
            action["patient_id"]
            for case in load().cases
            for alternative in case.acceptable
            for action in alternative
            if action.get("patient_id")
        }
    )


async def sweep(world_dir: Path = WORLD_DIR) -> dict[str, list[dict[str, Any]]]:
    settings = get_settings()
    catalogue = _catalogue(world_dir)
    specialties = [s["specialty_id"] for s in catalogue["specialties"]]
    providers = [p["provider_id"] for p in catalogue["providers"]]
    plans = [p.get("insurance_plan_id") or p.get("plan_id") for p in catalogue["insurance_plans"]]
    patients = _roster_patients()

    found: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def record(reason: str, **sample: Any) -> None:
        if len(found[reason]) < MAX_SAMPLES:
            found[reason].append(sample)

    client = ClinicClient(settings.platform_api_base_url, settings.platform_api_key)
    try:
        print(f"by plan and specialty ({len(plans)} x {len(specialties)})")
        for specialty in specialties:
            for plan in filter(None, plans):
                try:
                    response = await client.availability(
                        date_from=FROM, date_to=TO, specialty_id=specialty, insurer=[plan]
                    )
                except ClinicApiError:
                    continue
                for blocked in response.blocked or []:
                    record(
                        blocked.reason,
                        specialty_id=specialty,
                        insurer=plan,
                        provider_id=getattr(blocked, "provider_id", None),
                        via="insurer",
                    )

        print(f"by patient and specialty ({len(patients)} x {len(specialties)})")
        for patient_id in patients:
            for specialty in specialties:
                try:
                    response = await client.availability(
                        date_from=FROM, date_to=TO, specialty_id=specialty, patient_id=patient_id
                    )
                except ClinicApiError:
                    continue
                for blocked in response.blocked or []:
                    record(
                        blocked.reason,
                        patient_id=patient_id,
                        specialty_id=specialty,
                        provider_id=getattr(blocked, "provider_id", None),
                        via="patient",
                    )

        print(f"by provider, in a narrow window ({len(providers)})")
        for provider_id in providers:
            try:
                response = await client.availability(
                    date_from=NARROW_FROM, date_to=NARROW_TO, provider_id=provider_id
                )
            except ClinicApiError:
                continue
            for blocked in response.blocked or []:
                record(
                    blocked.reason,
                    provider_id=provider_id,
                    window=f"{NARROW_FROM}..{NARROW_TO}",
                    via="provider",
                    note="a window past the end of the rule does not report the rule",
                )
    finally:
        await client.aclose()
    return dict(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.corpus.discover", description=__doc__)
    parser.add_argument("--out", type=Path, default=WORLD_DIR)
    args = parser.parse_args(argv)

    if not get_settings().clinic_is_live:
        print("the clinic is not live; set PLATFORM_API_KEY in .env", file=sys.stderr)
        return 2

    found = asyncio.run(sweep(args.out))
    target = args.out / "blocked-samples.json"
    target.write_text(json.dumps(found, ensure_ascii=False, indent=1))

    print(f"\n{len(found)} of the {len(RULE_REASONS)} rule reasons have a real trigger:\n")
    for reason in RULE_REASONS:
        sample = found.get(reason)
        if sample:
            print(f"  {reason:28} {json.dumps(sample[0], ensure_ascii=False)}")
        else:
            print(f"  {reason:28} — not reached by this sweep")
    print(f"\nwrote {target}")
    print("each sample is a query a lane can build a caller around.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
