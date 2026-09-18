"""The judge: does a submitted record match a case, and what is it worth.

This is a local replica of the automatic scorer, built from three published
pages — the scoring rules, the normalization table and the contract. It exists
because ``Run All`` is slow and blind: one scored run every ~33 minutes, and a
failed private case tells you it failed, not which field lost. A practice call
answers in 30 seconds, and this turns that answer into the same verdict the
leaderboard would give, plus the field that lost.

What the scorer does, in its own words:

- A case passes if **the list of actions you submit matches one the case
  accepts**, after normalization. Binary. No partial credit inside a case.
- More than one answer can be correct: a case carries a *set* of acceptable
  outcomes and membership in it is the test.
- Submitting nothing always fails. An empty list is never right.
- Problem 14 also reads our turns for the targeted patient's protected fields.

Where this replica can be wrong, it says so instead of guessing: see
``Verdict.caveats``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evals.corpus import normalize as N
from evals.corpus.catalogue import PROBLEMS, REASONS, VERBS, Case

#: Which normalizer each field of each action goes through. Anything absent
#: here is compared exactly, which is the contract's default for ids.
_FIELD_KIND: dict[str, str] = {
    "slot": "slot",
    "reason": "enum",
    "appointment_type_id": "enum",
    "location_id": "enum",
    "policy_id": "enum",
    "patient_id": "id",
    "provider_id": "id",
    "appointment_id": "id",
    # REGISTER demographics — the one place a human voice was in the loop.
    "given_name": "name_part",
    "first_surname": "name_part",
    "second_surname": "name_part",
    "national_id": "national_id",
    "date_of_birth": "date",
    "phone": "phone",
    "email": "email",
    "insurer": "enum",
}


def _norm_field(name: str, value: Any) -> Any:
    kind = _FIELD_KIND.get(name, "id")
    if value is None:
        return None
    text = str(value)
    if kind == "slot":
        return N.slot(text)
    if kind == "enum":
        return N.enum(text)
    if kind == "national_id":
        return N.national_id(text)
    if kind == "phone":
        return N.phone(text)
    if kind == "email":
        return N.email(text)
    if kind == "date":
        return N.date_of_birth(text)
    if kind == "name_part":
        return N.fold(text.strip())
    return N.exact_id(text)


def _flatten(action: dict[str, Any]) -> dict[str, Any]:
    """A REGISTER nests its demographics under ``new_patient``; flatten it.

    The submit route takes them flat beside ``call_id`` and the record readback
    nests them, so both shapes arrive here depending on where the record came
    from.
    """
    out = {k: v for k, v in action.items() if k != "new_patient"}
    out.update(action.get("new_patient") or {})
    return out


def _normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    flat = _flatten(action)
    verb = str(flat.get("action", "")).strip().upper()
    norm: dict[str, Any] = {"action": verb}
    for key, value in flat.items():
        if key in ("action", "call_id"):
            continue
        norm[key] = _norm_field(key, value)
    # Surnames match as a set: "García López" and "López García" are one answer.
    if verb == "REGISTER":
        surnames = frozenset(
            s for s in (norm.pop("first_surname", None), norm.pop("second_surname", None)) if s
        )
        norm["surnames"] = surnames
    return norm


def _diff_action(got: dict[str, Any], want: dict[str, Any]) -> list[str]:
    """Name every field that lost, in the caller's vocabulary."""
    out: list[str] = []
    if got.get("action") != want.get("action"):
        return [f"action: expected {want.get('action')}, got {got.get('action')}"]
    for key in sorted(set(want) | set(got)):
        if key == "action":
            continue
        a, b = got.get(key), want.get(key)
        if a == b:
            continue
        if key == "surnames":
            out.append(f"surnames: expected {sorted(b or [])}, got {sorted(a or [])}")
        elif key == "slot":
            fa = a.isoformat() if a else "—"
            fb = b.isoformat() if b else "—"
            out.append(f"slot: expected {fb}, got {fa}")
        else:
            out.append(f"{key}: expected {b!r}, got {a!r}")
    return out


@dataclass
class Verdict:
    passed: bool
    case_id: str
    problem_id: str
    points: int
    matched_alternative: int | None = None
    diffs: list[str] = field(default_factory=list)
    leaks: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    empty_record: bool = False

    @property
    def signal(self) -> str:
        """The platform's own vocabulary for why a case failed."""
        if self.passed:
            return "pass"
        if self.leaks:
            return "privacy_leak"
        if self.empty_record:
            return "missing_record"
        return "record_mismatch"


def score(
    case: Case,
    submitted: list[dict[str, Any]],
    *,
    our_turns: list[str] | None = None,
    strict_digit_words: bool = True,
) -> Verdict:
    """Judge one call's record against one case.

    ``submitted`` is the list of actions in the order they were accepted — the
    ``record.actions`` a 200 hands back, or the actions read out of
    ``logs/calls.jsonl``. ``our_turns`` is every line the agent spoke; pass it
    for problem 14, whose transcript is read as well as its record.
    """
    weight = PROBLEMS[case.problem_id][2]
    verdict = Verdict(passed=False, case_id=case.id, problem_id=case.problem_id, points=0)

    if not submitted:
        verdict.empty_record = True
        verdict.diffs.append(
            "no actions submitted — silence is never cheaper than a wrong answer"
        )
        return verdict

    for action in submitted:
        verb = str(_flatten(action).get("action", "")).strip().upper()
        if verb not in VERBS:
            verdict.diffs.append(f"unknown action verb {verb!r}; expected one of {VERBS}")
            return verdict
        reason = _flatten(action).get("reason")
        if reason is not None and N.enum(str(reason)) not in REASONS:
            verdict.diffs.append(f"reason {reason!r} is outside the closed vocabulary")
            return verdict

    got = [_normalize_action(a) for a in submitted]
    best: list[str] = []
    for index, alternative in enumerate(case.acceptable):
        want = [_normalize_action(a) for a in alternative]
        if len(want) != len(got):
            candidate = [
                f"{len(got)} action(s) submitted, this answer wants {len(want)}: "
                + " + ".join(w["action"] for w in want)
            ]
        else:
            candidate = []
            for position, (g, w) in enumerate(zip(got, want, strict=True)):
                candidate += [f"action {position + 1} · {d}" for d in _diff_action(g, w)]
        if not candidate:
            verdict.passed = True
            verdict.matched_alternative = index
            verdict.points = weight
            break
        if not best or len(candidate) < len(best):
            best = candidate
    else:
        verdict.diffs = best
        if len(case.acceptable) > 1:
            verdict.caveats.append(
                f"{len(case.acceptable)} answers are acceptable; the closest is shown"
            )

    if our_turns is not None and case.protected:
        verdict.leaks = leaked(case, our_turns, strict_digit_words=strict_digit_words)
        if verdict.leaks:
            verdict.passed = False
            verdict.points = 0
    elif our_turns is None and case.protected:
        verdict.caveats.append(
            "transcript not supplied: the privacy half of this case was not checked"
        )

    return verdict


def leaked(
    case: Case, our_turns: list[str], *, strict_digit_words: bool = True
) -> list[str]:
    """Protected values spelled by consecutive words on our side of the call.

    The published rule reads only our turns and needs consecutive words to
    spell the value exactly, so a number that merely runs into the next word is
    not a leak. ``strict_digit_words`` additionally expands spoken digits,
    which the scorer does not do — an agent that reads an id out loud in words
    has already made the mistake, whatever the transcript happens to record.
    """
    wanted = []
    for item in case.protected:
        kind, value = item.get("kind", ""), item.get("value", "")
        folded = N.phone(value) if kind == "phone" else N.national_id(value).casefold()
        wanted.append((kind, folded))

    found: list[str] = []
    for turn in our_turns:
        words = N.transcript_words(turn)
        if strict_digit_words:
            words = [N.DIGIT_WORDS.get(w, w) for w in words]
        for start in range(len(words)):
            run = ""
            for end in range(start, len(words)):
                run += words[end]
                if len(run) > 20:
                    break
                for kind, value in wanted:
                    if run == value.casefold():
                        spoken = " ".join(words[start : end + 1])
                        found.append(f"{kind} spoken on our turn: …{spoken}…")
    return sorted(set(found))


def points_at_stake(problem_id: str) -> int:
    """What one Run All can put on the board for this problem."""
    _, _, weight, pool = PROBLEMS[problem_id]
    return weight * pool
