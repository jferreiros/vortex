"""SMS confirmations after an accepted book or cancel.

Covers the render helpers, the Twilio/dry-run clients, and the session hook:
an accepted book/cancel texts the calling number; everything else stays quiet.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from vortex.contract import (
    MADRID,
    Action,
    Appointment,
    BookAction,
    CancelAction,
    EscalateAction,
    NoAction,
    RegisterAction,
    RescheduleAction,
    SubmitResult,
    action_payload,
    action_route,
)
from vortex.line import session as session_module
from vortex.line import sms as sms_module
from vortex.line.session import CallSession
from vortex.line.sms import (
    SMS_DETAILS_BUDGET_SECS,
    SMS_SEND_TIMEOUT_SECS,
    DryRunSmsClient,
    SmsResult,
    TwilioSmsClient,
    action_fingerprint,
    booking_confirmation_text,
    cancellation_confirmation_text,
    format_slot_es,
    make_sms_client,
    resolve_details,
    twilio_is_configured,
)
from vortex.line.submit import remember_submitted_action, submitted_action
from vortex.line.twilio import StartPayload
from vortex.observability.tracing import mask_phone
from vortex.settings import Settings, get_settings, reset_settings

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=MADRID)
SLOT = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)
REMEMBERED_START = datetime(2026, 9, 30, 10, 0, tzinfo=MADRID)
CALLER = "+34600111222"
PATIENT = "P00042"


class AcceptingSubmitter:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="accepted", http_status=200)

    async def aclose(self) -> None:
        return None


class DuplicateSubmitter(AcceptingSubmitter):
    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="duplicate", http_status=409)


class DryRunSubmitter(AcceptingSubmitter):
    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        return SubmitResult(status="dry_run", detail="not sent")


class RejectingSubmitter(AcceptingSubmitter):
    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        return SubmitResult(status="rejected", http_status=422, detail="nope")


class OverlappingSubmitter(AcceptingSubmitter):
    """Holds the first POST open until a second one has been sent."""

    def __init__(self) -> None:
        super().__init__()
        self.overtaken = asyncio.Event()

    async def submit(self, call_id: str, action: Action) -> SubmitResult:
        self.sent.append((action_route(action), action_payload(action, call_id)))
        if len(self.sent) == 1:
            await self.overtaken.wait()
        else:
            self.overtaken.set()
        return SubmitResult(status="accepted", http_status=200)


class RecordingSmsClient(DryRunSmsClient):
    """Dry-run client that also keeps the typed ``SmsResult`` of every send."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SmsResult] = []

    async def send(self, *, to: str, body: str) -> SmsResult:
        result = await super().send(to=to, body=body)
        self.results.append(result)
        return result


def a_booking() -> BookAction:
    return BookAction(
        patient_id=PATIENT,
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
        slot=SLOT,
        policy_id="sanitas",
    )


def a_cancel() -> CancelAction:
    return CancelAction(appointment_id="A0001")


def make_session(
    settings: Settings,
    call_id: str,
    *,
    from_number: str | None = CALLER,
    submitter: AcceptingSubmitter | None = None,
) -> CallSession:
    params = {"from_number": from_number} if from_number else {}
    start = StartPayload(
        streamSid=f"MZ-{call_id}",
        callSid=call_id,
        customParameters=params,
    )
    session = CallSession.open(start, settings=settings, now=NOW)
    submitter = submitter or AcceptingSubmitter()
    session.submitter = submitter
    session.ctx.submitter = submitter
    session.sms = RecordingSmsClient()
    return session


def sms_events(settings: Settings, call_id: str) -> list[dict[str, Any]]:
    path = Path(settings.calls_log_path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return [x for x in lines if x["call_id"] == call_id and x["kind"].startswith("sms.")]


def one_sms_event(settings: Settings, call_id: str, kind: str) -> dict[str, Any]:
    """The single ``sms.*`` event of that kind, with its typed payload fields."""
    matching = [event for event in sms_events(settings, call_id) if event["kind"] == kind]
    assert len(matching) == 1
    return matching[0]


def remember_appointment(session: CallSession, *, start: datetime = REMEMBERED_START) -> None:
    appointment = Appointment(
        appointment_id="A0001",
        patient_id=PATIENT,
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
        start=start,
    )
    session.ctx.state.setdefault("diary_appointments", {})[appointment.appointment_id] = (
        appointment.model_dump(mode="json")
    )


# ---- render helpers ---------------------------------------------------------


def test_format_slot_es_uses_madrid_wall_clock() -> None:
    text = format_slot_es(SLOT)
    assert "jueves" in text
    assert "24" in text
    assert "septiembre" in text
    assert "16:30" in text


def test_format_slot_es_refuses_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="offset"):
        format_slot_es(SLOT.replace(tzinfo=None))


def test_booking_text_includes_doctor_and_site_when_known() -> None:
    text = booking_confirmation_text(
        when=SLOT, provider_name="Dr. Iglesia", location_name="Arenal Sur"
    )
    assert "Dr. Iglesia" in text
    assert "Arenal Sur" in text
    assert "16:30" in text
    assert "clínica" in text


def test_cancellation_text_falls_back_without_details() -> None:
    text = cancellation_confirmation_text()
    assert "Cita cancelada" in text
    assert "reservar" in text


# ---- clients ----------------------------------------------------------------


def test_make_sms_client_is_dry_run_without_twilio(offline_settings: Settings) -> None:
    assert not twilio_is_configured(offline_settings)
    client = make_sms_client(offline_settings)
    assert isinstance(client, DryRunSmsClient)


def test_twilio_is_configured_needs_from_or_messaging_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)
    reset_settings()
    assert not twilio_is_configured(get_settings())
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+34600999888")
    reset_settings()
    assert twilio_is_configured(get_settings())
    reset_settings()


@pytest.mark.asyncio
async def test_twilio_client_posts_form_body() -> None:
    client = TwilioSmsClient(
        "ACxxx",
        "token",
        from_number="+34600999888",
    )
    response = MagicMock()
    response.status_code = 201
    response.json.return_value = {"sid": "SMxxx"}
    response.text = "ok"
    client._http.post = AsyncMock(return_value=response)

    result = await client.send(to=CALLER, body="hola")

    assert result.status == "sent"
    assert result.sid == "SMxxx"
    kwargs = client._http.post.await_args.kwargs
    assert kwargs["data"]["To"] == CALLER
    assert kwargs["data"]["From"] == "+34600999888"
    assert kwargs["data"]["Body"] == "hola"
    await client.aclose()


@pytest.mark.asyncio
async def test_twilio_client_reports_http_errors() -> None:
    client = TwilioSmsClient(
        "ACxxx",
        "token",
        messaging_service_sid="MGxxx",
    )
    client._http.post = AsyncMock(side_effect=httpx.ConnectError("down"))

    result = await client.send(to=CALLER, body="hola")

    assert result.status == "failed"
    assert "ConnectError" in result.detail
    await client.aclose()


@pytest.mark.asyncio
async def test_the_drain_outlasts_the_whole_send_budget() -> None:
    """close() must not cancel a POST that is still inside the client's own timeout."""
    client = TwilioSmsClient("ACxxx", "token", from_number="+34600999888")

    assert client._http.timeout.read == SMS_SEND_TIMEOUT_SECS
    assert SMS_DETAILS_BUDGET_SECS + SMS_SEND_TIMEOUT_SECS <= session_module.SMS_DRAIN_TIMEOUT_SECS
    await client.aclose()


# ---- session hook -----------------------------------------------------------


@pytest.fixture
def sms_settings(offline_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Offline settings with the opt-in SMS flag turned on."""
    monkeypatch.setenv("VORTEX_SMS_CONFIRMATIONS", "true")
    reset_settings()
    yield get_settings()
    reset_settings()


@pytest.mark.asyncio
async def test_accepted_booking_sends_sms(sms_settings: Settings) -> None:
    session = make_session(sms_settings, "CA-book-sms")
    sms = session.sms
    assert isinstance(sms, RecordingSmsClient)

    await session.submit(a_booking())
    await session.close()

    assert len(sms.results) == 1
    assert sms.results[0].status == "dry_run"
    assert sms.results[0].to == CALLER
    event = one_sms_event(sms_settings, "CA-book-sms", "sms.dry_run")
    assert event["action_kind"] == "book"
    assert event["when"] == SLOT.isoformat()
    assert event["missing"] == []


@pytest.mark.asyncio
async def test_accepted_cancel_sends_sms(sms_settings: Settings) -> None:
    session = make_session(sms_settings, "CA-cancel-sms")
    remember_appointment(session)
    sms = session.sms
    assert isinstance(sms, RecordingSmsClient)

    await session.submit(a_cancel())
    await session.close()

    assert len(sms.results) == 1
    assert sms.results[0].status == "dry_run"
    assert sms.results[0].to == CALLER
    event = one_sms_event(sms_settings, "CA-cancel-sms", "sms.dry_run")
    assert event["action_kind"] == "cancel"
    assert event["when"] == REMEMBERED_START.isoformat()
    assert event["appointment_id"] == "A0001"


@pytest.mark.asyncio
async def test_cancel_without_remembered_appointment_still_texts(
    sms_settings: Settings,
) -> None:
    session = make_session(sms_settings, "CA-cancel-bare")
    sms = session.sms
    assert isinstance(sms, RecordingSmsClient)

    await session.submit(a_cancel())
    await session.close()

    assert len(sms.results) == 1
    assert sms.results[0].status == "dry_run"
    assert sms.results[0].to == CALLER
    event = one_sms_event(sms_settings, "CA-cancel-bare", "sms.dry_run")
    assert event["action_kind"] == "cancel"
    assert event["when"] == ""
    assert event["missing"] == ["appointment_details"]


@pytest.mark.asyncio
async def test_resolve_details_uses_the_remembered_appointment(
    offline_settings: Settings,
) -> None:
    session = make_session(offline_settings, "CA-cancel-details")
    remember_appointment(session)

    known = await resolve_details(session.ctx, a_cancel())
    session.ctx.state["diary_appointments"].clear()
    unknown = await resolve_details(session.ctx, a_cancel())
    await session.close()

    assert known.when == REMEMBERED_START
    assert known.provider_name == "Dra. Ortiz"
    assert known.location_name == "Arenal Centro"
    assert known.missing == []
    assert unknown.when is None
    assert unknown.missing == ["appointment_details"]


@pytest.mark.asyncio
async def test_resolve_details_drops_a_naive_remembered_start(
    offline_settings: Settings,
) -> None:
    session = make_session(offline_settings, "CA-cancel-naive")
    remember_appointment(session, start=REMEMBERED_START.replace(tzinfo=None))

    details = await resolve_details(session.ctx, a_cancel())
    await session.close()

    assert details.when is None
    assert details.missing == ["naive_appointment_start"]
    text = cancellation_confirmation_text(when=details.when)
    assert "Cita cancelada" in text
    assert "septiembre" not in text


@pytest.mark.asyncio
async def test_a_hung_catalogue_cannot_spend_the_whole_budget(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lookup has its own share, so what is left of the budget stays the POST's."""
    session = make_session(offline_settings, "CA-slow-catalogue")
    monkeypatch.setattr(sms_module, "SMS_DETAILS_BUDGET_SECS", 0.01)

    async def never_answers() -> Any:
        await asyncio.sleep(SMS_SEND_TIMEOUT_SECS)
        raise AssertionError("the detail budget should have cut the lookup")

    monkeypatch.setattr(session.ctx.clinic, "catalogue", never_answers)

    details = await resolve_details(session.ctx, a_booking())
    await session.close()

    assert details.when == SLOT
    assert details.missing == ["catalogue:TimeoutError"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        NoAction(reason="out_of_scope"),
        RegisterAction(
            given_name="Ana",
            first_surname="García",
            second_surname="López",
            national_id="12345678Z",
            date_of_birth=date(1990, 1, 1),
            phone=CALLER,
            email="ana@example.com",
            insurer="sanitas",
        ),
        RescheduleAction(
            appointment_id="A0001",
            provider_id="PR05",
            location_id="sur",
            slot=SLOT,
            policy_id="sanitas",
        ),
    ],
)
async def test_non_book_cancel_actions_do_not_sms(sms_settings: Settings, action: Action) -> None:
    session = make_session(sms_settings, "CA-no-sms")
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    await session.submit(action)
    await session.close()

    assert sms.sent == []


@pytest.mark.asyncio
async def test_missing_from_number_skips_sms(sms_settings: Settings) -> None:
    session = make_session(sms_settings, "CA-no-from", from_number=None)
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    await session.submit(a_booking())
    await session.close()

    assert sms.sent == []


@pytest.mark.asyncio
async def test_sms_force_to_overrides_caller(
    sms_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo override: every confirmation goes to VORTEX_SMS_FORCE_TO."""
    monkeypatch.setenv("VORTEX_SMS_FORCE_TO", "+34600000000")
    reset_settings()
    settings = get_settings()
    session = make_session(settings, "CA-force-to", from_number="+34600999888")
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    await session.submit(a_booking())
    await session.close()

    assert len(sms.sent) == 1
    assert sms.sent[0][0] == "+34600000000"


@pytest.mark.asyncio
@pytest.mark.parametrize("submitter_cls", [DryRunSubmitter, RejectingSubmitter])
async def test_non_accepted_submit_skips_sms(
    sms_settings: Settings, submitter_cls: type[AcceptingSubmitter]
) -> None:
    session = make_session(sms_settings, "CA-not-accepted", submitter=submitter_cls())
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    await session.submit(a_booking())
    await session.close()

    assert sms.sent == []


@pytest.mark.asyncio
async def test_duplicate_status_does_not_double_text(sms_settings: Settings) -> None:
    session = make_session(sms_settings, "CA-dup", submitter=AcceptingSubmitter())
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)
    booking = a_booking()

    await session.submit(booking)
    session.submitter = DuplicateSubmitter()
    session.ctx.submitter = session.submitter
    await session.submit(booking)
    await session.close()

    assert len(sms.sent) == 1
    assert action_fingerprint(booking) in session._sms_notified


@pytest.mark.asyncio
async def test_overlapping_submissions_text_their_own_action(
    sms_settings: Settings,
) -> None:
    """A booking whose POST is overtaken must not text the other action."""
    submitter = OverlappingSubmitter()
    session = make_session(sms_settings, "CA-overlap", submitter=submitter)
    remember_appointment(session)
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    await asyncio.gather(session.submit(a_booking()), session.submit(a_cancel()))
    await session.close()

    bodies = [body for _, body in sms.sent]
    assert len(bodies) == 2
    assert sum("Cita confirmada" in body for body in bodies) == 1
    assert sum("Cita cancelada" in body for body in bodies) == 1


@pytest.mark.asyncio
async def test_submit_action_tool_path_also_sends_sms(sms_settings: Settings) -> None:
    session = make_session(sms_settings, "CA-tool-sms")
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)
    booking = a_booking()

    await session.call_tool(
        "submit_action",
        {"action": {"kind": "book", **booking.model_dump(mode="json")}},
    )
    await session.close()

    assert len(sms.sent) == 1
    assert sms.sent[0][0] == CALLER


@pytest.mark.asyncio
async def test_sms_stays_silent_without_the_opt_in(offline_settings: Settings) -> None:
    assert not offline_settings.sms_confirmations
    session = make_session(offline_settings, "CA-opt-in")
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    await session.submit(a_booking())
    await session.close()

    assert sms.sent == []


@pytest.mark.asyncio
async def test_submit_records_the_action_the_arbiter_decided(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VORTEX_JEV_ARBITER", "true")
    reset_settings()
    session = make_session(get_settings(), "CA-arbiter-state")
    escalation = EscalateAction(reason="medical_emergency")

    async def escalate_instead(ctx: Any, action: Action) -> Action:
        return escalation

    from vortex.jev import arbiter

    monkeypatch.setattr(arbiter, "review", escalate_instead)

    await session.submit(NoAction(reason="patient_not_found"))
    await session.close()

    routes = [route for route, _ in session.submitter.sent]  # type: ignore[attr-defined]
    assert routes == [action_route(escalation)]
    assert submitted_action(session.ctx, NoAction(reason="patient_not_found")) == escalation
    reset_settings()


@pytest.mark.asyncio
async def test_a_booking_the_submission_replaced_sends_no_sms(
    sms_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The arbiter can turn a booking into an escalation before the POST."""
    session = make_session(sms_settings, "CA-arbiter-sms")
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    async def submit_an_escalation(ctx: Any, args: Any) -> SubmitResult:
        remember_submitted_action(ctx, EscalateAction(reason="medical_emergency"))
        return SubmitResult(status="accepted", http_status=200)

    monkeypatch.setattr(session_module, "submit_action", submit_an_escalation)

    await session.submit(a_booking())
    await session.close()

    assert sms.sent == []


@pytest.mark.asyncio
async def test_sms_events_never_persist_the_number_or_the_body(
    sms_settings: Settings,
) -> None:
    session = make_session(sms_settings, "CA-sms-privacy")

    await session.submit(a_booking())
    await session.close()

    logged = sms_events(sms_settings, "CA-sms-privacy")
    assert [event["kind"] for event in logged] == ["sms.sending", "sms.dry_run"]
    for event in logged:
        assert event["to"] == mask_phone(CALLER)
        assert "body" not in event
        assert "provider_name" not in event
        assert "location_name" not in event
        assert CALLER not in json.dumps(event, ensure_ascii=False)


@pytest.mark.asyncio
async def test_sms_disabled_flag_skips(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VORTEX_SMS_CONFIRMATIONS", "false")
    reset_settings()
    settings = get_settings()
    session = make_session(settings, "CA-disabled")
    sms = session.sms
    assert isinstance(sms, DryRunSmsClient)

    await session.submit(a_booking())
    await session.close()

    assert sms.sent == []
    reset_settings()
