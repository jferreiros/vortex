"""Expected values the harness computes instead of the case author.

The platform computes a case's expected slot through the same availability
endpoint we call. We do the same against the fake clinic, so a case never
hard-codes a minute that a fixture change would silently move.

Shape, anywhere inside an ``expect`` block::

    slot: {$earliest_slot: {specialty_id: general_practice, from: "{{ctx.today+1}}"}}

Keys of ``$earliest_slot``: ``specialty_id`` or ``provider_id`` (one required),
``location_id``, ``patient_id``, ``from`` (ISO date, default tomorrow), ``days``
(window, default 14, split into <=14-day spans), ``part_of_day``
(``morning`` < 14:00, ``afternoon`` >= 14:00), ``weekday`` (0 = Monday),
``on`` (an exact ISO date), and ``field``: ``start`` (default, the ISO
instant), ``provider_id`` (an ``$in`` of every provider tied at that minute),
``location_id``, ``appointment_type_id``, or ``slot`` (the whole slot object).

``$catalogue`` resolves to the fake catalogue as JSON, for reference checks.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from vortex.clinic.client import ClinicApi
from vortex.contract import MADRID, Slot


async def _slots(clinic: ClinicApi, spec: dict[str, Any], now: datetime) -> list[Slot]:
    start_day = date.fromisoformat(spec["from"]) if "from" in spec else now.date() + timedelta(1)
    if "on" in spec:
        start_day = date.fromisoformat(spec["on"])
        days = 1
    else:
        days = int(spec.get("days", 14))
    end_day = start_day + timedelta(days=days - 1)
    out: list[Slot] = []
    cursor = start_day
    while cursor <= end_day:
        span_end = min(cursor + timedelta(days=13), end_day)
        resp = await clinic.availability(
            date_from=cursor,
            date_to=span_end,
            provider_id=spec.get("provider_id"),
            specialty_id=spec.get("specialty_id"),
            location_id=spec.get("location_id"),
            patient_id=spec.get("patient_id"),
            insurer=[spec["insurer"]] if spec.get("insurer") else None,
        )
        out.extend(resp.slots)
        cursor = span_end + timedelta(days=1)
    today = now.date()
    out = [s for s in out if s.start.astimezone(MADRID).date() > today]
    part = spec.get("part_of_day")
    if part == "morning":
        out = [s for s in out if s.start.astimezone(MADRID).time() < time(14, 0)]
    elif part == "afternoon":
        out = [s for s in out if s.start.astimezone(MADRID).time() >= time(14, 0)]
    if "weekday" in spec:
        out = [s for s in out if s.start.astimezone(MADRID).weekday() == int(spec["weekday"])]
    return sorted(out, key=lambda s: s.start)


async def earliest_slot(clinic: ClinicApi, spec: dict[str, Any], now: datetime) -> Any:
    slots = await _slots(clinic, spec, now)
    if not slots:
        return {"$absent": True}
    first = slots[0]
    field = spec.get("field", "start")
    if field == "start":
        return first.start.isoformat()
    if field == "slot":
        return first.model_dump(mode="json")
    if field == "provider_id":
        tied = sorted({s.provider_id for s in slots if s.start == first.start})
        return {"$in": tied}
    if field == "location_id":
        tied = sorted({s.location_id for s in slots if s.start == first.start})
        return {"$in": tied}
    if field == "appointment_type_id":
        return first.appointment_type_id
    raise ValueError(f"$earliest_slot: unknown field {field!r}")


async def resolve_oracles(value: Any, clinic: ClinicApi, now: datetime) -> Any:
    """Replace every ``$earliest_slot`` / ``$catalogue`` inside ``value``."""
    if isinstance(value, dict):
        if len(value) == 1 and "$earliest_slot" in value:
            return await earliest_slot(clinic, value["$earliest_slot"], now)
        if len(value) == 1 and "$catalogue" in value:
            return (await clinic.catalogue()).model_dump(mode="json")
        return {k: await resolve_oracles(v, clinic, now) for k, v in value.items()}
    if isinstance(value, list):
        return [await resolve_oracles(v, clinic, now) for v in value]
    return value
