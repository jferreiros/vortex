from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vortex.observability.home_overview import home_overview
from vortex.observability.view import CallCard

MADRID = ZoneInfo("Europe/Madrid")


def _card(
    cid: str,
    action_kind: str | None,
    *,
    started: str,
    reason: str | None = None,
    live: bool = False,
) -> CallCard:
    return CallCard(
        call_id=cid,
        started_at=started,
        ended=not live,
        action_kind=action_kind,
        decline_reason=reason,
        reason=reason,
    )


def test_home_overview_counts_today_and_leaves_yesterday_out_of_today() -> None:
    now = datetime(2026, 9, 19, 16, 0, tzinfo=MADRID)
    cards = [
        _card("book-today", "book", started="2026-09-19T09:10:00+02:00"),
        _card("reg-today", "register", started="2026-09-19T10:00:00+02:00"),
        _card("move-today", "reschedule", started="2026-09-19T11:00:00+02:00"),
        _card("cancel-today", "cancel", started="2026-09-19T12:00:00+02:00"),
        _card(
            "esc-today",
            "escalate",
            started="2026-09-19T13:00:00+02:00",
            reason="medical_emergency",
        ),
        _card("live-today", None, started="2026-09-19T15:00:00+02:00", live=True),
        _card("book-yesterday", "book", started="2026-09-18T09:00:00+02:00"),
        _card(
            "unmet-week",
            "no-action",
            started="2026-09-17T09:00:00+02:00",
            reason="no_availability",
        ),
    ]
    out = home_overview(cards, now=now)
    today = out["today"]
    assert today["calls"] == 6
    assert today["booked"] == 1
    assert today["registered"] == 1
    assert today["rescheduled"] == 1
    assert today["cancelled"] == 1
    assert today["diary_touched"] == 3
    assert today["escalated"] == 1
    assert today["live"] == 1
    assert today["needs_human"] == 2
    assert today["contained_pct"] == 80.0
    assert today["human_reasons"][0]["key"] in {"en_curso", "medical_emergency"}
    assert out["unavailability"]["unmet_total"] == 2
    assert out["window_days"] == 7


def test_home_overview_empty_log_is_zeros_not_none() -> None:
    now = datetime(2026, 9, 19, 16, 0, tzinfo=MADRID)
    out = home_overview([], now=now)
    assert out["today"]["calls"] == 0
    assert out["today"]["contained_pct"] is None
    assert out["today"]["mix"] == []
    assert out["unavailability"]["unmet_total"] == 0
    assert out["cancellations"]["freed_total"] == 0
