"""Clinic-console knobs the line actually obeys."""

from __future__ import annotations

from datetime import datetime

import pytest

import vortex.clinic_policy as clinic_policy
from vortex.clinic_policy import earliest_bookable_date, reset_cache
from vortex.contract import MADRID


def test_earliest_bookable_date_never_same_day(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 18, 9, 0, tzinfo=MADRID)
    reset_cache()
    monkeypatch.setattr(clinic_policy, "minimum_booking_lead_hours", lambda: 2)
    assert earliest_bookable_date(now).isoformat() == "2026-09-19"
    monkeypatch.setattr(clinic_policy, "minimum_booking_lead_hours", lambda: 24)
    assert earliest_bookable_date(now).isoformat() == "2026-09-19"
    monkeypatch.setattr(clinic_policy, "minimum_booking_lead_hours", lambda: 48)
    assert earliest_bookable_date(now).isoformat() == "2026-09-20"
    reset_cache()
