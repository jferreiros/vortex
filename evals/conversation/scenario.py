"""Scenario files: ``evals/conversation/scenarios/*.yaml``.

Each file holds a ``group`` and a list of ``scenarios``. One scenario::

    - id: p13.correction_wins
      problem: 13
      now: "2026-09-18T09:00:00+02:00"      # optional
      from_number: "+34612345678"           # optional (absent = withheld)
      caller:
        - says: "Hola, soy Marta Ruiz, quiero cita de medicina general"
          means:
            identify: {name: "Marta Ruiz"}
            request: {intent: book, specialty_id: general_practice}
        - says: "Nací el 12 de marzo del 85"
          means: {identify: {date_of_birth: "1985-03-12"}}
        - says: "¿Y cuánto cuesta aparcar ahí?"
          interrupt_after_words: 4          # barge in while the agent reads options
          means: {off_topic: true}
        - says: "Vale, la primera que tenga"
          means: {accept: true}
      expect:
        actions:                            # exact list, in order (see matching.py)
          - {kind: book, patient_id: P00042, slot: {$earliest_slot: {...}}}
        trajectory_contains: [find_patient, find_slots, prepare_booking, submit_action]
        must_not_call: [prepare_cancel]
        privacy_of: [P00042]                # no national_id/phone of these on our turns
        transcript_must_not_contain: []     # normalised substrings, our turns only
        max_tool_calls: 14

``says`` is what the model hears. ``means`` is for the rules brain only; the
model never sees it. Keys of ``means``: ``identify``, ``patient`` (a third
party), ``request`` (``intent``, ``specialty_id``, ``complaint``, ``provider``,
``location_id``, ``address``, ``when``, ``part_of_day``, ``language``,
``appointment_ref``), ``register``, ``policy``, ``accept``, ``decline``,
``off_topic``, ``adversarial``, ``silence_secs``, ``end``, and ``ask`` (a
``clinic_facts`` input; ``request.location_id: as_told`` then books at the
one site that answer named).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


@dataclass
class CallerTurn:
    says: str
    means: dict[str, Any] = field(default_factory=dict)
    interrupt_after_words: int | None = None
    silence_secs: float | None = None


@dataclass
class Scenario:
    id: str
    group: str
    problem: int | None
    now: str | None
    from_number: str | None
    caller: list[CallerTurn]
    expect: dict[str, Any]
    tags: list[str]
    file: str
    name: str = ""


def load_scenarios(scenarios_dir: Path = SCENARIOS_DIR, only: str | None = None) -> list[Scenario]:
    out: list[Scenario] = []
    for path in sorted(scenarios_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        group = doc.get("group", path.stem)
        for raw in doc.get("scenarios", []):
            sid = raw.get("id")
            if not sid:
                raise ValueError(f"{path.name}: a scenario has no id")
            if only and only not in sid:
                continue
            turns = [
                CallerTurn(
                    says=str(t.get("says", "")),
                    means=dict(t.get("means", {}) or {}),
                    interrupt_after_words=t.get("interrupt_after_words"),
                    silence_secs=t.get("silence_secs"),
                )
                for t in raw.get("caller", [])
            ]
            out.append(
                Scenario(
                    id=sid,
                    group=group,
                    problem=raw.get("problem", doc.get("problem")),
                    now=raw.get("now", doc.get("now")),
                    from_number=raw.get("from_number", doc.get("from_number")),
                    caller=turns,
                    expect=dict(raw.get("expect", {}) or {}),
                    tags=list(raw.get("tags", [])),
                    file=path.name,
                    name=raw.get("name", sid),
                )
            )
    ids = [s.id for s in out]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate scenario ids: {sorted(dupes)}")
    return out
