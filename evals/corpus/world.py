"""Read the clinic snapshot, and check the published answers reproduce from it.

``snapshot.py`` freezes the real clinic. This reads it back and answers the one
question that decides whether the whole layer means anything: **does the
organisers' own answer to each published case exist in the availability their
API actually serves?**

If it does, our judge, our roster and our reading of the API agree, and a
failure in a practice call is our agent's. If it does not, one of those three
has drifted and every green case below it is worthless.

Running it is also how the two traps in ``/availability`` were confirmed rather
than assumed:

- Asked **without** ``patient_id`` it answers ``first_visit`` for everybody, so
  a snapshot taken that way cannot reproduce a single review booking.
- Asked **without** ``insurer`` it prices against the one plan on the record.
  Problem 17's cases return zero slots and ``blocked: specialty_not_covered``
  until the second plan is named — which is the whole problem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.corpus.catalogue import Roster, load

WORLD_DIR = Path(__file__).resolve().parent / "world"


@dataclass(frozen=True)
class World:
    """A snapshot on disk, indexed for lookups."""

    path: Path
    catalogue: dict[str, Any]
    per_patient: dict[str, list[dict[str, Any]]]
    manifest: dict[str, Any]

    @property
    def provider_specialty(self) -> dict[str, str]:
        return {
            p["provider_id"]: p["specialty_id"]
            for p in self.catalogue.get("providers", [])
            if p.get("provider_id") and p.get("specialty_id")
        }

    def slots_for(
        self, patient_id: str, specialty_id: str, policy_id: str = ""
    ) -> set[tuple[str, str, str, str]]:
        """Every ``(provider, location, type, start)`` offered to this patient.

        ``policy_id`` names a plan to be quoted against. Left out, the search
        prices against the one plan on the record — which is what makes
        problem 17 hard and why the snapshot keeps both.
        """
        out: set[tuple[str, str, str, str]] = set()
        for window in self.per_patient.get(f"{patient_id}:{specialty_id}:{policy_id}", []):
            for slot in (window.get("response") or {}).get("slots", []):
                out.add(
                    (
                        slot["provider_id"],
                        slot["location_id"],
                        slot["appointment_type_id"],
                        slot["start"],
                    )
                )
        return out


def exists(path: Path = WORLD_DIR) -> bool:
    return (path / "catalogue.json").exists()


def read(path: Path = WORLD_DIR) -> World:
    if not exists(path):
        raise FileNotFoundError(
            f"no snapshot at {path}. Take one: make evals-snapshot (needs PLATFORM_API_KEY)"
        )
    per_patient_file = path / "availability-per-patient.json"
    return World(
        path=path,
        catalogue=json.loads((path / "catalogue.json").read_text()),
        per_patient=json.loads(per_patient_file.read_text()) if per_patient_file.exists() else {},
        manifest=json.loads((path / "manifest.json").read_text()),
    )


@dataclass
class RosterCheck:
    case_id: str
    problem_id: str
    reproduced: bool
    detail: str


def verify_roster(world: World, roster: Roster | None = None) -> list[RosterCheck]:
    """Check every published BOOK answer against the snapshot's own slots.

    Only ``BOOK`` is checked. ``REGISTER`` books nothing, ``CANCEL`` and
    ``RESCHEDULE`` name an ``appointment_id`` from a diary rather than a slot,
    and ``NO_ACTION`` and ``ESCALATE`` carry no slot at all.
    """
    roster = roster or load()
    specialty_of = world.provider_specialty
    out: list[RosterCheck] = []
    for case in roster.cases:
        for index, alternative in enumerate(case.acceptable):
            for action in alternative:
                if action.get("action") != "BOOK":
                    continue
                specialty = specialty_of.get(action["provider_id"])
                if specialty is None:
                    out.append(
                        RosterCheck(
                            case.id,
                            case.problem_id,
                            False,
                            f"provider {action['provider_id']} is not in the snapshot's catalogue",
                        )
                    )
                    continue
                wanted = (
                    action["provider_id"],
                    action["location_id"],
                    action["appointment_type_id"],
                    action["slot"],
                )
                offered = self_slots = world.slots_for(action["patient_id"], specialty)
                if wanted in offered:
                    out.append(
                        RosterCheck(case.id, case.problem_id, True, f"answer {index} reproduces")
                    )
                    continue
                named = world.slots_for(
                    action["patient_id"], specialty, action.get("policy_id", "")
                )
                if wanted in named:
                    out.append(
                        RosterCheck(
                            case.id,
                            case.problem_id,
                            True,
                            f"answer {index} reproduces only once {action['policy_id']} is named "
                            "— the plan on the record does not buy this slot",
                        )
                    )
                    continue
                offered = self_slots | named
                same_minute = {s for s in offered if s[3] == action["slot"]}
                if same_minute:
                    detail = (
                        f"answer {index}: the minute is offered but not as "
                        f"{wanted[:3]} — the API offers {sorted(s[:3] for s in same_minute)}"
                    )
                elif not offered:
                    detail = (
                        f"answer {index}: the API offers this patient nothing in {specialty}. "
                        "Problem 17's cases look like this until the second plan is named"
                    )
                else:
                    detail = f"answer {index}: {action['slot']} is not offered to this patient"
                out.append(RosterCheck(case.id, case.problem_id, False, detail))
    return out
