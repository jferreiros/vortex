"""The design tokens have one source. docs/ carries a copy because GitHub Pages
serves only that folder. This test fails when the copy is stale: run
`make design-sync`. See DESIGN.md."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "vortex" / "observability" / "design.css"
COPY = REPO / "docs" / "design.css"


def test_docs_copy_matches_source() -> None:
    assert SOURCE.read_text(encoding="utf-8") == COPY.read_text(encoding="utf-8"), (
        "docs/design.css is stale: run `make design-sync`"
    )


def test_every_design_md_color_is_a_css_token() -> None:
    """Each colour in DESIGN.md's front matter exists as a CSS custom property."""
    front = (REPO / "DESIGN.md").read_text(encoding="utf-8").split("---")[1]
    css = SOURCE.read_text(encoding="utf-8")
    in_colors = False
    names: list[str] = []
    for line in front.splitlines():
        if line.startswith("colors:"):
            in_colors = True
            continue
        if in_colors and line and not line.startswith(" "):
            break
        if in_colors and line.strip():
            names.append(line.split(":", 1)[0].strip())
    assert names, "no colors block in DESIGN.md"
    missing = [n for n in names if f"--{n}:" not in css]
    assert not missing, f"tokens in DESIGN.md but not in design.css: {missing}"


def test_static_pages_load_the_tokens() -> None:
    for page in ("index.html", "tasks.html"):
        text = (REPO / "docs" / page).read_text(encoding="utf-8")
        assert 'href="design.css"' in text, f"docs/{page} does not load design.css"


def test_index_nav_links_reuse_chip() -> None:
    """docs/index.html must use .chip from design.css, not recreate it in page CSS."""
    text = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    assert ".nav a{" not in text and ".nav a {" not in text
    assert text.count('class="chip"') >= 7


def test_evals_report_uses_shared_pill_not_a_24px_override() -> None:
    """report.py inlines design.css; its own _CSS must stay layout-only."""
    from evals.common.report import _CSS, _pill
    from evals.common.results import CaseResult

    assert ".pill{" not in _CSS.replace(" ", "")
    assert ".pill::before" not in _CSS
    solid = _pill(CaseResult(id="a", name="a", status="pass"))
    assert 'class="pill"' in solid
    assert 'class="dot ok"' in solid
    hollow = _pill(CaseResult(id="b", name="b", status="pass", hollow=True))
    assert 'class="pill mute"' in hollow
    assert 'class="dot off"' in hollow
    assert "hollow" in hollow


def test_tasks_html_does_not_redefine_chip() -> None:
    """Page CSS lays out only; .chip lives in design.css (issue #80)."""
    text = (REPO / "docs" / "tasks.html").read_text(encoding="utf-8")
    style = text.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ".chip{" not in style.replace(" ", "")
    assert ".chip[aria-pressed" not in style
