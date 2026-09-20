"""``transfer_call``: hand a live Twilio call to a human at the clinic.

The number is clinic-editable (``public.clinic_settings.transfer_number``,
edited on the wall's Call settings page). Empty means the clinic takes no
transfers, and the tool says so instead of doing anything.

Only a *real* Twilio call can be transferred. ``/voice/incoming`` sets the
Media Stream's ``call_id`` parameter to Twilio's ``CallSid``, so on an inbound
phone call ``ctx.call_id`` is the sid to redirect. The organisers' practice
calls open the socket directly and their ``call_id`` is not a sid: there is
nothing to redirect, so the tool answers ``unavailable`` and the agent carries
on with the caller.

Order matters. The Twilio redirect replaces the call's TwiML, which tears our
media socket down within the second, so everything that has to be recorded is
recorded *before* the POST: the ESCALATE submission (hard rule 1 - a
transferred call still has to leave the platform one accepted record) and the
``call.transferred`` event. ``TRANSFERRED_KEY`` then stops the session's
end-of-call fallback from sending a second action on top of it.
"""

from __future__ import annotations

import logging
from xml.sax.saxutils import escape, quoteattr

import httpx

from vortex.contract import (
    ALL_REASONS,
    EscalateAction,
    SubmitInput,
    ToolContext,
    TransferCallInput,
    TransferResult,
)
from vortex.line.submit import submit_action
from vortex.settings import Settings, get_settings

log = logging.getLogger("vortex.line.transfer")

TWILIO_CALL_URL = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json"

#: The redirect is the last thing a live call waits on. Bounded so a slow
#: Twilio never eats the caller's remaining seconds.
TRANSFER_BUDGET_SECS = 6.0

#: Set on ``ctx.state`` the moment the ESCALATE is away and the redirect is
#: fired. ``CallSession._fallback_if_silent`` reads it: the socket dies with
#: the redirect, and this call's one record is already in.
TRANSFERRED_KEY = "call.transferred"

#: One short handover line per language we answer in, with the Twilio ``Say``
#: voice for it. Galician and Basque have no Twilio voice of their own, so they
#: are spoken by the Spanish one.
_HANDOVER: dict[str, tuple[str, str]] = {
    "es": ("es-ES", "Le paso con un compañero, un momento."),
    "ca": ("ca-ES", "Li passo amb un company, un moment."),
    "gl": ("es-ES", "Pásoo cun compañeiro, un momento."),
    "eu": ("es-ES", "Lankide batekin jarriko zaitut, momentu bat."),
    "en": ("en-US", "I am putting you through to a colleague, one moment."),
}


def _is_call_sid(call_id: str) -> bool:
    """A Twilio ``CallSid``: ``CA`` and 32 hex digits."""
    return call_id.startswith("CA") and len(call_id) == 34


def _settings_of(ctx: ToolContext) -> Settings:
    settings = getattr(ctx, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


def _language_of(ctx: ToolContext) -> str:
    session = getattr(ctx, "session", None)
    return str(getattr(session, "language", "") or "es")[:2].lower()


def transfer_number() -> str:
    """The clinic's transfer number, or "" when there is no store or no number."""
    try:
        from database import db

        return str(db.get_clinic_settings().get("transfer_number") or "").strip()
    except Exception:
        log.warning("clinic settings unreadable; transfers are off for this call")
        return ""


def build_twiml(language: str, to_number: str, from_number: str) -> str:
    """The TwiML that replaces the call: one sentence, then the dial."""
    voice_language, line = _HANDOVER.get(language, _HANDOVER["es"])
    return (
        "<Response>"
        f"<Say language={quoteattr(voice_language)}>{escape(line)}</Say>"
        f"<Dial callerId={quoteattr(from_number)}>{escape(to_number)}</Dial>"
        "</Response>"
    )


async def _redirect(settings: Settings, call_sid: str, twiml: str) -> bool:
    url = TWILIO_CALL_URL.format(account_sid=settings.twilio_account_sid, call_sid=call_sid)
    try:
        async with httpx.AsyncClient(
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=TRANSFER_BUDGET_SECS,
        ) as http:
            response = await http.post(url, data={"Twiml": twiml})
    except httpx.HTTPError as exc:
        log.warning("transfer redirect failed: %s: %s", type(exc).__name__, exc)
        return False
    if response.status_code in (200, 201):
        return True
    log.warning("transfer refused: HTTP %s %s", response.status_code, response.text[:200])
    return False


async def transfer_call(ctx: ToolContext, args: TransferCallInput) -> TransferResult:
    """The ``transfer_call`` tool. Submits, logs, then hands the caller over."""
    settings = _settings_of(ctx)
    number = transfer_number()
    if not number:
        return TransferResult(status="unavailable", reason="not_configured")
    if not (
        settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number
    ):
        return TransferResult(status="unavailable", reason="not_configured")
    if not _is_call_sid(ctx.call_id):
        return TransferResult(status="unavailable", reason="not_a_phone_call")

    reason = args.reason if args.reason in ALL_REASONS else "out_of_scope"
    # Before the redirect: the POST below kills this socket, and a call with no
    # accepted record is an attempted, failed case (hard rule 1).
    escalate = EscalateAction(reason=reason)  # type: ignore[arg-type]
    await submit_action(ctx, SubmitInput(action=escalate))
    ctx.state[TRANSFERRED_KEY] = True
    ctx.log.event("call.transferred", number=number, reason=reason)

    twiml = build_twiml(_language_of(ctx), number, settings.twilio_from_number)
    if not await _redirect(settings, ctx.call_id, twiml):
        # The ESCALATE already landed; the caller is still on the line with us.
        return TransferResult(status="unavailable", number=number, reason="twilio_failed")
    return TransferResult(status="transferred", number=number)
