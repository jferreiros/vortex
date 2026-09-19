"""Find a real caller for each decline reason the public roster never shows.

    uv run python -m evals.corpus.discover     # needs PLATFORM_API_KEY

Problem 6 is worth 12 points and has five shapes of refusal. The published
roster reaches two of them, so an agent can pass every public case and still
have never produced `allowance_exhausted` or `not_eligible_age`. The reasons
are not guessable — the contract says to read them from `/availability`'s
`blocked` and never to invent one — so the only honest way to build a case for
a reason is to find a patient the real clinic actually refuses for it.

The sweep runs the live API five ways and records what it finds in
``world/blocked-samples.json``:

1. by plan and specialty — the roster's own insurance rows;
2. by roster patient and specialty — the 24 patients the answers name;
3. by provider, in a window narrow enough to sit inside a leave;
4. by directory-harvested patient and specialty. `/directory` answers a name
   with ten fuzzy matches, so the roster's own persona names reach patients
   far outside its 24. This is the sweep that finds `allowance_exhausted`:
   the cap is per (patient, specialty) on the record plan, and none of the
   roster's own 24 patients has a spent plan. Its samples carry
   ``via: "directory"`` so a lane knows the caller was built, not looked up;
5. the shapes that should name the last three rules — `location_hours`,
   `type_not_offered`, `patient_history`. Every query the endpoint accepts was
   probed against the live clinic on 19 Sep 2026 and none of the three ever
   came back: the engine implements seven of the eleven rules and no query
   names the others. Each still gets a one-line note — under ``impossible``
   in the JSON, and printed with the report — so the board says *why*, not
   just what. A shape whose probes did not all come back is held under
   ``unverified`` instead: a lost query is not a clinic that reports nothing.
   If the clinic ever starts reporting one, the same probe records it as a
   sample instead.

Each sample is a concrete, reproducible query, so a lane can build a caller
around it.

**The window matters more than anything else here.** ``blocked`` reports a rule
only when it stops the whole window asked for. Ask for Dr. Requena from 21 to
30 September, inside his leave, and you get zero slots and
``provider_on_leave``. Ask from 21 September to 4 October, one day past the end
of it, and you get fifty slots in October and no ``blocked`` at all — the rule
vanishes and he looks available. An agent that widens its search to "find
something, anything" will never learn why the caller cannot have what they
asked for, and problem 3 turns on exactly that.

**Cost.** The directory harvest, the patient sweep and the probes are a few
thousand read-only GETs — several minutes at the default concurrency.
``--max-patients`` and ``--concurrency`` trim it; the roster-side sweeps always
run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from evals.corpus.catalogue import RULE_REASONS, load
from evals.corpus.world import WORLD_DIR
from vortex.clinic.client import ClinicApiError, ClinicClient
from vortex.contract import Catalogue, PatientRecord
from vortex.settings import get_settings

#: A fortnight inside the event, which is the longest span /availability takes.
FROM = date(2026, 9, 21)
TO = date(2026, 10, 4)

#: Deliberately narrow, and entirely inside Requena's 14–30 September leave.
#: A window that runs past the end of a rule does not report the rule.
NARROW_FROM = date(2026, 9, 21)
NARROW_TO = date(2026, 9, 30)

MAX_SAMPLES = 3

#: The directory harvest stops here. ~70 name queries surface this many
#: patients; five carried a spent plan on 19 Sep 2026, so the marginal patient
#: beyond it buys little and costs a query each.
MAX_PATIENTS = 480

#: How many harvested patients the patient_history probe walks past every
#: provider and site. Bounded: the probe exists to prove a shape dead, not to
#: sweep the space.
HISTORY_PROBE_PATIENTS = 30

CONCURRENCY = 12


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


def _seed_names() -> list[str]:
    """Given name plus each surname of every persona, one /directory query each.

    The directory wants a given name plus at least one surname and answers
    with ten fuzzy matches — surnames out of order, near-miss given names —
    so the roster's own names are enough to reach hundreds of patients
    without crawling a gazetteer.
    """
    names: set[str] = set()
    for case in load().cases:
        parts = str((case.persona.get("data") or {}).get("full_name") or "").split()
        if len(parts) >= 2:
            names.add(" ".join(parts[:2]))
            if len(parts) >= 3:
                names.add(f"{parts[0]} {parts[2]}")
    return sorted(names)


async def _harvest_patients(client: ClinicClient, sem: asyncio.Semaphore) -> list[PatientRecord]:
    """Every patient the seed names surface, deduplicated by id."""
    pool: dict[str, PatientRecord] = {}

    async def one(name: str) -> None:
        async with sem:
            try:
                found = await client.directory(name=name)
            except (ClinicApiError, httpx.HTTPError):
                return
            for patient in found:
                pool.setdefault(patient.patient_id, patient)

    seeds = _seed_names()
    await asyncio.gather(*(one(name) for name in seeds))
    print(f"  {len(pool)} patients from {len(seeds)} name queries")
    return sorted(pool.values(), key=lambda p: p.patient_id)


def _last_weekday(anchor: date, weekday: int) -> date:
    day = anchor
    while day.weekday() != weekday:
        day -= timedelta(days=1)
    return day


def _shut_windows(catalogue: Catalogue) -> list[dict[str, Any]]:
    """Single-day windows a site is shut for the whole of, from its own hours.

    A window the engine refuses to describe is the only place `location_hours`
    could live, so the probe asks for each site's last closed Sunday and —
    where the site opens no Saturday — its last Saturday, plus every site on
    the published closure day.
    """
    end = catalogue.bookable_to or date.today()
    sunday = _last_weekday(end, 6)
    saturday = _last_weekday(end, 5)
    windows: list[dict[str, Any]] = []
    for location in catalogue.locations:
        weekdays = {hours.weekday for hours in location.hours}
        for label, day in (("Sunday", sunday), ("Saturday", saturday)):
            if day.weekday() not in weekdays:
                windows.append({"location_id": location.location_id, "day": day, "why": label})
        for closure in catalogue.closure_days:
            windows.append(
                {"location_id": location.location_id, "day": closure, "why": "closure day"}
            )
    return windows


def _specialty_type(catalogue: Catalogue, specialty_id: str, visited: bool) -> str | None:
    """The type /availability resolves for this record: the specialty's own
    pair wins over the universal one, matching the patient's visited-ness."""
    new = not visited
    own = [t for t in catalogue.appointment_types if t.specialty_id == specialty_id]
    universal = [t for t in catalogue.appointment_types if t.specialty_id is None]
    for pool in (own, universal):
        for candidate in pool:
            if candidate.for_new_patients is None or candidate.for_new_patients == new:
                return candidate.appointment_type_id
    return None


def _type_gaps(catalogue: Catalogue) -> list[dict[str, str]]:
    """Places where a provider does not offer the type a record resolves to.

    `type_not_offered` could only come from such a gap. Empty means no query
    can ask for a type a provider lacks — the structural reason the rule is
    unreportable on this clinic.
    """
    by_specialty: dict[str, list[Any]] = defaultdict(list)
    for provider in catalogue.providers:
        by_specialty[provider.specialty_id].append(provider)
    gaps: list[dict[str, str]] = []
    for specialty, providers in sorted(by_specialty.items()):
        for visited in (False, True):
            type_id = _specialty_type(catalogue, specialty, visited)
            if type_id is None:
                gaps.append(
                    {
                        "specialty_id": specialty,
                        "patient": "new" if not visited else "returning",
                        "appointment_type_id": "",
                        "provider_id": "",
                        "note": "no type resolves at all",
                    }
                )
                continue
            for provider in providers:
                if type_id not in provider.appointment_type_ids:
                    gaps.append(
                        {
                            "specialty_id": specialty,
                            "patient": "new" if not visited else "returning",
                            "appointment_type_id": type_id,
                            "provider_id": provider.provider_id,
                            "note": "provider does not offer the resolved type",
                        }
                    )
    return gaps


async def _probe_availability(
    client: ClinicClient, sem: asyncio.Semaphore, *, day: date | None = None, **params: Any
) -> Any | None:
    """One availability GET: ``day`` for a single-day window, the standard
    fortnight otherwise."""
    async with sem:
        try:
            return await client.availability(date_from=day or FROM, date_to=day or TO, **params)
        except (ClinicApiError, httpx.HTTPError):
            return None


async def sweep_harvested_patients(
    client: ClinicClient,
    sem: asyncio.Semaphore,
    patients: list[PatientRecord],
    specialties: list[str],
    found: dict[str, list[dict[str, Any]]],
    record: Any,
) -> dict[str, int]:
    """Patient x specialty on the record plan, over harvested patients.

    The only sweep that reaches `allowance_exhausted`, which is scoped per
    (patient, specialty): a plan out of visits stops the providers of the
    specialty the visits were spent on, and no roster patient's plan is spent.
    Stops once the reason has its samples — the remaining patients buy no
    reason the earlier sweeps have not already found. Returns how many queries
    it ran and how many of them got no answer, because a sweep that lost
    queries to the API has not proved the reason absent.
    """
    total = len(patients) * len(specialties)
    done = 0
    failed = 0

    async def one(patient: PatientRecord, specialty: str) -> None:
        nonlocal failed
        response = await _probe_availability(
            client, sem, specialty_id=specialty, patient_id=patient.patient_id
        )
        if response is None:
            failed += 1
            return
        for blocked in response.blocked or []:
            record(
                blocked.reason,
                patient_id=patient.patient_id,
                insurer=patient.insurer,
                specialty_id=specialty,
                provider_id=blocked.provider_id,
                via="directory",
            )

    for start in range(0, len(patients), 24):
        if len(found.get("allowance_exhausted", [])) >= MAX_SAMPLES:
            break
        chunk = patients[start : start + 24]
        await asyncio.gather(
            *(one(patient, specialty) for patient in chunk for specialty in specialties)
        )
        done += len(chunk) * len(specialties)
        print(f"  {min(done, total)}/{total} patient x specialty queries")
    return {"queries": done, "failed": failed}


async def probe_unreportable(
    client: ClinicClient,
    sem: asyncio.Semaphore,
    live: Catalogue,
    pool: list[PatientRecord],
    record: Any,
) -> dict[str, dict[str, int]]:
    """The shapes that should name `location_hours`, `type_not_offered` and
    `patient_history`, probed so the report's impossibility notes are earned.

    - location_hours: a single-day window a site is shut for the whole of,
      with and without a patient;
    - type_not_offered: any catalogue gap where a provider lacks the type a
      record resolves to, put to that provider with a harvested patient whose
      visited-ness resolves to the missing type — another provider of the
      specialty offers it, and the wrong patient resolves to another type, so
      either substitution answers a question the gap did not ask;
    - patient_history: harvested patients past every provider and site.

    Anything one of these returns lands in ``record`` as a sample, so a clinic
    that starts reporting the rule is caught by the same run that says so.

    Every shape also counts the probes that got no answer. A timeout or an API
    error is not a clinic that reports nothing, so a shape that lost a probe is
    reported as unverified rather than impossible.
    """
    stats: dict[str, dict[str, int]] = {
        "location_hours": {"windows": 0, "blocked": 0, "failed": 0},
        "patient_history": {"queries": 0, "failed": 0},
    }

    windows = _shut_windows(live)
    roster_ids = _roster_patients()
    roster_patient = roster_ids[0] if roster_ids else (pool[0].patient_id if pool else None)
    for window in windows:
        for patient_id in (None, roster_patient):
            params: dict[str, Any] = {
                "specialty_id": "general_practice",
                "location_id": window["location_id"],
            }
            if patient_id:
                params["patient_id"] = patient_id
            response = await _probe_availability(client, sem, day=window["day"], **params)
            stats["location_hours"]["windows"] += 1
            if response is None:
                stats["location_hours"]["failed"] += 1
                continue
            for blocked in response.blocked or []:
                stats["location_hours"]["blocked"] += 1
                record(
                    blocked.reason,
                    location_id=window["location_id"],
                    day=str(window["day"]),
                    why=window["why"],
                    patient_id=patient_id,
                    via="shut-window",
                )

    gaps = _type_gaps(live)
    stats["type_not_offered"] = {"gaps": len(gaps), "probed": 0, "failed": 0, "unprobed": 0}
    by_visited: dict[bool, list[PatientRecord]] = {False: [], True: []}
    for patient in pool:
        by_visited[patient.has_visited_before].append(patient)
    for gap in gaps:
        visited = gap["patient"] == "returning"
        candidates = by_visited[visited]
        if not candidates or not gap["provider_id"]:
            stats["type_not_offered"]["unprobed"] += 1
            continue
        patient_id = candidates[0].patient_id
        response = await _probe_availability(
            client,
            sem,
            provider_id=gap["provider_id"],
            specialty_id=gap["specialty_id"],
            patient_id=patient_id,
        )
        stats["type_not_offered"]["probed"] += 1
        if response is None:
            stats["type_not_offered"]["failed"] += 1
            continue
        for blocked in response.blocked or []:
            record(
                blocked.reason,
                specialty_id=gap["specialty_id"],
                provider_id=blocked.provider_id,
                patient_id=patient_id,
                via="type-gap",
            )

    providers = [p.provider_id for p in live.providers]
    sites = [loc.location_id for loc in live.locations]
    probe_patients = [p.patient_id for p in pool[:HISTORY_PROBE_PATIENTS]]
    if probe_patients and providers and sites:
        print(
            f"  patient_history probe: {len(probe_patients)} patients x "
            f"{len(providers)} providers x {len(sites)} sites"
        )

        async def one(patient_id: str, provider_id: str, location_id: str) -> None:
            stats["patient_history"]["queries"] += 1
            response = await _probe_availability(
                client,
                sem,
                provider_id=provider_id,
                location_id=location_id,
                patient_id=patient_id,
            )
            if response is None:
                stats["patient_history"]["failed"] += 1
                return
            for blocked in response.blocked or []:
                record(
                    blocked.reason,
                    patient_id=patient_id,
                    provider_id=blocked.provider_id,
                    location_id=location_id,
                    via="history-probe",
                )

        await asyncio.gather(
            *(
                one(patient_id, provider_id, location_id)
                for patient_id in probe_patients
                for provider_id in providers
                for location_id in sites
            )
        )
    return stats


def _unverified_notes(
    found: dict[str, list[dict[str, Any]]], stats: dict[str, dict[str, int]]
) -> dict[str, str]:
    """One line per rule whose probes never came back, so the run cannot speak for it.

    A probe that timed out or hit an API error returns nothing, and nothing
    looks exactly like a clinic that reports no rule. These reasons are held
    back from ``impossible``: the shape is undecided until every probe answers.
    """
    notes: dict[str, str] = {}
    allowance = stats.get("allowance_exhausted", {})
    if "allowance_exhausted" not in found and allowance.get("failed"):
        notes["allowance_exhausted"] = (
            f"{allowance['failed']} of {allowance.get('queries', 0)} patient x specialty "
            "queries got no answer from the API — the plans behind them were never read; "
            "re-run before calling the reason unreachable"
        )
    location = stats.get("location_hours", {})
    if "location_hours" not in found and (location.get("failed") or not location.get("windows")):
        notes["location_hours"] = (
            f"{location.get('failed', 0)} of {location.get('windows', 0)} shut-window "
            "queries got no answer from the API — a lost probe is not a clinic that "
            "reports no rule; re-run"
        )
    gaps = stats.get("type_not_offered", {})
    if "type_not_offered" not in found and (gaps.get("failed") or gaps.get("unprobed")):
        notes["type_not_offered"] = (
            f"{gaps.get('failed', 0)} of {gaps.get('probed', 0)} catalogue-gap queries got "
            f"no answer from the API and {gaps.get('unprobed', 0)} gaps had no provider or "
            "no harvested patient of their own kind to ask with — the gaps were never put "
            "to the clinic; re-run"
        )
    history = stats.get("patient_history", {})
    if "patient_history" not in found and (history.get("failed") or not history.get("queries")):
        notes["patient_history"] = (
            f"{history.get('failed', 0)} of {history.get('queries', 0)} patient x provider "
            "x site queries got no answer from the API — the history shape was never "
            "fully probed; re-run"
        )
    return notes


def _impossible_notes(
    found: dict[str, list[dict[str, Any]]],
    stats: dict[str, dict[str, int]],
    harvested: int,
    specialties: int,
    unverified: dict[str, str],
) -> dict[str, str]:
    """One line per rule the sweep could not reach, saying why against this clinic.

    A rule in ``unverified`` gets no line: the sweep lost a probe it needed, so
    it has not earned the verdict.
    """
    notes: dict[str, str] = {}
    if "allowance_exhausted" not in found and "allowance_exhausted" not in unverified:
        notes["allowance_exhausted"] = (
            f"no harvested patient's record plan is spent for any of the {specialties} "
            f"specialties probed ({harvested} patients) — the cap is per patient and "
            "specialty; widen --max-patients and re-run"
        )
    if "location_hours" not in found and "location_hours" not in unverified:
        notes["location_hours"] = (
            f"the engine reports no rule: {stats['location_hours']['windows']} windows "
            "shut for the whole site (each site's last closed Sunday and Saturday, the "
            "published closure day; with and without a patient) all returned zero slots "
            "with blocked: [] — site hours live only in the catalogue, so this refusal "
            "is the agent's to derive"
        )
    if "type_not_offered" not in found and "type_not_offered" not in unverified:
        gaps = stats["type_not_offered"]["gaps"]
        notes["type_not_offered"] = (
            "the endpoint takes no appointment_type filter — the type is resolved from "
            "the specialty and the patient's record, and "
            + (
                "every provider offers both the new and the returning type of their "
                "specialty, so no query can ask for one a provider lacks"
                if not gaps
                else f"{gaps} catalogue gaps were probed live and none came back as a rule"
            )
        )
    if "patient_history" not in found and "patient_history" not in unverified:
        notes["patient_history"] = (
            "history enters the API only as has_visited_before, which picks the type, "
            "and referrals, which satisfy referral_required: "
            f"{stats['patient_history']['queries']} patient x provider x site queries "
            "over harvested patients answered only with the rules the engine implements"
        )
    return notes


async def sweep(
    world_dir: Path = WORLD_DIR, max_patients: int = MAX_PATIENTS, concurrency: int = CONCURRENCY
) -> dict[str, Any]:
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
    sem = asyncio.Semaphore(concurrency)
    stats: dict[str, dict[str, int]] = {}
    harvested = 0
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

        print("by directory-harvested patient and specialty")
        live = await client.catalogue()
        pool = await _harvest_patients(client, sem)
        roster_ids = set(patients)
        fresh = [p for p in pool if p.patient_id not in roster_ids][:max_patients]
        harvested = len(fresh)
        print(f"  {harvested} patients outside the roster's own {len(roster_ids)}")
        if len(found.get("allowance_exhausted", [])) < MAX_SAMPLES:
            stats["allowance_exhausted"] = await sweep_harvested_patients(
                client, sem, fresh, specialties, found, record
            )

        print("the shapes that should name the last three rules")
        stats.update(await probe_unreportable(client, sem, live, pool, record))
    finally:
        await client.aclose()

    unverified = _unverified_notes(dict(found), stats)
    return {
        "samples": dict(found),
        "impossible": _impossible_notes(
            dict(found), stats, harvested, len(specialties), unverified
        ),
        "unverified": unverified,
    }


def report(
    samples: dict[str, list[dict[str, Any]]],
    impossible: dict[str, str],
    unverified: dict[str, str] | None = None,
) -> None:
    unverified = unverified or {}
    print(f"\n{len(samples)} of the {len(RULE_REASONS)} rule reasons have a real trigger:\n")
    for reason in RULE_REASONS:
        sample = samples.get(reason)
        if sample:
            print(f"  {reason:28} {json.dumps(sample[0], ensure_ascii=False)}")
        elif reason in impossible:
            print(f"  {reason:28} — impossible from the API: {impossible[reason]}")
        elif reason in unverified:
            print(f"  {reason:28} — unverified, probes lost: {unverified[reason]}")
        else:
            print(f"  {reason:28} — not reached by this sweep")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.corpus.discover", description=__doc__)
    parser.add_argument("--out", type=Path, default=WORLD_DIR)
    parser.add_argument(
        "--max-patients", type=int, default=MAX_PATIENTS, help="cap on the directory harvest"
    )
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY, help="GETs in flight")
    args = parser.parse_args(argv)

    if not get_settings().clinic_is_live:
        print("the clinic is not live; set PLATFORM_API_KEY in .env", file=sys.stderr)
        return 2

    discovery = asyncio.run(
        sweep(args.out, max_patients=args.max_patients, concurrency=args.concurrency)
    )
    target = args.out / "blocked-samples.json"
    target.write_text(json.dumps(discovery, ensure_ascii=False, indent=1))

    report(discovery["samples"], discovery["impossible"], discovery["unverified"])
    print(f"\nwrote {target}")
    print("each sample is a query a lane can build a caller around; the lines marked")
    print("impossible name the shape no query the endpoint accepts can produce.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
