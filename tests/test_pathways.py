"""Outbound-call pathway registry and demo/ops status."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from vortex.line.confirmation_calls import (
    CANCELLATION_REBOOKING_JOB,
    confirmation_store_from_settings,
)
from vortex.line.pathways import (
    PATHWAYS,
    PathwayEvent,
    fire_pathway,
    pathway_for,
    resolve_target_phone,
)
from vortex.settings import Settings

MADRID = ZoneInfo("Europe/Madrid")


def test_builtin_pathways_are_wired_to_registered_jobs() -> None:
    assert pathway_for("appointment_cancelled").job == CANCELLATION_REBOOKING_JOB
    assert pathway_for("appointment_cancelled").motivo == "call_now"
    assert pathway_for("appointment_booked").job == "appointment_confirmation"
    assert pathway_for("appointment_booked").motivo == "programada"


def test_unknown_pathway_is_a_loud_programmer_error() -> None:
    with pytest.raises(KeyError, match="unknown outbound-call pathway"):
        pathway_for("typo")


@pytest.mark.parametrize(
    ("record", "fallback", "expected"),
    [
        ("612 345 678", "+34600000000", "+34612345678"),
        ("", "612 345 678", "+34612345678"),
        ("+44 7700 900123", "+34600000000", "+447700900123"),
        ("", "", ""),
    ],
)
def test_target_is_record_first_then_optional_fallback(
    record: str, fallback: str, expected: str
) -> None:
    assert resolve_target_phone(record, fallback) == expected


@pytest.mark.anyio
async def test_cancel_pathway_queues_immediate_call_without_dialling(tmp_path) -> None:
    settings = Settings(
        confirmation_calls=True,
        confirmation_calls_path=str(tmp_path / "calls.json"),
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=MADRID)
    call = await fire_pathway(
        settings,
        "appointment_cancelled",
        PathwayEvent(
            to="612 345 678",
            appointment_at=now + timedelta(days=1),
            patient_id="P1",
            appointment_id="A1",
        ),
        now=now,
    )
    assert call is not None
    assert call.to == "+34612345678"
    assert call.motivo == "call_now"
    assert call.job == CANCELLATION_REBOOKING_JOB
    assert call.call_at == now.isoformat()
    rows = confirmation_store_from_settings(settings)._read()
    assert [row.confirmation_id for row in rows] == [call.confirmation_id]


@pytest.mark.anyio
async def test_cancel_pathway_empty_target_is_a_guard_not_an_error(tmp_path) -> None:
    settings = Settings(
        confirmation_calls=True,
        confirmation_calls_path=str(tmp_path / "calls.json"),
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=MADRID)
    call = await fire_pathway(
        settings,
        "appointment_cancelled",
        PathwayEvent(to="", appointment_at=now + timedelta(days=1)),
        now=now,
    )
    assert call is None


@pytest.mark.anyio
async def test_cancel_pathway_loop_guard_skips_redial(tmp_path) -> None:
    settings = Settings(
        confirmation_calls=True,
        confirmation_calls_path=str(tmp_path / "calls.json"),
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=MADRID)
    call = await fire_pathway(
        settings,
        "appointment_cancelled",
        PathwayEvent(
            to="+34612345678",
            appointment_at=now + timedelta(days=1),
            already_offered_reschedule=True,
        ),
        now=now,
    )
    assert call is None


@pytest.mark.anyio
async def test_status_endpoint_exposes_runtime_readiness(monkeypatch) -> None:
    import vortex.api.pathways as api

    settings = Settings(
        confirmation_calls=True,
        twilio_account_sid="AC-test",
        twilio_auth_token="secret",
        twilio_from_number="+3197000000000",
        public_base_url="https://line.example.invalid",
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    response = await api.list_pathways()
    import json

    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["enabled"] is True
    assert payload["twilio_ready"] is True
    assert {row["name"] for row in payload["pathways"]} == set(PATHWAYS)
    assert all(row["job_registered"] for row in payload["pathways"])
