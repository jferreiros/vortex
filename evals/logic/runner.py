"""Run the tool-level cases in ``evals/logic/cases/*.yaml``.

Two case shapes live in the same files.

A *tool case* calls one tool and matches its output::

    - id: identity.dni.valid
      problem: 4
      tool: validate_national_id
      args: {value: "12345678z"}
      expect: {normalized: "12345678Z", kind: dni, valid: true}

A *flow case* runs tools in order, threads results with ``{{as.path}}`` and
matches the actions the call would have submitted::

    - id: flow.simple_booking
      problem: 1
      from_number: "+34612345678"
      steps:
        - as: patient
          tool: find_patient
          args: {name: "Marta Ruiz", date_of_birth: "1985-03-12"}
          expect: {status: found}
        - as: slots
          tool: find_slots
          args: {patient_id: "{{patient.patient.patient_id}}", specialty_id: general_practice,
                 date_from: "{{ctx.today+1}}", date_to: "{{ctx.today+7}}"}
        - as: booking
          tool: prepare_booking
          args: {patient_id: "{{patient.patient.patient_id}}", slot: "{{slots.slots[0]}}",
                 policy_id: sanitas}
        - tool: submit_action
          args: {action: "{{booking.action}}"}
      expect_actions:
        - kind: book
          patient_id: P00042
          slot: {$earliest_slot: {specialty_id: general_practice}}

File-level keys ``group``, ``now`` and ``from_number`` are defaults for every
case in the file. A case passing only through tools that are still contract
stubs is reported as *hollow*: green, but proving nothing yet.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path
from typing import Any

import yaml

from evals.common.context import make_context, submitted_actions
from evals.common.matching import mismatches
from evals.common.oracle import resolve_oracles
from evals.common.results import (
    RESULTS_DIR,
    CaseResult,
    RunResult,
    git_info,
    now_stamp,
)
from evals.common.stubs import is_stub, stub_tools
from evals.common.templating import TemplateError, render
from vortex import tools as registry
from vortex.tools import ToolError

CASES_DIR = Path(__file__).resolve().parent / "cases"


def load_cases(cases_dir: Path = CASES_DIR, only: str | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(cases_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        group = doc.get("group", path.stem)
        for raw in doc.get("cases", []):
            case = {
                "group": group,
                "now": doc.get("now"),
                "from_number": doc.get("from_number"),
                "file": path.name,
                **raw,
            }
            if "id" not in case:
                raise ValueError(f"{path.name}: a case has no id")
            if only and only not in case["id"]:
                continue
            cases.append(case)
    ids = [c["id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate case ids: {sorted(dupes)}")
    return cases


async def run_case(case: dict[str, Any], log_dir: Path) -> CaseResult:
    started = time.monotonic()
    result = CaseResult(
        id=case["id"],
        name=case.get("name", case["id"]),
        status="error",
        problem=case.get("problem"),
        group=case["group"],
        tags=list(case.get("tags", [])),
    )
    ctx = make_context(
        call_id=case["id"],
        now=case.get("now"),
        from_number=case.get("from_number"),
        log_dir=log_dir,
    )
    try:
        if "tool" in case:
            await _run_tool_case(case, ctx, result)
        elif "steps" in case:
            await _run_flow_case(case, ctx, result)
        else:
            result.details.append("case has neither 'tool' nor 'steps'")
    except TemplateError as exc:
        result.status = "error"
        result.details.append(f"template: {exc}")
    except ToolError as exc:
        result.status = "error"
        result.details.append(f"tool error: {exc}")
    except Exception as exc:  # a crash in a lane is a finding, not a harness failure
        result.status = "error"
        result.details.append(f"{type(exc).__name__}: {exc}")
        result.details.append(traceback.format_exc().strip().splitlines()[-1])
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result


async def _run_tool_case(case: dict[str, Any], ctx: Any, result: CaseResult) -> None:
    tool = case["tool"]
    if tool not in registry.TOOLS:
        result.details.append(f"unknown tool {tool!r}")
        return
    args = render(case.get("args", {}), {}, ctx.now)
    out = await registry.call_tool(tool, ctx, args)
    actual = out.model_dump(mode="json")
    expected = await resolve_oracles(
        render(case.get("expect", {}), {}, ctx.now), ctx.clinic, ctx.now
    )
    problems = mismatches(expected, actual)
    result.extra = {"tool": tool, "args": args, "actual": actual}
    result.hollow = is_stub(tool)
    if problems:
        result.status = "fail"
        result.details.extend(problems)
    else:
        result.status = "pass"
        if result.hollow:
            result.details.append(f"{tool} is still a contract stub")


async def _run_flow_case(case: dict[str, Any], ctx: Any, result: CaseResult) -> None:
    scope: dict[str, Any] = {}
    trail: list[str] = []
    touched: set[str] = set()
    for i, step in enumerate(case["steps"]):
        tool = step["tool"]
        if tool not in registry.TOOLS:
            result.details.append(f"step {i}: unknown tool {tool!r}")
            return
        touched.add(tool)
        args = render(step.get("args", {}), scope, ctx.now)
        out = await registry.call_tool(tool, ctx, args)
        actual = out.model_dump(mode="json")
        alias = step.get("as")
        if alias:
            scope[alias] = actual
        trail.append(tool)
        if "expect" in step:
            expected = await resolve_oracles(
                render(step["expect"], scope, ctx.now), ctx.clinic, ctx.now
            )
            problems = mismatches(expected, actual)
            if problems:
                result.status = "fail"
                result.details.append(f"step {i} ({tool}) did not match:")
                result.details.extend(f"  {p}" for p in problems)
                result.extra = {"trail": trail, "failed_step": i, "actual": actual}
                result.hollow = False
                return
    actions = submitted_actions(ctx)
    expected_actions = await resolve_oracles(
        render(case.get("expect_actions", []), scope, ctx.now), ctx.clinic, ctx.now
    )
    problems = mismatches(expected_actions, actions, "$actions")
    result.extra = {"trail": trail, "actions": actions}
    stubs_touched = sorted(t for t in touched if is_stub(t))
    result.hollow = bool(stubs_touched) and len(stubs_touched) == len(touched - {"submit_action"})
    if problems:
        result.status = "fail"
        result.details.extend(problems)
    else:
        result.status = "pass"
        if stubs_touched:
            result.details.append("still stubs: " + ", ".join(stubs_touched))


async def run_all(
    *, only: str | None = None, results_dir: Path = RESULTS_DIR, cases_dir: Path = CASES_DIR
) -> RunResult:
    cases = load_cases(cases_dir, only=only)
    run = RunResult(
        layer="logic",
        started_at=now_stamp(),
        mode={"clinic": "fake", "stub_tools": sorted(stub_tools())},
        git=git_info(),
    )
    started = time.monotonic()
    log_dir = results_dir / "logic" / "calls"
    for case in cases:
        run.cases.append(await run_case(case, log_dir))
    run.duration_ms = int((time.monotonic() - started) * 1000)
    if run.hollow:
        run.notes.append(
            f"{run.hollow} case(s) pass only through contract stubs. "
            "A hollow pass is not evidence the lane works."
        )
    return run


def run_sync(**kwargs: Any) -> RunResult:
    return asyncio.run(run_all(**kwargs))
