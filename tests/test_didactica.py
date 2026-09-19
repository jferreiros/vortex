"""docs/didactica.html is the standalone explainer: it has to open from a
file:// URL with no server and no build. That means the design tokens are
inlined instead of linked, so this test guards the two things that can rot:
the inlined copy going stale, and a relative asset sneaking back in.

Run `make didactica` when this fails. See DESIGN.md and scripts/build_didactica.py.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from scripts.build_didactica import PAGE, TOKENS_SOURCE, render

PAGE_HTML = PAGE.read_text(encoding="utf-8")
PAGE_BODY = PAGE_HTML.split("<body>", 1)[1]

REQUIRED_SECTIONS = (
    "vision",
    "arquitectura",
    "llamada",
    "piezas",
    "decisiones",
    "seguridad",
    "resiliencia",
    "evals",
    "reto1",
    "reto2",
    "jurado",
    "preguntas",
    "pendiente",
)


class _Collector(HTMLParser):
    """Collect ids, internal anchors, external references and open tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.anchors: list[str] = []
        self.external: list[str] = []
        self.open_tags: list[str] = []
        self.void = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "track",
            "wbr",
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            self.ids.add(element_id)
        href = values.get("href") or ""
        if href.startswith("#"):
            self.anchors.append(href[1:])
        elif href:
            self.external.append(href)
        if src := values.get("src"):
            self.external.append(src)
        if tag not in self.void:
            self.open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.void:
            return
        assert self.open_tags, f"</{tag}> closes nothing"
        assert self.open_tags[-1] == tag, (
            f"</{tag}> closes <{self.open_tags[-1]}>: the markup is not balanced"
        )
        self.open_tags.pop()


def _parse() -> _Collector:
    collector = _Collector()
    collector.feed(PAGE_HTML)
    return collector


def test_tokens_are_inlined_and_fresh() -> None:
    tokens_css = TOKENS_SOURCE.read_text(encoding="utf-8")
    assert render(PAGE_HTML, tokens_css) == PAGE_HTML, (
        "docs/didactica.html carries a stale copy of design.css: run `make didactica`"
    )
    assert "--surface-dark: #171717;" in PAGE_HTML


def test_page_is_self_contained() -> None:
    """No stylesheet link, no local asset: the file has to work on its own."""
    assert 'href="design.css"' not in PAGE_HTML
    assert "<link" not in PAGE_HTML
    for reference in _parse().external:
        assert reference.startswith(("http://", "https://", "mailto:")), (
            f"{reference} is a relative reference: the page would break when moved"
        )


def test_markup_is_balanced_and_anchors_resolve() -> None:
    page = _parse()
    assert not page.open_tags, f"unclosed tags: {page.open_tags}"
    missing = sorted(set(page.anchors) - page.ids)
    assert not missing, f"nav links point at ids that do not exist: {missing}"


def test_every_section_is_present_and_linked() -> None:
    page = _parse()
    for section in REQUIRED_SECTIONS:
        assert section in page.ids, f"section #{section} is missing"
        assert section in page.anchors, f"section #{section} has no nav chip"


def test_page_keeps_one_dark_surface() -> None:
    """DESIGN.md: exactly one inverted surface per page, and it is the verdict."""
    assert PAGE_BODY.count('class="card-dark') == 1
    assert "cta-strip-dark" not in PAGE_BODY


def test_page_adds_no_colour_of_its_own() -> None:
    """Page CSS lays out only. Colour comes from the tokens, never from here."""
    page_css = PAGE_HTML.rsplit("</style>", 2)[1]
    assert "#" not in re.sub(r"rgba?\([^)]*\)", "", page_css), (
        "the page stylesheet declares a hex colour; add a token to DESIGN.md instead"
    )


def test_the_challenge_one_numbers_match_the_dashboard() -> None:
    """The verdict card states the score the platform reported. Keep them together."""
    for claim in ("36 / 40", "18 de los 20", "49,3 %", "171 de 347"):
        assert claim in PAGE_BODY, f"the reto 1 card no longer states {claim!r}"
