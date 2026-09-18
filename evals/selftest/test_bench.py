"""The bench tests itself: the catalogue, the roll-up, the policy, the publish tree.

    uv run pytest evals/selftest/test_bench.py -q

No network, no key, no model. These make sure a recommendation follows the
stated policy and a published index says what the run said.
"""

from __future__ import annotations

import json

import pytest

from evals.bench import pricing
from evals.bench.publish import README, build_files, index_entry
from evals.bench.runner import (
    RECEPTIONIST_P95_CAP_MS,
    Candidate,
    aggregate,
    estimate_eur,
    load_candidates,
    recommend,
)
from evals.common.results import CaseResult, RunResult
from evals.conversation.scenario import Scenario
from vortex.models import ModelSpec

# ---- catalogue --------------------------------------------------------------


def test_catalogue_ids_are_provider_slash_model() -> None:
    rows = pricing.entries()
    assert rows, "models.yaml lists no models"
    for row in rows:
        assert "/" in row["id"], row["id"]
        provider = row["id"].split("/", 1)[0]
        assert provider in ("helmcode", "vercel", "cloudflare", "custom", "openai"), row["id"]
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids in models.yaml"


def test_default_candidates_exclude_paid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    defaults = {c.id for c in load_candidates()}
    with_paid = {c.id for c in load_candidates(include_paid=True)}
    assert defaults <= with_paid
    paid = {r["id"] for r in pricing.entries() if r.get("paid")}
    assert not defaults & paid
    assert "helmcode/qwen3.6" in defaults


def test_explicit_model_outside_the_catalogue_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELMCODE_API_KEY", "k")
    from vortex.settings import reset_settings

    reset_settings()
    try:
        [cand] = load_candidates(["helmcode/some-new-model"])
    finally:
        reset_settings()
    assert cand.label == "helmcode/some-new-model"
    assert cand.spec.model == "some-new-model"
    assert pricing.price_usd(cand.id) is None


# ---- prices -------------------------------------------------------------------


def test_perk_costs_nothing_and_unknown_costs_nothing() -> None:
    assert pricing.cost_eur("helmcode/qwen3.6", 1_000_000, 1_000_000) == 0.0
    assert pricing.cost_eur("helmcode/model-nobody-listed", 1_000_000, 1_000_000) == 0.0


def test_known_price_converts_to_euros() -> None:
    # gpt-4.1-mini: 0.40 / 1.60 USD per 1M, 0.92 EUR per USD.
    eur = pricing.cost_eur("openai/gpt-4.1-mini", 1_000_000, 1_000_000)
    assert eur == pytest.approx((0.40 + 1.60) * 0.92)
    per_call = pricing.list_cost_per_call_eur("openai/gpt-4.1-mini")
    assert per_call is not None and 0.001 < per_call < 0.02


def test_brake_counts_only_priced_runnable_models() -> None:
    spec = ModelSpec("openai", "gpt-4.1-mini", "", "key")
    free = ModelSpec("helmcode", "qwen3.6", "https://x", "key")
    nokey = ModelSpec("vercel", "anthropic/claude-haiku-4.5", "https://x", "")
    est = estimate_eur(
        [
            Candidate("openai/gpt-4.1-mini", "ref", spec),
            Candidate("helmcode/qwen3.6", "free", free, billing="perk"),
            Candidate("vercel/anthropic/claude-haiku-4.5", "nokey", nokey),
        ],
        scenarios=10,
        repeat=2,
    )
    assert est["openai/gpt-4.1-mini"] > 0
    assert est["helmcode/qwen3.6"] == 0
    assert "vercel/anthropic/claude-haiku-4.5" not in est


# ---- the roll-up ----------------------------------------------------------------


def _case(
    scenario: str, status: str, problem: int, *, ms: list[int], fallback: bool = False
) -> CaseResult:
    return CaseResult(
        id=f"m::{scenario}",
        name=scenario,
        status=status,
        problem=problem,
        group="m",
        extra={
            "scenario": scenario,
            "scenario_group": "booking" if problem < 10 else "difficult",
            "llm_ms": ms,
            "tokens": {"in": 1000 * len(ms), "out": 30 * len(ms)},
            "fallback_used": fallback,
            "notes": ["reply cut by max_tokens=120"] if status == "fail" else [],
        },
        cost_eur=0.0,
    )


def _scenario(sid: str, problem: int) -> Scenario:
    return Scenario(
        id=sid,
        group="g",
        problem=problem,
        now=None,
        from_number=None,
        caller=[],
        expect={},
        tags=[],
        file="x.yaml",
    )


def test_aggregate_weights_by_problem_and_counts_everything() -> None:
    cand = Candidate(
        "helmcode/qwen3.6", "q", ModelSpec("helmcode", "qwen3.6", "https://x", "k"), billing="perk"
    )
    cases = [
        _case("p1.a", "pass", 1, ms=[100, 200]),  # weight 1
        _case("p13.b", "fail", 13, ms=[300, 3000], fallback=True),  # weight 4
        _case("p6.c", "pass", 6, ms=[400]),  # weight 3
    ]
    block = aggregate(
        cand, cases, [_scenario("p1.a", 1), _scenario("p13.b", 13), _scenario("p6.c", 6)]
    )
    assert block["scenarios"] == 3 and block["pass"] == 2 and block["fail"] == 1
    assert block["pass_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert block["weighted_pass_rate"] == pytest.approx((1 + 3) / (1 + 4 + 3), abs=1e-3)
    assert block["by_problem"]["13"] == {"pass": 0, "total": 1, "weight": 4}
    assert block["by_group"]["booking"] == {"pass": 2, "total": 2}
    assert block["llm_rounds"] == 5
    assert block["llm_p50_ms"] == 300
    assert block["llm_p95_ms"] > 2000
    assert block["tokens_in"] == 5000 and block["tokens_in_per_scenario"] == 1667
    assert block["fallback_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert block["cut_by_max_tokens"] == 1
    assert block["perk"] is True and block["list_cost_per_call_eur"] is None


# ---- the policy ---------------------------------------------------------------------


def _block(mid: str, weighted: float, p50: int, p95: int, price: float | None = None) -> dict:
    return {
        "id": mid,
        "status": "ran",
        "scenarios": 10,
        "pass": round(weighted * 10),
        "pass_rate": weighted,
        "weighted_pass_rate": weighted,
        "llm_p50_ms": p50,
        "llm_p95_ms": p95,
        "list_cost_per_call_eur": price,
        "perk": price is None,
    }


CURRENT = {
    "receptionist": {"id": "helmcode/qwen3.6"},
    "arbiter": {"id": "helmcode/deepseek-v4-flash"},
}


def test_receptionist_needs_the_latency_cap_arbiter_does_not() -> None:
    models = [
        _block("slow-but-right", 0.95, 5000, 9000),
        _block("fast-enough", 0.80, 1500, RECEPTIONIST_P95_CAP_MS - 1),
        _block("helmcode/qwen3.6", 0.60, 1200, 2500),
    ]
    out = recommend(models, CURRENT)
    assert out["recommended"]["receptionist"]["id"] == "fast-enough"
    assert "under the" in out["recommended"]["receptionist"]["reason"]
    assert out["recommended"]["arbiter"]["id"] == "slow-but-right"
    assert out["changes"] == {"receptionist": True, "arbiter": True}
    assert out["current"]["receptionist"] == "helmcode/qwen3.6"


def test_cap_is_dropped_when_nobody_meets_it() -> None:
    models = [_block("a", 0.5, 6000, 9000), _block("b", 0.7, 7000, 9500)]
    out = recommend(models, CURRENT)
    assert out["recommended"]["receptionist"]["id"] == "b"
    assert "no model met" in out["recommended"]["receptionist"]["reason"]


def test_ties_go_to_lower_p50_then_lower_price() -> None:
    models = [
        _block("pricey-fast", 0.8, 1000, 2000, price=0.010),
        _block("cheap-fast", 0.8, 1000, 2000, price=0.001),
        _block("cheap-slower", 0.8, 1500, 2000, price=0.0005),
    ]
    out = recommend(models, CURRENT)
    assert out["recommended"]["receptionist"]["id"] == "cheap-fast"
    assert out["recommended"]["arbiter"]["id"] == "cheap-slower"


def test_keep_when_the_current_model_wins() -> None:
    models = [_block("helmcode/qwen3.6", 0.9, 1000, 2000), _block("other", 0.5, 900, 1800)]
    out = recommend(models, CURRENT)
    assert out["recommended"]["receptionist"]["id"] == "helmcode/qwen3.6"
    assert out["changes"]["receptionist"] is False


def test_nothing_ran_means_no_recommendation() -> None:
    out = recommend([{"id": "x", "status": "skipped"}], CURRENT)
    assert out["recommended"] == {}
    assert "note" in out["policy"]


# ---- publish ----------------------------------------------------------------------------


def _bench_run() -> RunResult:
    run = RunResult(
        layer="bench",
        started_at="2026-09-19T00:11:33+00:00",
        git={"sha": "abc1234", "branch": "feat/bench", "dirty": "no"},
        mode={"models": ["a", "b"], "repeat": 1, "scenarios": 2},
    )
    run.cases = [
        CaseResult(id="a::s1", name="s1", status="pass", group="a", problem=1),
        CaseResult(id="a::s2", name="s2", status="fail", group="a", problem=4),
    ]
    run.summary = {
        "models": [
            _block("a", 0.5, 1000, 2000),
            {"id": "b", "status": "skipped", "skip_reason": "no key"},
        ],
        "routing": {
            "current": {"receptionist": "a", "arbiter": "a"},
            "recommended": {"receptionist": {"id": "a", "reason": "r", "runner_up": ""}},
            "changes": {"receptionist": False},
            "policy": {},
        },
    }
    return run


def test_index_entry_keeps_the_headline_and_drops_the_bulk() -> None:
    entry = index_entry("bench", _bench_run(), "runs/bench/x.json")
    assert entry["verdict"] == "FAIL"
    assert entry["totals"]["pass"] == 1 and entry["totals"]["fail"] == 1
    assert [m["id"] for m in entry["models"]] == ["a", "b"]
    assert entry["models"][1]["skip_reason"] == "no key"
    assert entry["routing"]["current"]["receptionist"] == "a"
    assert "cases" not in entry
    assert entry["mode"] == {"repeat": 1, "scenarios": 2, "models": ["a", "b"]}


def test_build_files_appends_to_the_index_and_dedupes() -> None:
    run = _bench_run()
    existing = {
        "runs": [
            {
                "layer": "logic",
                "started_at": "2026-09-18T20:00:00+00:00",
                "path": "runs/logic/old.json",
            }
        ]
    }
    files = build_files({"bench": run}, existing)
    path = "runs/bench/20260919T001133Z-abc1234.json"
    assert set(files) == {path, "latest/bench.json", "index.json", "README.md"}
    assert files[path] == files["latest/bench.json"]
    assert files["README.md"] == README
    index = json.loads(files["index.json"])
    assert [e["path"] for e in index["runs"]] == [path, "runs/logic/old.json"]
    assert "bench" in index["layers"]
    # Publishing the same run twice does not duplicate the entry.
    again = json.loads(build_files({"bench": run}, index)["index.json"])
    assert [e["path"] for e in again["runs"]] == [path, "runs/logic/old.json"]
    # The full run is intact on the branch.
    assert json.loads(files[path])["cases"][0]["id"] == "a::s1"
