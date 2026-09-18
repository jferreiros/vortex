"""Layer 5: the same scenarios, every candidate model, one matrix.

    python -m evals bench                         # every default model with a key
    python -m evals bench --models helmcode/qwen3.6,helmcode/deepseek-v4-flash
    python -m evals bench --repeat 3              # pass^3 per scenario
    python -m evals bench --only p4.              # one problem
    python -m evals bench --max-eur 2.00          # the brake for paid models

Every candidate in ``models.yaml`` plays the layer-2 scenarios through the
model brain: the lane's real system prompt, the lane's exposed tools, the
runtime's request settings (``vortex.models``). Scoring is the layer-2 scoring,
by final state. What the bench adds is the comparison:

- pass rate and problem-weighted pass rate per model, per problem, per group
- LLM round trip p50/p95 (request to full reply; not TTFT, the runtime streams)
- tokens and cost per scenario, list-price €/call from the call profile
- how often a model hung up with nothing submitted, how often the token cap
  cut its reply
- a routing recommendation per role, with the reason, beside the routing the
  environment currently sets

The result is one ``RunResult`` (layer ``bench``): a case per model and
scenario, ``summary.models`` with the per-model roll-up, ``summary.routing``
with current and recommended, ``summary.scenarios`` with the roster the
matrix was drawn on. ``python -m evals publish`` pushes it to the
``bench-results`` branch; ``docs/bench.html`` reads it from there.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.bench import pricing
from evals.common.results import RESULTS_DIR, CaseResult, RunResult, git_info, now_stamp
from evals.conversation.runner import play
from evals.conversation.scenario import SCENARIOS_DIR, Scenario, load_scenarios
from evals.corpus.catalogue import PROBLEMS
from vortex.models import ROLE_ARBITER, ROLE_RECEPTIONIST, ModelSpec, resolve, routing_table

LAYER = "bench"

#: A receptionist that answers slower than this at p95 loses the caller. The
#: runtime streams and speaks the first sentence early, so the full round trip
#: can exceed what the caller perceives; the cap is deliberately loose.
RECEPTIONIST_P95_CAP_MS = 4000

#: Tokens one scenario costs, for the brake. Measured on 2026-09-19: the
#: system prompt plus tools is ~18k tokens per round and a scenario takes
#: five to eight rounds. Deliberately high: a brake that under-estimates is
#: not a brake.
EST_TOKENS_IN_PER_SCENARIO = 90_000
EST_TOKENS_OUT_PER_SCENARIO = 500

#: problem number -> weight, from the organisers' roster.
PROBLEM_WEIGHT: dict[int, int] = {number: weight for number, _, weight, _ in PROBLEMS.values()}


@dataclass
class Candidate:
    id: str
    label: str
    spec: ModelSpec
    default: bool = True
    paid: bool = False
    billing: str = ""
    notes: str = ""

    @property
    def skip_reason(self) -> str:
        if not self.spec.available:
            return f"no key for provider {self.spec.provider}"
        return ""


def load_candidates(
    models: list[str] | None = None, *, include_paid: bool = False
) -> list[Candidate]:
    """The models this run compares, in catalogue order.

    Explicit ``models`` win: an id outside the catalogue still runs, with the
    id as its label and no price. Without them, the catalogue's defaults,
    minus the paid ones unless asked.
    """
    rows = {row["id"]: row for row in pricing.entries()}
    ids = [m.strip() for m in models if m.strip()] if models else None
    if ids is None:
        ids = [
            rid
            for rid, row in rows.items()
            if row.get("default") and (include_paid or not row.get("paid"))
        ]
    out: list[Candidate] = []
    for rid in ids:
        row = rows.get(rid, {})
        out.append(
            Candidate(
                id=rid,
                label=str(row.get("label") or rid),
                spec=resolve(rid),
                default=bool(row.get("default", False)),
                paid=bool(row.get("paid", False)),
                billing=str(row.get("billing") or ""),
                notes=str(row.get("notes") or ""),
            )
        )
    return out


def estimate_eur(candidates: list[Candidate], scenarios: int, repeat: int) -> dict[str, float]:
    """What the run would cost at list price, per model. Perks and unknown prices are 0."""
    per_run = max(1, scenarios) * max(1, repeat)
    return {
        c.id: pricing.cost_eur(
            c.id, EST_TOKENS_IN_PER_SCENARIO * per_run, EST_TOKENS_OUT_PER_SCENARIO * per_run
        )
        for c in candidates
        if not c.skip_reason
    }


# ---- one model ----------------------------------------------------------------


async def run_model(
    cand: Candidate,
    scenarios: list[Scenario],
    *,
    repeat: int,
    concurrency: int,
    log_dir: Path,
    record: bool = False,
) -> list[CaseResult]:
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(scenario: Scenario) -> CaseResult:
        async with gate:
            result = await play(
                scenario, "model", log_dir / cand.spec.slug, repeat, spec=cand.spec, record=record
            )
        result.id = f"{cand.id}::{scenario.id}"
        result.group = cand.id
        result.tags = [scenario.group, *scenario.tags]
        result.extra["scenario"] = scenario.id
        result.extra["scenario_group"] = scenario.group
        return result

    return list(await asyncio.gather(*(one(s) for s in scenarios)))


def _pct(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return float(statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1])


def aggregate(
    cand: Candidate, cases: list[CaseResult], scenarios: list[Scenario]
) -> dict[str, Any]:
    """The per-model roll-up the matrix, the page and Discord read."""
    by_problem: dict[str, dict[str, int]] = {}
    by_group: dict[str, dict[str, int]] = {}
    weighted_hit = weighted_total = 0
    latencies: list[int] = []
    tokens_in = tokens_out = rounds = 0
    fallbacks = cut = 0
    for case in cases:
        passed = case.status == "pass"
        problem = case.problem or 0
        weight = PROBLEM_WEIGHT.get(problem, 1)
        weighted_total += weight
        weighted_hit += weight if passed else 0
        row = by_problem.setdefault(str(problem), {"pass": 0, "total": 0, "weight": weight})
        row["total"] += 1
        row["pass"] += int(passed)
        grow = by_group.setdefault(case.extra.get("scenario_group", "-"), {"pass": 0, "total": 0})
        grow["total"] += 1
        grow["pass"] += int(passed)
        ms = [int(x) for x in case.extra.get("llm_ms", [])]
        latencies.extend(ms)
        rounds += len(ms)
        tokens = case.extra.get("tokens") or {}
        tokens_in += int(tokens.get("in", 0))
        tokens_out += int(tokens.get("out", 0))
        fallbacks += int(bool(case.extra.get("fallback_used")))
        cut += sum(1 for n in case.extra.get("notes", []) if str(n).startswith("reply cut"))
    n = len(cases)
    passes = sum(1 for c in cases if c.status == "pass")
    unweighted = passes / n if n else 0.0
    return {
        "id": cand.id,
        "label": cand.label,
        "provider": cand.spec.provider,
        "model": cand.spec.model,
        "billing": cand.billing,
        "paid": cand.paid,
        "notes": cand.notes,
        "status": "ran",
        "scenarios": n,
        "pass": passes,
        "fail": sum(1 for c in cases if c.status == "fail"),
        "error": sum(1 for c in cases if c.status == "error"),
        "unverified": sum(1 for c in cases if c.status == "unverified"),
        "pass_rate": round(unweighted, 4),
        "weighted_pass_rate": round(
            weighted_hit / weighted_total if weighted_total else unweighted, 4
        ),
        "by_problem": dict(sorted(by_problem.items(), key=lambda kv: int(kv[0]))),
        "by_group": by_group,
        "llm_p50_ms": round(_pct(latencies, 0.50)),
        "llm_p95_ms": round(_pct(latencies, 0.95)),
        "llm_rounds": rounds,
        "llm_rounds_per_scenario": round(rounds / n, 1) if n else 0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_in_per_scenario": round(tokens_in / n) if n else 0,
        "cost_eur": round(sum(c.cost_eur for c in cases), 4),
        "list_cost_per_call_eur": pricing.list_cost_per_call_eur(cand.id),
        "perk": pricing.is_perk(cand.id),
        "fallback_rate": round(fallbacks / n, 4) if n else 0.0,
        "cut_by_max_tokens": cut,
        "duration_ms": sum(c.duration_ms for c in cases),
    }


def skipped_block(cand: Candidate, reason: str) -> dict[str, Any]:
    return {
        "id": cand.id,
        "label": cand.label,
        "provider": cand.spec.provider,
        "model": cand.spec.model,
        "billing": cand.billing,
        "paid": cand.paid,
        "notes": cand.notes,
        "status": "skipped",
        "skip_reason": reason,
        "scenarios": 0,
        "pass": 0,
        "pass_rate": 0.0,
        "weighted_pass_rate": 0.0,
        "list_cost_per_call_eur": pricing.list_cost_per_call_eur(cand.id),
        "perk": pricing.is_perk(cand.id),
    }


# ---- the recommendation -----------------------------------------------------------


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def recommend(models: list[dict[str, Any]], current: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Which model each role should run, by a stated policy.

    receptionist: highest weighted pass rate among models whose LLM p95 stays
    under ``RECEPTIONIST_P95_CAP_MS``; ties go to the lower p50, then the lower
    list price. If nothing meets the cap, the cap is dropped and the reason
    says so.

    arbiter: highest weighted pass rate, full stop; ties go to the lower list
    price, then the lower p50. It runs after the hangup, so latency is free.

    A recommendation is a number the team can argue with, not an order: the
    routing itself stays in ``.env``.
    """
    ran = [m for m in models if m.get("status") == "ran" and m.get("scenarios")]
    out: dict[str, Any] = {"current": {}, "recommended": {}, "policy": {}}
    for role, block in current.items():
        out["current"][role] = block.get("id", "")
    if not ran:
        out["policy"]["note"] = "no model ran; nothing to recommend"
        return out

    def price(m: dict[str, Any]) -> float:
        value = m.get("list_cost_per_call_eur")
        return float(value) if value is not None else 9e9

    # receptionist
    fast = [m for m in ran if m.get("llm_p95_ms", 0) <= RECEPTIONIST_P95_CAP_MS]
    pool, capped = (fast, True) if fast else (ran, False)
    best = sorted(pool, key=lambda m: (-m["weighted_pass_rate"], m.get("llm_p50_ms", 0), price(m)))
    top = best[0]
    reason = (
        f"weighted pass {top['weighted_pass_rate'] * 100:.0f}% "
        f"({top['pass']}/{top['scenarios']}), p50 {_fmt_ms(top.get('llm_p50_ms', 0))}, "
        f"p95 {_fmt_ms(top.get('llm_p95_ms', 0))}"
    )
    reason += (
        f" under the {RECEPTIONIST_P95_CAP_MS / 1000:.0f} s cap"
        if capped
        else f"; no model met the {RECEPTIONIST_P95_CAP_MS / 1000:.0f} s p95 cap, so it was dropped"
    )
    out["recommended"][ROLE_RECEPTIONIST] = {
        "id": top["id"],
        "reason": reason,
        "runner_up": best[1]["id"] if len(best) > 1 else "",
    }
    # arbiter
    best_a = sorted(ran, key=lambda m: (-m["weighted_pass_rate"], price(m), m.get("llm_p50_ms", 0)))
    top_a = best_a[0]
    out["recommended"][ROLE_ARBITER] = {
        "id": top_a["id"],
        "reason": (
            f"highest weighted pass {top_a['weighted_pass_rate'] * 100:.0f}% "
            f"({top_a['pass']}/{top_a['scenarios']}); latency does not count after the hangup"
        ),
        "runner_up": best_a[1]["id"] if len(best_a) > 1 else "",
    }
    out["policy"] = {
        "receptionist": (
            f"max weighted pass rate with LLM p95 <= {RECEPTIONIST_P95_CAP_MS} ms; "
            "ties: lower p50, then lower list price"
        ),
        "arbiter": "max weighted pass rate; ties: lower list price, then lower p50",
    }
    out["changes"] = {
        role: rec["id"] != out["current"].get(role, "") for role, rec in out["recommended"].items()
    }
    return out


# ---- the run ---------------------------------------------------------------------


class BudgetExceeded(RuntimeError):
    pass


async def run_all(
    *,
    models: list[str] | None = None,
    only: str | None = None,
    repeat: int = 1,
    max_eur: float = 1.0,
    concurrency: int = 3,
    include_paid: bool = False,
    record: bool = False,
    results_dir: Path = RESULTS_DIR,
    scenarios_dir: Path = SCENARIOS_DIR,
) -> RunResult:
    candidates = load_candidates(models, include_paid=include_paid)
    scenarios = load_scenarios(scenarios_dir, only=only)
    run = RunResult(
        layer=LAYER,
        started_at=now_stamp(),
        mode={
            "models": [c.id for c in candidates],
            "repeat": repeat,
            "concurrency": concurrency,
            "clinic": "fake",
            "scenarios": len(scenarios),
            "only": only or "",
        },
        git=git_info(),
    )
    estimate = estimate_eur(candidates, len(scenarios), repeat)
    total_estimate = sum(estimate.values())
    if total_estimate > max_eur:
        raise BudgetExceeded(
            f"estimated {total_estimate:.2f} € at list price, above --max-eur {max_eur:.2f}: "
            + ", ".join(f"{k} {v:.2f} €" for k, v in estimate.items() if v)
        )
    run.summary["estimate_eur"] = round(total_estimate, 4)

    log_dir = results_dir / LAYER / "calls"
    started = time.monotonic()
    runnable = [c for c in candidates if not c.skip_reason]
    blocks: list[dict[str, Any]] = []
    for cand in candidates:
        if cand.skip_reason:
            run.notes.append(f"{cand.id}: skipped, {cand.skip_reason}")
            run.cases.append(
                CaseResult(
                    id=f"{cand.id}::*",
                    name=cand.label,
                    status="skipped",
                    group=cand.id,
                    details=[cand.skip_reason],
                )
            )
            blocks.append(skipped_block(cand, cand.skip_reason))
    results = await asyncio.gather(
        *(
            run_model(
                c, scenarios, repeat=repeat, concurrency=concurrency, log_dir=log_dir, record=record
            )
            for c in runnable
        )
    )
    for cand, cases in zip(runnable, results, strict=True):
        run.cases.extend(cases)
        blocks.append(aggregate(cand, cases, scenarios))
    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.cost_eur = round(sum(c.cost_eur for c in run.cases), 4)

    order = {c.id: i for i, c in enumerate(candidates)}
    blocks.sort(
        key=lambda b: (b.get("status") != "ran", -b.get("weighted_pass_rate", 0), order[b["id"]])
    )
    run.summary["models"] = blocks
    run.summary["scenarios"] = [
        {
            "id": s.id,
            "problem": s.problem,
            "group": s.group,
            "weight": PROBLEM_WEIGHT.get(s.problem or 0, 1),
        }
        for s in scenarios
    ]
    run.summary["routing"] = recommend(blocks, routing_table())
    run.summary["receptionist_p95_cap_ms"] = RECEPTIONIST_P95_CAP_MS
    run.summary["latency_note"] = (
        "LLM latency is the full round trip per model call (request to complete reply), "
        "not time to first token. The runtime streams, so the caller hears the first "
        "sentence earlier than this."
    )
    if not runnable:
        run.notes.append(
            "No candidate had a key. Set HELMCODE_API_KEY (or another provider's key)."
        )
    ran = [b for b in blocks if b.get("status") == "ran"]
    if ran:
        top = ran[0]
        run.notes.append(
            f"Best by weighted pass rate: {top['id']} at {top['weighted_pass_rate'] * 100:.0f}% "
            f"({top['pass']}/{top['scenarios']}), p50 {_fmt_ms(top.get('llm_p50_ms', 0))}."
        )
    return run


def run_sync(**kwargs: Any) -> RunResult:
    return asyncio.run(run_all(**kwargs))
