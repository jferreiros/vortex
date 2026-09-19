"""Discover or buy a European Twilio From number and point VoiceUrl at us.

Usage:
  uv run python scripts/twilio_setup.py
  uv run python scripts/twilio_setup.py --base-url https://<tunnel-host>
  uv run python scripts/twilio_setup.py --list-only
  uv run python scripts/twilio_setup.py --search
  uv run python scripts/twilio_setup.py --buy

Lists IncomingPhoneNumbers, prefers an existing EU voice number, and
(unless --list-only) sets VoiceUrl to ``<public_base>/voice/incoming`` (POST).

``--search`` lists available EU local numbers (ES first). ``--buy`` purchases
the first voice-capable ES number, then other EU countries. Never searches
or buys US (+1) numbers.
"""

from __future__ import annotations

import argparse

import httpx

from vortex.line.twilio import is_european_e164
from vortex.settings import get_settings

NUMBERS_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json"
NUMBER_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers/{pn_sid}.json"
AVAILABLE_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/{sid}/AvailablePhoneNumbers/{iso}/{kind}.json"
)
NUMBER_KINDS = ("Local", "Mobile", "National")
VERIFY_HINT_NUMBER = "+34662046392"

# Prefer Spain, then the rest of the EU. Never US.
EU_ISO_ORDER = (
    "ES",
    "DE",
    "FR",
    "IT",
    "PT",
    "IE",
    "NL",
    "BE",
    "AT",
    "PL",
    "SE",
    "DK",
    "FI",
    "GR",
    "CZ",
    "HU",
    "RO",
    "SK",
    "SI",
    "HR",
    "BG",
    "LT",
    "LV",
    "EE",
    "LU",
    "CY",
    "MT",
)

def _err_snippet(response: httpx.Response) -> str:
    return response.text[:600]


def _trial_purchase_blocked(body: str) -> bool:
    lowered = body.lower()
    return (
        "21404" in body
        or "unverified" in lowered
        or "trial" in lowered
        and ("verif" in lowered or "purchase" in lowered)
    )


def _print_verify_steps() -> None:
    print("BLOCKER: Twilio trial cannot purchase a number until a personal phone is verified.")
    print("Do this in the Twilio console (do not buy a US / +1 number):")
    print("  1. Open https://console.twilio.com/us1/develop/phone-numbers/manage/verified")
    print(f"  2. Verify the personal number {VERIFY_HINT_NUMBER} (Spain).")
    print("  3. Add trial credit if the account balance is $0 (Billing).")
    print("  4. Phone Numbers -> Buy a number -> Country: Spain (or another EU country).")
    print("     Voice capable. Never United States / +1.")
    print("  5. Re-run: uv run python scripts/twilio_setup.py --buy")


def _pick_existing(numbers: list[dict]) -> dict | None:
    eu = [row for row in numbers if is_european_e164(str(row.get("phone_number") or ""))]
    if eu:
        return eu[0]
    return None


def _search_available(http: httpx.Client, sid: str, iso: str) -> list[dict]:
    found: list[dict] = []
    for kind in NUMBER_KINDS:
        url = AVAILABLE_URL.format(sid=sid, iso=iso, kind=kind)
        response = http.get(url, params={"VoiceEnabled": "true", "PageSize": "5"})
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            print(f"  {iso}/{kind}: search HTTP {response.status_code}: {_err_snippet(response)}")
            continue
        rows = list(response.json().get("available_phone_numbers") or [])
        for row in rows:
            row["_kind"] = kind
            found.append(row)
        if found:
            break
    if not found:
        print(f"  {iso}: no Local/Mobile/National inventory")
    return found


def _buy_number(http: httpx.Client, sid: str, phone: str) -> dict | None:
    if not is_european_e164(phone):
        print(f"REFUSED: will not buy non-EU number {phone}")
        return None
    response = http.post(NUMBERS_URL.format(sid=sid), data={"PhoneNumber": phone})
    if response.status_code not in (200, 201):
        print(f"ERROR: buy {phone} HTTP {response.status_code}: {_err_snippet(response)}")
        if _trial_purchase_blocked(response.text):
            _print_verify_steps()
        return None
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="",
        help="Public https base (overrides VORTEX_PUBLIC_BASE_URL)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Print numbers and do not change VoiceUrl",
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help="Search available EU voice numbers (no purchase)",
    )
    parser.add_argument(
        "--buy",
        action="store_true",
        help="Purchase the first available EU (prefer ES) voice number",
    )
    args = parser.parse_args()

    settings = get_settings()
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    if not sid or not token:
        print("ERROR: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env")
        return 2

    with httpx.Client(auth=(sid, token), timeout=20.0) as http:
        response = http.get(NUMBERS_URL.format(sid=sid))
        if response.status_code != 200:
            print(f"ERROR: list numbers HTTP {response.status_code}: {_err_snippet(response)}")
            return 1
        numbers = response.json().get("incoming_phone_numbers") or []

        print("=== IncomingPhoneNumbers ===")
        if not numbers:
            print("  (none)")
        for row in numbers:
            phone = str(row.get("phone_number") or "")
            region = "EU" if is_european_e164(phone) else "NON-EU"
            print(
                f"  {phone}  [{region}]  sid={row.get('sid')}  "
                f"voice={row.get('voice_url') or '(none)'}"
            )

        if args.search or (args.buy and not numbers):
            print("=== Available EU numbers (VoiceEnabled, Local/Mobile/National) ===")
            found: list[tuple[str, dict]] = []
            for iso in EU_ISO_ORDER:
                rows = _search_available(http, sid, iso)
                for row in rows:
                    phone = str(row.get("phone_number") or "")
                    if not is_european_e164(phone):
                        continue
                    print(
                        f"  {iso}/{row.get('_kind')} {phone}  {row.get('friendly_name') or ''}"
                    )
                    found.append((iso, row))
                if found and iso == "ES":
                    break
                if args.buy and found:
                    break
            if not found:
                print("  (no EU inventory returned, or search denied)")

            if args.buy:
                if not found:
                    print("ERROR: no European number to purchase.")
                    _print_verify_steps()
                    return 1
                iso, row = found[0]
                phone = str(row.get("phone_number") or "")
                print(f"=== buying {iso} {phone} ===")
                bought = _buy_number(http, sid, phone)
                if bought is None:
                    return 1
                numbers = [bought]
                print(f"bought {bought.get('phone_number')} sid={bought.get('sid')}")

        if args.list_only or (args.search and not args.buy):
            chosen = _pick_existing(numbers) if numbers else None
            if chosen is not None:
                print(f"TWILIO_FROM_NUMBER={chosen.get('phone_number')}")
            return 0

        if not numbers:
            print(
                "ERROR: this Twilio account has no IncomingPhoneNumbers. "
                "Search with --search or purchase with --buy (EU only)."
            )
            _print_verify_steps()
            return 1

        chosen = _pick_existing(numbers)
        if chosen is None:
            print("ERROR: account numbers exist but none are European. Refusing US/non-EU From.")
            return 1

        from_number = str(chosen.get("phone_number") or "")
        pn_sid = str(chosen.get("sid") or "")
        print(f"TWILIO_FROM_NUMBER={from_number}")

        base = (args.base_url or settings.public_base_url).rstrip("/")
        if not base:
            print("ERROR: VORTEX_PUBLIC_BASE_URL (or --base-url) is required to set VoiceUrl")
            return 2

        voice_url = f"{base}/voice/incoming"
        patch = http.post(
            NUMBER_URL.format(sid=sid, pn_sid=pn_sid),
            data={"VoiceUrl": voice_url, "VoiceMethod": "POST"},
        )
        if patch.status_code not in (200, 201):
            print(f"ERROR: set VoiceUrl HTTP {patch.status_code}: {_err_snippet(patch)}")
            return 1
        print(f"=== VoiceUrl -> {voice_url} (POST) ===")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
