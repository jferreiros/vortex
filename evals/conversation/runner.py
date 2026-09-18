"""Play every scenario against a brain and score it like the platform would.

Checks, in order of weight:

1. **Actions.** The list of actions the call would have submitted matches the
   scenario's ``expect.actions`` (exact list, shapes as in ``matching.py``).
   Final state, not transcript: this is what the leaderboard scores.
2. **Trajectory.** ``trajectory_contains`` is an ordered subsequence of tool
   names; ``must_not_call`` are tools that must never appear; ``max_tool_calls``
   caps the budget.
3. **Transcript.** ``privacy_of`` forbids those patients' national id and phone
   on our turns, after the platform's normalisation. ``transcript_must_not_contain``
   and ``transcript_must_contain`` are normalised substrings on our turns.

A scenario that ends with no submission gets the session's fallback
(``no-action/out_of_scope``) and says so. ``--repeat k`` runs each scenario k
times and reports pass^k: it passes only if every run passes.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path
from typing import Any

from evals.common.context import make_context, submitted_actions
from evals.common.matching import mismatches, normalize_for_leak
from evals.common.oracle import resolve_oracles
from evals.common.results import RESULTS_DIR, CaseResult, RunResult, git_info, now_stamp
from evals.common.stubs import is_stub
from evals.common.templating import render
from evals.conversation.brains import make_brain, pick_brain
from evals.conversation.brains.base import Trace
from evals.conversation.brains.openai_brain import (
    DEFAULT_OPENAI_MODEL,
    CassetteMiss,
    spec_for,
)
from evals.conversation.scenario import SCENARIOS_DIR, Scenario, load_scenarios
from vortex.clinic.client import FakeClinicClient
from vortex.contract import NoAction, SubmitInput
from vortex.line.submit import submit_action
from vortex.models import ModelSpec

FALLBACK = NoAction(reason="out_of_scope")


def _is_subsequence(needle: list[str], hay: list[str]) -> bool:
    it = iter(hay)
    return all(any(x == item for x in it) for item in needle)


async def play_once(
    scenario: Scenario, brain_name: str, log_dir: Path, **brain_kwargs: Any
) -> CaseResult:
    started = time.monotonic()
    result = CaseResult(
        id=scenario.id,
        name=scenario.name,
        status="error",
        problem=scenario.problem,
        group=scenario.group,
        tags=list(scenario.tags),
    )
    ctx = make_context(
        call_id=scenario.id, now=scenario.now, from_number=scenario.from_number, log_dir=log_dir
    )
    trace = Trace(ctx=ctx)
    try:
        brain = make_brain(brain_name, **brain_kwargs)
        await brain.start(scenario, trace)
        for turn in scenario.caller:
            await brain.hear(turn, trace)
        await brain.hangup(trace)
    except Exception as exc:
        if isinstance(exc, CassetteMiss):
            result.status = "unverified"
            result.details.append(str(exc))
        else:
            result.status = "error"
            result.details.append(f"{type(exc).__name__}: {exc}")
            result.details.append(traceback.format_exc().strip().splitlines()[-1])
        result.duration_ms = int((time.monotonic() - started) * 1000)
        result.extra = {
            "brain": brain_name,
            "model": trace.model,
            "trajectory": trace.trajectory,
            "transcript": trace.transcript,
            "llm_ms": trace.llm_ms,
        }
        return result

    fallback_used = False
    actions = submitted_actions(ctx)
    if not actions:
        # The session does exactly this when the socket closes with nothing accepted.
        await submit_action(ctx, SubmitInput(action=FALLBACK))
        fallback_used = True
        actions = submitted_actions(ctx)

    problems: list[str] = []
    expect = scenario.expect
    expected_actions = await resolve_oracles(
        render(expect.get("actions", []), {}, ctx.now), FakeClinicClient(), ctx.now
    )
    if expect.get("actions_any_order"):
        unmatched = list(actions)
        for shape in expected_actions:
            hit = next((a for a in unmatched if not mismatches(shape, a)), None)
            if hit is None:
                problems.append(f"$actions: no submitted action matches {shape}")
            else:
                unmatched.remove(hit)
        if unmatched:
            problems.append(f"$actions: {len(unmatched)} unexpected action(s): {unmatched}")
    else:
        problems.extend(mismatches(expected_actions, actions, "$actions"))
    if fallback_used:
        problems_note = (
            "no submission before hang-up; the session fallback sent no-action/out_of_scope"
        )
        (
            problems
            if expected_actions and expected_actions[0].get("kind") != "no-action"
            else result.details
        ).append(problems_note)

    traj = trace.trajectory
    must = expect.get("trajectory_contains", [])
    if must and not _is_subsequence(must, traj):
        problems.append(f"trajectory {traj} does not contain {must} in order")
    for forbidden in expect.get("must_not_call", []):
        if forbidden in traj:
            problems.append(f"called {forbidden}, which the scenario forbids")
    cap = expect.get("max_tool_calls")
    if cap is not None and len(traj) > cap:
        problems.append(f"{len(traj)} tool calls, cap is {cap}")

    ours = normalize_for_leak(" ".join(t for role, t in trace.transcript if role == "assistant"))
    clinic = FakeClinicClient()
    for pid in expect.get("privacy_of", []):
        record = next((p for p in clinic._patients if p.patient_id == pid), None)
        if record is None:
            problems.append(f"privacy_of: unknown patient {pid}")
            continue
        for label, value in (("national_id", record.national_id), ("phone", record.phone)):
            needle = (
                normalize_for_leak(value)[-9:] if label == "phone" else normalize_for_leak(value)
            )
            if needle and needle in ours:
                problems.append(f"LEAK: {pid}'s {label} appears on our turns")
    for needle in expect.get("transcript_must_not_contain", []):
        if normalize_for_leak(needle) in ours:
            problems.append(f"our turns contain forbidden text {needle!r}")
    for needle in expect.get("transcript_must_contain", []):
        if normalize_for_leak(needle) not in ours:
            problems.append(f"our turns never say {needle!r}")

    tools_touched = {c.name for c in trace.calls} - {"submit_action"}
    result.hollow = bool(tools_touched) and all(is_stub(t) for t in tools_touched)
    result.status = "fail" if problems else "pass"
    result.details.extend(problems)
    if result.status == "pass" and result.hollow:
        result.details.append("every tool touched is still a contract stub")
    result.details.extend(trace.notes[:3])
    result.cost_eur = trace.cost_eur
    result.duration_ms = int((time.monotonic() - started) * 1000)
    result.extra = {
        "brain": brain_name,
        "model": trace.model,
        "actions": actions,
        "trajectory": traj,
        "transcript": trace.transcript,
        "tool_calls": len(traj),
        "tokens": {"in": trace.tokens_in, "out": trace.tokens_out},
        "llm_ms": trace.llm_ms,
        "notes": trace.notes,
        "fallback_used": fallback_used,
    }
    return result


async def play(
    scenario: Scenario, brain_name: str, log_dir: Path, repeat: int, **brain_kwargs: Any
) -> CaseResult:
    runs = [
        await play_once(scenario, brain_name, log_dir, **brain_kwargs)
        for _ in range(max(1, repeat))
    ]
    if repeat <= 1:
        return runs[0]
    passed = sum(1 for r in runs if r.status == "pass")
    worst = next((r for r in runs if r.status != "pass"), runs[0])
    worst.details.insert(0, f"pass^{repeat}: {passed}/{repeat} runs passed")
    worst.cost_eur = sum(r.cost_eur for r in runs)
    worst.duration_ms = sum(r.duration_ms for r in runs)
    worst.extra["runs"] = [r.status for r in runs]
    worst.extra["llm_ms"] = [ms for r in runs for ms in r.extra.get("llm_ms", [])]
    return worst


async def run_all(
    *,
    only: str | None = None,
    brain: str = "auto",
    model: str | None = None,
    repeat: int = 1,
    record: bool = False,
    results_dir: Path = RESULTS_DIR,
    scenarios_dir: Path = SCENARIOS_DIR,
    spec: ModelSpec | None = None,
) -> RunResult:
    brain_name = pick_brain(brain)
    scenarios = load_scenarios(scenarios_dir, only=only)
    kwargs: dict[str, Any] = {}
    model_id = ""
    if brain_name in ("openai", "replay", "model"):
        kwargs = {"model": model, "record": record}
        if spec is not None:
            kwargs["spec"] = spec
            model_id = spec.id
        elif brain_name != "openai":
            model_id = spec_for(model).id
        else:
            model_id = f"openai/{model or DEFAULT_OPENAI_MODEL}"
    run = RunResult(
        layer="conversation",
        started_at=now_stamp(),
        mode={"brain": brain_name, "model": model_id, "repeat": repeat, "clinic": "fake"},
        git=git_info(),
    )
    started = time.monotonic()
    log_dir = results_dir / "conversation" / "calls"
    for scenario in scenarios:
        run.cases.append(await play(scenario, brain_name, log_dir, repeat, **kwargs))
    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.cost_eur = sum(c.cost_eur for c in run.cases)
    if brain_name == "rules":
        run.notes.append(
            "Brain: rules (offline reference). This verifies the tools and the harness, "
            "not the model. Use --brain model for the runtime's model, or --brain replay."
        )
    if brain_name == "replay":
        run.notes.append(
            "Brain: replay. Model answers come from recorded cassettes; unverified = prompt drift."
        )
    if run.hollow:
        run.notes.append(f"{run.hollow} scenario(s) pass only through contract stubs.")
    return run


def run_sync(**kwargs: Any) -> RunResult:
    return asyncio.run(run_all(**kwargs))
