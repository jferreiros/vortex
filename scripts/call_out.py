"""Place an outbound Twilio call that bridges into the receptionist /ws.

Usage:
  uv run python scripts/call_out.py --dry-run
  uv run python scripts/call_out.py --to +34600000000
  uv run python scripts/call_out.py --to +34600000000 --base-url https://<tunnel-host>

Without --dry-run it dials via Twilio. The answered party is connected to
``/voice/outbound``, which returns ``<Connect><Stream>`` into ``/ws``.
"""

from __future__ import annotations

import argparse
import asyncio

from vortex.line.confirmation_calls import TwilioCallsClient
from vortex.line.twilio import public_ws_url, twiml_connect_stream
from vortex.settings import get_settings


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", default="+34600000000", help="E.164 destination")
    parser.add_argument(
        "--base-url",
        default="",
        help="Public https base of this server (overrides VORTEX_PUBLIC_BASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the TwiML and what would be dialled without calling Twilio",
    )
    args = parser.parse_args()

    settings = get_settings()
    base = (args.base_url or settings.public_base_url).rstrip("/")
    ws_url = public_ws_url(base or "https://example.invalid", settings.ws_path)
    preview = twiml_connect_stream(ws_url, {"call_id": "CA_preview", "from_number": args.to})

    print("=== outbound call ===")
    print(f"to: {args.to}")
    print(f"from: {settings.twilio_from_number or '(unset)'}")
    print(f"base: {base or '(none)'}")
    print(f"ws: {ws_url}")
    print("=== TwiML ===")
    print(preview)

    if args.dry_run:
        print("=== dry-run: not dialled ===")
        return 0

    if not base:
        print("ERROR: needs a public base URL (--base-url or VORTEX_PUBLIC_BASE_URL)")
        return 2
    creds = (
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_from_number,
    )
    if not all(creds):
        print("ERROR: needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER")
        return 2

    client = TwilioCallsClient(creds[0], creds[1], from_number=creds[2])
    twiml_url = f"{base}/voice/outbound"
    status_url = f"{base}/voice/status"
    try:
        result = await client.place(to=args.to, twiml_url=twiml_url, status_callback_url=status_url)
        print(f"=== place: {result.status} ===")
        print(f"  detail={result.detail!r} sid={result.sid!r}")
        return 0 if result.status == "queued" else 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
