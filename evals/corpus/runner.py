"""Layer 4: the official roster and the surface it is drawn from.

    python -m evals corpus                 # probes + roster integrity, no keys
    python -m evals corpus --judge-log logs/calls.jsonl
    python -m evals corpus --coverage      # points at stake, printed

Three things run here, and each says plainly what it did and did not verify.

**Roster integrity.** Every published case parses, every verb and every reason
is in the contract's closed vocabulary, every action carries the fields its
route takes. A roster that stopped parsing after an organiser's correction is
the kind of failure that would otherwise surface as a lost Run All.

**Probes.** The enumerated documented surface — 27 date phrases across the
event's days, all 20 triage rows, the check-letter arithmetic — run against our
own lane tools. A probe that passes only because the tool is still a contract
stub is reported hollow, never as a pass.

**Judging real calls.** With ``--judge-log`` the runner reads a call log,
joins each call to the public case it dialled and scores the record the way the
leaderboard would, naming the field that lost. Practice calls are free and
uncapped; this turns them into the feedback ``Run All`` refuses to give.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

from evals.common.context import make_context
from evals.common.results import RESULTS_DIR, CaseResult, RunResult, git_info
from evals.common.stubs import is_stub
from evals.corpus import judge, probes, world
from evals.corpus import normalize as N
from evals.corpus.catalogue import (
    PROBLEMS,
    REASONS,
    VERBS,
    Case,
    Roster,
    load,
    max_points,
)
from vortex import tools as registry

LAYER = "corpus"

#: Which tool answers each probe family, and the input field it takes.
_PROBE_TOOL = {
    "dates": "resolve_date",
    "triage": "triage",
    "ids": "validate_national_id",
}

#: The fields each submit route carries, from the contract.
_ROUTE_FIELDS: dict[str, set[str]] = {
    "REGISTER": {
        "given_name",
        "first_surname",
        "second_surname",
        "national_id",
        "date_of_birth",
        "phone",
        "email",
        "insurer",
    },
    "BOOK": {
        "patient_id",
        "provider_id",
        "location_id",
        "appointment_type_id",
        "slot",
        "policy_id",
    },
    "RESCHEDULE": {"appointment_id", "provider_id", "location_id", "slot", "policy_id"},
    "CANCEL": {"appointment_id"},
    "NO_ACTION": {"reason"},
    "ESCALATE": {"reason"},
}


# ---- roster integrity -------------------------------------------------------


def _integrity_cases(roster: Roster) -> list[CaseResult]:
    out: list[CaseResult] = []
    for case in roster.cases:
        started = time.perf_counter()
        details: list[str] = []
        if not case.acceptable:
            details.append("no acceptable answer: this case can never pass")
        for index, alternative in enumerate(case.acceptable):
            if not alternative:
                details.append(f"answer {index} is an empty action list")
            for action in alternative:
                verb = action.get("action")
                if verb not in VERBS:
                    details.append(f"answer {index}: verb {verb!r} is not in the contract")
                    continue
                flat = dict(action)
                flat.update(flat.pop("new_patient", {}) or {})
                present = {k for k in flat if k != "action"}
                missing = _ROUTE_FIELDS[verb] - present
                extra = present - _ROUTE_FIELDS[verb]
                if missing:
                    details.append(f"answer {index} {verb}: missing {sorted(missing)}")
                if extra:
                    details.append(f"answer {index} {verb}: unexpected {sorted(extra)}")
                reason = flat.get("reason")
                if reason is not None and reason not in REASONS:
                    details.append(f"answer {index}: reason {reason!r} is outside the vocabulary")
        for item in case.protected:
            if item.get("kind") not in ("national_id", "phone"):
                details.append(f"protected field of unknown kind {item.get('kind')!r}")
        out.append(
            CaseResult(
                id=f"roster.{case.id}",
                name=case.summary or case.shape(),
                status="fail" if details else "pass",
                problem=case.number,
                group="roster",
                duration_ms=int((time.perf_counter() - started) * 1000),
                details=details,
                tags=["roster", case.problem_id],
                extra={"shape": case.shape(), "weight": case.weight},
            )
        )
    return out


# ---- probes -----------------------------------------------------------------


async def _run_probe(probe: probes.Probe, log_dir: Path) -> CaseResult:
    tool_name = _PROBE_TOOL[probe.family]
    started = time.perf_counter()
    spec = registry.TOOLS.get(tool_name)
    base = dict(
        id=probe.id,
        name=probe.description,
        problem=probe.problem,
        group=probe.family,
        tags=["probe", probe.family],
        extra={"expectation": probe.expectation},
    )
    if spec is None:
        return CaseResult(
            **base,
            status="error",
            details=[f"no tool named {tool_name} in the registry"],
        )
    payload = dict(probe.payload)
    now = payload.pop("now", None)
    ctx = make_context(call_id=probe.id, now=now, log_dir=log_dir)
    try:
        args = spec.input_model(**payload)
        result = await spec.fn(ctx, args)
    except Exception:  # noqa: BLE001 - a probe never fails the whole run
        return CaseResult(
            **base,
            status="error",
            duration_ms=int((time.perf_counter() - started) * 1000),
            details=traceback.format_exc().strip().splitlines()[-3:],
        )
    details = probe.check(result)
    return CaseResult(
        **base,
        status="fail" if details else "pass",
        hollow=not details and is_stub(tool_name),
        duration_ms=int((time.perf_counter() - started) * 1000),
        details=details,
    )


def _probe_list(roster: Roster) -> list[probes.Probe]:
    known_ids = sorted(
        {
            (a.get("new_patient") or {}).get("national_id")
            for c in roster.cases
            for alt in c.acceptable
            for a in alt
            if a.get("action") == "REGISTER"
        }
        - {None}
    )
    return probes.date_probes() + probes.triage_probes() + probes.id_probes(known_ids)


def _skipped_families(roster: Roster) -> list[CaseResult]:
    """Say out loud what cannot be checked without the clinic.

    A scoreboard that omits what it could not test is a scoreboard that lies.
    """
    seen = {r for c in roster.cases for r in c.reasons}
    out = [
        CaseResult(
            id=f"p6.reason.{reason}",
            name=f"no public case ever asks for {reason}",
            status="skipped",
            problem=6,
            group="rules",
            details=[
                "the private pool can draw this refusal shape and the roster never shows it",
                "needs the clinic catalogue to build a caller for: set PLATFORM_API_KEY "
                "and run python -m evals.corpus.snapshot",
            ],
            tags=["probe", "rules", "unreached-reason"],
        )
        for reason in probes.unreached_reasons(seen)
    ]
    for index, (fact, consequence) in enumerate(probes.site_closure_notes()):
        out.append(
            CaseResult(
                id=f"p5.site_closure.{index:02d}",
                name=fact,
                status="skipped",
                problem=5,
                group="rules",
                details=[
                    consequence,
                    "belongs to find_slots, not resolve_date: needs the clinic catalogue",
                ],
                tags=["probe", "dates", "site-closure"],
            )
        )
    for index, (fact, consequence) in enumerate(probes.KNOWN_INTERACTIONS):
        out.append(
            CaseResult(
                id=f"p6.interaction.{index:02d}",
                name=fact,
                status="skipped",
                problem=6,
                group="rules",
                details=[consequence, "needs the clinic catalogue"],
                tags=["probe", "rules", "interaction"],
            )
        )
    return out


# ---- judging real calls -----------------------------------------------------


def _read_call_log(path: Path) -> dict[str, dict[str, Any]]:
    """Group a JSONL call log by ``call_id``, keeping what the judge needs.

    The log's event field is ``kind``, not ``event``, and a submitted action is
    logged twice: ``submit.sent`` carries the payload before the POST,
    ``submit.result`` carries it with the platform's answer. Read the result and
    fall back to what was sent, so a call whose POST never came back is judged
    on what it tried to submit rather than counted as silence.
    """
    calls: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        call_id = event.get("call_id")
        if not call_id:
            continue
        call = calls.setdefault(
            call_id,
            {"actions": [], "attempted": [], "our_turns": [], "from_number": None},
        )
        kind = event.get("kind") or event.get("event")
        payload = event.get("payload") or {}
        if kind == "submit.result" and payload:
            call["actions"].append(_action_from(event.get("route", ""), payload))
        elif kind == "submit.sent" and payload:
            call["attempted"].append(_action_from(event.get("route", ""), payload))
        elif kind == "turn.assistant" and event.get("text"):
            call["our_turns"].append(str(event["text"]))
        elif kind == "call.started":
            params = event.get("custom_parameters") or {}
            call["from_number"] = event.get("from_number") or params.get("from_number")
    for call in calls.values():
        if not call["actions"]:
            call["actions"] = call["attempted"]
    return calls


def _action_from(route: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Turn a submit route plus its body into the record shape the judge reads."""
    verb = route.rstrip("/").rsplit("/", 1)[-1].replace("-", "_").upper()
    body = {k: v for k, v in payload.items() if k != "call_id"}
    if verb == "REGISTER":
        return {"action": verb, "new_patient": body}
    return {"action": verb, **body}


def _phone_index(roster: Roster) -> dict[str, list[Case]]:
    """Public cases by the persona's phone, which is the only join we get.

    Nothing tells us which case was dialled. ``start.customParameters`` carries
    ``call_id`` and ``from_number`` and nothing else, and the submissions
    readback carries ``call_id``, ``record`` and ``received_at``. ``from_number``
    is the number the clinic holds for the caller, so it names the persona —
    uniquely for most of the roster, ambiguously for a handful who share one.
    """
    index: dict[str, list[Case]] = {}
    for case in roster.cases:
        phone = case.persona.get("phone") or (case.persona.get("data") or {}).get("phone")
        if phone:
            index.setdefault(N.phone(str(phone)), []).append(case)
    return index


def _judge_cases(
    roster: Roster, log_path: Path, case_id: str | None = None
) -> tuple[list[CaseResult], list[str]]:
    notes: list[str] = []
    if not log_path.exists():
        return [], [f"{log_path} does not exist: no calls to judge"]
    calls = _read_call_log(log_path)
    if not calls:
        return [], [f"{log_path} holds no call events"]
    forced = roster.get(case_id) if case_id else None
    if case_id and forced is None:
        return [], [f"no public case matches {case_id!r}"]
    index = _phone_index(roster)
    out: list[CaseResult] = []
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for call_id, call in calls.items():
        case = forced
        if case is None:
            number = call.get("from_number")
            candidates = index.get(N.phone(str(number)), []) if number else []
            if len(candidates) == 1:
                case = candidates[0]
            elif len(candidates) > 1:
                ambiguous.append(
                    f"{call_id[:12]} -> {number} is shared by {len(candidates)} cases "
                    f"({', '.join(sorted({c.problem_id for c in candidates}))})"
                )
                continue
        if case is None:
            unmatched.append(f"{call_id[:12]} (from_number {call.get('from_number') or 'absent'})")
            continue
        verdict = judge.score(case, call["actions"], our_turns=call["our_turns"] or None)
        out.append(
            CaseResult(
                id=f"judged.{case.id}",
                name=f"{case.summary or case.shape()} · call {call_id[:8]}",
                status="pass" if verdict.passed else "fail",
                problem=case.number,
                group="judged",
                details=verdict.diffs + verdict.leaks + verdict.caveats,
                tags=["judged", case.problem_id, verdict.signal],
                extra={"points": verdict.points, "signal": verdict.signal},
            )
        )
    if unmatched:
        notes.append(
            f"{len(unmatched)} call(s) could not be matched to a public case by caller "
            "number and were not judged: " + "; ".join(unmatched[:4])
        )
        notes.append(
            "nothing names the case on the wire, so a withheld number — which is what "
            "problem 4's callers look like — can only be judged with --case <id>"
        )
    if ambiguous:
        notes.append(
            f"{len(ambiguous)} call(s) were not guessed because the caller number is "
            "shared: " + "; ".join(ambiguous[:3]) + ". Re-run with --case <id>"
        )
        notes.append(
            "the organisers reuse a persona across problems, so a number identifies "
            "only 26 of the 73 cases on its own. A practice call is dialled one case "
            "at a time, so --case is the reliable way to say which"
        )
    return out, notes


# ---- the run ----------------------------------------------------------------


def _roster_reproduction_cases(roster: Roster, run_result: RunResult) -> list[CaseResult]:
    """Does the API actually offer each published answer? Needs a snapshot."""
    if not world.exists():
        run_result.notes.append(
            "--verify-roster needs a clinic snapshot: make evals-snapshot (needs PLATFORM_API_KEY)"
        )
        return [
            CaseResult(
                id="world.snapshot",
                name="the clinic snapshot is missing",
                status="skipped",
                group="world",
                details=["run: make evals-snapshot"],
                tags=["world"],
            )
        ]
    snapshot = world.read()
    run_result.mode["snapshot_taken_at"] = snapshot.manifest.get("taken_at")
    if snapshot.manifest.get("roster_sha256") != roster.sha256:
        run_result.notes.append(
            "the snapshot was taken for a different roster; re-take it after make evals-fetch"
        )
    out = []
    for check in world.verify_roster(snapshot, roster):
        out.append(
            CaseResult(
                id=f"world.{check.case_id}",
                name=check.detail,
                status="pass" if check.reproduced else "fail",
                problem=PROBLEMS[check.problem_id][0],
                group="world",
                details=[] if check.reproduced else [check.detail],
                tags=["world", check.problem_id],
            )
        )
    return out


async def run(
    *,
    only: str | None = None,
    judge_log: Path | None = None,
    case_id: str | None = None,
    verify_roster: bool = False,
    results_dir: Path = RESULTS_DIR,
) -> RunResult:
    started = time.perf_counter()
    roster = load()
    log_dir = results_dir / "calls" / LAYER
    run_result = RunResult(
        layer=LAYER,
        started_at=__import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        git=git_info(),
        mode={
            "roster": str(roster.path.name),
            "roster_sha256": roster.sha256[:12],
            "cases": len(roster.cases),
            "judge_log": str(judge_log) if judge_log else None,
        },
    )

    cases = _integrity_cases(roster)

    probe_list = [p for p in _probe_list(roster) if not only or only in p.id]
    results = await asyncio.gather(*(_run_probe(p, log_dir) for p in probe_list))
    cases += list(results)
    cases += [c for c in _skipped_families(roster) if not only or only in c.id]

    if verify_roster:
        cases += _roster_reproduction_cases(roster, run_result)

    if judge_log is not None:
        judged, notes = _judge_cases(roster, judge_log, case_id)
        cases += judged
        run_result.notes += notes

    run_result.cases = cases
    run_result.duration_ms = int((time.perf_counter() - started) * 1000)
    run_result.summary = _summary(roster, cases)
    run_result.notes += _notes(roster, cases)
    return run_result


def _summary(roster: Roster, cases: list[CaseResult]) -> dict[str, Any]:
    by_group = Counter(c.group for c in cases)
    judged = [c for c in cases if c.group == "judged"]
    return {
        "roster_sha256": roster.sha256,
        "roster_cases": len(roster.cases),
        "max_points_per_run": max_points(),
        "groups": dict(by_group),
        "judged_points": sum(int(c.extra.get("points", 0)) for c in judged if c.passed),
        "coverage": coverage_table(roster),
    }


def _notes(roster: Roster, cases: list[CaseResult]) -> list[str]:
    notes = [
        f"roster: {len(roster.cases)} published cases, sha256 {roster.sha256[:12]} "
        f"(re-fetch each morning: the booking slot moves overnight)",
        f"one Run All can put {max_points()} points on the board",
    ]
    hollow = [c for c in cases if c.hollow]
    if hollow:
        notes.append(
            f"{len(hollow)} probe(s) passed only through a contract stub and are not counted"
        )
    skipped = [c for c in cases if c.status == "skipped"]
    if skipped:
        notes.append(
            f"{len(skipped)} documented situation(s) need the clinic catalogue and were not run"
        )
    return notes


def coverage_table(roster: Roster) -> list[dict[str, Any]]:
    """Points at stake against what the public roster actually exercises."""
    rows = []
    for problem_id, (number, title, weight, pool) in sorted(
        PROBLEMS.items(), key=lambda kv: kv[1][0]
    ):
        cases = roster.by_problem(problem_id)
        shapes = sorted({c.shape() for c in cases})
        languages = sorted({c.language for c in cases})
        rows.append(
            {
                "n": number,
                "problem_id": problem_id,
                "title": title,
                "weight": weight,
                "points_at_stake": weight * pool,
                "public_cases": len(cases),
                "shapes": shapes,
                "languages": languages,
                "noisy": sum(1 for c in cases if c.noisy),
            }
        )
    return rows


def run_sync(**kwargs: Any) -> RunResult:
    return asyncio.run(run(**kwargs))
