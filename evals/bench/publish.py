"""Persist runs: push the latest run of every layer to a results branch.

``evals/results/`` is git-ignored, so a run is gone when the runner is. This
puts each run on the ``bench-results`` branch of the same repository::

    runs/<layer>/<stamp>-<sha>.json   every run, full detail, forever
    latest/<layer>.json               the last run of each layer
    index.json                        one entry per run with the headline numbers
    README.md                         what the branch is

``docs/bench.html`` reads ``index.json`` and ``latest/bench.json`` from
raw.githubusercontent.com, so the GitHub Pages site shows every run without
a build step and without touching ``main``.

The commit is built with git plumbing (``hash-object``, ``update-index`` on a
temporary index, ``write-tree``, ``commit-tree``) and pushed as
``<commit>:refs/heads/<branch>``. The working tree and the current branch are
never touched, so this runs from a dirty checkout, a worktree or CI alike.
A non-fast-forward push (someone else published first) is retried from a
fresh fetch, so two publishers never lose each other's runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.common.report import LAYERS
from evals.common.results import REPO_ROOT, RESULTS_DIR, RunResult, load_latest

DEFAULT_BRANCH = "bench-results"
MAX_INDEX_RUNS = 1000

README = """# Vortex evals — results branch

Every run of `python -m evals` that someone published lands here, in full.
Nothing on this branch is edited by hand.

| Path | What |
| --- | --- |
| `runs/<layer>/<stamp>-<sha>.json` | one run, every case, every transcript |
| `latest/<layer>.json` | the last run of each layer |
| `index.json` | one entry per run: verdict, totals, per-model numbers, routing |

The page at https://jferreiros.github.io/vortex/bench.html reads `index.json`
and `latest/bench.json` from this branch. To add a run:

```bash
make bench            # or make evals, make evals-conversation BRAIN=model ...
make bench-publish    # == uv run python -m evals publish
```
"""


@dataclass
class Outcome:
    ok: bool
    lines: list[str] = field(default_factory=list)
    commit: str = ""
    files: list[str] = field(default_factory=list)


def _git(
    *args: str, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None, check: bool = True
) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def _stamp(iso: str) -> str:
    """``2026-09-19T00:11:33+00:00`` -> ``20260919T001133Z``: sortable, safe in a path."""
    return iso.replace("+00:00", "Z").replace(":", "").replace("-", "")


def index_entry(layer: str, run: RunResult, path: str) -> dict[str, Any]:
    """The headline of one run: what the page needs to draw a row or a point."""
    data = run.to_json()
    entry: dict[str, Any] = {
        "layer": layer,
        "started_at": run.started_at,
        "path": path,
        "sha": run.git.get("sha", ""),
        "branch": run.git.get("branch", ""),
        "dirty": run.git.get("dirty", ""),
        "verdict": run.verdict,
        "totals": data["totals"],
        "duration_ms": run.duration_ms,
        "cost_eur": run.cost_eur,
        "mode": {k: v for k, v in run.mode.items() if not isinstance(v, dict)},
        "notes": run.notes[:4],
    }
    if layer == "bench":
        keep = (
            "id",
            "label",
            "status",
            "skip_reason",
            "pass",
            "scenarios",
            "pass_rate",
            "weighted_pass_rate",
            "llm_p50_ms",
            "llm_p95_ms",
            "tokens_in_per_scenario",
            "cost_eur",
            "list_cost_per_call_eur",
            "perk",
            "paid",
            "fallback_rate",
            "cut_by_max_tokens",
            "by_problem",
            "by_group",
        )
        entry["models"] = [
            {k: m[k] for k in keep if k in m} for m in run.summary.get("models") or []
        ]
        routing = run.summary.get("routing") or {}
        entry["routing"] = {
            "current": routing.get("current") or {},
            "recommended": routing.get("recommended") or {},
            "changes": routing.get("changes") or {},
        }
    return entry


def build_files(
    runs: dict[str, RunResult], existing_index: dict[str, Any] | None
) -> dict[str, str]:
    """Path -> content for one publish. Pure: no git, no clock beyond ``updated_at``."""
    index = dict(existing_index or {})
    entries: list[dict[str, Any]] = list(index.get("runs") or [])
    files: dict[str, str] = {}
    for layer, run in runs.items():
        path = f"runs/{layer}/{_stamp(run.started_at)}-{run.git.get('sha') or 'nosha'}.json"
        payload = json.dumps(run.to_json(), indent=1, ensure_ascii=False) + "\n"
        files[path] = payload
        files[f"latest/{layer}.json"] = payload
        entries = [e for e in entries if e.get("path") != path]
        entries.append(index_entry(layer, run, path))
    entries.sort(key=lambda e: e.get("started_at", ""), reverse=True)
    index["runs"] = entries[:MAX_INDEX_RUNS]
    index["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    index["layers"] = list(LAYERS)
    index["repo"] = index.get("repo") or "jferreiros/vortex"
    files["index.json"] = json.dumps(index, indent=1, ensure_ascii=False) + "\n"
    files["README.md"] = README
    return files


def _read_index(ref: str) -> dict[str, Any] | None:
    if not ref:
        return None
    try:
        return json.loads(_git("show", f"{ref}:index.json"))
    except (RuntimeError, json.JSONDecodeError):
        return None


def _commit_files(files: dict[str, str], parent: str, message: str) -> str:
    """Build a commit with exactly ``parent``'s tree plus ``files``. Returns the sha."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if parent:
            _git("read-tree", parent, env=env)
        for path, content in files.items():
            proc = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=REPO_ROOT,
                input=content,
                text=True,
                capture_output=True,
                check=True,
            )
            blob = proc.stdout.strip()
            _git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = _git("write-tree", env=env)
    args = ["commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    return _git(*args)


def publish(
    *,
    results_dir: Path = RESULTS_DIR,
    branch: str = DEFAULT_BRANCH,
    remote: str = "origin",
    layers: list[str] | None = None,
    dry_run: bool = False,
    message: str | None = None,
    attempts: int = 3,
) -> Outcome:
    wanted = layers or list(LAYERS)
    runs = {layer: run for layer in wanted if (run := load_latest(layer, results_dir)) is not None}
    if not runs:
        return Outcome(False, [f"nothing to publish: no latest.json under {results_dir}"])
    out = Outcome(True)
    remote_ref = f"refs/remotes/{remote}/{branch}"
    for attempt in range(1, attempts + 1):
        try:
            _git("fetch", "--quiet", remote, f"+refs/heads/{branch}:{remote_ref}")
        except RuntimeError:
            pass  # first publish: the branch does not exist yet
        parent = _git("rev-parse", "--verify", "--quiet", remote_ref, check=False)
        files = build_files(runs, _read_index(parent))
        summary = ", ".join(f"{layer} {run.verdict}" for layer, run in runs.items())
        sha = next(iter(runs.values())).git.get("sha", "")
        msg = message or f"results: {summary} @ {sha}"
        commit = _commit_files(files, parent, msg)
        out.commit = commit
        out.files = sorted(files)
        if dry_run:
            out.lines.append(f"dry run: built {commit[:10]} on top of {parent[:10] or 'nothing'}")
            out.lines.extend(f"  {p}" for p in out.files)
            return out
        proc = subprocess.run(
            ["git", "push", "--quiet", remote, f"{commit}:refs/heads/{branch}"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            _git("update-ref", remote_ref, commit, check=False)
            out.lines.append(f"published {commit[:10]} to {remote}/{branch} ({summary})")
            for path in sorted(files):
                if path.startswith("runs/"):
                    out.lines.append(f"  https://github.com/jferreiros/vortex/blob/{branch}/{path}")
            out.lines.append("  page: https://jferreiros.github.io/vortex/bench.html")
            return out
        out.lines.append(f"push attempt {attempt} rejected: {proc.stderr.strip()[:200]}")
    out.ok = False
    out.lines.append("gave up: the branch moved under every attempt")
    return out
