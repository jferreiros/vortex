"""database/: the product's own persistence layer.

Uses ``evals.common.context.make_context`` for a real ``ToolContext`` over
``FakeClinicClient`` — the same fixtures the rest of the offline suite reads
(P00042 / PR01 / A0001 come straight from ``vortex/clinic/fixtures.py``), and
a fresh SQLite file per test (``tmp_path``) so tests never share state, the
same rule every call gets its own pipeline.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from database import confirmations, db
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

MADRID = ZoneInfo("Europe/Madrid")

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
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "vortex_product.db"


def _ctx(tmp_path: Path, call_id: str = "CALL-1", *, said: str | None = None):
    ctx = make_context(call_id=call_id, log_dir=tmp_path / "call-logs")
    if said:
        ctx.log.user_turn(said)
    return ctx


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_migrate_is_idempotent(db_path: Path) -> None:
    conn1 = db.connect(db_path)
    conn1.close()
    conn2 = db.connect(db_path)  # must not fail re-running the same migration
    version = conn2.execute("PRAGMA user_version").fetchone()[0]
    conn2.close()
    assert version == 1


# ---------------------------------------------------------------------------
# booking
# ---------------------------------------------------------------------------


async def _book(tmp_path: Path, db_path: Path, *, call_id: str = "CALL-1") -> None:
    ctx = _ctx(tmp_path, call_id, said="Quiero una cita con el médico de cabecera")
    remember_patient(ctx, P00042)
    action = BookAction(
        patient_id="P00042",
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
        slot=datetime(2026, 9, 25, 10, 0, tzinfo=MADRID),
        policy_id="sanitas",
    )
    await persist_submission(ctx, action, db_path=db_path)


@pytest.mark.asyncio
async def test_booking_creates_appointment_and_inbound_call_with_language(
    tmp_path: Path, db_path: Path
) -> None:
    await _book(tmp_path, db_path)

    with db.connection(db_path) as conn:
        call = db.get_call_by_call_id(conn, "CALL-1")
        assert call is not None
        assert call.direction == "inbound"
        assert call.purpose == "booking"
        assert call.outcome == "book"
        # Detected from the caller's own words ("Quiero una cita...").
        assert call.language == "es"
        assert call.appointment_id is not None

        appt = db.get_appointment(conn, call.appointment_id)
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
        # Rule 5: language lives on the call, never duplicated onto the row.
        assert not hasattr(appt, "language")


@pytest.mark.asyncio
async def test_repeated_identical_booking_submit_does_not_double_insert(
    tmp_path: Path, db_path: Path
) -> None:
    """The platform's own 409 "duplicate, treat as success" must not mint a
    second appointment for the same call."""
    await _book(tmp_path, db_path)
    await _book(tmp_path, db_path)  # same call_id, same action: a retried submit

    with db.connection(db_path) as conn:
        rows = conn.execute("SELECT COUNT(*) AS n FROM appointments").fetchone()
        assert rows["n"] == 1
        calls = conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# cancellation / reschedule of a pre-existing (fixture) appointment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_backfills_unseen_appointment_and_updates_status(
    tmp_path: Path, db_path: Path
) -> None:
    """A0001 (P00042 / PR01 / centro, from vortex/clinic/fixtures.py) has
    never been booked through this database — exactly the normal case,
    since the read-only clinic never learns about our own bookings (see
    database/hooks.py, _backfill_appointment)."""
    ctx = _ctx(tmp_path, "CALL-2", said="Quiero cancelar mi cita, por favor")
    CallMemory.of(ctx).identified_patient = P00042

    await persist_submission(ctx, CancelAction(appointment_id="A0001"), db_path=db_path)

    with db.connection(db_path) as conn:
        appt = db.get_appointment(conn, "A0001")
        assert appt is not None
        assert appt.status == "cancelled"
        assert appt.patient_id == "P00042"
        assert appt.provider_id == "PR01"
        assert appt.site_id == "centro"

        call = db.get_call_by_call_id(conn, "CALL-2")
        assert call is not None
        assert call.purpose == "cancellation"
        assert call.outcome == "cancel"
        assert call.appointment_id == "A0001"
        assert call.language == "es"
        # The discovering call is what booking_call_id points at, since this
        # database never saw a real booking call for A0001.
        assert appt.booking_call_id == call.id


@pytest.mark.asyncio
async def test_reschedule_moves_slot_and_resets_status_to_scheduled(
    tmp_path: Path, db_path: Path
) -> None:
    ctx = _ctx(tmp_path, "CALL-3", said="I need to move my appointment")
    CallMemory.of(ctx).identified_patient = P00042

    action = RescheduleAction(
        appointment_id="A0001",
        provider_id="PR02",
        location_id="norte",
        slot=datetime(2026, 10, 5, 11, 0, tzinfo=MADRID),
        policy_id="sanitas",
    )
    await persist_submission(ctx, action, db_path=db_path)

    with db.connection(db_path) as conn:
        appt = db.get_appointment(conn, "A0001")
        assert appt is not None
        assert appt.status == "scheduled"
        assert appt.provider_id == "PR02"
        assert appt.site_id == "norte"
        assert appt.slot_start.startswith("2026-10-05T11:00")

        call = db.get_call_by_call_id(conn, "CALL-3")
        assert call is not None
        assert call.purpose == "reschedule"
        assert call.language == "en"


@pytest.mark.asyncio
async def test_cancellation_of_unknown_appointment_with_no_identified_patient_is_skipped(
    tmp_path: Path, db_path: Path
) -> None:
    """Cannot back a row without knowing whose appointment it is; the call
    must not crash, and nothing false gets written."""
    ctx = _ctx(tmp_path, "CALL-4")
    await persist_submission(ctx, CancelAction(appointment_id="A0001"), db_path=db_path)

    with db.connection(db_path) as conn:
        assert db.get_appointment(conn, "A0001") is None
        # The call itself is still recorded — only the appointment link is missing.
        call = db.get_call_by_call_id(conn, "CALL-4")
        assert call is not None
        assert call.purpose == "cancellation"


# ---------------------------------------------------------------------------
# both foreign keys are navigable both ways
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appointment_and_call_are_navigable_both_ways(tmp_path: Path, db_path: Path) -> None:
    await _book(tmp_path, db_path)

    with db.connection(db_path) as conn:
        call = db.get_call_by_call_id(conn, "CALL-1")
        assert call is not None

        # appointment -> its booking call
        bundle = db.appointment_with_calls(conn, call.appointment_id)
        assert bundle is not None
        assert bundle.booking_call.call_id == "CALL-1"
        assert bundle.confirmation_call is None

        # call -> its appointment
        found = db.call_with_appointment(conn, call.id)
        assert found is not None
        found_call, found_appt = found
        assert found_call.id == call.id
        assert found_appt is not None
        assert found_appt.id == call.appointment_id


def test_every_appointment_has_a_booking_call(db_path: Path) -> None:
    """The NOT NULL + FK on booking_call_id is the schema itself enforcing
    rule 1 — inserting an appointment with an unknown call must fail."""
    with db.connection(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_appointment(
                conn,
                id="APT-X",
                booking_call_id=999_999,  # no such call
                patient_id="P00042",
                slot_start="2026-09-25T10:00:00+02:00",
                slot_end="2026-09-25T10:15:00+02:00",
            )


# ---------------------------------------------------------------------------
# confirmations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_call_confirms_appointment(tmp_path: Path, db_path: Path) -> None:
    await _book(tmp_path, db_path, call_id="CALL-BOOK")
    with db.connection(db_path) as conn:
        appt = db.get_appointment(conn, db.get_call_by_call_id(conn, "CALL-BOOK").appointment_id)

    # The fixed booking above is for 2026-09-25; run the job as if "today"
    # were the day before it.
    conn = db.connect(db_path)
    try:
        caller = confirmations.SimulatedConfirmationCaller(
            log_path=tmp_path / "calls.jsonl", settings_describe={"clinic": "fake", "voice": "stub"}
        )
        results = await confirmations.run_confirmations(
            conn, caller=caller, today=datetime(2026, 9, 24).date()
        )
    finally:
        conn.close()

    assert len(results) == 1
    result_appt, result = results[0]
    assert result_appt.id == appt.id
    assert result.outcome == "confirmed"

    with db.connection(db_path) as conn:
        updated = db.get_appointment(conn, appt.id)
        assert updated.status == "confirmed"
        assert updated.confirmation_call_id is not None
        confirmation_call = db.get_call(conn, updated.confirmation_call_id)
        assert confirmation_call.direction == "outbound"
        assert confirmation_call.purpose == "confirmation"
        assert confirmation_call.outcome == "confirmed"


@pytest.mark.asyncio
async def test_confirmation_call_cancel_and_no_answer_branches(
    tmp_path: Path, db_path: Path
) -> None:
    await _book(tmp_path, db_path, call_id="CALL-CANCEL-BRANCH")
    await _book(tmp_path, db_path, call_id="CALL-NOANSWER-BRANCH")
    with db.connection(db_path) as conn:
        appts = [
            r["id"] for r in conn.execute("SELECT id FROM appointments ORDER BY id").fetchall()
        ]
    cancel_id, no_answer_id = appts[0], appts[1]

    conn = db.connect(db_path)
    try:
        caller = confirmations.SimulatedConfirmationCaller(
            log_path=tmp_path / "calls.jsonl",
            force_outcome={cancel_id: "cancel", no_answer_id: "no_answer"},
        )
        results = await confirmations.run_confirmations(
            conn, caller=caller, today=datetime(2026, 9, 24).date()
        )
    finally:
        conn.close()

    outcomes = {appt.id: result.outcome for appt, result in results}
    assert outcomes[cancel_id] == "cancel"
    assert outcomes[no_answer_id] == "no_answer"

    with db.connection(db_path) as conn:
        assert db.get_appointment(conn, cancel_id).status == "cancelled"
        no_answer_appt = db.get_appointment(conn, no_answer_id)
        assert no_answer_appt.status == "scheduled"  # rule 2: unchanged
        assert no_answer_appt.confirmation_call_id is not None  # still recorded


@pytest.mark.asyncio
async def test_confirmation_job_is_idempotent_within_a_day(tmp_path: Path, db_path: Path) -> None:
    await _book(tmp_path, db_path, call_id="CALL-IDEMPOTENT")
    caller = confirmations.SimulatedConfirmationCaller(log_path=tmp_path / "calls.jsonl")
    today = datetime(2026, 9, 24).date()

    conn = db.connect(db_path)
    try:
        first = await confirmations.run_confirmations(conn, caller=caller, today=today)
        second = await confirmations.run_confirmations(conn, caller=caller, today=today)
    finally:
        conn.close()

    assert len(first) == 1
    assert len(second) == 0  # already confirmed; not dialled again
