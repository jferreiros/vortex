"""Dry-run (or live Twilio) SMS confirmation for a fake book + cancel.

Usage:
  uv run python scripts/try_sms.py
  uv run python scripts/try_sms.py --to +34600111222
  uv run python scripts/try_sms.py --live --to +34600111222

Without Twilio keys (or without --live) this only prints what would be sent.
With --live and TWILIO_* configured, it POSTs the messages for real.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from vortex.contract import MADRID, Appointment, BookAction, CancelAction
from vortex.line.sms import (
    DryRunSmsClient,
    booking_confirmation_text,
    cancellation_confirmation_text,
    format_slot_es,
    make_sms_client,
    twilio_is_configured,
)
from vortex.settings import get_settings

SLOT = datetime(2026, 9, 24, 16, 30, tzinfo=MADRID)
APPT_START = datetime(2026, 9, 30, 10, 0, tzinfo=MADRID)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default="+34600111222", help="E.164 destination")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually POST to Twilio when credentials are configured",
    )
    args = parser.parse_args()

    settings = get_settings()
    book_body = booking_confirmation_text(
        when=SLOT,
        provider_name="Dr. Iglesia",
        location_name="Arenal Sur",
    )
    cancel_body = cancellation_confirmation_text(
        when=APPT_START,
        provider_name="Dra. Ortiz",
        location_name="Arenal Centro",
    )

    print("=== SMS preview ===")
    print(f"to: {args.to}")
    print(f"book:   {book_body}")
    print(f"cancel: {cancel_body}")
    print(f"slot wording: {format_slot_es(SLOT)}")
    print(f"twilio configured: {twilio_is_configured(settings)}")
    print(f"sms_confirmations: {settings.sms_confirmations}")

    # Sanity-check the action shapes the session would notify on.
    _ = BookAction(
        patient_id="P00042",
        provider_id="PR05",
        location_id="sur",
        appointment_type_id="review",
        slot=SLOT,
        policy_id="sanitas",
    )
    _ = CancelAction(appointment_id="A0001")
    _ = Appointment(
        appointment_id="A0001",
        patient_id="P00042",
        provider_id="PR01",
        location_id="centro",
        appointment_type_id="review",
        start=APPT_START,
    )

    if not args.live:
        client = DryRunSmsClient()
        await client.send(to=args.to, body=book_body)
        await client.send(to=args.to, body=cancel_body)
        print("=== dry-run recorded ===")
        for to, body in client.sent:
            print(f"  -> {to}: {body}")
        print("Re-run with --live and TWILIO_* set to send for real.")
        return 0

    if not twilio_is_configured(settings):
        print("ERROR: --live needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and")
        print("       TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM_NUMBER.")
        return 2

    client = make_sms_client(settings)
    try:
        for label, body in (("book", book_body), ("cancel", cancel_body)):
            result = await client.send(to=args.to, body=body)
            print(f"=== {label}: {result.status} ===")
            print(f"  detail={result.detail!r} sid={result.sid!r}")
            if result.status == "failed":
                return 1
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
