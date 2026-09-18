"""``scripts/ci/coderabbit_issues``: the parser reads both shapes of the review.

The CLI links each finding with an OSC-8 escape, and the workflow strips the
colour codes before the script ever opens the file. That leaves the path in one
of two places, so the parser has to find it in either.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
