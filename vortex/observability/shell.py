"""The console shell: sidebar, clinic switcher, page head.

Every team page renders inside ``console_page``. The public wall keeps its
own top nav (``live._nav``) because a projector has no room for a sidebar.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from nicegui import ui

from vortex.observability.icons import NAV, icon

#: (label, path, children). Children render indented under their parent.
SECTIONS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("Overview", "/", ()),
    ("Agents", "/agents", ()),
    ("Calls", "/calls", (("Live", "/calls/live"),)),
    ("Patients", "/patients", ()),
    ("Insights", "/insights", ()),
    (
        "Settings",
        "/settings",
        (
            ("Rules", "/settings/rules"),
            ("Integrations", "/settings/integrations"),
            ("Engineering", "/settings/engineering"),
        ),
    ),
)


def _is_on(active: str, path: str, children: tuple[tuple[str, str], ...]) -> bool:
    if active == path:
        return True
    if path == "/":
        return False
    if any(active == child for _, child in children):
        return False
    return active.startswith(path + "/")


def _nav_link(label: str, path: str, *, on: bool) -> None:
    with ui.link("", path).classes("nav-item on" if on else "nav-item"):
        if path in NAV:
            icon(NAV[path])
        ui.label(label)


def sidebar(active: str, *, health: dict[str, Any] | None, clinic: str, who: str | None) -> None:
    from vortex.observability import live  # late import: live imports this module

    with ui.element("aside").classes("sidebar"):
        with ui.link("", "/").classes("brand"):
            icon("mark")
            ui.label("Vortex")
        with ui.element("div").classes("clinic-switcher"):
            with ui.element("div"):
                ui.label(clinic).classes("name")
                ui.label("1 clinic · 3 sites").classes("meta")
            ui.label("▾").classes("caret")
        for label, path, children in SECTIONS:
            on = _is_on(active, path, children)
            _nav_link(label, path, on=on)
            if children and (on or any(active == c for _, c in children)):
                with ui.element("div").classes("nav-sub"):
                    for sub_label, sub_path in children:
                        _nav_link(sub_label, sub_path, on=active == sub_path)
        with ui.element("div").classes("foot"):
            live._line_pill(health, short=True)
            with ui.link("", "/wall", new_tab=True).classes("nav-item"):
                icon("wall")
                ui.label("Open the wall")
            if who:
                ui.label(f"Signed in · {who}").classes("caption-sm")
            ui.button("Sign out", on_click=live._logout).props("flat no-caps").classes(
                "button-quiet"
            )


@contextmanager
def console_page(
    active: str,
    title: str,
    sub: str,
    *,
    health: dict[str, Any] | None,
    clinic: str,
    who: str | None = None,
    controls: Callable[[], None] | None = None,
) -> Iterator[ui.element]:
    """Sidebar + page head. Yields the content container."""
    with ui.element("div").classes("app"):
        sidebar(active, health=health, clinic=clinic, who=who)
        with ui.element("div").classes("content"):
            with ui.element("main").classes("page"):
                with ui.element("div").classes("page-head"):
                    with ui.element("div"):
                        ui.label(title).classes("title")
                        if sub:
                            ui.label(sub).classes("sub")
                    if controls is not None:
                        with ui.element("div").classes("row"):
                            controls()
                body = ui.element("div").classes("stack").style("gap: 32px")
                yield body


def preview_chip(text: str = "Preview") -> None:
    ui.label(text).classes("chip-preview")


def preview_note(text: str) -> None:
    with ui.element("div").classes("preview-note row"):
        preview_chip()
        ui.label(text)


def section(title: str, meta: str | None = None) -> ui.element:
    with ui.element("div").classes("section-title"):
        ui.label(title).classes("t")
        if meta:
            ui.label(meta).classes("m")
    return ui.element("div")


def bars(rows, *, empty: str) -> None:
    """Horizontal bars from insights.Bar rows."""
    if not rows:
        ui.label(empty).classes("empty")
        return
    with ui.element("div").classes("bars"):
        for bar in rows:
            with ui.element("div").classes("bar-row"):
                ui.label(bar.label).classes("label")
                with ui.element("div").classes("track"):
                    ui.element("div").classes("fill").style(f"width:{max(bar.share * 100, 2):.0f}%")
                ui.label(str(bar.value)).classes("n")


def hours(rows) -> None:
    if not rows:
        ui.label("No call with a timestamp yet.").classes("empty")
        return
    with ui.element("div").classes("hours"):
        for bar in rows:
            ui.element("div").classes("col on" if bar.value else "col").style(
                f"height:{max(bar.share * 100, 3):.0f}%"
            )
    with ui.element("div").classes("hours-axis"):
        for bar in rows:
            ui.label(bar.label if int(bar.key) % 6 == 0 else "")


def table(
    headers: tuple[str, ...], rows: list[list[Any]], *, classes: tuple[str, ...] = ()
) -> None:
    """A plain table. Each cell is text; ``classes[i]`` styles column i."""
    with ui.element("div").classes("table-wrap"), ui.element("table").classes("table"):
        with ui.element("thead"), ui.element("tr"):
            for head in headers:
                with ui.element("th"):
                    ui.label(head)
        with ui.element("tbody"):
            for row in rows:
                with ui.element("tr"):
                    for index, cell in enumerate(row):
                        cls = classes[index] if index < len(classes) else ""
                        with ui.element("td").classes(cls):
                            if callable(cell):
                                cell()
                            else:
                                ui.label("—" if cell in (None, "") else str(cell))
