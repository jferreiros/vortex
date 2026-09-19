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
    card: CallCard, *, date_from: str, time_from: str | None = None, slots=None, **extra_args
) -> CallCard:
    card.tools.append(
        ToolStep(
            name="find_slots",
            args={
                "date_from": date_from,
                "date_to": date_from,
                "time_from": time_from,
                **extra_args,
            },
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


def test_unavailability_reasons_drops_other_and_renormalises_to_100() -> None:
    cards = [
        _card("a", "no-action", "no_availability"),
        _card("b", "no-action", "no_availability"),
        _card("c", "no-action", "provider_on_leave"),
        _card("d", "no-action", "out_of_scope"),  # -> "other", excluded
        _card("e", "no-action", "medical_emergency"),  # -> "other", excluded
    ]
    out = bi.unavailability_reasons(cards)
    # unmet_total still counts every unmet call, "other" included.
    assert out["unmet_total"] == 5
    keys = [b["key"] for b in out["buckets"]]
    assert "other" not in keys
    assert keys == ["no_slot_in_window", "provider_unavailable"]
    # The two shown buckets (2 + 1 = 3 calls) sum their pct to 100%.
    assert sum(b["pct"] for b in out["buckets"]) == 100.0
    assert out["buckets"][0]["pct"] == round(200 / 3, 1)


def test_unavailability_reasons_empty_buckets_when_only_other() -> None:
    out = bi.unavailability_reasons([_card("a", "no-action", "out_of_scope")])
    assert out["unmet_total"] == 1
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


def test_provider_ranking_explains_why_requests_did_not_book() -> None:
    booked = _say(_card("a", "book"), "quiero con la dra ortiz")
    booked.action_payload = {"provider_id": "PR01"}

    on_leave = _say(_card("b", "no-action", "provider_on_leave"), "necesito a la dra ortiz")
    out_of_network = _say(
        _card("c", "no-action", "provider_not_in_network"), "quiero a la doctora ortiz"
    )
    elsewhere = _say(_card("d", "book"), "pedí a la dra ortiz")
    elsewhere.action_payload = {"provider_id": "PR02"}
    registered = _say(_card("e", "register"), "soy nueva, con la dra ortiz")

    out = bi.provider_ranking([booked, on_leave, out_of_network, elsewhere, registered])
    row = next(r for r in out["providers"] if r["id"] == "PR01")
    assert row["requests"] == 5
    assert row["booked"] == 1
    assert row["unmet"] == 2
    assert row["unmet_reasons"] == [
        {"key": "provider_unavailable", "label": "Médico concreto no disponible", "count": 2}
    ]
    assert row["booked_elsewhere"] == 1
    assert row["other_outcomes"] == 1  # the register call: named, no appointment sought


def test_requested_provider_ids_uses_resolved_name_too() -> None:
    card = _card("a", "no-action", "no_availability", provider_name="Dr. Sáez")
    assert "PR02" in bi.requested_provider_ids(card)


# ---------------------------------------------------------------------------
# 3. Service occupancy
# ---------------------------------------------------------------------------


def _occ(out: dict, specialty_id: str) -> dict:
    return next(r for r in out["all"] if r["id"] == specialty_id)


def test_service_occupancy_over_100_when_requests_outrun_slots() -> None:
    booked_slot = _find_slots(
        _card("a"),
        date_from="2026-09-22",
        specialty_id="dermatology",
        slots=[{"start": "2026-09-22T10:00:00+02:00", "provider_id": "PR04"}],
    )
    declined_1 = _find_slots(
        _card("b", "no-action", "no_availability"),
        date_from="2026-09-22",
        specialty_id="dermatology",
    )
    declined_2 = _find_slots(
        _card("c", "no-action", "no_availability"),
        date_from="2026-09-22",
        specialty_id="dermatology",
    )
    out = bi.service_occupancy([booked_slot, declined_1, declined_2])
    row = _occ(out, "dermatology")
    assert row["requested"] == 3
    assert row["offered"] == 1
    assert row["declined_full"] == 2
    assert row["occupancy_pct"] == 300.0
    # One provider on staff; occupancy 300% needs three to cover it all.
    assert row["providers"] == 1
    assert row["extra_providers_needed"] == 2


def test_service_occupancy_zero_when_no_demand_and_no_extra_providers() -> None:
    out = bi.service_occupancy([])
    row = _occ(out, "general_practice")
    assert row["requested"] == 0
    assert row["occupancy_pct"] == 0.0
    assert row["extra_providers_needed"] == 0


def test_service_occupancy_covers_every_catalogue_specialty() -> None:
    out = bi.service_occupancy([_card("a", "book")])
    assert {r["id"] for r in out["all"]} == {
        "general_practice",
        "paediatrics",
        "dermatology",
        "orthopaedics",
        "gynaecology",
        "physiotherapy",
    }
    assert all(r["name"] for r in out["all"])


def test_service_occupancy_request_without_specialty_or_provider_counts_nowhere() -> None:
    # No specialty_id and no provider_id: the caller's intent is unknown,
    # same rule the heatmap applies to an hour-less request.
    vague = _find_slots(_card("a"), date_from="2026-09-22")
    out = bi.service_occupancy([vague])
    assert all(r["requested"] == 0 for r in out["all"])


def test_service_occupancy_scopes_demand_and_supply_per_site() -> None:
    # PR06 (physiotherapy) sits at "sur" only.
    physio_at_sur = _find_slots(
        _card("a"),
        date_from="2026-09-22",
        specialty_id="physiotherapy",
        slots=[{"start": "2026-09-22T10:00:00+02:00", "provider_id": "PR06", "location_id": "sur"}],
    )
    out = bi.service_occupancy([physio_at_sur])
    sites = {s["id"]: s for s in out["sites"]}
    sur_row = next(r for r in sites["sur"]["services"] if r["id"] == "physiotherapy")
    norte_row = next(r for r in sites["norte"]["services"] if r["id"] == "physiotherapy")
    assert sur_row["requested"] == 1
    assert sur_row["offered"] == 1
    assert norte_row["requested"] == 0
    assert norte_row["offered"] == 0


# ---------------------------------------------------------------------------
# 4. Demand vs. supply heatmap
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


def _cell(view: dict, weekday: int, band: str) -> dict:
    return next(c for c in view["rows"][weekday]["cells"] if c["band"] == band)


def test_heatmap_marks_each_sites_closed_cells_from_its_hours() -> None:
    out = bi.demand_supply_heatmap([])
    sites = {s["id"]: s for s in out["sites"]}
    assert set(sites) == {"centro", "norte", "sur"}

    # Weekdays 09:00–20:00 cover all four bands; Sunday is shut everywhere.
    assert sites["norte"]["open"][0] == [True] * 4
    assert sites["norte"]["open"][6] == [False] * 4
    # Norte does not open Saturday; Centro opens 09:00–14:00 (a band that
    # half-overlaps the site's hours still counts as open).
    assert sites["norte"]["open"][5] == [False] * 4
    assert sites["centro"]["open"][5] == [True, True, False, False]
    # Sur shuts Friday lunchtime.
    assert sites["sur"]["open"][4] == [True, True, False, False]
    # The combined view marks a cell open while any site is.
    assert out["open"][5] == [True, True, False, False]
    assert out["open"][6] == [False] * 4
    assert sites["sur"]["hours_label"] == "L–J 09:00–20:00 · V 09:00–14:00"


def test_heatmap_splits_demand_and_supply_per_site() -> None:
    # 2026-09-22 is a Tuesday.
    to_sur = _find_slots(
        _card("a"), date_from="2026-09-22", time_from="16:00:00", location_id="sur"
    )
    anywhere = _find_slots(_card("b"), date_from="2026-09-22", time_from="16:00:00")
    physio = _find_slots(
        _card("c"), date_from="2026-09-22", time_from="16:00:00", specialty_id="physiotherapy"
    )
    offered_sur = _find_slots(
        _card("d"),
        date_from="2026-09-22",
        slots=[{"start": "2026-09-22T16:30:00+02:00", "provider_id": "PR05", "location_id": "sur"}],
    )
    out = bi.demand_supply_heatmap([to_sur, anywhere, physio, offered_sur])
    sites = {s["id"]: s for s in out["sites"]}

    # A request counts once in the network view, and against every site it
    # could have landed in: Sur explicitly, all three when no site is named,
    # Sur only for physiotherapy (its one provider sits there).
    assert _cell(out, 1, "Tarde")["demand"] == 3
    assert _cell(sites["sur"], 1, "Tarde")["demand"] == 3
    assert _cell(sites["centro"], 1, "Tarde")["demand"] == 1
    assert _cell(sites["norte"], 1, "Tarde")["demand"] == 1

    # An offered slot lands on its own site only.
    assert _cell(out, 1, "Tarde")["availability"] == 1
    assert _cell(sites["sur"], 1, "Tarde")["availability"] == 1
    assert _cell(sites["norte"], 1, "Tarde")["availability"] == 0


def test_business_insights_bundles_everything_and_lists_data_gaps() -> None:
    out = bi.business_insights([_card("a", "no-action", "no_availability")])
    assert set(out) == {
        "calls_considered",
        "unavailability",
        "providers",
        "occupancy",
        "heatmap",
        "cancellations",
        "data_gaps",
    }
    assert out["calls_considered"] == 1
    assert len(out["data_gaps"]) >= 1


def test_is_real_call_excludes_every_offline_artefact() -> None:
    real = _card("CA-fake-123-00", "book")
    probe = _card("probe:adversarial.sales_call", "no-action", "out_of_scope")
    corpus_case = _card("adversarial-082c314b2882", "book")
    corpus_case.clinic = "synthetic-data"
    demo = _card("demo-book-1789820978", "book")
    demo.voice = "demo"
    assert bi.is_real_call(real) is True
    assert bi.is_real_call(probe) is False
    assert bi.is_real_call(corpus_case) is False
    assert bi.is_real_call(demo) is False


def test_business_insights_drops_probes_corpus_cases_and_demo_calls() -> None:
    real = _card("CA-fake-1", "book")
    real.action_payload = {"provider_id": "PR01"}
    probe = _card("probe:x", "no-action", "out_of_scope")
    corpus_case = _card("the_rules-abc123", "no-action", "no_availability")
    corpus_case.clinic = "synthetic-data"
    demo = _card("demo-book-1", "book")
    demo.voice = "demo"
    out = bi.business_insights([real, probe, corpus_case, demo])
    assert out["calls_considered"] == 1


# ---------------------------------------------------------------------------
# 5. Cancellations: reused vs. lost
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


def test_cancellation_lead_time_buckets_and_median() -> None:
    # One cancellation 12 h ahead of the slot, one 6 d ahead.
    close = _cancelled(
        _listed(
            _card("a", started_at="2026-09-19T10:00:00+00:00"),
            appointment_id="A1",
            provider_id="PR01",
            start="2026-09-19T22:00:00+00:00",
        ),
        appointment_id="A1",
        ts="2026-09-19T10:30:00+00:00",
    )
    far = _cancelled(
        _listed(
            _card("b", started_at="2026-09-19T10:00:00+00:00"),
            appointment_id="A2",
            provider_id="PR01",
            start="2026-09-25T10:00:00+00:00",
        ),
        appointment_id="A2",
        ts="2026-09-19T10:30:00+00:00",
    )
    lead = bi.cancellation_slots([close, far], now=_NOW)["lead_time"]
    assert lead["count"] == 2
    assert lead["median_hours"] == 78.0  # median of 12 h and 144 h
    counts = {b["key"]: b["count"] for b in lead["buckets"]}
    assert counts == {"under_24h": 1, "h24_48": 0, "h48_7d": 1, "over_7d": 0}
    assert lead["suggested_action"]


def test_cancellation_lead_time_skips_the_call_without_started_at() -> None:
    freed = _cancelled(
        _listed(
            _card("a"),  # no started_at
            appointment_id="A1",
            provider_id="PR01",
            start="2026-09-21T09:00:00+00:00",
        ),
        appointment_id="A1",
        ts="2026-09-19T08:00:00+00:00",
    )
    lead = bi.cancellation_slots([freed], now=_NOW)["lead_time"]
    assert lead["count"] == 0
    assert lead["median_hours"] is None


def test_cancellation_relocation_speed_measures_minutes_to_reoccupation() -> None:
    start = "2026-09-25T09:00:00+00:00"
    freed = _cancelled(
        _listed(
            _card("a", started_at="2026-09-20T08:00:00+00:00"),
            appointment_id="A1",
            provider_id="PR01",
            start=start,
        ),
        appointment_id="A1",
        ts="2026-09-20T08:05:00+00:00",
    )
    rebook = _booked(
        _card("b", started_at="2026-09-20T08:35:00+00:00"), provider_id="PR01", slot=start
    )
    out = bi.cancellation_slots([freed, rebook], now=_NOW)
    assert out["relocated"] == 1
    # From the cancel submit (08:05) to the rebooking call's start (08:35).
    assert out["relocation_speed"] == {"count": 1, "median_minutes": 30.0}


def test_cancel_rate_is_over_every_appointment_action() -> None:
    start = "2026-09-25T09:00:00+00:00"
    cards = [
        _booked(_card("b1"), provider_id="PR01", slot=start),
        _booked(_card("b2"), provider_id="PR02", slot=start),
        _cancelled(
            _listed(_card("c1"), appointment_id="A1", provider_id="PR01", start=start),
            appointment_id="A1",
            ts="2026-09-19T08:00:00+00:00",
        ),
        _card("x", "no-action", "no_availability"),  # not an appointment action
    ]
    out = bi.cancellation_slots(cards, now=_NOW)
    assert out["cancel_rate"] == {"cancels": 1, "appointments": 3, "pct": 33.3}


def test_cancellations_by_provider_rank_freed_and_lost() -> None:
    cards = [
        _cancelled(
            _listed(
                _card("a"),
                appointment_id="A1",
                provider_id="PR01",
                start="2026-09-19T09:00:00+00:00",
            ),
            appointment_id="A1",
            ts="2026-09-18T08:00:00+00:00",
        ),
        _cancelled(
            _listed(
                _card("b"),
                appointment_id="A2",
                provider_id="PR01",
                start="2026-09-25T09:00:00+00:00",
            ),
            appointment_id="A2",
            ts="2026-09-18T08:00:00+00:00",
        ),
        _cancelled(
            _listed(
                _card("c"),
                appointment_id="A3",
                provider_id="PR02",
                start="2026-09-19T10:00:00+00:00",
            ),
            appointment_id="A3",
            ts="2026-09-18T08:00:00+00:00",
        ),
    ]
    rows = bi.cancellation_slots(cards, now=_NOW)["by_provider"]
    assert rows == [
        {"id": "PR01", "name": "Dra. Ortiz", "freed": 2, "lost": 1},
        {"id": "PR02", "name": "Dr. Sáez", "freed": 1, "lost": 1},
    ]


def test_classify_cancel_reason_buckets() -> None:
    assert (
        bi.classify_cancel_reason(_say(_card("a"), "me equivoqué de día, la tenía mal apuntada"))
        == "mistake"
    )
    assert (
        bi.classify_cancel_reason(_say(_card("b"), "ya estoy mejor, ya se me ha pasado"))
        == "health"
    )
    assert (
        bi.classify_cancel_reason(_say(_card("c"), "me ha surgido una reunión en el trabajo"))
        == "scheduling"
    )
    assert (
        bi.classify_cancel_reason(_say(_card("d"), "porque al final no me hace falta"))
        == "no_longer_needed"
    )
    assert bi.classify_cancel_reason(_say(_card("e"), "sí, cancélemela por favor")) == "unknown"
    assert bi.classify_cancel_reason(_card("f")) == "unknown"
    assert bi.classify_cancel_reason(_say(_card("g"), "es que tengo un compromiso")) == "other"


def test_cancel_reasons_keep_residual_buckets_last_even_when_larger() -> None:
    def _mk(cid: str, text: str) -> CallCard:
        card = _listed(
            _card(cid),
            appointment_id=f"A-{cid}",
            provider_id="PR01",
            start="2026-09-19T09:00:00+00:00",
        )
        card = _cancelled(card, appointment_id=f"A-{cid}", ts="2026-09-18T08:00:00+00:00")
        return _say(card, text)

    # One specific reason (mistake) with a single case; three residual "other"
    # cases outnumber it, yet must still print below it.
    cards = [_mk("m1", "me equivoqué de día")] + [
        _mk(f"o{i}", "es que tengo un compromiso") for i in range(3)
    ]
    out = bi.cancellation_slots(cards, now=_NOW)
    keys = [r["key"] for r in out["reasons"]]
    assert keys[0] == "mistake"
    assert keys[-1] == "other"
    assert out["reasons"][0]["count"] == 1
    assert out["reasons"][-1]["count"] == 3


def test_cancel_reasons_are_not_sorted_by_count() -> None:
    def _mk(cid: str, text: str) -> CallCard:
        card = _listed(
            _card(cid),
            appointment_id=f"A-{cid}",
            provider_id="PR01",
            start="2026-09-19T09:00:00+00:00",
        )
        card = _cancelled(card, appointment_id=f"A-{cid}", ts="2026-09-18T08:00:00+00:00")
        return _say(card, text)

    # "scheduling" has a single case, "mistake" has five — a count-based sort
    # would put mistake first. It must not: the fixed bucket order wins.
    cards = [_mk("s1", "me ha surgido un imprevisto")] + [
        _mk(f"m{i}", "me equivoqué de día") for i in range(5)
    ]
    out = bi.cancellation_slots(cards, now=_NOW)
    keys = [r["key"] for r in out["reasons"]]
    assert keys.index("scheduling") < keys.index("mistake")


def test_waitlist_counts_unmet_callers_who_wanted_a_lost_slot() -> None:
    freed = _cancelled(
        _listed(
            _card("a"),
            appointment_id="A1",
            provider_id="PR01",
            start="2026-09-19T09:00:00+00:00",
        ),
        appointment_id="A1",
        ts="2026-09-18T08:00:00+00:00",
    )
    u1 = _say(_card("u1", "no-action", "no_availability"), "quiero a la dra ortiz")
    u2 = _say(_card("u2", "no-action", "provider_on_leave"), "necesito a la dra ortiz")
    # A different doctor and no matching band: does not count.
    u3 = _say(_card("u3", "no-action", "no_availability"), "quiero al dr sáez")
    out = bi.cancellation_slots([freed, u1, u2, u3], now=_NOW)
    assert out["lost"] == 1
    assert out["waitlist"]["lost_with_demand"] == 1
    assert out["waitlist"]["callers"] == 2
    assert out["waitlist"]["suggested_action"]


def test_waitlist_ignores_relocated_and_pending_slots() -> None:
    start = "2026-09-25T09:00:00+00:00"
    pending = _cancelled(
        _listed(_card("a"), appointment_id="A1", provider_id="PR01", start=start),
        appointment_id="A1",
        ts="2026-09-18T08:00:00+00:00",
    )
    relocated = _cancelled(
        _listed(_card("b"), appointment_id="A2", provider_id="PR02", start=start),
        appointment_id="A2",
        ts="2026-09-18T08:00:00+00:00",
    )
    rebook = _booked(_card("r"), provider_id="PR02", slot=start)
    unmet = _say(_card("u", "no-action", "no_availability"), "quiero a la dra ortiz")
    out = bi.cancellation_slots([pending, relocated, rebook, unmet], now=_NOW)
    assert out["waitlist"]["callers"] == 0
    assert out["waitlist"]["suggested_action"] is None


def test_repeat_cancellers_counted_without_exposing_numbers() -> None:
    cards = [
        _cancelled(
            _listed(
                _card("a", from_number="+34611"),
                appointment_id="A1",
                provider_id="PR01",
                start="2026-09-25T09:00:00+00:00",
            ),
            appointment_id="A1",
            ts="2026-09-19T08:00:00+00:00",
        ),
        _cancelled(
            _listed(
                _card("b", from_number="+34611"),
                appointment_id="A2",
                provider_id="PR01",
                start="2026-09-26T09:00:00+00:00",
            ),
            appointment_id="A2",
            ts="2026-09-19T09:00:00+00:00",
        ),
        _cancelled(
            _listed(
                _card("c", from_number="+34622"),
                appointment_id="A3",
                provider_id="PR02",
                start="2026-09-26T10:00:00+00:00",
            ),
            appointment_id="A3",
            ts="2026-09-19T09:30:00+00:00",
        ),
        # Same number but not a cancel action: does not count.
        _card("d", "no-action", "no_availability", from_number="+34611"),
    ]
    out = bi.cancellation_slots(cards, now=_NOW)
    assert out["repeat_callers"] == {"callers": 1, "cancellations": 2}
    assert "+34611" not in str(out)
