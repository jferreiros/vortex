"""Run the day-before-the-appointment confirmation job once.

    uv run python database/scripts/run_confirmations.py
    uv run python database/scripts/run_confirmations.py --for 2026-09-25
    uv run python database/scripts/run_confirmations.py --force cancel:LCL-abc123

Places a (simulated) outbound confirmation call to every appointment
scheduled for tomorrow (or the date passed to ``--for``) that has not
already been confirmed, and updates each one's status from the result. See
``database/confirmations.py`` for the rule and ``database/README.md`` for
what "simulated" stands in for until the line can really dial out.

This is the interface the line is meant to call on a schedule once it can:
one function, ``confirmations.run_confirmations(caller=...)``, given
something that places the call. Today only a script does. It reads and
writes the hosted Postgres like everything else, so ``SUPABASE_URL`` and
``SUPABASE_SERVICE_ROLE_KEY`` have to be set.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from database import confirmations, remote  # noqa: E402
from vortex.settings import get_settings  # noqa: E402


def _parse_force(pairs: list[str]) -> dict[str, confirmations.ConfirmationOutcome]:
    """``["cancel:LCL-abc", "no_answer:APT-901"]`` -> ``{"LCL-abc": "cancel", ...}``."""
    forced: dict[str, confirmations.ConfirmationOutcome] = {}
    for pair in pairs:
        outcome, _, appointment_id = pair.partition(":")
        if not appointment_id or outcome not in ("confirmed", "cancel", "no_answer"):
            raise SystemExit(f"--force expects outcome:appointment_id, got {pair!r}")
        forced[appointment_id] = outcome  # type: ignore[assignment]
    return forced


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--for",
        dest="for_date",
        type=date.fromisoformat,
        default=None,
        help="Run as if today were this date (default: the real today).",
    )
    parser.add_argument(
        "--force",
        action="append",
        default=[],
        metavar="OUTCOME:APPOINTMENT_ID",
        help="Force one appointment's outcome (confirmed|cancel|no_answer). Repeatable.",
    )
    args = parser.parse_args()

    settings = get_settings()
    caller = confirmations.SimulatedConfirmationCaller(
        log_path=settings.calls_log_path,
        force_outcome=_parse_force(args.force),
        settings_describe=settings.describe(),
    )
    if not remote.enabled():
        raise SystemExit(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set — there is no store to read."
        )
    results = await confirmations.run_confirmations(caller=caller, today=args.for_date)

    if not results:
        print("No appointments due for confirmation.")
        return
    for appt, result in results:
        print(
            f"{appt.id}  {appt.slot_start}  {appt.patient_name or appt.patient_id}"
            f"  -> {result.outcome}  (call {result.call_id})"
        )


if __name__ == "__main__":
    asyncio.run(main())
