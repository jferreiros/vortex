from __future__ import annotations

from vortex.observability import insights
from vortex.observability.agents import AGENTS, get_agent, preview_agents, real_agents
from vortex.observability.view import CallCard, ToolStep
from vortex.tools import TOOLS


def _card(cid: str, status_kind: str | None, reason: str | None = None, **kw) -> CallCard:
    card = CallCard(call_id=cid, ended=True, action_kind=status_kind, decline_reason=reason, **kw)
    return card


def test_reasons_and_outcomes_are_sorted_bars() -> None:
    cards = [
        _card("a", "no-action", "specialty_not_covered"),
        _card("b", "no-action", "specialty_not_covered"),
        _card("c", "no-action", "no_availability"),
        _card("d", "book"),
    ]
    bars = insights.reasons(cards, {"specialty_not_covered": "Not covered"})
    assert [b.key for b in bars] == ["specialty_not_covered", "no_availability"]
    assert bars[0].label == "Not covered"
    assert bars[0].share == 1.0
    assert bars[1].share == 0.5
    outcomes = insights.outcomes(cards)
    assert outcomes[0].key == "refused"


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


def test_patients_merge_by_name_and_mask_phone() -> None:
    a = _card("a", "book", patient_name="Marta Ruiz", from_number="+34612345678")
    a.tools = [ToolStep("find_patient", status="ok", result={"patient": {"insurer": "sanitas"}})]
    b = _card("b", "no-action", "no_availability", patient_name="Marta Ruiz")
    c = _card("c", None, from_number="+34699000111")
    rows = insights.patients([a, b, c])
    assert [r.name for r in rows] == ["Marta Ruiz", "Unidentified patient"]
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
