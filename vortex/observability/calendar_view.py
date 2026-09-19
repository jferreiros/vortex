"""The doctor calendar: ``/calendar`` (public).

A day x time grid per doctor, built from the clinic catalogue and filled from
the call log. The source is the synthetic-data pack by default; point
``VORTEX_CALENDAR_LOG`` at ``logs/calls.jsonl`` and the same grid fills live as
calls book, move and cancel.

The doctor types their name to open their own diary (no roster dump). The grid
shows one week at a time. Today's visits sit under it as full cards, with a
plain-language note. Long notes are summarised with Hugging Face when
``HF_TOKEN`` is set.

This module reuses the chrome from ``live.py`` (nav, footer, dots, pills) the
same way ``console.py`` does, and follows DESIGN.md: layout only lives in
``board.css``, colour comes from the tokens.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Any

from nicegui import ui

from vortex.clinic.client import FakeClinicClient
from vortex.contract import MADRID, Catalogue
from vortex.observability import calendar as cal
from vortex.observability import live
from vortex.settings import get_settings

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
_PATIENTS: dict[str, cal.PatientBrief] = cal.patient_index()
_LOCATION_NAMES: dict[str, str] = {loc.location_id: loc.name for loc in _CATALOGUE.locations}
_TYPE_NAMES: dict[str, str] = {
    item.appointment_type_id: item.name for item in _CATALOGUE.appointment_types
}
_PLAN_NAMES: dict[str, str] = {plan.insurer_id: plan.name for plan in _CATALOGUE.insurance_plans}


def _today() -> date:
    raw = os.environ.get("VORTEX_CALENDAR_TODAY")
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(MADRID).date()


def _title_for(day: date) -> tuple[str, str]:
    return day.strftime("%a"), day.strftime("%d/%m")


def _cell_key(cell: cal.CalendarCell) -> str:
    return f"{cell.start.isoformat()}|{cell.location_id}|{cell.patient_id}"


def _named(calendars: list[cal.DoctorCalendar], query: str) -> list[cal.DoctorCalendar]:
    needle = query.strip().casefold()
    if not needle:
        return []
    exact = [c for c in calendars if c.name.casefold() == needle]
    if exact:
        return exact
    return [c for c in calendars if needle in c.name.casefold()]


def _brief(cell: cal.CalendarCell) -> cal.VisitBrief:
    return cal.briefing_for(
        cell,
        _PATIENTS,
        location_names=_LOCATION_NAMES,
        type_names=_TYPE_NAMES,
        plan_names=_PLAN_NAMES,
    )


def _kv(key: str, value: str) -> None:
    with ui.element("div").classes("kv"):
        ui.label(key)
        ui.label(value or "—")


def _sex_label(sex: str) -> str:
    key = (sex or "").strip().upper()
    if key == "F":
        return "Woman"
    if key == "M":
        return "Man"
    return sex.strip()


def _week_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"{monday.strftime('%d')}–{sunday.strftime('%d %b')}"
    return f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b')}"


def _clamp_week(monday: date, calendar: cal.DoctorCalendar) -> date:
    if not calendar.days:
        return monday
    first = cal.week_start(calendar.days[0].day)
    last = cal.week_start(calendar.days[-1].day)
    if monday < first:
        return first
    if monday > last:
        return last
    return monday


def _login(query: str, error: str, submit: Any, set_query: Any) -> None:
    with ui.element("div").classes("card login"):
        ui.label("Your diary").classes("heading-lg")
        ui.label("Type your name to open it.").classes("body-sm")
        ui.element("div").style("height: 16px")
        name = (
            ui.input(placeholder="Doctor name", value=query)
            .props("dense outlined")
            .classes("w-full")
        )
        name.on_value_change(lambda e: set_query(str(e.value or "")))
        status = ui.label(error).classes("error")
        if error:
            status.set_text(error)

        def go() -> None:
            set_query(str(name.value or ""))
            submit(str(name.value or ""))

        ui.button("Open", on_click=go).props("unelevated no-caps").classes("button-primary")
        name.on("keydown.enter", go)


def _briefing_card(brief: cal.VisitBrief, summary: str) -> None:
    with ui.element("div").classes("card cal-brief"):
        with ui.element("div").classes("section-title"):
            ui.label(brief.start.strftime("%H:%M")).classes("t")
            ui.label(brief.appointment_type or "Visit").classes("m")
        with ui.element("div").classes("cal-brief-pills"):
            with ui.element("span").classes("pill soft"):
                ui.label("Returning" if brief.has_visited_before else "New patient")
            if brief.sex:
                with ui.element("span").classes("pill soft"):
                    ui.label(_sex_label(brief.sex))
            if brief.age:
                with ui.element("span").classes("pill soft"):
                    ui.label(brief.age)
        _kv("Patient", brief.full_name)
        _kv("When", brief.start.strftime("%a %d/%m · %H:%M"))
        _kv("Site", brief.location_name)
        _kv("Insurer", brief.insurer)
        _kv("Phone", brief.phone)
        note = summary or brief.note
        if note:
            ui.label("For the consult").classes("kicker")
            ui.label(note).classes("body-sm cal-note")


def _booked_on(calendar: cal.DoctorCalendar, day: date) -> list[cal.CalendarCell]:
    cells = [
        cell
        for slot in calendar.days
        if slot.day == day
        for cell in slot.cells
        if cell.status == "booked"
    ]
    cells.sort(key=lambda cell: cell.start)
    return cells


def _week_bar(
    monday: date,
    calendar: cal.DoctorCalendar,
    shift: Any,
) -> None:
    first = cal.week_start(calendar.days[0].day) if calendar.days else monday
    last = cal.week_start(calendar.days[-1].day) if calendar.days else monday
    with ui.element("div").classes("cal-week"):
        prev = (
            ui.button("Previous", on_click=lambda: shift(-7))
            .props("flat no-caps")
            .classes("button-quiet")
        )
        if monday <= first:
            prev.props("disable")
        ui.label(_week_label(monday)).classes("cal-week-label")
        nxt = (
            ui.button("Next", on_click=lambda: shift(7))
            .props("flat no-caps")
            .classes("button-quiet")
        )
        if monday >= last:
            nxt.props("disable")


def _today_visits(visits: list[cal.VisitBrief], summaries: dict[str, str]) -> None:
    with ui.element("div").classes("section-title"):
        ui.label("Today").classes("t")
        ui.label(f"{len(visits)} visit" if len(visits) == 1 else f"{len(visits)} visits").classes(
            "m"
        )
    if not visits:
        with ui.element("div").classes("empty-state"):
            ui.label("No visits today").classes("t")
            ui.label("Booked slots for this doctor land here on the day.").classes("d")
        return
    with ui.element("div").classes("cal-today-list"):
        for brief in visits:
            key = brief.start.isoformat()
            _briefing_card(brief, summaries.get(key, ""))


def _grid(
    calendar: cal.DoctorCalendar | None,
    monday: date,
    today: date,
    selected_key: str,
    open_cell: Any,
    shift: Any,
) -> None:
    with ui.element("div").classes("section-title"):
        ui.label(calendar.name if calendar else "Calendar").classes("t")
        if calendar:
            ui.label(calendar.specialty or "Diary").classes("m")
    if calendar is None:
        with ui.element("div").classes("empty-state"):
            ui.label("Nothing to show yet").classes("t")
            ui.label("This doctor has no open day in the window.").classes("d")
        return

    _week_bar(monday, calendar, shift)

    days = cal.week_dates(monday)
    times: list[time] = calendar.times
    by_day: dict[date, dict[time, cal.CalendarCell]] = {
        day.day: {cell.start.time(): cell for cell in day.cells} for day in calendar.days
    }

    with ui.element("div").classes("cal-grid-wrap"):
        grid = ui.element("div").classes("cal-grid cal-grid-week")
        grid.style("grid-template-columns: 56px repeat(7, minmax(0, 1fr));")
        with grid:
            ui.element("div").classes("cal-corner")
            for day in days:
                dow, dom = _title_for(day)
                head = ui.element("div").classes(
                    "cal-colhead today" if day == today else "cal-colhead"
                )
                with head:
                    ui.label(dow).classes("cal-dow")
                    ui.label(dom).classes("cal-date")
                    if day == today:
                        ui.label("Today").classes("cal-dow")
            for slot_time in times:
                with ui.element("div").classes("cal-timelabel"):
                    ui.label(slot_time.strftime("%H:%M"))
                for day in days:
                    cell = by_day.get(day, {}).get(slot_time)
                    if cell is None:
                        ui.element("div").classes("cal-cell off")
                    elif cell.status == "booked":
                        key = _cell_key(cell)
                        classes = "cal-cell booked on" if key == selected_key else "cal-cell booked"
                        who = cell.patient_id or "Booked"
                        kind = cell.appointment_type_id or "appointment"
                        block = (
                            ui.button(who, on_click=lambda c=cell: open_cell(c))
                            .props("flat unelevated no-caps")
                            .classes(classes)
                        )
                        with block:
                            ui.tooltip(f"{who} · {kind}")
                    else:
                        ui.element("div").classes("cal-cell free")


@ui.page("/calendar")
def calendar_page() -> None:
    live._apply_chrome()
    ui.page_title("Vortex · Calendar")
    stage = ui.element("div").classes("shell")
    state: dict[str, Any] = {
        "provider": None,
        "query": "",
        "cell": "",
        "error": "",
        "week": None,
    }
    rendered: dict[str, Any] = {"sig": None}

    def set_query(query: str) -> None:
        state["query"] = query

    def submit(query: str) -> None:
        events = cal.load_source_events()
        bookings = cal.bookings_from_events(events, cal.appointment_index())
        calendars = cal.build_calendars(_CATALOGUE, bookings, days_window=DAYS_WINDOW)
        found = _named(calendars, query)
        if len(found) == 1:
            state["provider"] = found[0].provider_id
            state["week"] = _clamp_week(cal.week_start(_today()), found[0])
            state["cell"] = ""
            state["error"] = ""
            redraw()
            return
        if not found:
            state["error"] = "No doctor by that name."
        else:
            state["error"] = "Several doctors match — type the full name."
        redraw()

    def sign_out() -> None:
        state["provider"] = None
        state["cell"] = ""
        state["week"] = None
        state["error"] = ""
        redraw()

    def open_cell(cell: cal.CalendarCell) -> None:
        state["cell"] = _cell_key(cell)
        redraw()

    def shift_week(delta: int) -> None:
        current = state["week"] or cal.week_start(_today())
        state["week"] = current + timedelta(days=delta)
        redraw()

    def redraw() -> None:
        events = cal.load_source_events()
        bookings = cal.bookings_from_events(events, cal.appointment_index())
        calendars = cal.build_calendars(_CATALOGUE, bookings, days_window=DAYS_WINDOW)
        total_booked = sum(c.booked for c in calendars)
        today = _today()
        sig = (
            tuple((c.provider_id, c.booked, c.capacity, len(c.days)) for c in calendars),
            state["provider"],
            state["cell"],
            state["error"],
            state["week"],
            today,
        )
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig

        selected = next(
            (c for c in calendars if c.provider_id == state["provider"]),
            None,
        )
        if state["provider"] and selected is None and calendars:
            state["provider"] = None
            state["cell"] = ""
            state["week"] = None

        monday = state["week"]
        if selected is not None:
            monday = _clamp_week(monday or cal.week_start(today), selected)
            state["week"] = monday

        today_cells = _booked_on(selected, today) if selected else []
        today_briefs = [_brief(cell) for cell in today_cells]
        token = get_settings().hf_token
        summaries = {
            brief.start.isoformat(): cal.summarize_note(brief.note, token=token)
            for brief in today_briefs
            if brief.note
        }

        stage.clear()
        with stage:
            slot = live._nav("/calendar", team=False)
            with slot:
                live._pill(f"{total_booked} booked", "ok", "mute")
            with ui.element("main").classes("page"):
                if selected is None or monday is None:
                    with ui.element("div").classes("page-head"):
                        with ui.element("div"):
                            ui.label("Calendar").classes("title")
                            ui.label(
                                "Each doctor's diary, filling as calls book, move and cancel."
                            ).classes("sub")
                    _login(state["query"], state["error"], submit, set_query)
                else:
                    with ui.element("div").classes("page-head"):
                        with ui.element("div"):
                            ui.label("Calendar").classes("title")
                            ui.label(
                                "One week at a time. Today's visits sit under the grid."
                            ).classes("sub")
                        ui.button("Change doctor", on_click=sign_out).props("flat no-caps").classes(
                            "button-quiet"
                        )
                    _grid(selected, monday, today, state["cell"], open_cell, shift_week)
                    _today_visits(today_briefs, summaries)
            live._footer()

    redraw()
    ui.timer(0.8, redraw)
