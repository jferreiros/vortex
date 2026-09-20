"""database/: the product's own persistence layer, against real Postgres.

There is no SQLite double and no in-memory store any more, so these tests
need the real thing: ``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY`` set and
``make supabase-migrate`` already run. Without them the whole module skips —
the rest of the offline suite still runs with no key and no network.

Isolation comes from a per-test ``tag`` (a random hex string woven into every
id these tests write) plus a purge before and after each test, so two people
can run this against the same project at the same time. The one exception is
``A0001``: the backfill path has to use a real fixture appointment id from
``vortex/clinic/fixtures.py``, so the purge deletes that row outright.

``ToolContext`` comes from ``evals.common.context.make_context`` over
``FakeClinicClient`` — the same fixtures the offline suite reads (P00042 /
PR01 / A0001).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from database import confirmations, db, remote
from database.hooks import persist_submission
from evals.common.context import make_context
from vortex.contract import (
    BookAction,
    CancelAction,
    PatientRecord,
    RescheduleAction,
    remember_patient,
)
from vortex.line.session import CallMemory

requires_db = pytest.mark.skipif(
    not (
        os.environ.get("SUPABASE_URL", "").strip()
        and (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        )
    ),
    reason="needs a migrated Supabase: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY",
)

pytestmark = requires_db

MADRID = ZoneInfo("Europe/Madrid")

#: The one fixture appointment id the backfill path has to use verbatim.
FIXTURE_APPOINTMENT = "A0001"

P00042 = PatientRecord(
    patient_id="P00042",
    given_name="Marta",
    first_surname="Ruiz",
    second_surname="López",
    phone="+34612345678",
    email="marta@example.com",
    insurer="sanitas",
)


@pytest.fixture
def tag() -> str:
    """One random marker per test, woven into every id it writes."""
    return uuid4().hex[:10]


def _purge(tag: str) -> None:
    calls = (
        remote.select("calls", {"call_id": f"like.*{tag}*", "select": "id,appointment_id"}) or []
    )
    for call in calls:
        appointment_id = call.get("appointment_id")
        if appointment_id:
            remote.delete("appointments", {"id": f"eq.{appointment_id}"})
    remote.delete("appointments", {"rebooked_from_id": f"like.*{tag}*"})
    remote.delete("appointments", {"id": f"like.*{tag}*"})
    remote.delete("appointments", {"id": f"eq.{FIXTURE_APPOINTMENT}"})
    remote.delete("calls", {"call_id": f"like.*{tag}*"})
    remote.delete("wall_cancellations", {"provider_id": f"like.*{tag}*"})
    remote.delete("wall_documents", {"kind": f"like.*{tag}*"})
    remote.delete("suggestion_rejections", {"patient_id": f"like.*{tag}*"})


@pytest.fixture(autouse=True)
def clean_slate(tag: str):
    _purge(tag)
    yield
    _purge(tag)


@pytest.fixture
def slot_day(tag: str) -> date:
    """A calendar day nobody else's run is using — the confirmation job
    queries by date, so two concurrent runs would otherwise see each other's
    appointments."""
    return date(2030, 1, 1) + timedelta(days=int(tag[:4], 16) % 3000)


def _ctx(tmp_path: Path, call_id: str, *, said: str | None = None) -> Any:
    ctx = make_context(call_id=call_id, log_dir=tmp_path / "call-logs")
    if said:
        ctx.log.user_turn(said)
    return ctx


async def _book(
    tmp_path: Path,
    *,
    call_id: str,
    slot: datetime,
) -> None:
    ctx = _ctx(tmp_path, call_id, said="Quiero una cita con el médico de cabecera")
    remember_patient(ctx, P00042)
    action = BookAction(
        patient_id="P00042",
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
        slot=slot,
        policy_id="sanitas",
    )
    await persist_submission(ctx, action)


# ---------------------------------------------------------------------------
# the store itself
# ---------------------------------------------------------------------------


def test_every_product_table_is_reachable() -> None:
    """The migration ran and the service-role grants are in place. A `None`
    here means the table is missing, not that it is empty."""
    for table in (
        "calls",
        "appointments",
        "wall_cancellations",
        "rebooking_requests",
        "clinic_settings",
        "wall_documents",
        "suggestion_rejections",
    ):
        assert remote.select(table, {"limit": "1"}) is not None, f"{table} unreachable"


def test_calls_motivo_round_trips(tag: str) -> None:
    """An outbound call's motivo (confirmacion / recordatorio / call_now, or
    any other string — the column has no CHECK, unlike purpose/outcome)
    persists and reads back."""
    call = db.insert_call(
        call_id=f"OUT-{tag}",
        direction="outbound",
        purpose="confirmation",
        started_at="2026-09-19T18:00:00+00:00",
        motivo="recordatorio",
    )
    assert call.motivo == "recordatorio"
    reread = db.get_call_by_call_id(f"OUT-{tag}")
    assert reread is not None
    assert reread.motivo == "recordatorio"


def test_calls_motivo_defaults_to_null_for_inbound(tag: str) -> None:
    call = db.insert_call(
        call_id=f"IN-{tag}",
        direction="inbound",
        purpose="booking",
        started_at="2026-09-19T18:00:00+00:00",
    )
    assert call.motivo is None


def test_insert_call_updates_the_same_row_and_never_blanks_a_column(tag: str) -> None:
    """A retried identical submit (the platform's 409 "duplicate, treat as
    success") must update the row, not mint a second one — and a second write
    that does not know the motivo must not erase it."""
    first = db.insert_call(
        call_id=f"RETRY-{tag}",
        direction="outbound",
        purpose="confirmation",
        started_at="2026-09-19T18:00:00+00:00",
        duration_ms=4000,
        motivo="confirmacion",
    )
    second = db.insert_call(
        call_id=f"RETRY-{tag}",
        direction="outbound",
        purpose="confirmation",
        started_at="2026-09-19T18:00:00+00:00",
        outcome="confirmed",
    )
    assert second.id == first.id
    assert second.motivo == "confirmacion"
    assert second.duration_ms == 4000
    assert second.outcome == "confirmed"


def test_update_call_outcome_patches_a_queued_row(tag: str) -> None:
    """A scheduled outbound call is written once, queued, at insert_call time
    — its result lands later, off a webhook, through update_call_outcome."""
    db.insert_call(
        call_id=f"CALLNOW-{tag}",
        direction="outbound",
        purpose="reschedule",
        started_at="2026-09-19T18:00:00+00:00",
        motivo="call_now",
    )
    updated = db.update_call_outcome(
        f"CALLNOW-{tag}",
        outcome="reschedule",
        transcript="Sí, búsquenme otra",
        detail="handoff_to_voice_agent",
    )
    assert updated is not None
    assert updated.outcome == "reschedule"
    assert updated.transcript == "Sí, búsquenme otra"
    assert updated.detail == "handoff_to_voice_agent"

    # A later webhook that only knows the transcript must not blank the
    # outcome an earlier one already set.
    again = db.update_call_outcome(f"CALLNOW-{tag}", transcript="still there")
    assert again is not None
    assert again.outcome == "reschedule"
    assert again.transcript == "still there"

    # Never mints a row for an unknown call_id.
    assert db.update_call_outcome(f"NO-SUCH-CALL-{tag}", outcome="confirmed") is None


def test_rebooked_from_id_links_a_fresh_booking_to_the_one_it_replaces(
    tag: str, slot_day: date
) -> None:
    call = db.insert_call(
        call_id=f"REBOOK-{tag}",
        direction="inbound",
        purpose="booking",
        started_at="2026-09-19T18:00:00+00:00",
        outcome="book",
    )
    db.insert_appointment(
        id=f"OLD-{tag}",
        booking_call_id=call.id,
        status="cancelled",
        patient_id="P00042",
        slot_start=f"{slot_day.isoformat()}T10:00:00+02:00",
        slot_end=f"{slot_day.isoformat()}T10:15:00+02:00",
    )
    appt = db.insert_appointment(
        id=f"NEW-{tag}",
        booking_call_id=call.id,
        patient_id="P00042",
        slot_start=f"{slot_day.isoformat()}T11:00:00+02:00",
        slot_end=f"{slot_day.isoformat()}T11:15:00+02:00",
        rebooked_from_id=f"OLD-{tag}",
    )
    assert appt.rebooked_from_id == f"OLD-{tag}"
    reread = db.get_appointment(f"NEW-{tag}")
    assert reread is not None
    assert reread.rebooked_from_id == f"OLD-{tag}"


# ---------------------------------------------------------------------------
# booking
# ---------------------------------------------------------------------------


async def test_booking_creates_appointment_and_inbound_call_with_language(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    await _book(
        tmp_path,
        call_id=f"CALL-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
    )

    call = db.get_call_by_call_id(f"CALL-{tag}")
    assert call is not None
    assert call.direction == "inbound"
    assert call.purpose == "booking"
    assert call.outcome == "book"
    # Detected from the caller's own words ("Quiero una cita...").
    assert call.language == "es"
    assert call.appointment_id is not None

    appt = db.get_appointment(call.appointment_id)
    assert appt is not None
    assert appt.status == "scheduled"
    assert appt.patient_id == "P00042"
    assert appt.patient_name == "Marta Ruiz López"
    assert appt.provider_id == "PR01"
    assert appt.provider_name  # resolved from the catalogue
    assert appt.specialty_id == "general_practice"
    assert appt.site_id == "centro"
    assert appt.insurer == "sanitas"
    assert appt.booking_call_id == call.id
    assert appt.confirmation_call_id is None
    assert appt.rebooked_from_id is None
    # Rule 5: language lives on the call, never duplicated onto the row.
    assert not hasattr(appt, "language")


async def test_repeated_identical_booking_submit_does_not_double_insert(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    slot = datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID)
    await _book(tmp_path, call_id=f"CALL-{tag}", slot=slot)
    await _book(tmp_path, call_id=f"CALL-{tag}", slot=slot)  # a retried submit

    calls = remote.select("calls", {"call_id": f"eq.CALL-{tag}"}) or []
    assert len(calls) == 1
    appointments = db.list_appointments(date_from=slot_day, date_to=slot_day, patient_id="P00042")
    assert len(appointments) == 1


async def test_booking_on_a_handoff_call_links_back_to_the_cancelled_appointment(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    """CallSession.open stashes the handoff's appointment_id on
    ctx.state["rebooking_from_appointment_id"] the moment it is detected;
    _record_booking reads it back, so the booking a call_now rebooking call
    ends in is not an unrelated visit in the database."""
    ctx = _ctx(tmp_path, f"CANCEL-{tag}", said="Cancele mi cita")
    CallMemory.of(ctx).identified_patient = P00042
    await persist_submission(ctx, CancelAction(appointment_id=FIXTURE_APPOINTMENT))

    ctx = _ctx(tmp_path, f"REBOOKED-{tag}", said="Quiero otra fecha para mi cita")
    remember_patient(ctx, P00042)
    ctx.state["rebooking_from_appointment_id"] = FIXTURE_APPOINTMENT
    await persist_submission(
        ctx,
        BookAction(
            patient_id="P00042",
            provider_id="PR01",
            location_id="centro",
            appointment_type_id="review",
            slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
            policy_id="sanitas",
        ),
    )

    call = db.get_call_by_call_id(f"REBOOKED-{tag}")
    assert call is not None
    assert call.appointment_id is not None
    appt = db.get_appointment(call.appointment_id)
    assert appt is not None
    assert appt.rebooked_from_id == FIXTURE_APPOINTMENT


# ---------------------------------------------------------------------------
# cancellation / reschedule of a pre-existing (fixture) appointment
# ---------------------------------------------------------------------------


async def test_cancellation_backfills_unseen_appointment_and_updates_status(
    tmp_path: Path, tag: str
) -> None:
    """A0001 (P00042 / PR01 / centro, from vortex/clinic/fixtures.py) has
    never been booked through this database — exactly the normal case, since
    the read-only clinic never learns about our own bookings."""
    ctx = _ctx(tmp_path, f"CANCEL-{tag}", said="Quiero cancelar mi cita, por favor")
    CallMemory.of(ctx).identified_patient = P00042

    await persist_submission(ctx, CancelAction(appointment_id=FIXTURE_APPOINTMENT))

    appt = db.get_appointment(FIXTURE_APPOINTMENT)
    assert appt is not None
    assert appt.status == "cancelled"
    assert appt.patient_id == "P00042"
    assert appt.provider_id == "PR01"
    assert appt.site_id == "centro"

    call = db.get_call_by_call_id(f"CANCEL-{tag}")
    assert call is not None
    assert call.purpose == "cancellation"
    assert call.outcome == "cancel"
    assert call.appointment_id == FIXTURE_APPOINTMENT
    assert call.language == "es"
    # The discovering call is what booking_call_id points at, since this
    # database never saw a real booking call for A0001.
    assert appt.booking_call_id == call.id


async def test_reschedule_moves_slot_and_resets_status_to_scheduled(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    ctx = _ctx(tmp_path, f"MOVE-{tag}", said="I need to move my appointment")
    CallMemory.of(ctx).identified_patient = P00042

    await persist_submission(
        ctx,
        RescheduleAction(
            appointment_id=FIXTURE_APPOINTMENT,
            provider_id="PR02",
            location_id="norte",
            slot=datetime(slot_day.year, slot_day.month, slot_day.day, 11, 0, tzinfo=MADRID),
            policy_id="sanitas",
        ),
    )

    appt = db.get_appointment(FIXTURE_APPOINTMENT)
    assert appt is not None
    assert appt.status == "scheduled"
    assert appt.provider_id == "PR02"
    assert appt.site_id == "norte"
    assert appt.slot_start.startswith(f"{slot_day.isoformat()}T11:00")

    call = db.get_call_by_call_id(f"MOVE-{tag}")
    assert call is not None
    assert call.purpose == "reschedule"
    assert call.language == "en"


async def test_cancellation_of_unknown_appointment_with_no_identified_patient_is_skipped(
    tmp_path: Path, tag: str
) -> None:
    """Cannot back a row without knowing whose appointment it is; the call
    must not crash, and nothing false gets written."""
    ctx = _ctx(tmp_path, f"ANON-{tag}")
    await persist_submission(ctx, CancelAction(appointment_id=FIXTURE_APPOINTMENT))

    assert db.get_appointment(FIXTURE_APPOINTMENT) is None
    # The call itself is still recorded — only the appointment link is missing.
    call = db.get_call_by_call_id(f"ANON-{tag}")
    assert call is not None
    assert call.purpose == "cancellation"


# ---------------------------------------------------------------------------
# both directions are navigable
# ---------------------------------------------------------------------------


async def test_appointment_and_call_are_navigable_both_ways(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    await _book(
        tmp_path,
        call_id=f"CALL-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
    )

    call = db.get_call_by_call_id(f"CALL-{tag}")
    assert call is not None
    assert call.appointment_id is not None

    # appointment -> its booking call
    bundle = db.appointment_with_calls(call.appointment_id)
    assert bundle is not None
    assert bundle.booking_call.call_id == f"CALL-{tag}"
    assert bundle.confirmation_call is None

    # call -> its appointment
    found = db.call_with_appointment(call.id)
    assert found is not None
    found_call, found_appt = found
    assert found_call.id == call.id
    assert found_appt is not None
    assert found_appt.id == call.appointment_id

    # and the map a screen uses to get from a visit back to its transcript
    assert db.call_id_by_appointment()[call.appointment_id] == f"CALL-{tag}"


# ---------------------------------------------------------------------------
# wall cancellations (the board's Horarios cancel buttons)
# ---------------------------------------------------------------------------


def test_wall_cancellation_roundtrip(tag: str, slot_day: date) -> None:
    row = db.insert_wall_cancellation(
        provider_id=f"PR-{tag}",
        site_id="centro",
        slot_start=f"{slot_day.isoformat()}T09:00:00+02:00",
        appointment_id="A000645",
        patient_name="Marta Ruiz",
        provider_name="Dra. Uno",
    )
    assert row.id
    mine = [r for r in db.list_wall_cancellations() if r.provider_id == f"PR-{tag}"]
    assert len(mine) == 1
    assert mine[0].site_id == "centro"
    assert mine[0].slot_start == f"{slot_day.isoformat()}T09:00:00+02:00"
    assert mine[0].appointment_id == "A000645"


async def test_wall_cancel_row_flips_a_known_appointment_by_id(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    await _book(
        tmp_path,
        call_id=f"CALL-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
    )
    call = db.get_call_by_call_id(f"CALL-{tag}")
    assert call is not None and call.appointment_id is not None

    touched = db.cancel_appointment_row(appointment_id=call.appointment_id)
    assert touched == call.appointment_id
    assert db.get_appointment(call.appointment_id).status == "cancelled"
    # Idempotent: an already-cancelled row is not touched twice.
    assert db.cancel_appointment_row(appointment_id=call.appointment_id) is None


async def test_wall_cancel_row_falls_back_to_provider_and_minute(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    """A visit replayed from the log carries no appointment_id — the wall
    still has to cancel the row, keyed by doctor + minute."""
    await _book(
        tmp_path,
        call_id=f"CALL-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
    )
    call = db.get_call_by_call_id(f"CALL-{tag}")
    assert call is not None and call.appointment_id is not None

    touched = db.cancel_appointment_row(
        provider_id="PR01", slot_start=f"{slot_day.isoformat()}T10:00:00+02:00"
    )
    assert touched == call.appointment_id
    assert db.get_appointment(call.appointment_id).status == "cancelled"
    # A different minute of the same doctor must not match.
    assert (
        db.cancel_appointment_row(
            provider_id="PR01", slot_start=f"{slot_day.isoformat()}T10:15:00+02:00"
        )
        is None
    )


async def test_wall_cancel_rows_only_touches_the_window(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    later = slot_day + timedelta(days=11)
    await _book(
        tmp_path,
        call_id=f"IN-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
    )
    await _book(
        tmp_path,
        call_id=f"OUT-{tag}",
        slot=datetime(later.year, later.month, later.day, 10, 0, tzinfo=MADRID),
    )
    in_call = db.get_call_by_call_id(f"IN-{tag}")
    out_call = db.get_call_by_call_id(f"OUT-{tag}")
    assert in_call is not None and out_call is not None

    touched = db.cancel_appointment_rows(provider_id="PR01", day_from=slot_day, day_to=slot_day)
    assert in_call.appointment_id in touched
    assert out_call.appointment_id not in touched
    assert db.get_appointment(in_call.appointment_id).status == "cancelled"
    # Outside the range: untouched.
    assert db.get_appointment(out_call.appointment_id).status == "scheduled"


# ---------------------------------------------------------------------------
# confirmations
# ---------------------------------------------------------------------------


async def test_confirmation_call_confirms_appointment(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    await _book(
        tmp_path,
        call_id=f"BOOK-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
    )
    booking_call = db.get_call_by_call_id(f"BOOK-{tag}")
    assert booking_call is not None and booking_call.appointment_id is not None
    appointment_id = booking_call.appointment_id

    caller = confirmations.SimulatedConfirmationCaller(
        settings_describe={"clinic": "fake", "voice": "stub"},
    )
    results = await confirmations.run_confirmations(
        caller=caller, today=slot_day - timedelta(days=1)
    )

    by_id = {appt.id: result for appt, result in results}
    assert by_id[appointment_id].outcome == "confirmed"

    updated = db.get_appointment(appointment_id)
    assert updated is not None
    assert updated.status == "confirmed"
    assert updated.confirmation_call_id is not None
    confirmation_call = db.get_call(updated.confirmation_call_id)
    assert confirmation_call is not None
    assert confirmation_call.direction == "outbound"
    assert confirmation_call.purpose == "confirmation"
    assert confirmation_call.outcome == "confirmed"
    # Mirrors vortex.line.confirmation_calls.KNOWN_MOTIVOS: this job only ever
    # places the day-before "will you come" call.
    assert confirmation_call.motivo == "confirmacion"
    # Clean up the outbound call the job minted (its id is not tagged).
    remote.delete("calls", {"call_id": f"eq.{by_id[appointment_id].call_id}"})


async def test_confirmation_call_cancel_and_no_answer_branches(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    await _book(
        tmp_path,
        call_id=f"CANCELB-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 9, 0, tzinfo=MADRID),
    )
    await _book(
        tmp_path,
        call_id=f"NOANSW-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 12, 0, tzinfo=MADRID),
    )
    cancel_id = db.get_call_by_call_id(f"CANCELB-{tag}").appointment_id
    no_answer_id = db.get_call_by_call_id(f"NOANSW-{tag}").appointment_id

    caller = confirmations.SimulatedConfirmationCaller(
        force_outcome={cancel_id: "cancel", no_answer_id: "no_answer"},
    )
    results = await confirmations.run_confirmations(
        caller=caller, today=slot_day - timedelta(days=1)
    )

    outcomes = {appt.id: result.outcome for appt, result in results}
    assert outcomes[cancel_id] == "cancel"
    assert outcomes[no_answer_id] == "no_answer"

    assert db.get_appointment(cancel_id).status == "cancelled"
    no_answer_appt = db.get_appointment(no_answer_id)
    assert no_answer_appt.status == "scheduled"  # rule 2: unchanged
    assert no_answer_appt.confirmation_call_id is not None  # still recorded

    for appt, result in results:
        if appt.id in {cancel_id, no_answer_id}:
            remote.delete("calls", {"call_id": f"eq.{result.call_id}"})


async def test_confirmation_job_is_idempotent_within_a_day(
    tmp_path: Path, tag: str, slot_day: date
) -> None:
    await _book(
        tmp_path,
        call_id=f"IDEM-{tag}",
        slot=datetime(slot_day.year, slot_day.month, slot_day.day, 10, 0, tzinfo=MADRID),
    )
    appointment_id = db.get_call_by_call_id(f"IDEM-{tag}").appointment_id
    caller = confirmations.SimulatedConfirmationCaller()
    today = slot_day - timedelta(days=1)

    first = await confirmations.run_confirmations(caller=caller, today=today)
    second = await confirmations.run_confirmations(caller=caller, today=today)

    assert appointment_id in {appt.id for appt, _ in first}
    assert appointment_id not in {appt.id for appt, _ in second}  # not dialled again

    for appt, result in first:
        if appt.id == appointment_id:
            remote.delete("calls", {"call_id": f"eq.{result.call_id}"})


# ---------------------------------------------------------------------------
# clinic console documents
# ---------------------------------------------------------------------------


def test_clinic_settings_round_trip() -> None:
    """clinic_settings is a single shared row (id = 1), so this one puts back
    what it found."""
    before = db.get_clinic_settings()
    try:
        saved = db.put_clinic_settings(
            {
                "minimum_booking_lead_hours": 48,
                "patient_identification_fields_required": 2,
            }
        )
        assert saved["minimum_booking_lead_hours"] == 48
        assert saved["patient_identification_fields_required"] == 2
        assert db.get_clinic_settings()["minimum_booking_lead_hours"] == 48
        # Clamped, not trusted.
        assert (
            db.put_clinic_settings({"minimum_booking_lead_hours": 500})[
                "minimum_booking_lead_hours"
            ]
            == 96
        )
    finally:
        db.put_clinic_settings(before)


def test_wall_documents_and_suggestion_rejections(tag: str) -> None:
    kind = f"pathways-{tag}"
    assert db.get_wall_document(kind) is None
    db.put_wall_document(kind, {"pathways": [{"id": "annual"}]})
    assert db.get_wall_document(kind)["pathways"][0]["id"] == "annual"

    patient = f"P-{tag}"
    assert db.list_suggestion_rejections(patient) == []
    db.add_suggestion_rejection(patient, "first-visit-then-gap")
    db.add_suggestion_rejection(patient, "first-visit-then-gap")  # idempotent
    assert db.list_suggestion_rejections(patient) == ["first-visit-then-gap"]
