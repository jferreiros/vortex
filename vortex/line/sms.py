"""SMS confirmations for accepted book/cancel submits.

Sends a short Spanish text to the calling number after the platform accepts a
``BookAction`` or ``CancelAction``. Failures are logged and never change the
submit result: the scoring path must not wait on Twilio.

Two clients share one interface:

- ``TwilioSmsClient``  live POST to Twilio's Messages API.
- ``DryRunSmsClient``  records what would have been sent (no network).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

import httpx

from vortex.contract import (
    MADRID,
    Action,
    Appointment,
    BookAction,
    CancelAction,
    Catalogue,
    ToolContext,
)
from vortex.settings import Settings

TWILIO_MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

# One budget for a whole confirmation: the catalogue lookup that fills the body
# and the POST that sends it. ``CallSession`` drains for exactly this long, so a
# hangup never cancels a Twilio response that is still inside its own timeout.
SMS_BUDGET_SECS = 8.0
# The lookup's share of the budget. Whatever is left over is the POST's.
SMS_DETAILS_BUDGET_SECS = 2.0
SMS_SEND_TIMEOUT_SECS = SMS_BUDGET_SECS - SMS_DETAILS_BUDGET_SECS
assert SMS_SEND_TIMEOUT_SECS > 0, "the lookup must not eat the whole SMS budget"

WEEKDAYS_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

SmsStatus = Literal["sent", "dry_run", "skipped", "failed"]


@dataclass(frozen=True)
class SmsResult:
    status: SmsStatus
    detail: str = ""
    to: str = ""
    body: str = ""
    sid: str = ""


class SmsClient(Protocol):
    async def send(self, *, to: str, body: str) -> SmsResult: ...

    async def aclose(self) -> None: ...


class DryRunSmsClient:
    """No Twilio keys. Records what would have gone out."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, *, to: str, body: str) -> SmsResult:
        self.sent.append((to, body))
        return SmsResult(
            status="dry_run", detail="no Twilio credentials: not sent", to=to, body=body
        )

    async def aclose(self) -> None:
        return None


class TwilioSmsClient:
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        *,
        messaging_service_sid: str = "",
        from_number: str = "",
        timeout: float = SMS_SEND_TIMEOUT_SECS,
    ):
        if not messaging_service_sid and not from_number:
            raise ValueError("Twilio SMS needs TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM_NUMBER")
        self._account_sid = account_sid
        self._messaging_service_sid = messaging_service_sid
        self._from_number = from_number
        self._http = httpx.AsyncClient(
            auth=(account_sid, auth_token),
            timeout=timeout,
        )

    async def send(self, *, to: str, body: str) -> SmsResult:
        data: dict[str, str] = {"To": to, "Body": body}
        if self._messaging_service_sid:
            data["MessagingServiceSid"] = self._messaging_service_sid
        else:
            data["From"] = self._from_number
        url = TWILIO_MESSAGES_URL.format(account_sid=self._account_sid)
        try:
            response = await self._http.post(url, data=data)
        except httpx.HTTPError as exc:
            return SmsResult(
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
                to=to,
                body=body,
            )
        if response.status_code in (200, 201):
            sid = ""
            try:
                sid = str(response.json().get("sid") or "")
            except ValueError:
                sid = ""
            return SmsResult(status="sent", detail="accepted by Twilio", to=to, body=body, sid=sid)
        return SmsResult(
            status="failed",
            detail=f"HTTP {response.status_code}: {response.text[:300]}",
            to=to,
            body=body,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def twilio_is_configured(settings: Settings) -> bool:
    """True when the env has enough Twilio material to attempt a real send."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return False
    return bool(settings.twilio_messaging_service_sid or settings.twilio_from_number)


def make_sms_client(settings: Settings) -> SmsClient:
    if twilio_is_configured(settings):
        return TwilioSmsClient(
            settings.twilio_account_sid,
            settings.twilio_auth_token,
            messaging_service_sid=settings.twilio_messaging_service_sid,
            from_number=settings.twilio_from_number,
        )
    return DryRunSmsClient()


def format_slot_es(when: datetime) -> str:
    """``jueves 24 de septiembre a las 16:30`` in Europe/Madrid.

    A naive ``when`` is refused: ``astimezone`` would read it in the machine's
    timezone and text the caller an hour the clinic never offered.
    """
    if when.utcoffset() is None:
        raise ValueError(f"appointment datetime must carry an offset: {when.isoformat()}")
    local = when.astimezone(MADRID)
    weekday = WEEKDAYS_ES[local.weekday()]
    month = MONTHS_ES[local.month - 1]
    return f"{weekday} {local.day} de {month} a las {local.strftime('%H:%M')}"


def booking_confirmation_text(
    *,
    when: datetime,
    provider_name: str = "",
    location_name: str = "",
) -> str:
    stamp = format_slot_es(when)
    if provider_name and location_name:
        head = f"Cita confirmada con {provider_name} en {location_name}: {stamp}."
    elif provider_name:
        head = f"Cita confirmada con {provider_name}: {stamp}."
    elif location_name:
        head = f"Cita confirmada en {location_name}: {stamp}."
    else:
        head = f"Cita confirmada: {stamp}."
    return f"{head} Para cambios o cancelaciones, llama a la clínica."


def cancellation_confirmation_text(
    *,
    when: datetime | None = None,
    provider_name: str = "",
    location_name: str = "",
) -> str:
    if when is None:
        return "Cita cancelada: hemos cancelado tu cita. Para reservar otra, llama a la clínica."
    stamp = format_slot_es(when)
    if provider_name and location_name:
        head = f"Cita cancelada con {provider_name} en {location_name}: {stamp}."
    elif provider_name:
        head = f"Cita cancelada con {provider_name}: {stamp}."
    elif location_name:
        head = f"Cita cancelada en {location_name}: {stamp}."
    else:
        head = f"Cita cancelada: hemos cancelado tu cita de {stamp}."
    return f"{head} Para reservar otra cita, llama a la clínica."


def action_fingerprint(action: Action) -> str:
    """Stable id so a 409 duplicate does not text the caller twice."""
    return action.model_dump_json()


def remembered_appointment(ctx: ToolContext, appointment_id: str) -> Appointment | None:
    raw = ctx.state.get("diary_appointments", {}).get(appointment_id)
    if not raw:
        return None
    return Appointment.model_validate(raw)


@dataclass
class AppointmentDetails:
    when: datetime | None = None
    provider_id: str = ""
    location_id: str = ""
    provider_name: str = ""
    location_name: str = ""
    missing: list[str] = field(default_factory=list)


def _names_from_catalogue(
    catalogue: Catalogue, *, provider_id: str, location_id: str
) -> tuple[str, str]:
    provider_name = ""
    location_name = ""
    if provider_id:
        for provider in catalogue.providers:
            if provider.provider_id == provider_id:
                provider_name = provider.name
                break
    if location_id:
        for location in catalogue.locations:
            if location.location_id == location_id:
                location_name = location.name
                break
    return provider_name, location_name


async def resolve_details(ctx: ToolContext, action: Action) -> AppointmentDetails:
    """Best-effort date/doctor/site for the SMS body. Never raises."""
    details = AppointmentDetails()
    if isinstance(action, BookAction):
        details.when = action.slot
        details.provider_id = action.provider_id
        details.location_id = action.location_id
    elif isinstance(action, CancelAction):
        known = remembered_appointment(ctx, action.appointment_id)
        if known is None:
            details.missing.append("appointment_details")
            return details
        if known.start.utcoffset() is not None:
            details.when = known.start
        else:
            details.missing.append("naive_appointment_start")
        details.provider_id = known.provider_id
        details.location_id = known.location_id
    else:
        details.missing.append("unsupported_action")
        return details

    try:
        catalogue = await asyncio.wait_for(ctx.clinic.catalogue(), SMS_DETAILS_BUDGET_SECS)
    except Exception as exc:  # noqa: BLE001 - SMS must not break the call
        details.missing.append(f"catalogue:{type(exc).__name__}")
        return details

    details.provider_name, details.location_name = _names_from_catalogue(
        catalogue,
        provider_id=details.provider_id,
        location_id=details.location_id,
    )
    if details.provider_id and not details.provider_name:
        details.missing.append("provider_name")
    if details.location_id and not details.location_name:
        details.missing.append("location_name")
    return details


def render_confirmation_text(action: Action, details: AppointmentDetails) -> str:
    if isinstance(action, BookAction):
        assert details.when is not None
        return booking_confirmation_text(
            when=details.when,
            provider_name=details.provider_name,
            location_name=details.location_name,
        )
    if isinstance(action, CancelAction):
        return cancellation_confirmation_text(
            when=details.when,
            provider_name=details.provider_name,
            location_name=details.location_name,
        )
    raise TypeError(f"SMS is only for book/cancel, not {type(action).__name__}")


def notification_payload(action: Action, details: AppointmentDetails) -> dict[str, Any]:
    """Compact log fields for sms.* events.

    Clinic ids and enums only. ``CallLog.event`` writes every field here to
    ``calls.jsonl`` verbatim, and the doctor's and the site's names are free
    text about where a named patient is treated - the message the caller reads
    carries them, the log does not.
    """
    payload: dict[str, Any] = {
        "action_kind": action.kind,
        "when": details.when.isoformat() if details.when else "",
        "provider_id": details.provider_id,
        "location_id": details.location_id,
        "missing": list(details.missing),
    }
    if isinstance(action, CancelAction):
        payload["appointment_id"] = action.appointment_id
    if isinstance(action, BookAction):
        payload["patient_id"] = action.patient_id
        payload["appointment_type_id"] = action.appointment_type_id
    return payload
