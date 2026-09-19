"""Dry-run (or live Twilio) day-before confirmation call for a fake booking.

Usage:
  uv run python scripts/try_confirmation_call.py
  uv run python scripts/try_confirmation_call.py --lang ca
  uv run python scripts/try_confirmation_call.py --live --to +34600111222 \
      --base-url https://<tunnel-host>

Without --live it prints the TwiML and what would be dialled. With --live it
writes a pending row to the store (so the /confirmation/* webhooks resolve it)
and places the real call. --wait polls the store afterwards and prints the
recorded outcome once the call ends.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta

from vortex.contract import MADRID
from vortex.line.confirmation_calls import (
    ConfirmationCall,
    DryRunCallsClient,
    TwilioCallsClient,
    ask_text,
    confirmation_store_from_settings,
    twilio_calls_configured,
    twiml_ask,
)
from vortex.settings import get_settings

WHEN = datetime(2026, 9, 20, 11, 0, tzinfo=MADRID) + timedelta(days=1)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default="+34600000000", help="E.164 destination")
    parser.add_argument(
        "--lang", default="es", help="ISO-639-1 the call speaks: es, ca, gl, eu, en"
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Public https base of this server (overrides VORTEX_PUBLIC_BASE_URL)",
    )
    parser.add_argument("--live", action="store_true", help="Dial for real via Twilio")
    parser.add_argument(
        "--wait", type=int, default=0, help="Seconds to poll the store for the outcome"
    )
    args = parser.parse_args()

    settings = get_settings()
    base = (args.base_url or settings.public_base_url).rstrip("/")

    when = datetime.now(tz=MADRID).replace(hour=11, minute=0, second=0, microsecond=0)
    when = when + timedelta(days=1)
    # A manual demo trigger, not the scheduler: the <24h rule and the lead are
    # for the automated path, so the row is built directly and dialled now.
    import uuid

    now = datetime.now(tz=MADRID)
    call = ConfirmationCall(
        confirmation_id=uuid.uuid4().hex,
        to=args.to,
        appointment_at=when.isoformat(),
        call_at=now.isoformat(),
        language=args.lang,
        provider_name="Dra. Ortiz",
        location_name="Arenal Centro",
        provider_id="PR01",
        location_id="centro",
        patient_id="P00042",
    )

    print("=== confirmation call preview ===")
    print(f"to: {call.to}  lang: {call.language}")
    print(f"appointment: {call.appointment_at}  call_at: {call.call_at}")
    script = ask_text(
        language=call.language,
        when=call.appointment_dt,
        provider_name=call.provider_name,
        location_name=call.location_name,
    )
    print(f"script: {script}")
    print(f"twilio configured: {twilio_calls_configured(settings)}  base: {base or '(none)'}")

    if not args.live:
        client = DryRunCallsClient()
        twiml = twiml_ask(call, base or "https://example.invalid")
        print("=== TwiML ===")
        print(twiml)
        result = await client.place(to=call.to, twiml_url="<url>", status_callback_url="<url>")
        print(f"=== dry-run: {result.status} ({result.detail}) ===")
        print("Re-run with --live, TWILIO_* set and --base-url to dial for real.")
        return 0

    if not base:
        print("ERROR: --live needs a public base URL (--base-url or VORTEX_PUBLIC_BASE_URL)")
        print("       so Twilio can fetch /confirmation/twiml from this server.")
        return 2
    creds = (
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_from_number,
    )
    if not all(creds):
        print("ERROR: --live needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER")
        return 2

    store = confirmation_store_from_settings(settings)
    await store.add(call)
    # Build the real client from the credentials themselves: --base-url may be
    # the only public URL, and make_calls_client would silently dry-run then.
    client = TwilioCallsClient(creds[0], creds[1], from_number=creds[2])
    twiml_url = f"{base}/confirmation/twiml?cid={call.confirmation_id}"
    status_url = f"{base}/confirmation/status?cid={call.confirmation_id}"
    try:
        result = await client.place(to=call.to, twiml_url=twiml_url, status_callback_url=status_url)
        print(f"=== place: {result.status} ===")
        print(f"  detail={result.detail!r} sid={result.sid!r}")
        if result.status == "failed":
            return 1
        await store.update(call.confirmation_id, status="calling", twilio_call_sid=result.sid)
    finally:
        await client.aclose()

    if args.wait:
        deadline = asyncio.get_running_loop().time() + args.wait
        while asyncio.get_running_loop().time() < deadline:
            row = await store.get(call.confirmation_id)
            if row and row.status not in ("pending", "calling"):
                print(f"=== outcome: {row.status} ===")
                print(f"  detail={row.detail!r} transcript={row.transcript!r}")
                return 0
            await asyncio.sleep(2)
        print("=== no outcome yet (still calling or webhook unreachable) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
