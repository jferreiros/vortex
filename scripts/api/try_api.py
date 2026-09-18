"""Hit the live Prosper platform API and dump every response to disk.

Calls every parameter-free catalogue endpoint plus a best-effort
`/api/v1/availability`, saves each raw JSON body under a fresh timestamped
folder in `api_results/`, and prints a one-line status per call. Read-only:
it never touches `/api/v1/submit/*` (those need a live call_id and mutate
records).

    uv run python scripts/api/try_api.py
    uv run python scripts/api/try_api.py --specialty-id dermatology --location-id sur
    uv run python scripts/api/try_api.py --name "Marta Ruiz Gomez"
    uv run python scripts/api/try_api.py --patient-id P00042
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx  # noqa: E402

from vortex.settings import get_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def slugify(method: str, path: str) -> str:
    return f"{method}_{path.strip('/').replace('/', '_')}"


def call(
    client: httpx.Client, out_dir: Path, method: str, path: str, params: dict[str, Any] | None = None
) -> Any:
    """Make one request, save the raw body, print a status line, return the parsed body."""
    clean = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
    try:
        response = client.request(method, path, params=clean)
        status = response.status_code
        try:
            body: Any = response.json()
        except ValueError:
            body = {"_raw_text": response.text}
    except httpx.HTTPError as exc:
        status = 0
        body = {"_error": str(exc)}

    slug = slugify(method, path)
    (out_dir / f"{slug}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False))
    query = f"?{clean}" if clean else ""
    print(f"{method} {path}{query} -> {status}")
    return body if status and status < 400 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", help="availability window start (ISO date), default tomorrow")
    parser.add_argument("--date-to", help="availability window end (ISO date), default +2 days")
    parser.add_argument("--provider-id")
    parser.add_argument("--specialty-id", help="default: first specialty from /api/v1/specialties")
    parser.add_argument("--location-id")
    parser.add_argument("--patient-id", help="also fetches this patient's appointments")
    parser.add_argument("--insurer", action="append", help="repeatable")
    parser.add_argument("--name", help="directory search by name")
    parser.add_argument("--national-id", help="directory search by DNI/NIE")
    parser.add_argument("--phone", help="directory search by phone")
    parser.add_argument("--dob", help="directory search by date of birth (ISO date)")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.platform_api_key:
        print("PLATFORM_API_KEY is not set in .env - nothing to call.", file=sys.stderr)
        raise SystemExit(1)

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out_dir = REPO_ROOT / "api_results" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"base url: {settings.platform_api_base_url}")
    print(f"results:  {out_dir.relative_to(REPO_ROOT)}\n")

    ok = 0
    total = 0

    def track(body: Any) -> Any:
        nonlocal ok, total
        total += 1
        if body is not None:
            ok += 1
        return body

    with httpx.Client(
        base_url=settings.platform_api_base_url.rstrip("/"),
        headers={"X-Api-Key": settings.platform_api_key},
        timeout=10.0,
    ) as client:
        track(call(client, out_dir, "GET", "/api/v1/health"))
        track(call(client, out_dir, "GET", "/api/v1/clinic"))
        track(call(client, out_dir, "GET", "/api/v1/providers"))
        track(call(client, out_dir, "GET", "/api/v1/locations"))
        specialties = track(call(client, out_dir, "GET", "/api/v1/specialties"))
        track(call(client, out_dir, "GET", "/api/v1/appointment-types"))
        track(call(client, out_dir, "GET", "/api/v1/insurance-plans"))
        track(call(client, out_dir, "GET", "/api/v1/submissions", {"limit": 5}))

        specialty_id = args.specialty_id
        if not specialty_id and not args.provider_id and specialties:
            items = specialties.get("specialties", [])
            specialty_id = items[0]["id"] if items else None

        date_from = args.date_from or (date.today() + timedelta(days=1)).isoformat()
        date_to = args.date_to or (date.today() + timedelta(days=3)).isoformat()
        track(
            call(
                client,
                out_dir,
                "GET",
                "/api/v1/availability",
                {
                    "date_from": date_from,
                    "date_to": date_to,
                    "provider_id": args.provider_id,
                    "specialty_id": specialty_id,
                    "location_id": args.location_id,
                    "patient_id": args.patient_id,
                    "insurer": args.insurer,
                },
            )
        )

        if args.name or args.national_id or args.phone or args.dob:
            track(
                call(
                    client,
                    out_dir,
                    "GET",
                    "/api/v1/directory",
                    {
                        "name": args.name,
                        "national_id": args.national_id,
                        "phone": args.phone,
                        "date_of_birth": args.dob,
                    },
                )
            )

        if args.patient_id:
            track(
                call(
                    client,
                    out_dir,
                    "GET",
                    f"/api/v1/patients/{args.patient_id}/appointments",
                    {"when": "all"},
                )
            )

    print(f"\n{ok}/{total} calls ok. Results saved under {out_dir.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
