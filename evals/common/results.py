"""Results: one record per case, one file per run, and the diff between runs.

Layout under ``evals/results/``::

    <layer>/latest.json            the last run of that layer
    <layer>/history/<ts>.json      every run, for the trend
    summary.md                     the cross-layer summary (CI reads this)
    report.html                    the same, for a screen

``evals/baselines/<layer>.json`` is the accepted reference. ``python -m evals
accept`` copies the latest run there. A run is compared with both the previous
run and the baseline.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = EVALS_DIR.parent
RESULTS_DIR = EVALS_DIR / "results"
BASELINES_DIR = EVALS_DIR / "baselines"

STATUSES = ("pass", "fail", "error", "unverified", "skipped")


@dataclass
class CaseResult:
    id: str
    name: str
    status: str  # one of STATUSES
    problem: int | None = None
    group: str = ""
    hollow: bool = False  # passed, but every tool it touched is still a stub
    duration_ms: int = 0
    details: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cost_eur: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass
class RunResult:
    layer: str
    started_at: str
    duration_ms: int = 0
    mode: dict[str, Any] = field(default_factory=dict)
    git: dict[str, str] = field(default_factory=dict)
    cases: list[CaseResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cost_eur: float = 0.0
    # Layer-specific roll-ups (the voice layer keeps its per-stack table here).
    summary: dict[str, Any] = field(default_factory=dict)

    # ---- totals -----------------------------------------------------------
    def count(self, status: str) -> int:
        return sum(1 for c in self.cases if c.status == status)

    @property
    def hollow(self) -> int:
        return sum(1 for c in self.cases if c.status == "pass" and c.hollow)

    @property
    def solid_passes(self) -> int:
        return sum(1 for c in self.cases if c.status == "pass" and not c.hollow)

    @property
    def verdict(self) -> str:
        if self.count("fail") or self.count("error"):
            return "FAIL"
        if not self.cases:
            return "EMPTY"
        if self.count("unverified") == len(self.cases):
            return "UNVERIFIED"
        return "PASS"

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["totals"] = {s: self.count(s) for s in STATUSES}
        data["totals"]["hollow"] = self.hollow
        data["verdict"] = self.verdict
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RunResult:
        cases = [CaseResult(**c) for c in data.get("cases", [])]
        return cls(
            layer=data["layer"],
            started_at=data["started_at"],
            duration_ms=data.get("duration_ms", 0),
            mode=data.get("mode", {}),
            git=data.get("git", {}),
            cases=cases,
            notes=data.get("notes", []),
            cost_eur=data.get("cost_eur", 0.0),
            summary=data.get("summary", {}),
        )


def git_info() -> dict[str, str]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (subprocess.CalledProcessError, OSError):
            return ""

    return {
        "sha": run("rev-parse", "--short", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": "yes" if run("status", "--porcelain") else "no",
    }


def now_stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def save_run(run: RunResult, results_dir: Path = RESULTS_DIR) -> Path:
    layer_dir = results_dir / run.layer
    (layer_dir / "history").mkdir(parents=True, exist_ok=True)
    data = run.to_json()
    stamp = run.started_at.replace(":", "").replace("+00:00", "Z")
    (layer_dir / "history" / f"{stamp}.json").write_text(json.dumps(data, indent=1))
    latest = layer_dir / "latest.json"
    if latest.exists():
        latest.replace(layer_dir / "previous.json")
    latest.write_text(json.dumps(data, indent=1))
    return latest


def load_run(path: Path) -> RunResult | None:
    if not path.exists():
        return None
    try:
        return RunResult.from_json(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def load_previous(layer: str, results_dir: Path = RESULTS_DIR) -> RunResult | None:
    return load_run(results_dir / layer / "previous.json")


def load_latest(layer: str, results_dir: Path = RESULTS_DIR) -> RunResult | None:
    return load_run(results_dir / layer / "latest.json")


def load_baseline(layer: str, baselines_dir: Path = BASELINES_DIR) -> RunResult | None:
    return load_run(baselines_dir / f"{layer}.json")


def accept_baseline(layer: str, results_dir: Path = RESULTS_DIR) -> Path | None:
    latest = results_dir / layer / "latest.json"
    if not latest.exists():
        return None
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    target = BASELINES_DIR / f"{layer}.json"
    # The baseline is for diffing statuses. Drop the bulky per-case payloads.
    data = json.loads(latest.read_text())
    for case in data.get("cases", []):
        case.pop("extra", None)
        case["details"] = case.get("details", [])[:3]
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return target


@dataclass
class Diff:
    against: str  # "previous" or "baseline"
    reference_at: str = ""
    fixed: list[str] = field(default_factory=list)  # was not pass, now pass
    broke: list[str] = field(default_factory=list)  # was pass, now not pass
    new: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    changed: list[tuple[str, str, str]] = field(default_factory=list)  # id, before, after

    @property
    def empty(self) -> bool:
        return not (self.fixed or self.broke or self.new or self.gone or self.changed)


def diff_runs(current: RunResult, reference: RunResult | None, against: str) -> Diff:
    diff = Diff(against=against)
    if reference is None:
        return diff
    diff.reference_at = reference.started_at
    before = {c.id: c for c in reference.cases}
    after = {c.id: c for c in current.cases}
    for cid, case in after.items():
        prev = before.get(cid)
        if prev is None:
            diff.new.append(cid)
            continue
        if prev.status != case.status or prev.hollow != case.hollow:
            b = prev.status + (" (hollow)" if prev.hollow and prev.status == "pass" else "")
            a = case.status + (" (hollow)" if case.hollow and case.status == "pass" else "")
            diff.changed.append((cid, b, a))
            if case.status == "pass" and prev.status != "pass":
                diff.fixed.append(cid)
            elif prev.status == "pass" and case.status != "pass":
                diff.broke.append(cid)
    for cid in before:
        if cid not in after:
            diff.gone.append(cid)
    return diff
