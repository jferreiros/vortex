"""The token of a workflow that runs pull request code stays narrow.

`coderabbit` checks out the head of a pull request and runs the CodeRabbit CLI
on it, so it must not hold `issues: write`. Filing the findings belongs to
`coderabbit-issues`, which `workflow_run` runs from the default branch.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
REVIEW = WORKFLOWS / "coderabbit.yml"
FILER = WORKFLOWS / "coderabbit-issues.yml"
WIDE = "issues"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def granted(workflow: dict) -> list[dict]:
    jobs = workflow.get("jobs", {}).values()
    return [workflow.get("permissions") or {}, *[job.get("permissions") or {} for job in jobs]]


def triggers(workflow: dict) -> dict:
    """`on:` is the YAML 1.1 boolean, so safe_load keys it as True."""
    return workflow.get("on") or workflow[True]


def test_the_review_workflow_cannot_write_issues() -> None:
    for block in granted(load(REVIEW)):
        assert block.get(WIDE) != "write", f"{REVIEW.name} widens the token with `issues: write`"


def test_the_review_workflow_still_comments_on_the_pr() -> None:
    assert (load(REVIEW).get("permissions") or {}).get("pull-requests") == "write"


def test_the_filer_runs_on_the_review_finishing() -> None:
    fired_by = triggers(load(FILER))
    assert list(fired_by) == ["workflow_run"]
    assert fired_by["workflow_run"]["workflows"] == ["coderabbit"]


def test_the_filer_is_the_one_that_writes_issues() -> None:
    assert (load(FILER).get("permissions") or {}).get(WIDE) == "write"


def test_the_filer_never_blocks_a_merge() -> None:
    assert all(job["continue-on-error"] for job in load(FILER)["jobs"].values())
