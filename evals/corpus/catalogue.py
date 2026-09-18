"""The official case roster, loaded and indexed.

``cases/public-cases.json`` is the file the Problems page links: 73 published
cases with the persona, the caller prompt the organisers feed their own caller,
the audio bed, the protected fields and — the part nothing else gives us — the
set of actions each case accepts.

The roster is the export at Friday's anchor (09:00 Europe/Madrid). Only the
slot in a booking answer moves, and only overnight, so re-run ``fetch.py`` each
morning of the event.

Weights and case counts come from the Problems page. Points are
``passed cases x weight``, with no denominator, so the whole open roster is
worth 196.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

CASES_FILE = Path(__file__).resolve().parent / "cases" / "public-cases.json"

#: problem_id -> (number, title, weight, private cases per Run All)
#: Weight is what each *passed case* is worth. The Switchboard scores nothing
#: and Run All never dials it, so its weight is 0 and its pool is empty.
PROBLEMS: dict[str, tuple[int, str, int, int]] = {
    "simple_booking": (1, "The Simple Booking", 1, 4),
    "switchboard": (2, "The Switchboard", 0, 0),
    "doctor_and_site": (3, "The Doctor and the Site", 2, 4),
    "the_new_patient": (4, "The New Patient", 2, 4),
    "when_exactly": (5, "When Exactly", 2, 4),
    "the_rules": (6, "The Rules", 3, 4),
    "no_slot_free": (7, "No Slot Free", 2, 4),
    "change_and_cancel": (8, "Change and Cancel", 2, 4),
    "third_party": (9, "The Third Party", 3, 4),
    "triage": (10, "Triage", 3, 4),
    "languages": (11, "Languages", 3, 4),
    "noise": (12, "Noise", 3, 4),
    "difficult_caller": (13, "The Difficult Caller", 4, 4),
    "adversarial": (14, "Adversarial and Privacy", 4, 4),
    "nearest_site": (15, "The Nearest Site", 3, 4),
    "the_questions": (16, "The Questions", 3, 4),
    "second_policy": (17, "The Second Policy", 4, 4),
    "the_real_call": (18, "The Real Call", 5, 4),
}

#: The full closed vocabulary from the contract. The first eleven mirror the
#: clinic's own restrictions one-for-one; the rest are endings that are not a
#: clinic rule.
RULE_REASONS = (
    "not_eligible_age",
    "referral_required",
    "provider_not_in_network",
    "specialty_not_covered",
    "location_not_covered",
    "insurer_referral_required",
    "allowance_exhausted",
    "provider_on_leave",
    "location_hours",
    "type_not_offered",
    "patient_history",
)
OTHER_REASONS = (
    "no_availability",
    "clinic_closed",
    "patient_not_found",
    "provider_not_found",
    "caller_not_authorised",
    "out_of_scope",
    "medical_emergency",
)
REASONS = RULE_REASONS + OTHER_REASONS

VERBS = ("REGISTER", "BOOK", "RESCHEDULE", "CANCEL", "NO_ACTION", "ESCALATE")


def max_points() -> int:
    """196: every scored problem's private pool passed in one run."""
    return sum(w * n for _, _, w, n in PROBLEMS.values())


@dataclass(frozen=True)
class Case:
    id: str
    problem_id: str
    language: str
    reference_time: str
    persona: dict[str, Any]
    caller_prompt: str
    summary: str
    audio: dict[str, Any]
    protected: list[dict[str, str]]
    acceptable: list[list[dict[str, Any]]]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def number(self) -> int:
        return PROBLEMS[self.problem_id][0]

    @property
    def weight(self) -> int:
        return PROBLEMS[self.problem_id][2]

    @property
    def now(self) -> datetime:
        return datetime.fromisoformat(self.reference_time)

    @property
    def verbs(self) -> list[str]:
        """The verbs of the first acceptable answer. Enough to group by shape."""
        return [a["action"] for a in self.acceptable[0]]

    @property
    def reasons(self) -> list[str]:
        return sorted({a["reason"] for alt in self.acceptable for a in alt if a.get("reason")})

    @property
    def noisy(self) -> bool:
        return self.audio.get("background", "silence") != "silence"

    def shape(self) -> str:
        """``BOOK`` / ``NO_ACTION(no_availability)`` / ``CANCEL+CANCEL``."""
        parts = []
        for a in self.acceptable[0]:
            parts.append(a["action"] + (f"({a['reason']})" if a.get("reason") else ""))
        return "+".join(parts)


@dataclass(frozen=True)
class Roster:
    cases: list[Case]
    sha256: str
    path: Path

    def by_problem(self, problem_id: str) -> list[Case]:
        return [c for c in self.cases if c.problem_id == problem_id]

    def get(self, case_id: str) -> Case | None:
        for c in self.cases:
            if c.id == case_id or c.id.endswith(case_id):
                return c
        return None

    def filter(self, only: str | None = None, problem: str | None = None) -> list[Case]:
        out = self.cases
        if problem:
            out = [c for c in out if c.problem_id == problem or str(c.number) == problem]
        if only:
            out = [c for c in out if only in c.id or only in c.problem_id]
        return out


@lru_cache(maxsize=1)
def load(path: Path = CASES_FILE) -> Roster:
    """Read the roster once per process. Raises if the file is missing."""
    if not path.exists():  # pragma: no cover - the file is committed
        raise FileNotFoundError(
            f"{path} is missing. Run: uv run python -m evals.corpus.fetch"
        )
    blob = path.read_bytes()
    doc = json.loads(blob)
    cases = []
    for raw in doc["cases"]:
        if raw["problem_id"] not in PROBLEMS:
            raise ValueError(f"{raw['id']}: unknown problem_id {raw['problem_id']!r}")
        cases.append(
            Case(
                id=raw["id"],
                problem_id=raw["problem_id"],
                language=raw.get("language", "en"),
                reference_time=raw["reference_time"],
                persona=raw.get("persona", {}),
                caller_prompt=raw.get("caller_prompt", ""),
                summary=raw.get("summary", ""),
                audio=raw.get("audio", {}) or {},
                protected=list(raw.get("protected", []) or []),
                acceptable=[alt["actions"] for alt in raw["expected"]["acceptable"]],
                raw=raw,
            )
        )
    return Roster(cases=cases, sha256=hashlib.sha256(blob).hexdigest(), path=path)
