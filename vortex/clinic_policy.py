"""Clinic-console rules the line actually obeys.

The wall's Call settings page writes ``clinic_settings`` in the product
database. Identity and diary read the same row so a saved knob is not
theatre. Defaults match today's behaviour (one identifying field, next
calendar day) when the table is empty or unreadable — a missing store must
not change a scored call.
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta
from typing import Any

from vortex.contract import MADRID

_CACHE_TTL_S = 5.0
_cache: tuple[float, dict[str, Any]] | None = None

DEFAULTS = {
    "minimum_booking_lead_hours": 24,
    "patient_identification_fields_required": 1,
    "call_time_cap_minutes": 3,
}


def _load() -> dict[str, Any]:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_S:
        return _cache[1]
    try:
        from database import db
        from vortex.settings import get_settings

        with db.connection(get_settings().product_db_path) as conn:
            values = db.get_clinic_settings(conn)
    except Exception:
        values = dict(DEFAULTS)
    _cache = (now, values)
    return values


def reset_cache() -> None:
    global _cache
    _cache = None


def identification_fields_required() -> int:
    return int(_load()["patient_identification_fields_required"])


def minimum_booking_lead_hours() -> int:
    return int(_load()["minimum_booking_lead_hours"])


def earliest_bookable_date(now: datetime) -> date:
    """First calendar day a slot may land on.

    The platform never books same-day, so the floor is always tomorrow.
    Extra lead hours from the wall become extra whole days (24 h → tomorrow,
    48 h → the day after), matching the settings card's "1 día / 2 días"
    labels instead of cutting tomorrow morning off a 09:00 call.
    """
    local = now.astimezone(MADRID) if now.tzinfo else now.replace(tzinfo=MADRID)
    today = local.date()
    days = max(1, math.ceil(minimum_booking_lead_hours() / 24))
    return today + timedelta(days=days)
