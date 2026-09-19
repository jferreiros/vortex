"""Inline the design tokens into the standalone didactic page.

``docs/didactica.html`` has to open from a ``file://`` URL with no server and no
build step, so it cannot load ``design.css`` through a ``<link>``. This writes
``vortex/observability/design.css`` into the page's ``<style id="design-tokens">``
element, the same way ``evals/common/report.py`` inlines it for the evals report.

Run it after ``make design-sync``. ``--check`` exits 1 when the inlined copy is
stale, which is what ``tests/test_didactica.py`` asserts.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOKENS_SOURCE = REPO / "vortex" / "observability" / "design.css"
PAGE = REPO / "docs" / "didactica.html"

TOKENS_BLOCK = re.compile(r'(<style id="design-tokens">)(.*?)(</style>)', re.DOTALL)
CLOSING_STYLE_TAG = "</style>"


def render(page_html: str, tokens_css: str) -> str:
    """Return ``page_html`` with the design tokens inlined."""
    assert TOKENS_BLOCK.search(page_html), (
        f'{PAGE.name} has no <style id="design-tokens"> element to fill'
    )
    assert CLOSING_STYLE_TAG not in tokens_css, (
        "design.css contains a closing style tag and cannot be inlined"
    )
    inlined = f"\n{tokens_css.strip()}\n"
    return TOKENS_BLOCK.sub(lambda m: m.group(1) + inlined + m.group(3), page_html, count=1)


def main(argv: list[str]) -> int:
    tokens_css = TOKENS_SOURCE.read_text(encoding="utf-8")
    page_html = PAGE.read_text(encoding="utf-8")
    built = render(page_html, tokens_css)

    if "--check" in argv:
        if built != page_html:
            print(
                "docs/didactica.html carries a stale copy of design.css: run `make didactica`",
                file=sys.stderr,
            )
            return 1
        print("docs/didactica.html tokens are up to date")
        return 0

    if built == page_html:
        print("docs/didactica.html tokens already up to date")
        return 0

    PAGE.write_text(built, encoding="utf-8")
    print(f"inlined {len(tokens_css)} bytes of design.css into docs/{PAGE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
