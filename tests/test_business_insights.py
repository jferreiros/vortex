from __future__ import annotations

from datetime import datetime

from vortex.observability import business_insights as bi
from vortex.observability.view import CallCard, ToolStep, Turn


def _card(cid: str, action_kind: str | None = None, reason: str | None = None, **kw) -> CallCard:
    return CallCard(call_id=cid, ended=True, action_kind=action_kind, decline_reason=reason, **kw)


def _say(card: CallCard, text: str) -> CallCard:
    card.turns.append(Turn("user", text))
    return card


def _find_slots(
    card: CallCard, *, date_from: str, time_from: str | None = None, slots=None
) -> CallCard:
    card.tools.append(
        ToolStep(
            name="find_slots",
            args={"date_from": date_from, "date_to": date_from, "time_from": time_from},
            result={"slots": slots or []},
            status="ok",
        )
    )
    return card


# ---------------------------------------------------------------------------
# 1. Unavailability reasons
# ---------------------------------------------------------------------------


def test_classify_unmet_maps_structured_reason_to_bucket() -> None:
    assert bi.classify_unmet(_card("a", "no-action", "no_availability")) == "no_slot_in_window"
    assert bi.classify_unmet(_card("b", "no-action", "provider_on_leave")) == "provider_unavailable"
    assert bi.classify_unmet(_card("c", "no-action", "type_not_offered")) == "specialty_no_agenda"
    assert bi.classify_unmet(_card("d", "no-action", "referral_required")) == "policy_not_covered"
    assert bi.classify_unmet(_card("e", "no-action", "clinic_closed")) == "out_of_hours"
    assert bi.classify_unmet(_card("f", "no-action", "out_of_scope")) == "other"


def test_classify_unmet_falls_back_to_keywords_when_reason_missing() -> None:
    out_of_hours = _say(_card("a", "no-action"), "vale, pero eso es cuando ya estáis cerrados")
    assert bi.classify_unmet(out_of_hours) == "out_of_hours"

    no_slot = _say(_card("b", "no-action"), "no me viene bien esa hora, ¿no hay nada otro día?")
    assert bi.classify_unmet(no_slot) == "no_slot_in_window"

    policy = _say(_card("c", "no-action"), "mi seguro no lo cubre, ¿seguro que no lo cubre?")
    assert bi.classify_unmet(policy) == "policy_not_covered"

    unclear = _say(_card("d", "no-action"), "ya, bueno, vale, gracias")
    assert bi.classify_unmet(unclear) == "other"


def test_classify_unmet_detects_provider_unavailable_from_negation_near_name() -> None:
    card = _say(_card("a", "no-action"), "quería con la doctora ortiz pero me dicen que no está")
    assert bi.classify_unmet(card) == "provider_unavailable"


def test_is_unmet_demand_excludes_successful_and_unrelated_calls() -> None:
    booked = _card("a", "book")
    booked.tools = [ToolStep("find_slots", status="ok")]
    assert bi.is_unmet_demand(booked) is False

    registered = _card("b", "register")
    registered.decline_reason = None
    assert bi.is_unmet_demand(registered) is False

    cancelled = _card("c", "cancel")
    assert bi.is_unmet_demand(cancelled) is False

    declined = _card("d", "no-action", "no_availability")
    assert bi.is_unmet_demand(declined) is True

    abandoned = _card("e", None)
    abandoned.tools = [ToolStep("find_slots", status="ok")]
    assert bi.is_unmet_demand(abandoned) is True

    just_looked_up = _card("f", None)
    just_looked_up.tools = [ToolStep("find_patient", status="ok")]
    assert bi.is_unmet_demand(just_looked_up) is False


def test_unavailability_reasons_ranks_and_suggests() -> None:
    cards = [
        _card("a", "no-action", "no_availability"),
        _card("b", "no-action", "no_availability"),
        _card("c", "no-action", "provider_on_leave"),
        _card("d", "book"),  # excluded: successful
    ]
    out = bi.unavailability_reasons(cards)
    assert out["unmet_total"] == 3
    assert out["buckets"][0]["key"] == "no_slot_in_window"
    assert out["buckets"][0]["count"] == 2
    assert out["buckets"][0]["pct"] == round(200 / 3, 1)
    assert out["suggested_action"] is not None


def test_unavailability_reasons_empty_when_nothing_unmet() -> None:
    out = bi.unavailability_reasons([_card("a", "book")])
    assert out["unmet_total"] == 0
    assert out["buckets"] == []
    assert out["suggested_action"] is None


# ---------------------------------------------------------------------------
# 2. Provider ranking
# ---------------------------------------------------------------------------


def test_provider_ranking_counts_mentions_and_success() -> None:
    started_at = "2026-09-01T09:00:00+00:00"
    booked = _say(_card("a", "book", started_at=started_at), "quiero con la dra ortiz")
    booked.action_payload = {"provider_id": "PR01", "slot": "2026-09-08T09:00:00+00:00"}

    failed_1 = _say(_card("b", "no-action", "provider_not_in_network"), "necesito a la dra ortiz")
    failed_2 = _say(_card("c", "no-action", "no_availability"), "quiero a la doctora ortiz")

    out = bi.provider_ranking([booked, failed_1, failed_2], min_requests=2, low_success_pct=50.0)
    rows = {r["id"]: r for r in out["providers"]}
    assert rows["PR01"]["requests"] == 3
    assert rows["PR01"]["booked"] == 1
    assert rows["PR01"]["median_wait_days"] == 7.0
    assert rows["PR01"]["flagged"] is True  # 3 requests, 33% success < 50%
    assert out["suggested_action"] is not None
    assert "Ortiz" in out["suggested_action"]


def test_provider_ranking_no_suggestion_when_nobody_flagged() -> None:
    booked = _say(_card("a", "book"), "con la dra ortiz")
    booked.action_payload = {"provider_id": "PR01"}
    out = bi.provider_ranking([booked])
    assert out["suggested_action"] is None


def test_requested_provider_ids_uses_resolved_name_too() -> None:
    card = _card("a", "no-action", "no_availability", provider_name="Dr. Sáez")
    assert "PR02" in bi.requested_provider_ids(card)


# ---------------------------------------------------------------------------
# 3. Demand vs. supply heatmap
# ---------------------------------------------------------------------------


def test_heatmap_counts_demand_and_availability_by_band() -> None:
    # 2026-09-22 is a Tuesday.
    demanded = _find_slots(_card("a"), date_from="2026-09-22", time_from="16:00:00")
    offered = _find_slots(
        _card("b"),
        date_from="2026-09-23",
        slots=[{"start": "2026-09-23T09:30:00+02:00", "provider_id": "PR01"}],
    )
    out = bi.demand_supply_heatmap([demanded, offered])
    tuesday = next(r for r in out["rows"] if r["weekday"] == "Martes")
    wednesday = next(r for r in out["rows"] if r["weekday"] == "Miércoles")
    tarde_cell = next(c for c in tuesday["cells"] if c["band"] == "Tarde")
    manana_cell = next(c for c in wednesday["cells"] if c["band"] == "Mañana")
    assert tarde_cell["demand"] == 1
    assert tarde_cell["availability"] == 0
    assert manana_cell["availability"] == 1
    assert out["suggested_action"] is not None
    assert "martes" in out["suggested_action"].lower()


def test_heatmap_with_no_calls_has_empty_grid_and_no_suggestion() -> None:
    out = bi.demand_supply_heatmap([])
    assert len(out["rows"]) == 7
    assert all(c["demand"] == 0 for r in out["rows"] for c in r["cells"])
    assert out["suggested_action"] is None


def test_business_insights_bundles_everything_and_lists_data_gaps() -> None:
    out = bi.business_insights([_card("a", "no-action", "no_availability")])
    assert set(out) == {
        "calls_considered",
        "unavailability",
        "providers",
        "heatmap",
        "cancellations",
        "data_gaps",
    }
    assert out["calls_considered"] == 1
    assert len(out["data_gaps"]) >= 1


# ---------------------------------------------------------------------------
# 4. Cancellations: reused vs. lost
# ---------------------------------------------------------------------------


def _listed(card: CallCard, *, appointment_id: str, provider_id: str, start: str) -> CallCard:
    appt = {"appointment_id": appointment_id, "provider_id": provider_id, "start": start}
    step = ToolStep(name="list_appointments", result={"appointments": [appt]}, status="ok")
    card.tools.append(step)
    return card


def _cancelled(card: CallCard, *, appointment_id: str, ts: str) -> CallCard:
    card.action_kind = "cancel"
    card.action_payload = {"appointment_id": appointment_id}
    card.events = [{"kind": "submit.result", "route": "/api/v1/submit/cancel", "ts": ts}]
    return card


def _booked(card: CallCard, *, provider_id: str, slot: str) -> CallCard:
    card.action_kind = "book"
    card.action_payload = {"provider_id": provider_id, "slot": slot}
    return card


_NOW = datetime.fromisoformat("2026-09-20T10:00:00+00:00")


def test_cancellation_relocated_by_a_different_call() -> None:
    start = "2026-09-21T09:00:00+00:00"
    card = _listed(_card("a"), appointment_id="A1", provider_id="PR01", start=start)
    freed = _cancelled(card, appointment_id="A1", ts="2026-09-19T08:00:00+00:00")
    rebooked = _booked(_card("b"), provider_id="PR01", slot=start)
    out = bi.cancellation_slots([freed, rebooked], now=_NOW)
    assert out["freed_total"] == 1
    assert out["relocated"] == 1
    assert out["lost"] == 0
    assert out["recovery_rate_pct"] == 100.0


def test_cancellation_lost_when_day_arrives_unfilled() -> None:
    start = "2026-09-19T09:00:00+00:00"
    card = _listed(_card("a"), appointment_id="A1", provider_id="PR01", start=start)
    freed = _cancelled(card, appointment_id="A1", ts="2026-09-18T08:00:00+00:00")
    out = bi.cancellation_slots([freed], now=_NOW)  # start is before _NOW: the day already happened
    assert out["freed_total"] == 1
    assert out["lost"] == 1
    assert out["relocated"] == 0
    assert out["recovery_rate_pct"] == 0.0
    assert "vacíos" in out["suggested_action"]


def test_cancellation_pending_does_not_count_towards_recovery_rate() -> None:
    start = "2026-09-25T09:00:00+00:00"
    card = _listed(_card("a"), appointment_id="A1", provider_id="PR01", start=start)
    freed = _cancelled(card, appointment_id="A1", ts="2026-09-19T08:00:00+00:00")
    out = bi.cancellation_slots([freed], now=_NOW)  # start is after _NOW: still has a chance
    assert out["freed_total"] == 1
    assert out["pending"] == 1
    assert out["relocated"] == 0
    assert out["lost"] == 0
    assert out["recovery_rate_pct"] is None


def test_cancellation_skipped_without_a_list_appointments_lookup() -> None:
    freed = _cancelled(_card("a"), appointment_id="A404", ts="2026-09-19T08:00:00+00:00")
    out = bi.cancellation_slots([freed], now=_NOW)
    assert out["freed_total"] == 0


def test_cancellation_original_booking_does_not_count_as_its_own_relocation() -> None:
    # The call that cancels A1 also shows up as a "book" action in card.events
    # history elsewhere is not modelled here; what matters is that a booking
    # from the *same* call_id as the cancellation is never read as a relocation.
    card = _card("a")
    _listed(card, appointment_id="A1", provider_id="PR01", start="2026-09-21T09:00:00+00:00")
    _cancelled(card, appointment_id="A1", ts="2026-09-19T08:00:00+00:00")
    out = bi.cancellation_slots([card], now=_NOW)
    assert out["relocated"] == 0
    assert out["pending"] == 1


def test_cancellation_daily_breakdown_only_appears_with_volume() -> None:
    start = "2026-09-19T09:00:00+00:00"
    few = [
        _cancelled(
            _listed(_card(f"c{i}"), appointment_id=f"A{i}", provider_id="PR01", start=start),
            appointment_id=f"A{i}",
            ts="2026-09-18T08:00:00+00:00",
        )
        for i in range(3)
    ]
    assert bi.cancellation_slots(few, now=_NOW)["daily"] is None

    many = [
        _cancelled(
            _listed(_card(f"m{i}"), appointment_id=f"B{i}", provider_id="PR01", start=start),
            appointment_id=f"B{i}",
            ts="2026-09-18T08:00:00+00:00",
        )
        for i in range(5)
    ]
    daily = bi.cancellation_slots(many, now=_NOW)["daily"]
    assert daily == [{"date": "2026-09-19", "freed": 5, "relocated": 0, "lost": 5}]
