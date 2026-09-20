from __future__ import annotations

from datetime import date

import pytest

from vortex.observability import insights, pricing
from vortex.observability.agents import AGENTS, get_agent, preview_agents, real_agents
from vortex.observability.view import CallCard, ToolStep
from vortex.tools import TOOLS


def _card(cid: str, status_kind: str | None, reason: str | None = None, **kw) -> CallCard:
    card = CallCard(call_id=cid, ended=True, action_kind=status_kind, decline_reason=reason, **kw)
    return card


def test_reasons_and_outcomes_are_sorted_bars() -> None:
    cards = [
        _card("a", "no-action", "specialty_not_covered", submit_status="accepted"),
        _card("b", "no-action", "specialty_not_covered", submit_status="accepted"),
        _card("c", "no-action", "no_availability", submit_status="accepted"),
        _card("d", "book", submit_status="accepted"),
    ]
    bars = insights.reasons(cards, {"specialty_not_covered": "Not covered"})
    assert [b.key for b in bars] == ["specialty_not_covered", "no_availability"]
    assert bars[0].label == "Not covered"
    assert bars[0].share == 1.0
    assert bars[1].share == 0.5
    outcomes = insights.outcomes(cards)
    assert outcomes[0].key == "refused"


def test_outcomes_count_unsent_action_as_ended() -> None:
    """A prepared book that never reached /submit is ended, not booked."""
    cards = [
        _card("sent", "book", submit_status="accepted"),
        _card("unsent", "book"),
        _card("route_only", "cancel", submit_route="/api/v1/submit/cancel"),
    ]
    bars = insights.outcomes(cards)
    by_key = {b.key: b.value for b in bars}
    assert by_key == {"booked": 1, "ended": 1, "cancelled": 1}


def test_tool_latency_slowest_first_and_failures() -> None:
    card = _card("a", "book")
    card.tools = [
        ToolStep("find_patient", status="ok", ms=40),
        ToolStep("find_slots", status="ok", ms=90),
        ToolStep("find_slots", status="fail", error="boom"),
    ]
    rows = insights.tool_latency([card])
    assert rows[0][0] == "find_slots"
    assert insights.tool_failures([card])["find_slots"] == 1


def test_handle_times_and_hours() -> None:
    cards = [
        _card("a", "book", duration_ms=30000, started_at="2026-09-19T08:05:00+00:00"),
        _card("b", "book", duration_ms=90000, started_at="2026-09-19T08:50:00+00:00"),
    ]
    med, p90, mx = insights.handle_times(cards)
    assert med == 60.0
    assert mx == 90.0
    hours = insights.calls_by_hour(cards)
    assert len(hours) == 24
    assert hours[10].value == 2  # 08:00 UTC is 10:00 in Madrid in September


def test_calls_by_hour_skips_naive_timestamps() -> None:
    """Naive started_at must not be treated as UTC — skip it instead."""
    cards = [
        _card("aware", "book", started_at="2026-09-19T08:05:00+00:00"),
        _card("naive", "book", started_at="2026-09-19T08:05:00"),
    ]
    hours = insights.calls_by_hour(cards)
    assert hours[10].value == 1
    assert sum(h.value for h in hours) == 1


def test_percentiles_pick_a_real_call_never_an_average_of_two() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert insights.percentiles(values, 0.5, 0.95) == [30.0, 100.0]
    assert insights.percentiles(values, 0.0) == [10.0]
    assert insights.percentiles([], 0.5, 0.95) == [None, None]
    assert insights.percentiles([7.0], 0.5, 0.95) == [7.0, 7.0]


def test_handle_seconds_skips_live_calls_and_calls_with_no_duration() -> None:
    cards = [
        _card("a", "book", duration_ms=30000),
        _card("b", "book", duration_ms=None),
        CallCard(call_id="live", ended=False, duration_ms=99000),
    ]
    assert insights.handle_seconds(cards) == [30.0]


def test_on_day_keeps_the_calls_that_started_that_day_in_madrid() -> None:
    cards = [
        # 23:30 UTC is 01:30 the next day in Madrid: it belongs to the 20th.
        _card("late", "book", started_at="2026-09-19T23:30:00+00:00"),
        _card("same", "book", started_at="2026-09-19T08:00:00+00:00"),
        _card("naive", "book", started_at="2026-09-19T08:00:00"),
        _card("none", "book"),
    ]
    assert [c.call_id for c in insights.on_day(cards, date(2026, 9, 19))] == ["same"]
    assert [c.call_id for c in insights.on_day(cards, date(2026, 9, 20))] == ["late"]


def _metered(call_id: str, *, chars: int = 1_000_000, tts_model: str = "eleven_flash_v2_5"):
    card = _card(call_id, "book", duration_ms=30000)
    card.usage = {
        "metered": True,
        "stt": {"provider": "soniox", "model": "stt-rt-v5", "audio_seconds": 60.0},
        "llm": {
            "provider": "helmcode",
            "model": "deepseek-v4-flash",
            "prompt_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
        },
        "tts": [{"provider": "elevenlabs", "model": tts_model, "characters": chars}],
    }
    return card


def test_cost_per_call_averages_the_calls_it_could_price_in_full() -> None:
    # A call that never reached TTS is fully priced; one that did is partial,
    # because ElevenLabs publishes no per-character list price we have verified.
    priced_one = _metered("a", chars=0)
    priced_two = _metered("b", chars=0)
    partial = _metered("c")
    unmetered = _card("old", "book", duration_ms=30000)  # logged before metering
    stub = _card("stub", "book", duration_ms=30000)
    stub.usage = {"metered": False, "stt": {}, "llm": {}, "tts": []}

    summary = insights.cost_per_call([priced_one, priced_two, partial, unmetered, stub])
    assert summary.metered == 3
    assert summary.priced == 2
    assert summary.unpriced == ["TTS eleven_flash_v2_5"]
    assert summary.perk is True
    # Only STT is paid at the margin: the LLM leg is a perk and the TTS leg is
    # not on the priced calls at all.
    rate = pricing.eur_per_usd()
    stt = 0.002 * rate
    llm = (0.14 + 0.28) * rate
    assert summary.avg_paid_eur == pytest.approx(stt)
    assert summary.avg_list_eur == pytest.approx(stt + llm)
    assert summary.total_list_eur == pytest.approx(2 * (stt + llm))


def test_cost_per_call_has_no_average_when_nothing_could_be_priced() -> None:
    summary = insights.cost_per_call([_card("old", "book", duration_ms=30000)])
    assert summary.metered == 0
    assert summary.priced == 0
    assert summary.avg_list_eur is None
    assert summary.avg_paid_eur is None


def test_patients_merge_by_patient_id_and_mask_phone() -> None:
    a = _card(
        "a",
        "book",
        patient_id="P00042",
        patient_name="Marta Ruiz",
        from_number="+34612345678",
    )
    a.tools = [ToolStep("find_patient", status="ok", result={"patient": {"insurer": "sanitas"}})]
    # Same directory id, different phone — one row.
    b = _card(
        "b",
        "no-action",
        "no_availability",
        patient_id="P00042",
        patient_name="Marta Ruiz",
        from_number="+34699999999",
    )
    # Same name, different directory id — separate row.
    d = _card(
        "d",
        "book",
        patient_id="P00099",
        patient_name="Marta Ruiz",
        from_number="+34611111111",
    )
    c = _card("c", None, from_number="+34699000111")
    rows = insights.patients([a, b, d, c])
    assert [r.key for r in rows] == ["P00042", "P00099", "+34699000111"]
    assert [r.name for r in rows] == ["Marta Ruiz", "Marta Ruiz", "Unidentified patient"]
    assert rows[0].calls == 2
    assert rows[0].insurer == "sanitas"
    assert rows[0].last_call_id == "a"
    assert insights.mask_phone("+34612345678") == "+346•••••678"
    assert insights.mask_phone(None) == "—"


def test_agents_registry_names_real_tools() -> None:
    assert [a.slug for a in real_agents()] == ["scheduling"]
    assert len(preview_agents()) == len(AGENTS) - 1
    for agent in AGENTS:
        unknown = [t for t in agent.tools if t not in TOOLS]
        assert not unknown, f"{agent.slug} names tools that do not exist: {unknown}"
    assert get_agent("nope") is None
