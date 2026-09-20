"""observability/calendar.py: the per-doctor grid and how the log fills it.

The builders are pure, so these tests hand them a tiny hand-built catalogue and
a list of log events and check the slots that come out. One integration test at
the end runs the real offline catalogue through the synthetic-data pack.
"""

from __future__ import annotations

from datetime import date, datetime, time

from vortex.clinic.client import FakeClinicClient
from vortex.contract import (
    MADRID,
    Appointment,
    Catalogue,
    OpeningHours,
    PatientRecord,
    ProviderRecord,
    ProviderSchedule,
)
from vortex.observability import calendar as cal

#: A provider who sits at Centro on Mondays only, 09:00-10:00: four 15-min steps.
_MONDAY = 0
_START = date(2026, 10, 5)  # a Monday
_FIESTA = date(2026, 10, 12)  # the next Monday, a published closure day


def _catalogue() -> Catalogue:
    provider = ProviderRecord(
        provider_id="PR01",
        name="Dra. Uno",
        specialty_id="general",
        specialty_name="General practice",
        location_ids=["centro"],
        schedules=[
            ProviderSchedule(
                location_id="centro",
                hours=[OpeningHours(weekday=_MONDAY, opens=time(9, 0), closes=time(10, 0))],
            )
        ],
    )
    return Catalogue(
        providers=[provider],
        bookable_from=_START,
        bookable_to=date(2026, 10, 31),
        closure_days=[_FIESTA],
        slot_minutes=15,
    )


def _slot(hour: int, minute: int) -> str:
    return datetime(2026, 10, 5, hour, minute, tzinfo=MADRID).isoformat()


def _book_event(
    hour: int,
    minute: int,
    *,
    patient: str = "P00001",
    appt_type: str = "review",
    appointment_id: str = "",
) -> dict:
    return {
        "kind": "submit.result",
        "call_id": "roster:x",
        "payload": {
            "action": "BOOK",
            "patient_id": patient,
            "provider_id": "PR01",
            "location_id": "centro",
            "appointment_type_id": appt_type,
            "appointment_id": appointment_id,
            "slot": _slot(hour, minute),
        },
    }


def _appt(appointment_id: str, hour: int, minute: int) -> cal.Booking:
    return cal.Booking(
        provider_id="PR01",
        location_id="centro",
        start=datetime(2026, 10, 5, hour, minute, tzinfo=MADRID),
        appointment_id=appointment_id,
    )


def _only_calendar(events: list[dict], appt_index: dict | None = None) -> cal.DoctorCalendar:
    bookings = cal.bookings_from_events(events, appt_index or {})
    calendars = cal.build_calendars(_catalogue(), bookings, start_from=_START, days_window=8)
    assert len(calendars) == 1
    return calendars[0]


def _cell_at(calendar: cal.DoctorCalendar, hour: int, minute: int) -> cal.CalendarCell:
    day = next(d for d in calendar.days if d.day == _START)
    return next(c for c in day.cells if c.start.time() == time(hour, minute))


# ---- the empty grid -------------------------------------------------------


def test_grid_follows_open_hours_and_skips_closure_days() -> None:
    calendar = _only_calendar([])
    # Only the first Monday survives: the second (12 Oct) is a closure day.
    assert [d.day for d in calendar.days] == [_START]
    # 09:00-10:00 in 15-min steps is exactly four steps, none at or past 10:00.
    assert calendar.times == [time(9, 0), time(9, 15), time(9, 30), time(9, 45)]
    assert calendar.capacity == 4
    assert calendar.booked == 0
    assert all(cell.status == "free" for d in calendar.days for cell in d.cells)


# ---- BOOK -----------------------------------------------------------------


def test_book_fills_the_named_slot() -> None:
    calendar = _only_calendar([_book_event(9, 15, patient="P00007")])
    booked = _cell_at(calendar, 9, 15)
    assert booked.status == "booked"
    assert booked.patient_id == "P00007"
    assert booked.appointment_type_id == "review"
    assert calendar.booked == 1
    # The other three steps stay free.
    assert _cell_at(calendar, 9, 0).status == "free"


# ---- CANCEL ---------------------------------------------------------------


def test_cancel_frees_the_slot_via_appointment_id() -> None:
    events = [
        _book_event(9, 30),
        {
            "kind": "submit.result",
            "call_id": "roster:x",
            "payload": {"action": "CANCEL", "appointment_id": "A1"},
        },
    ]
    calendar = _only_calendar(events, {"A1": _appt("A1", 9, 30)})
    assert _cell_at(calendar, 9, 30).status == "free"
    assert calendar.booked == 0


def test_cancel_frees_a_slot_booked_earlier_in_the_same_stream() -> None:
    # A3 is created by the BOOK itself, so it is absent from appt_index.
    events = [
        _book_event(9, 45, appointment_id="A3"),
        {
            "kind": "submit.result",
            "call_id": "roster:y",
            "payload": {"action": "CANCEL", "appointment_id": "A3"},
        },
    ]
    calendar = _only_calendar(events)
    assert _cell_at(calendar, 9, 45).status == "free"
    assert calendar.booked == 0


def test_wall_cancel_frees_the_slot_by_key() -> None:
    """The Horarios cancel buttons don't write a CANCEL event — the board
    drops the slot with cal.drop_cancelled over database/'s table."""
    bookings = cal.bookings_from_events([_book_event(9, 30, patient="P00007")])
    key = cal.cancel_key("PR01", "centro", "2026-10-05T09:30:00+02:00")
    assert key in bookings
    calendar = _only_calendar([])
    calendars = cal.build_calendars(
        _catalogue(), cal.drop_cancelled(bookings, {key}), start_from=_START, days_window=8
    )
    assert calendars[0].booked == calendar.booked == 0
    # The input dict is untouched — drop_cancelled returns a fresh one.
    assert key in bookings


def test_cancel_key_rejects_a_bad_slot() -> None:
    assert cal.cancel_key("PR01", "centro", "not-a-date") is None
    assert cal.cancel_key("", "centro", "2026-10-05T09:30:00+02:00") is None


# ---- RESCHEDULE -----------------------------------------------------------


def test_reschedule_moves_from_the_old_slot_to_the_new_one() -> None:
    events = [
        _book_event(9, 0),
        {
            "kind": "submit.result",
            "call_id": "roster:x",
            "payload": {
                "action": "RESCHEDULE",
                "appointment_id": "A2",
                "provider_id": "PR01",
                "location_id": "centro",
                "slot": _slot(9, 45),
            },
        },
    ]
    calendar = _only_calendar(events, {"A2": _appt("A2", 9, 0)})
    assert _cell_at(calendar, 9, 0).status == "free"
    assert _cell_at(calendar, 9, 45).status == "booked"
    assert calendar.booked == 1


# ---- the grid signature the view redraws on -------------------------------


def test_grid_signature_notices_a_moved_booking() -> None:
    """The view redraws only on a new signature, so a move must change it.

    Totals stay put when a booking moves inside the same doctor's window: same
    booked count, same capacity, same open days. Only the cells differ.
    """
    before = [_only_calendar([_book_event(9, 0)])]
    moved = [
        _only_calendar(
            [
                _book_event(9, 0),
                {
                    "kind": "submit.result",
                    "call_id": "roster:x",
                    "payload": {
                        "action": "RESCHEDULE",
                        "appointment_id": "A2",
                        "provider_id": "PR01",
                        "location_id": "centro",
                        "slot": _slot(9, 45),
                    },
                },
            ],
            {"A2": _appt("A2", 9, 0)},
        )
    ]
    assert before[0].booked == moved[0].booked
    assert before[0].capacity == moved[0].capacity
    assert len(before[0].days) == len(moved[0].days)
    assert cal.grid_signature(before) != cal.grid_signature(moved)


def test_grid_signature_is_stable_for_an_unchanged_grid() -> None:
    same = _only_calendar([_book_event(9, 30)])
    again = _only_calendar([_book_event(9, 30)])
    assert cal.grid_signature([same]) == cal.grid_signature([again])


# ---- non-diary verbs ------------------------------------------------------


def test_no_action_and_register_never_touch_a_calendar() -> None:
    events = [
        {"kind": "submit.result", "payload": {"action": "NO_ACTION", "reason": "out_of_scope"}},
        {"kind": "submit.result", "payload": {"action": "REGISTER", "new_patient": {}}},
    ]
    assert cal.bookings_from_events(events, {}) == {}


# ---- end to end, offline --------------------------------------------------


async def test_real_catalogue_fills_from_the_synthetic_pack() -> None:
    catalogue = await FakeClinicClient().catalogue()
    events = cal.load_source_events()
    if not events:
        # The pack is a generated artifact; skip cleanly if it is not present.
        import pytest

        pytest.skip("synthetic-data pack not generated")
    bookings = cal.bookings_from_events(events, cal.appointment_index())
    calendars = cal.build_calendars(catalogue, bookings)

    assert calendars, "expected one calendar per provider"
    # The roster BOOKs land on at least one doctor.
    assert any(c.booked for c in calendars)
    # The Fiesta Nacional is never an open day on any doctor's grid.
    fiesta = date(2026, 10, 12)
    assert all(d.day != fiesta for c in calendars for d in c.days)
    # No booked cell exceeds its doctor's capacity accounting.
    for c in calendars:
        assert c.booked <= c.capacity


# ---- visit briefing -------------------------------------------------------


def test_patient_index_joins_given_name_and_surnames() -> None:
    index = cal.patient_index(
        [
            {
                "patient_id": "P00007",
                "given_name": "Marta",
                "first_surname": "Ruiz",
                "second_surname": "López",
                "phone": "612345678",
                "insurer": "sanitas",
                "note": "Hard of hearing — speak slowly.",
                "has_visited_before": True,
            }
        ]
    )
    person = index["P00007"]
    assert person.full_name == "Marta Ruiz López"
    assert person.phone == "612345678"
    assert person.insurer == "sanitas"
    assert person.has_visited_before is True


def test_briefing_for_joins_the_roster_and_keeps_unknown_ids() -> None:
    patients = cal.patient_index(
        [
            {
                "patient_id": "P00007",
                "given_name": "Marta",
                "first_surname": "Ruiz",
                "second_surname": "López",
                "insurer": "sanitas",
                "note": "Hard of hearing — speak slowly.",
                "has_visited_before": True,
                "phone": "612345678",
            }
        ]
    )
    cell = cal.CalendarCell(
        start=datetime(2026, 10, 5, 9, 15, tzinfo=MADRID),
        status="booked",
        patient_id="P00007",
        appointment_type_id="review",
        location_id="centro",
    )
    brief = cal.briefing_for(
        cell,
        patients,
        location_names={"centro": "Arenal Centro"},
        type_names={"review": "Review"},
        plan_names={"sanitas": "Sanitas"},
    )
    assert brief.full_name == "Marta Ruiz López"
    assert brief.location_name == "Arenal Centro"
    assert brief.appointment_type == "Review"
    assert brief.insurer == "Sanitas"
    assert brief.note == "Hipoacusia: habla despacio."
    assert brief.has_visited_before is True

    unknown = cal.CalendarCell(
        start=datetime(2026, 10, 5, 9, 30, tzinfo=MADRID),
        status="booked",
        patient_id="P99999",
        appointment_type_id="first_visit",
        location_id="norte",
    )
    missing = cal.briefing_for(unknown, patients)
    assert missing.full_name == ""
    assert missing.location_name == "norte"
    assert missing.appointment_type == "first visit"
    assert missing.note == ""


def test_summarize_note_skips_short_text_and_missing_token() -> None:
    cal.clear_summary_cache()
    long_note = " ".join(["word"] * 50)
    assert cal.summarize_note("Hard of hearing — speak slowly.", token="hf_x") == ""
    assert cal.summarize_note(long_note, token="") == ""


def test_summarize_note_caches_huggingface_payload() -> None:
    cal.clear_summary_cache()
    long_note = " ".join(["word"] * 50)
    calls = {"n": 0}

    def post(url, *, headers, json, timeout):
        del url, headers, timeout
        assert json["inputs"] == long_note
        calls["n"] += 1
        return {"summary_text": "Speak slowly. Hard of hearing."}

    first = cal.summarize_note(long_note, token="hf_x", post=post)
    second = cal.summarize_note(long_note, token="hf_x", post=post)
    assert first == "Speak slowly. Hard of hearing."
    assert second == first
    assert calls["n"] == 1


def test_clinical_note_strips_pack_metadata() -> None:
    assert cal.clinical_note("Hard of hearing — speak slowly.") == "Hard of hearing — speak slowly."
    assert (
        cal.clinical_note(
            "Fake record. Hard of hearing; speak slowly. Holds a dermatology referral."
        )
        == "Hard of hearing; speak slowly. Holds a dermatology referral."
    )
    assert (
        cal.clinical_note("Fake record. Published case: first thing Monday the twelfth of October.")
        == "first thing Monday the twelfth of October."
    )
    assert (
        cal.clinical_note("Roster record. Cases: simple_booking-12dc84a98cb2, triage-b2163776cec8.")
        == ""
    )
    assert (
        cal.clinical_note("Roster record. Cases: simple_booking-12dc84a98cb2, noise-04791d2a653e.")
        == ""
    )
    assert (
        cal.clinical_note(
            "Roster record. Cases: the_questions-1eaff9b8dea3, when_exactly-72cdb35b9682."
        )
        == ""
    )
    assert cal.clinical_note("") == ""


def test_readable_note_is_a_plain_sentence() -> None:
    assert cal.readable_note("Hard of hearing — speak slowly.") == "Hipoacusia: habla despacio."
    assert (
        cal.readable_note(
            "Fake record. Published cases: orthopaedics Thursday, general practice Saturday."
        )
        == ""
    )
    assert (
        cal.readable_note("Fake record. Published case: first thing Monday the twelfth of October.")
        == ""
    )
    assert (
        cal.readable_note("Roster record. Cases: simple_booking-12dc84a98cb2, triage-b2163776cec8.")
        == ""
    )
    assert (
        cal.readable_note(
            "Roster record. Cases: the_questions-1eaff9b8dea3, when_exactly-72cdb35b9682."
        )
        == ""
    )
    assert cal.readable_note("Roster record. Cases: difficult_caller-8e5f87c31fd2.") == ""
    assert (
        cal.readable_note(
            "Fake record. Hard of hearing; speak slowly. Holds a dermatology referral."
        )
        == "Hipoacusia: habla despacio. Trae derivación a dermatología."
    )


def test_clinic_api_records_fill_the_diary() -> None:
    record = PatientRecord(
        patient_id="P00007",
        given_name="Marta",
        first_surname="Ruiz",
        phone="612345678",
        insurer="sanitas",
        note="Hard of hearing — speak slowly.",
        has_visited_before=True,
        sex="F",
        date_of_birth=date(1984, 3, 1),
    )
    patients = cal.patient_index_from_records([record])
    assert patients["P00007"].full_name == "Marta Ruiz"
    assert patients["P00007"].phone == "612345678"
    visit = Appointment(
        appointment_id="A1",
        patient_id="P00007",
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
        start=datetime(2026, 10, 5, 9, 0, tzinfo=MADRID),
        duration_minutes=15,
    )
    bookings = cal.bookings_from_appointments([visit])
    calendars = cal.build_calendars(_catalogue(), bookings, start_from=_START, days_window=8)
    payload = cal.doctor_agenda(calendars, patients, name="Dra. Uno", today=_START, week=_START)
    assert payload["visits"][0]["full_name"] == "Marta Ruiz"
    assert payload["visits"][0]["phone"] == "612345678"
    assert payload["visits"][0]["note"] == "Hipoacusia: habla despacio."
    assert payload["visits"][0]["location_id"] == "centro"
    assert payload["visits"][0]["appointment_type_id"] == "review"
    assert payload["sites"][0]["id"] == "centro"


def test_agenda_options_lists_catalogue_dropdowns() -> None:
    opts = cal.agenda_options(_catalogue())
    assert opts["ok"] is True
    assert opts["doctors"][0]["name"] == "Dra. Uno"
    assert opts["doctors"][0]["id"] == "PR01"


def test_suggest_doctors_stays_empty_until_you_type() -> None:
    calendars = [_only_calendar([])]
    assert cal.suggest_doctors(calendars, "") == {"ok": True, "doctors": []}
    hits = cal.suggest_doctors(calendars, "uno")["doctors"]
    assert hits[0]["name"] == "Dra. Uno"


def test_doctor_agenda_never_lists_the_roster() -> None:
    events = [_book_event(9, 0, patient="P00007")]
    calendars = [_only_calendar(events)]
    patients = cal.patient_index(
        [
            {
                "patient_id": "P00007",
                "given_name": "Marta",
                "first_surname": "Ruiz",
                "note": (
                    "Fake record. Published cases: orthopaedics Thursday, "
                    "general practice Saturday."
                ),
            }
        ]
    )
    miss = cal.doctor_agenda(calendars, patients, name="", today=_START)
    assert miss == {"ok": False, "error": "no_match"}
    payload = cal.doctor_agenda(
        calendars,
        patients,
        name="Dra. Uno",
        today=_START,
        week=_START,
    )
    assert payload["ok"] is True
    assert payload["doctor"]["name"] == "Dra. Uno"
    assert len(payload["days"]) == 7
    assert payload["month"] == "2026-10-01"
    assert payload["month_label"] == "Octubre 2026"
    assert len(payload["weeks"]) >= 4
    fifth = next(cell for week in payload["weeks"] for cell in week if cell["date"] == "2026-10-05")
    assert fifth["visits"][0]["full_name"] == "Marta Ruiz"
    assert payload["visits"][0]["full_name"] == "Marta Ruiz"
    assert payload["visits"][0]["note"] == ""
    # The slot key a wall cancellation posts back rides on every visit row.
    visit = payload["visits"][0]
    assert visit["provider_id"] == "PR01"
    assert visit["patient_id"] == "P00007"
    assert visit["location_id"] == "centro"
    assert visit["slot"].startswith("2026-10-05T09:00")
    booked = next(cell for cell in payload["days"][0]["cells"] if cell["status"] == "booked")
    assert booked["visit"]["full_name"] == "Marta Ruiz"
    assert booked["visit"]["duration_minutes"] == 15
    assert booked["part"] == "start"
    later = cal.doctor_agenda(
        calendars,
        patients,
        name="Dra. Uno",
        today=_START,
        week=_FIESTA,
    )
    assert later["visits"][0]["full_name"] == "Marta Ruiz"


def test_doctor_agenda_hides_unnamed_patients() -> None:
    events = [_book_event(9, 0, patient="P00007"), _book_event(9, 15, patient="")]
    calendars = [_only_calendar(events)]
    patients = cal.patient_index(
        [{"patient_id": "P00007", "given_name": "Marta", "first_surname": "Ruiz"}]
    )
    payload = cal.doctor_agenda(calendars, patients, name="Dra. Uno", today=_START, week=_START)
    names = [row["full_name"] for row in payload["visits"]]
    assert names == ["Marta Ruiz"]
    chips = [row["full_name"] for week in payload["weeks"] for day in week for row in day["visits"]]
    assert "Unknown patient" not in chips
    assert "" not in chips


def test_doctor_agenda_spans_appointment_type_duration() -> None:
    events = [_book_event(9, 0, patient="P00007", appt_type="first_visit")]
    calendars = [_only_calendar(events)]
    patients = cal.patient_index(
        [{"patient_id": "P00007", "given_name": "Marta", "first_surname": "Ruiz"}]
    )
    payload = cal.doctor_agenda(
        calendars,
        patients,
        name="Dra. Uno",
        today=_START,
        week=_START,
        type_durations={"first_visit": 30, "review": 15},
    )
    by_time = {cell["time"]: cell for cell in payload["days"][0]["cells"]}
    assert by_time["09:00"]["part"] == "start"
    assert by_time["09:00"]["visit"]["duration_minutes"] == 30
    assert by_time["09:15"]["status"] == "booked"
    assert by_time["09:15"]["part"] == "cont"
    assert by_time["09:15"]["visit"]["full_name"] == "Marta Ruiz"
    assert by_time["09:30"]["status"] == "free"
    assert payload["visits"][0]["duration_minutes"] == 30


def test_assign_provider_fills_a_blank_doctor() -> None:
    blank = cal.Booking(
        provider_id="",
        location_id="centro",
        start=datetime(2026, 10, 5, 9, 0, tzinfo=MADRID),
        patient_id="P00007",
        appointment_type_id="review",
    )
    filled = cal.assign_provider(_catalogue(), blank)
    assert filled.provider_id == "PR01"
    named = cal.assign_provider(_catalogue(), _appt("A1", 9, 0))
    assert named.provider_id == "PR01"


def test_clinic_agenda_opens_without_a_doctor() -> None:
    events = [_book_event(9, 0, patient="P00007")]
    calendars = [_only_calendar(events)]
    patients = cal.patient_index(
        [{"patient_id": "P00007", "given_name": "Marta", "first_surname": "Ruiz"}]
    )
    payload = cal.clinic_agenda(calendars, patients, today=_START, week=_START)
    assert payload["ok"] is True
    # No specialty picked: the API sends no placeholder name, the wall's
    # own SectionHeader falls back to "Schedule".
    assert payload["doctor"]["name"] == ""
    fifth = next(cell for week in payload["weeks"] for cell in week if cell["date"] == "2026-10-05")
    assert fifth["visits"][0]["full_name"] == "Marta Ruiz"
    assert fifth["visits"][0]["provider_name"] == "Dra. Uno"


def test_clinic_agenda_filters_by_specialty() -> None:
    gp = ProviderRecord(
        provider_id="PR01",
        name="Dra. Uno",
        specialty_id="general",
        specialty_name="General practice",
        location_ids=["centro"],
        schedules=[
            ProviderSchedule(
                location_id="centro",
                hours=[OpeningHours(weekday=_MONDAY, opens=time(9, 0), closes=time(10, 0))],
            )
        ],
    )
    derm = ProviderRecord(
        provider_id="PR02",
        name="Dr. Dos",
        specialty_id="dermatology",
        specialty_name="Dermatology",
        location_ids=["centro"],
        schedules=[
            ProviderSchedule(
                location_id="centro",
                hours=[OpeningHours(weekday=_MONDAY, opens=time(9, 0), closes=time(10, 0))],
            )
        ],
    )
    catalogue = Catalogue(
        providers=[gp, derm],
        bookable_from=_START,
        bookable_to=date(2026, 10, 31),
        closure_days=[_FIESTA],
        slot_minutes=15,
    )
    events = [
        _book_event(9, 0, patient="P00007"),
        {
            "kind": "submit.result",
            "call_id": "roster:y",
            "payload": {
                "action": "BOOK",
                "patient_id": "P00008",
                "provider_id": "PR02",
                "location_id": "centro",
                "appointment_type_id": "review",
                "slot": _slot(9, 15),
            },
        },
    ]
    bookings = cal.bookings_from_events(events)
    calendars = cal.build_calendars(catalogue, bookings, start_from=_START, days_window=8)
    patients = cal.patient_index(
        [
            {"patient_id": "P00007", "given_name": "Marta", "first_surname": "Ruiz"},
            {"patient_id": "P00008", "given_name": "Luis", "first_surname": "Sanz"},
        ]
    )
    derm_only = cal.clinic_agenda(
        calendars,
        patients,
        specialty_id="dermatology",
        today=_START,
        week=_START,
    )
    names = [
        row["full_name"] for week in derm_only["weeks"] for day in week for row in day["visits"]
    ]
    assert names == ["Luis Sanz"]
    assert derm_only["doctor"]["name"] == "Dermatology"


async def test_load_agenda_bookings_reads_the_synthetic_pack() -> None:
    catalogue = await FakeClinicClient().catalogue()
    bookings = cal.load_agenda_bookings(catalogue)
    if not bookings:
        import pytest

        pytest.skip("synthetic-data pack not generated")
    assert any(row.provider_id for row in bookings.values())


def test_summarize_note_returns_empty_when_the_api_fails() -> None:
    cal.clear_summary_cache()
    long_note = " ".join(["word"] * 50)

    def post(url, *, headers, json, timeout):
        del url, headers, json, timeout
        raise RuntimeError("429")

    assert cal.summarize_note(long_note, token="hf_x", post=post) == ""
