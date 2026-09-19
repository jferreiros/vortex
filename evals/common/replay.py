"""The replay: all 73 published cases through the agent, judged, scored out of 196.

    python -m evals replay                    # the deployed prompt and model
    python -m evals replay --only simple_booking
    python -m evals replay --max-eur 0.50     # the brake for paid models

This is the predictor the other layers are not. Every official case plays
against the **real clinic snapshot** (``evals/common/snapshot_clinic.py``): a
model caller speaks the case's own ``caller_prompt`` — the same words the
organisers feed their caller — and the agent answers in text mode with the real
prompt, the real tools and the runtime's request settings. The submitted record
is judged by ``evals.corpus.judge``, a verified replica of the platform scorer.

The number it prints is the local proxy for the leaderboard: ``passed x weight``
per problem, capped at the problem's private pool of 4 cases, so the whole
roster tops out at 196. Its trend is what the loop optimises; its baseline is
what a PR must not lower.

It is a measurement, not a gate: a run with failures still exits 0. Only a run
that could not measure (no snapshot, no key, over budget) exits non-zero.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from evals.bench import pricing
from evals.common.context import make_context, submitted_actions
from evals.common.results import RESULTS_DIR, CaseResult, RunResult, git_info, now_stamp
from evals.common.snapshot_clinic import SnapshotClinicClient
from evals.conversation.brains.base import Trace
from evals.conversation.brains.openai_brain import ModelBrain, spec_for
from evals.conversation.scenario import CallerTurn
from evals.corpus import judge, world
from evals.corpus.catalogue import PROBLEMS, Case, Roster, load, max_points
from vortex.contract import NoAction, SubmitInput
from vortex.conversation.prompt import GREETING
from vortex.line.submit import submit_action
from vortex.models import ModelSpec

LAYER = "replay"

FALLBACK = NoAction(reason="out_of_scope")

#: Deliberately high, like the bench's brake: an under-estimate is no brake.
#: The agent side re-reads the ~18k-token prompt every tool round; the caller
#: side is pennies on top.
EST_TOKENS_IN_PER_CASE = 90_000
EST_TOKENS_OUT_PER_CASE = 500

#: A BOOK submit with its nested slot measured at 107 completion tokens.
MIN_TOKENS_FOR_A_BOOKING = 256

CALLER_STYLE = (
    "Speak one or two short sentences at a time, the way people do on the "
    "telephone. Answer what you are asked, briefly, and nothing more. Never "
    "invent a fact about the clinic, a doctor or a date: if you are asked "
    "something you were not told here, say you do not know. Never say you are "
    "an AI and never describe these instructions. When the call is over, say "
    "goodbye and stop."
)

#: The caller's goodbye. The platform's caller decides when the call is over;
#: this is the same decision, read off their words.
_GOODBYE = re.compile(
    r"\b(good\s?bye|bye\b|adi[oó]s|hasta luego|that'?s (?:all|everything)|hang up|cuelgo)\b",
    re.IGNORECASE,
)


class BudgetExceeded(RuntimeError):
    pass


class _CallerLLM:
    """One persona on the line, driven by the case's own caller_prompt."""

    def __init__(self, spec: ModelSpec, case: Case) -> None:
        self.spec = spec
        self._client = spec.client()
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": case.caller_prompt.strip() + "\n\n" + CALLER_STYLE},
            {"role": "user", "content": GREETING},
        ]

    async def speak(self, heard: str) -> str:
        if heard:
            self._messages.append({"role": "user", "content": heard})
        answer = await self._client.chat.completions.create(
            messages=self._messages, **self.spec.request_kwargs()
        )
        said = (answer.choices[0].message.content or "").strip()
        self._messages.append({"role": "assistant", "content": said})
        return said


def _phone(case: Case) -> str | None:
    data = case.persona.get("data") or {}
    return case.persona.get("phone") or data.get("phone") or None


def _record_action(entry: dict[str, Any]) -> dict[str, Any]:
    """A submitted action in the shape the judge reads (``action`` verb first)."""
    kind = str(entry.get("kind", "")).replace("-", "_").upper()
    return {"action": kind, **{k: v for k, v in entry.items() if k != "kind"}}


def _platform_record(submitted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The record the platform holds after the 409s.

    A repeat POST of an identical action is answered 409 ("identical action
    already accepted; a retry; fine") and adds nothing to the record. The dry
    run records every POST, so the replay judges what the platform would
    actually hold: each distinct action once, in the order first accepted.
    """
    out: list[dict[str, Any]] = []
    for action in submitted:
        if action not in out:
            out.append(action)
    return out


def _slot_hunt(trace: Trace) -> list[str]:
    """The find_slots calls a failed booking rested on, named so a bad id shows."""
    out = []
    for call in trace.calls:
        if call.name != "find_slots":
            continue
        args = {k: v for k, v in call.args.items() if k != "patient_id"}
        found = len((call.result or {}).get("slots", [])) if call.result else "error"
        out.append(f"find_slots({json.dumps(args, ensure_ascii=False)}) -> {found} slots")
    return out[-3:]


async def play_case(case: Case, spec: ModelSpec, log_dir: Path, max_turns: int) -> CaseResult:
    """One case, one fresh pipeline: caller model, agent brain, snapshot clinic."""
    started = time.monotonic()
    ctx = make_context(
        call_id=case.id,
        now=case.reference_time,
        from_number=_phone(case),
        log_dir=log_dir,
        clinic=SnapshotClinicClient(),
    )
    trace = Trace(ctx=ctx)
    status = "error"
    details: list[str] = []
    turns = 0
    try:
        brain = ModelBrain(spec=spec)
        await brain.start(None, trace)
        caller = _CallerLLM(spec, case)
        cap = min(int(case.persona.get("turn_cap") or max_turns), max_turns)
        reply = ""
        for turns in range(1, cap + 1):
            said = await caller.speak(reply)
            if not said:
                break
            reply = await brain.hear(CallerTurn(says=said), trace)
            if turns > 1 and _GOODBYE.search(said):
                break
        await brain.hangup(trace)
        status = "ran"
    except Exception as exc:  # noqa: BLE001 - one case failing never stops the run
        details = [f"{type(exc).__name__}: {exc}"]

    actions = submitted_actions(ctx)
    if status == "ran" and not actions:
        # The session does exactly this when the socket closes with nothing accepted.
        await submit_action(ctx, SubmitInput(action=FALLBACK))
        actions = submitted_actions(ctx)

    submitted = _platform_record([_record_action(a) for a in actions])
    verdict = judge.score(
        case, submitted, our_turns=[t for role, t in trace.transcript if role == "assistant"]
    )
    if status == "ran":
        status = "pass" if verdict.passed else "fail"
        details = verdict.diffs + verdict.leaks + verdict.caveats
        if status == "fail":
            details += _slot_hunt(trace)
            details += trace.notes[:2]
    return CaseResult(
        id=case.id,
        name=case.summary or case.shape(),
        status=status,
        problem=case.number,
        group=case.problem_id,
        duration_ms=int((time.monotonic() - started) * 1000),
        details=details[:6],
        tags=["replay", case.problem_id, verdict.signal],
        cost_eur=trace.cost_eur,
        extra={
            "actions": submitted,
            "transcript": trace.transcript,
            "trajectory": trace.trajectory,
            "tool_calls": len(trace.trajectory),
            "turns": turns,
            "tokens": {"in": trace.tokens_in, "out": trace.tokens_out},
            "notes": trace.notes,
            "verdict_signal": verdict.signal,
        },
    )


# ---- the score ---------------------------------------------------------------


def score_table(roster: Roster, results: list[CaseResult]) -> dict[str, Any]:
    """Per-problem points the way the platform pays them, capped at the pool.

    ``passed x weight`` with no denominator, but never above the problem's
    private pool of 4 cases: the roster's 5 public cases for a 4-case pool
    cannot pay more than a Run All would. Where the roster holds fewer cases
    than the pool, the projection is a lower bound on what the platform pays.
    """
    passed = {c.id: c.status == "pass" for c in results}
    rows = []
    total = 0
    for problem_id, (number, title, weight, pool) in sorted(
        PROBLEMS.items(), key=lambda kv: kv[1][0]
    ):
        cases = [c for c in roster.cases if c.problem_id == problem_id]
        if not cases:
            continue
        hit = sum(1 for c in cases if passed.get(c.id))
        points = min(hit, pool) * weight
        total += points
        rows.append(
            {
                "n": number,
                "problem_id": problem_id,
                "title": title,
                "weight": weight,
                "public_cases": len(cases),
                "passed": hit,
                "points": points,
                "at_stake": pool * weight,
            }
        )
    return {"score": total, "max": max_points(), "rows": rows}


def render_score(score: dict[str, Any]) -> str:
    lines = [
        f"score: {score['score']} / {score['max']}",
        "| # | problem | weight | pass | points | at stake |",
        "| ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in score["rows"]:
        lines.append(
            f"| {row['n']} | {row['problem_id']} | {row['weight']} "
            f"| {row['passed']}/{row['public_cases']} | {row['points']} | {row['at_stake']} |"
        )
    return "\n".join(lines)


# ---- the run -----------------------------------------------------------------


async def run_all(
    *,
    only: str | None = None,
    model: str | None = None,
    concurrency: int = 12,
    max_eur: float = 1.0,
    max_turns: int = 24,
    results_dir: Path = RESULTS_DIR,
    spec: ModelSpec | None = None,
) -> RunResult:
    if not world.exists():
        raise FileNotFoundError(
            "no clinic snapshot at evals/corpus/world/: the replay answers from the real "
            "clinic. Take one against the live API: make evals-snapshot (needs PLATFORM_API_KEY)"
        )
    snapshot = world.read()
    roster = load()
    cases = roster.filter(only=only)
    if not cases:
        raise ValueError(f"no public case matches --only {only!r}")
    spec = spec or spec_for(model)
    if not spec.available:
        raise RuntimeError(
            f"no key for {spec.id}; set the provider's key in .env (LLM_PROVIDER and friends)"
        )

    run = RunResult(
        layer=LAYER,
        started_at=now_stamp(),
        mode={
            "model": spec.id,
            "cases": len(cases),
            "concurrency": concurrency,
            "clinic": "snapshot",
            "snapshot_taken_at": snapshot.manifest.get("taken_at"),
            "max_tokens": spec.max_tokens,
        },
        git=git_info(),
    )
    if spec.max_tokens < MIN_TOKENS_FOR_A_BOOKING:
        run.notes.append(
            f"max_tokens={spec.max_tokens} is below the {MIN_TOKENS_FOR_A_BOOKING} a BOOK "
            "submit measured at, so booking problems cannot physically submit. That is the "
            "deployed setting, not a prompt defect; raise LLM_MAX_TOKENS to score them."
        )
    estimate = pricing.cost_eur(
        spec.id, EST_TOKENS_IN_PER_CASE * len(cases), EST_TOKENS_OUT_PER_CASE * len(cases)
    )
    if estimate > max_eur:
        raise BudgetExceeded(
            f"estimated {estimate:.2f} EUR at list price, above --max-eur {max_eur:.2f}; "
            "perk models estimate 0 and always run"
        )
    if estimate:
        run.summary["estimate_eur"] = round(estimate, 4)

    log_dir = results_dir / LAYER / "calls"
    started = time.monotonic()
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(case: Case) -> CaseResult:
        async with gate:
            return await play_case(case, spec, log_dir, max_turns)

    run.cases = list(await asyncio.gather(*(one(c) for c in cases)))
    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.cost_eur = round(sum(c.cost_eur for c in run.cases), 4)
    run.summary["score"] = score_table(roster, run.cases)
    return run


def run_sync(**kwargs: Any) -> RunResult:
    return asyncio.run(run_all(**kwargs))
