"""``scripts/ci/coderabbit_issues``: the parser reads both shapes of the review.

The CLI links each finding with an OSC-8 escape, and the workflow strips the
colour codes before the script ever opens the file. That leaves the path in one
of two places, so the parser has to find it in either.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "coderabbit_issues", ROOT / "scripts" / "ci" / "coderabbit_issues.py"
)
assert SPEC and SPEC.loader
cr = importlib.util.module_from_spec(SPEC)
sys.modules["coderabbit_issues"] = cr
SPEC.loader.exec_module(cr)

LINKED = (
    "  major [Stability & Availability]\n"
    "  → \x1b]8;;vscode://file//home/runner/work/vortex/vortex/vortex/line/session.py:297"
    "\x07vortex/line/session.py:297\x1b]8;;\x07\n"
    "  Retry an unaccepted action instead of skipping it.\n"
    "  The submit returned 503 and the loop moved on.\n"
)

# What the workflow actually hands the script: the escapes are already gone.
PLAIN = (
    "  major [Stability & Availability]\n"
    "  → vortex/line/session.py:297\n"
    "  Retry an unaccepted action instead of skipping it.\n"
    "  The submit returned 503 and the loop moved on.\n"
)


def test_the_linked_shape_yields_a_location_and_a_title() -> None:
    (found,) = cr.parse(LINKED)
    assert found["location"] == "vortex/line/session.py:297"
    assert found["title"] == "Retry an unaccepted action instead of skipping it."


def test_the_plain_shape_yields_the_same_thing() -> None:
    """The regression: this is the shape that produced `?` titles."""
    (found,) = cr.parse(PLAIN)
    assert found["location"] == "vortex/line/session.py:297"
    assert found["title"] == "Retry an unaccepted action instead of skipping it."


def test_a_line_range_is_kept() -> None:
    (found,) = cr.parse(PLAIN.replace(":297", ":297-301"))
    assert found["location"] == "vortex/line/session.py:297-301"


def test_a_finding_inside_a_design_note_is_not_filed() -> None:
    assert cr.parse(PLAIN.replace("vortex/line/session.py", "docs/research/05-data.md")) == []


def test_a_minor_finding_is_not_filed() -> None:
    assert cr.parse(PLAIN.replace("  major [", "  minor [")) == []


def test_the_same_finding_twice_is_filed_once() -> None:
    assert len(cr.parse(PLAIN + PLAIN)) == 1


def _gh(monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, stderr: str = "") -> list:
    """Capture the gh argv and answer with a canned result."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    return calls


def test_the_lookup_reads_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _gh(monkeypatch, 0, "[CR] one — a.py:1\n[CR] two — b.py:2\n")
    assert cr.existing_titles("jferreiros/vortex") == {"[CR] one — a.py:1", "[CR] two — b.py:2"}
    assert "--paginate" in calls[0]
    assert "--limit" not in calls[0]


def test_a_failed_lookup_raises_instead_of_answering_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression: an empty answer let a re-review file the same issue twice."""
    _gh(monkeypatch, 1, "", "HTTP 403")
    with pytest.raises(cr.LookupFailed, match="HTTP 403"):
        cr.existing_titles("jferreiros/vortex")


def test_a_failed_lookup_creates_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    review = tmp_path / "review.txt"
    review.write_text(PLAIN)
    calls = _gh(monkeypatch, 1, "", "HTTP 403")
    monkeypatch.setattr(sys, "argv", ["coderabbit_issues.py", str(review), "--pr", "85"])
    with pytest.raises(SystemExit) as exit_code:
        cr.main()
    assert exit_code.value.code == 1
    assert [argv[1] for argv in calls] == ["api"]
