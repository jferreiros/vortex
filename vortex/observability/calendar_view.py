"""The doctor calendar: ``/calendar`` (public).

A day x time grid per doctor, built from the clinic catalogue and filled from
the call log. The source is the synthetic-data pack by default; point
``VORTEX_CALENDAR_LOG`` at ``logs/calls.jsonl`` and the same grid fills live as
calls book, move and cancel.

This module reuses the chrome from ``live.py`` (nav, footer, dots, pills) the
same way ``console.py`` does, and follows DESIGN.md: layout only lives in
``board.css``, colour comes from the tokens.
"""

from __future__ import annotations

import os
from datetime import date, time
from typing import Any

from nicegui import ui

from vortex.clinic.client import FakeClinicClient
from vortex.contract import Catalogue
from vortex.observability import calendar as cal
from vortex.observability import live

#: How many days each doctor's grid spans, from the first bookable day. Default
#: (unset) is the whole bookable window, so every booked slot in the pack shows;
#: set ``VORTEX_CALENDAR_DAYS`` to a number to narrow it.
_ENV_DAYS = os.environ.get("VORTEX_CALENDAR_DAYS")
DAYS_WINDOW: int | None = int(_ENV_DAYS) if _ENV_DAYS else None


def _run_now(coro: Any) -> Any:
    """Drive a coroutine that completes without awaiting, with no event loop.

    ``FakeClinicClient.catalogue()`` builds nothing on demand - the catalogue is
    ready in ``__init__`` - so a single ``send`` returns it. This avoids
    ``asyncio.run`` inside NiceGUI's running loop.
    """
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("catalogue() did not complete synchronously")


#: The catalogue never changes during the event, so it is built once. Offline it
#: comes from the fixtures; the grid only needs schedules, hours and the window.
_CATALOGUE: Catalogue = _run_now(FakeClinicClient().catalogue())


def _title_for(day: date) -> tuple[str, str]:
    return day.strftime("%a"), day.strftime("%d/%m")


def _rail(
    calendars: list[cal.DoctorCalendar],
    selected: cal.DoctorCalendar | None,
    pick: Any,
) -> None:
    with ui.element("div").classes("section-title"):
        ui.label("Doctors").classes("t")
        ui.label(f"{len(calendars)} providers · this window").classes("m")
    with ui.element("div").classes("cal-rail"):
        for calendar in calendars:
            on = selected is not None and calendar.provider_id == selected.provider_id
            button = ui.element("button").classes("cal-doc on" if on else "cal-doc")
            button.on("click", lambda cid=calendar.provider_id: pick(cid))
            capacity = calendar.capacity
            pct = round(100 * calendar.booked / capacity) if capacity else 0
            with button:
                with ui.element("div").classes("row"):
                    live._dot("ok" if calendar.booked else "off")
                    ui.label(calendar.name).classes("cal-doc-name")
                ui.label(calendar.specialty or "—").classes("cal-doc-spec")
                with ui.element("div").classes("cal-bar"):
                    ui.element("div").classes("cal-bar-fill").style(f"width:{pct}%")
                ui.label(f"{calendar.booked}/{capacity} booked").classes("cal-doc-count")


def _grid(calendar: cal.DoctorCalendar | None) -> None:
    with ui.element("div").classes("section-title"):
        ui.label(calendar.name if calendar else "Calendar").classes("t")
        if calendar:
            ui.label(f"{calendar.booked} booked · {len(calendar.days)} open days").classes("m")
    if calendar is None or not calendar.days:
        with ui.element("div").classes("empty-state"):
            ui.label("Nothing to show yet").classes("t")
            ui.label("This doctor has no open day in the window.").classes("d")
        return

    times: list[time] = calendar.times
    days = [day.day for day in calendar.days]
    by_day: dict[date, dict[time, cal.CalendarCell]] = {
        day.day: {cell.start.time(): cell for cell in day.cells} for day in calendar.days
    }

    with ui.element("div").classes("cal-grid-wrap"):
        grid = ui.element("div").classes("cal-grid")
        grid.style(f"grid-template-columns: 56px repeat({len(days)}, minmax(40px, 1fr));")
        with grid:
            ui.element("div").classes("cal-corner")
            for day in days:
                dow, dom = _title_for(day)
                with ui.element("div").classes("cal-colhead"):
                    ui.label(dow).classes("cal-dow")
                    ui.label(dom).classes("cal-date")
            for slot_time in times:
                with ui.element("div").classes("cal-timelabel"):
                    ui.label(slot_time.strftime("%H:%M"))
                for day in days:
                    cell = by_day.get(day, {}).get(slot_time)
                    if cell is None:
                        ui.element("div").classes("cal-cell off")
                    elif cell.status == "booked":
                        with ui.element("div").classes("cal-cell booked"):
                            who = cell.patient_id or "Booked"
                            kind = cell.appointment_type_id or "appointment"
                            ui.tooltip(f"{who} · {kind}")
                    else:
                        ui.element("div").classes("cal-cell free")


@ui.page("/calendar")
def calendar_page() -> None:
    live._apply_chrome()
    ui.page_title("Vortex · Calendar")
    stage = ui.element("div").classes("shell")
    state: dict[str, Any] = {"provider": None}
    rendered: dict[str, Any] = {"sig": None}

    def pick(provider_id: str) -> None:
        state["provider"] = provider_id
        redraw()

    def redraw() -> None:
        events = cal.load_source_events()
        bookings = cal.bookings_from_events(events, cal.appointment_index())
        calendars = cal.build_calendars(_CATALOGUE, bookings, days_window=DAYS_WINDOW)
        total_booked = sum(c.booked for c in calendars)
        sig = (
            tuple((c.provider_id, c.booked, c.capacity, len(c.days)) for c in calendars),
            state["provider"],
        )
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig

        if state["provider"] is None and calendars:
            # Default to the busiest doctor, so the grid opens on a filled one.
            state["provider"] = max(calendars, key=lambda c: c.booked).provider_id
        selected = next(
            (c for c in calendars if c.provider_id == state["provider"]),
            calendars[0] if calendars else None,
        )

        stage.clear()
        with stage:
            slot = live._nav("/calendar", team=False)
            with slot:
                live._pill(f"{total_booked} booked", "ok", "mute")
            with ui.element("main").classes("page"):
                with ui.element("div").classes("page-head"):
                    with ui.element("div"):
                        ui.label("Calendar").classes("title")
                        ui.label(
                            "Each doctor's diary, filling as calls book, move and cancel."
                        ).classes("sub")
                _rail(calendars, selected, pick)
                ui.element("div").style("height: 24px")
                _grid(selected)
            live._footer()

    redraw()
    ui.timer(0.8, redraw)
