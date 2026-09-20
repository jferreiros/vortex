"""Write the scripted demo calls into ``public.call_events`` and the product tables.

    make seed-demo

A wall with no calls behind it reads as a broken wall, and a laptop that has
never answered the phone has none. This drips the scripted calls in
``vortex/observability/demo.py`` into the store spread across the last seven
days, with one of every outcome the Clinic View has a column for: booked,
rescheduled, cancelled, no-action and escalated.

Three things happen to a scripted call on the way in, and each one is the
reason the board can show it:

1. **The timestamps move.** ``CallLog`` stamps ``now``; a demo needs a week of
   history, so every event of a call is re-stamped from that call's slot in
   the schedule below, three seconds apart, and the summary gets a duration to
   match.
2. **The ``call_id`` gets the ``demo-wall-`` prefix**, which is what makes this
   re-runnable: every row with that prefix is deleted before anything is
   written, so running it twice leaves exactly one copy of each call rather
   than two.
3. **``voice`` stops saying ``demo``.** ``business_insights.is_real_call``
   drops any call logged with ``voice="demo"`` — that filter exists to keep
   the console's own replay button out of the clinic's numbers. These calls
   *are* the clinic's numbers for a demo, so they are logged as the pipeline
   would log them.

Product rows are written too (``calls`` for every finished call,
``appointments`` for the ones that put something in the diary), so the agenda
and the Calls page are not empty either. Both are upserts keyed on the id, and
both are cleared by prefix first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vortex.observability import demo, supabase_log  # noqa: E402
from vortex.observability.view import build_call  # noqa: E402

#: Every call this script writes carries it, and every row carrying it is
#: deleted before the run. Nothing else in the codebase mints this prefix.
PREFIX = "demo-wall-"

#: Appointment ids this script mints, so the diary rows can be cleared the
#: same way the calls are.
APPOINTMENT_PREFIX = "APT-DEMO-"

#: Seconds between two events of the same call once re-stamped.
EVENT_GAP_S = 3

#: How far back each call sits, as ``(key, days_ago, hours_ago, minutes_ago)``
#: from the moment the script runs. Order matches the order the helpers below
#: produce the calls in. Four of the twelve land today so the Home page's
#: "hoy" snapshot is not empty, and the rest fill the seven-day window the
#: unmet-demand and cancellation panels read.
#:
#: Nothing here is left unfinished on purpose. A call with no ``call.ended``
#: reads as live for three minutes (``_shared.STALE_AFTER_S``) and as an
#: agent that submitted nothing for ever after — the exact failure hard rule
#: 1 is about. "En curso" is for a line that is actually ringing.
SCHEDULE: tuple[tuple[str, int, int, int], ...] = (
    ("cancel-1", 6, 6, 0),
    ("cancel-2", 5, 8, 0),
    ("cancel-3", 4, 4, 0),
    ("cancel-4", 2, 5, 0),
    ("cancel-5", 0, 5, 0),
    ("rebook-1", 5, 2, 0),
    ("rebook-2", 1, 3, 0),
    ("unmet", 3, 6, 0),
    ("book", 0, 1, 35),
    ("refused", 0, 2, 30),
    ("reschedule", 1, 7, 0),
    ("escalate", 0, 3, 40),
)

#: ``action_kind`` from the submit route -> what the ``calls`` row says.
PURPOSE = {
    "book": "booking",
    "register": "booking",
    "reschedule": "reschedule",
    "cancel": "cancellation",
    "no-action": "info",
    "escalate": "other",
}
OUTCOME = {
    "book": "book",
    "register": "register",
    "reschedule": "reschedule",
    "cancel": "cancel",
    "no-action": "no_action",
    "escalate": "escalate",
}


# --- generating ---------------------------------------------------------------


async def _generate() -> list[list[dict[str, Any]]]:
    """Run every scripted helper with its writes intercepted.

    ``CallLog`` looks ``enqueue`` up on the module for each event, so swapping
    it here catches the whole scripted set without the helpers knowing. Nothing
    reaches the store until this function has handed the events back.
    """
    captured: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []

    def collect(event: dict[str, Any]) -> None:
        call_id = str(event.get("call_id") or "?")
        if call_id not in captured:
            captured[call_id] = []
            order.append(call_id)
        captured[call_id].append(dict(event))

    real_enqueue = supabase_log.enqueue
    supabase_log.enqueue = collect  # type: ignore[assignment]
    try:
        # Five cancellations, two bookings into freed slots, one unmet caller.
        await demo.write_cancellation_pack(None, delay_s=0.0)
        await demo.write_scripted_call(None, scenario="book", delay_s=0.0)
        await demo.write_scripted_call(None, scenario="refuse", delay_s=0.0)
        await demo.write_reschedule_call("demo-reschedule", delay_s=0.0)
        await demo.write_escalate_call("demo-escalate", delay_s=0.0)
    finally:
        supabase_log.enqueue = real_enqueue  # type: ignore[assignment]

    return [captured[call_id] for call_id in order]


def _retarget(value: Any, old: str, new: str) -> Any:
    """Swap the call id everywhere it appears, including inside the submit
    payloads that carry their own copy of it."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {key: _retarget(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_retarget(item, old, new) for item in value]
    return value


def _restamp(events: list[dict[str, Any]], *, key: str, start: datetime) -> list[dict[str, Any]]:
    old_id = str(events[0].get("call_id") or "?")
    new_id = f"{PREFIX}{key}"
    span_ms = max(len(events) - 1, 1) * EVENT_GAP_S * 1000
    out: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        moved = _retarget(event, old_id, new_id)
        moved["call_id"] = new_id
        moved["ts"] = (start + timedelta(seconds=index * EVENT_GAP_S)).isoformat(
            timespec="milliseconds"
        )
        if moved.get("kind") == "call.started":
            # Not "demo": see the module docstring — is_real_call drops those.
            moved["voice"] = "pipecat"
        if moved.get("kind") == "call.summary":
            moved["duration_ms"] = span_ms
        out.append(moved)
    return out


def _schedule(calls: list[list[dict[str, Any]]], now: datetime) -> list[list[dict[str, Any]]]:
    if len(calls) != len(SCHEDULE):
        raise SystemExit(
            f"the scripted helpers produced {len(calls)} calls but SCHEDULE has "
            f"{len(SCHEDULE)} slots — keep the two in step"
        )
    return [
        _restamp(
            events,
            key=key,
            start=now - timedelta(days=days, hours=hours, minutes=minutes),
        )
        for events, (key, days, hours, minutes) in zip(calls, SCHEDULE, strict=True)
    ]


# --- writing ------------------------------------------------------------------


def _clear() -> None:
    """Drop everything a previous run of this script wrote. Prefix-scoped, so
    a real call logged on this machine is never touched."""
    from database import remote

    remote.delete("appointments", {"id": f"like.{APPOINTMENT_PREFIX}%"})
    remote.delete("calls", {"call_id": f"like.{PREFIX}%"})
    remote.delete("call_events", {"call_id": f"like.{PREFIX}%"})


def _product_rows(calls: list[list[dict[str, Any]]]) -> tuple[int, int]:
    """One ``calls`` row per finished call, one ``appointments`` row per call
    that put a slot in the diary. Returns the two counts."""
    from database import db

    call_rows = 0
    appointment_rows = 0
    for events in calls:
        card = build_call(str(events[0]["call_id"]), events)
        if not card.ended or not card.action_kind:
            continue
        kind = card.action_kind
        payload = card.action_payload or {}
        record = db.insert_call(
            call_id=card.call_id,
            direction="inbound",
            purpose=PURPOSE.get(kind, "other"),
            started_at=str(card.started_at or events[0]["ts"]),
            language="es",
            from_number=card.from_number,
            duration_ms=int(card.duration_ms) if card.duration_ms else None,
            outcome=OUTCOME.get(kind),
        )
        call_rows += 1
        slot = payload.get("slot")
        if kind not in {"book", "reschedule"} or not slot:
            continue
        start = datetime.fromisoformat(str(slot))
        appointment_id = f"{APPOINTMENT_PREFIX}{card.call_id.removeprefix(PREFIX).upper()}"
        db.insert_appointment(
            id=appointment_id,
            booking_call_id=record.id,
            patient_id=str(payload.get("patient_id") or card.patient_id or "P00000"),
            patient_name=card.patient_name,
            patient_phone=card.from_number,
            provider_id=payload.get("provider_id"),
            provider_name=card.provider_name,
            site_id=payload.get("location_id"),
            slot_start=start.isoformat(),
            slot_end=(start + timedelta(minutes=15)).isoformat(),
            insurer=payload.get("policy_id"),
            appointment_type_id=payload.get("appointment_type_id"),
            reason=card.reason,
        )
        db.link_call_to_appointment(record.id, appointment_id)
        appointment_rows += 1
    return call_rows, appointment_rows


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build the calls and print the plan without touching the store",
    )
    args = parser.parse_args()

    if not args.dry_run and not supabase_log.configured():
        print(
            "no store configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env",
            file=sys.stderr,
        )
        return 1

    now = datetime.now().astimezone()
    calls = _schedule(await _generate(), now)
    events = [event for call in calls for event in call]

    if args.dry_run:
        for call in calls:
            print(f"{call[0]['ts']}  {call[0]['call_id']:<28} {len(call):>3} events")
        print(f"\n{len(calls)} calls, {len(events)} events (dry run: nothing written)")
        return 0

    _clear()
    supabase_log.upsert_events(events)
    call_rows, appointment_rows = _product_rows(calls)
    supabase_log.flush()

    outcomes = sorted(
        {build_call(str(c[0]["call_id"]), c).status for c in calls},
    )
    print(
        f"seeded {len(calls)} calls / {len(events)} events into call_events, "
        f"{call_rows} calls rows, {appointment_rows} appointments rows"
    )
    print("outcomes: " + ", ".join(outcomes))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
