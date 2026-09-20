"""The clinic console: Overview, Agents, Calls › Live, Patients, Insights,
Settings. Team pages, inside the sidebar shell.

Everything on these pages is either real (the call log, the clinic API,
``/health``, the evals summary) or carries a Preview chip. The words come from
``explain.py`` and ``agents.py``; the numbers from ``insights.py``.
"""

from __future__ import annotations

from typing import Any

from nicegui import ui

from vortex.clinic import make_clinic_client
from vortex.observability import agents, callfeed, explain, insights, live, pricing
from vortex.observability.shell import (
    bars,
    console_page,
    hours,
    preview_chip,
    preview_note,
    section,
    table,
)
from vortex.observability.view import CallCard
from vortex.settings import get_settings
from vortex.tools import TOOLS

REASON_LABELS = {k: v.rstrip(".") for k, v in explain.REASON_TEXT.items()}


def _guard() -> bool:
    live._apply_chrome()
    if not live._ops_ok():
        live._login_form()
        return False
    return True


def _who() -> str | None:
    return "team"


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _attention(cards: list[CallCard]) -> list[tuple[str, str, str, str, str]]:
    """(dot, title, detail, meta, href) rows that need a human."""
    rows: list[tuple[str, str, str, str, str]] = []
    for card in cards[:60]:
        href = f"/call/{card.call_id}"
        when = live._clock(card.started_at)
        if card.status == "escalated":
            rows.append(
                (
                    "warn",
                    f"Escalated · {live._caller(card)}",
                    explain.reason_text(card.decline_reason) or "Handed to a person.",
                    when,
                    href,
                )
            )
        elif card.ended and card.action_kind and not (card.submit_status or card.submit_route):
            rows.append(
                (
                    "bad",
                    f"Prepared but never submitted · {live._caller(card)}",
                    "The socket closed before the action was sent.",
                    when,
                    href,
                )
            )
        elif card.submit_status and card.submit_status not in {"accepted", "submitted", "dry_run"}:
            rows.append(
                (
                    "bad",
                    f"Submission {card.submit_status} · {live._caller(card)}",
                    f"The platform answered {card.submit_status} on "
                    f"{card.submit_route or 'the submit route'}.",
                    when,
                    href,
                )
            )
        elif card.ended and not card.patient_name and card.action_kind in {"no-action", None}:
            rows.append(
                (
                    "warn",
                    "Unidentified patient",
                    f"{card.from_number or 'No number'} · "
                    f"{explain.reason_text(card.decline_reason) or 'No patient matched.'}",
                    when,
                    href,
                )
            )
        elif card.reason == "stale":
            rows.append(
                (
                    "off",
                    f"Socket went quiet · {live._caller(card)}",
                    "No event for three minutes. Treated as ended.",
                    when,
                    href,
                )
            )
    return rows[:8]


@ui.page("/")
def overview_page() -> None:
    live._apply_chrome()
    if not live._ops_ok():
        live._login_form()
        return
    ui.page_title("Vortex · Overview")
    cards, health = live._load_cards()
    stats = explain.stats_for(cards)
    with console_page(
        "/",
        "Overview",
        f"{live.CLINIC_NAME}'s AI front desk. What is on the line now, what needs a "
        "person, and how the day is going.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
        controls=lambda: live._line_pill(health),
    ) as body:
        with body:
            live._kpis(cards)
            with ui.element("div").classes("cols-2"):
                with ui.element("div"):
                    with section(
                        "Agents on duty",
                        f"{len(agents.real_agents())} live · "
                        f"{len(agents.preview_agents())} in preview",
                    ):
                        with ui.element("div").classes("agent-grid"):
                            for agent in agents.AGENTS:
                                _agent_card(
                                    agent, stats if not agent.preview else None, compact=True
                                )
                with ui.element("div"):
                    attention = _attention(cards)
                    with section(
                        "Needs attention",
                        f"{len(attention)} items" if attention else "nothing right now",
                    ):
                        if not attention:
                            with ui.element("div").classes("empty-state"):
                                ui.label("All clear").classes("t")
                                ui.label(
                                    "Escalations, failed submissions and unidentified "
                                    "patients show here."
                                ).classes("d")
                        for dot, title, detail, meta, href in attention:
                            with ui.link(target=href).classes("attn"):
                                live._dot(dot)
                                with ui.element("div"):
                                    ui.label(title).classes("t")
                                    ui.label(detail).classes("d")
                                ui.label(meta).classes("m")
            live._live_strip(cards, live._feature(cards))
            with section("Recent calls", "Click a row for the full story"):
                live._calls_table(cards, link=True, limit=10)
        live._footer()


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


def _agent_card(agent: agents.Agent, stats: explain.Stats | None, *, compact: bool = False) -> None:
    with ui.link(target=f"/agents/{agent.slug}").classes(
        "agent-card live" if not agent.preview else "agent-card"
    ):
        with ui.element("div").classes("row"):
            ui.label(agent.role).classes("role")
            ui.element("div").classes("grow")
            if agent.preview:
                preview_chip()
            else:
                live._pill("On duty", "ok", "mute")
        ui.label(agent.name).classes("name")
        if not compact:
            ui.label(agent.summary).classes("summary")
        if stats is not None:
            with ui.element("div").classes("kpis"):
                for n, label in (
                    (str(stats.calls), "calls"),
                    (str(stats.booked), "booked"),
                    (str(stats.refused + stats.escalated), "refused or escalated"),
                ):
                    with ui.element("div"):
                        ui.label(n).classes("n")
                        ui.label(label).classes("l")
        elif agent.preview and not compact:
            ui.label("No calls yet. This agent is on the roadmap.").classes("caption-sm")


@ui.page("/agents")
def agents_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Agents")
    cards, health = live._load_cards()
    stats = explain.stats_for(cards)
    with console_page(
        "/agents",
        "Agents",
        "Every voice agent the clinic runs. One is on the line today; the others are on "
        "the roadmap and say so.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
    ) as body:
        with body:
            with ui.element("div").classes("agent-grid"):
                for agent in agents.AGENTS:
                    _agent_card(agent, stats if not agent.preview else None)
        live._footer()


@ui.page("/agents/{slug}")
def agent_page(slug: str) -> None:
    if not _guard():
        return
    agent = agents.get_agent(slug)
    cards, health = live._load_cards()
    ui.page_title(f"Vortex · {agent.name if agent else 'Agent'}")
    with console_page(
        "/agents",
        agent.name if agent else "Unknown agent",
        agent.role if agent else "",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
        controls=(lambda: preview_chip())
        if agent and agent.preview
        else (lambda: live._pill("On duty", "ok", "mute")),
    ) as body:
        with body:
            if agent is None:
                with ui.element("div").classes("empty-state"):
                    ui.label("No agent with this name").classes("t")
                    ui.link("Back to Agents", "/agents").classes("caption-sm")
                return
            if agent.preview:
                preview_note(
                    "This agent is on the roadmap. The description below is the plan; there "
                    "are no calls and no numbers."
                )
            ui.label(agent.summary).classes("lede")
            if not agent.preview:
                live._kpis(cards)
            with ui.element("div").classes("cols-3"):
                with ui.element("div"):
                    with section("Tools it can call", f"{len(agent.tools)}"):
                        for name in agent.tools:
                            spec = TOOLS.get(name)
                            with ui.element("div").classes("tl-row"):
                                live._dot("ok" if spec else "off")
                                with ui.element("div"):
                                    with ui.element("div").classes("row").style("gap:0"):
                                        ui.label(explain.tool_description(name)).classes("what")
                                        ui.label(name).classes("tool")
                                    endpoint = explain.tool_endpoint(name)
                                    if endpoint:
                                        ui.label(endpoint).classes("said")
                                ui.label("")
                with ui.element("div"):
                    with section("Rules it enforces"):
                        for rule in agent.rules:
                            ui.label(rule).classes("feature-bullet")
                    if agent.will_do:
                        ui.element("div").style("height:16px")
                        with section("What it will do"):
                            for item in agent.will_do:
                                ui.label(item).classes("feature-bullet")
                with ui.element("div"):
                    with section("Profile"):
                        with ui.element("dl").classes("def"):
                            for k, v in (
                                ("Languages", ", ".join(agent.languages)),
                                ("Channels", ", ".join(agent.channels)),
                                ("Status", agent.status_label),
                                ("Clinic data", "read-only EHR API"),
                            ):
                                ui.html(f"<dt>{k}</dt><dd>{live._escape(v)}</dd>")
            if not agent.preview:
                with section("Recent calls", "Newest first"):
                    live._calls_table(cards, link=True, limit=15)
        live._footer()


# ---------------------------------------------------------------------------
# Calls › Live
# ---------------------------------------------------------------------------


@ui.page("/calls/live/classic")
async def calls_live_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Live")
    cards, health = live._load_cards()
    with console_page(
        "/calls/live",
        "Live",
        explain.LIVE_SUB,
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
        controls=lambda: ui.link("Open the wall ↗", "/wall", new_tab=True).classes("pill"),
    ) as body:
        stage = body
        rendered: dict[str, Any] = {"sig": None}

        async def redraw() -> None:
            cards, health = await live._load_cards_async()
            sig = live._signature(cards, health)
            if sig == rendered["sig"]:
                return
            rendered["sig"] = sig
            featured = live._feature(cards)
            stage.clear()
            with stage:
                live._live_strip(cards, featured)
                live._workflow_panel(featured)

        await redraw()
        ui.timer(0.6, redraw)
        live._footer()


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------


@ui.page("/patients")
def patients_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Patients")
    cards, health = live._load_cards()
    rows = insights.patients(cards)
    with console_page(
        "/patients",
        "Patients",
        "Everyone who has called the line, with their last outcome. Built from the calls; "
        "the clinic's own record stays in the EHR.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
    ) as body:
        with body:
            if not rows:
                with ui.element("div").classes("empty-state"):
                    ui.label("No patient yet").classes("t")
                    ui.label("The first call fills this table.").classes("d")
            else:
                with ui.element("div").classes("stat-grid"):
                    live._stat(str(len(rows)), "patients seen")
                    live._stat(
                        str(sum(1 for r in rows if r.name != "Unidentified patient")),
                        "matched in the directory",
                    )
                    live._stat(str(sum(r.calls for r in rows)), "calls")
                table(
                    (
                        "Patient",
                        "Phone",
                        "Insurer",
                        "Calls",
                        "Last outcome",
                        "Why not booked",
                        "Last call",
                    ),
                    [
                        [
                            r.name,
                            r.phone,
                            r.insurer,
                            r.calls,
                            (lambda r=r: _status_cell(r.last_status)),
                            r.last_reason,
                            (
                                lambda r=r: ui.link(
                                    r.last_call_id, f"/call/{r.last_call_id}"
                                ).classes("caption-sm mono")
                            ),
                        ]
                        for r in rows
                    ],
                    classes=("", "mono", "", "num", "", "mute", "id"),
                )
        live._footer()


def _status_cell(status: str) -> None:
    with ui.element("div").classes("row"):
        live._dot(live._status_dot(status))
        ui.label(explain.STATUS_LABEL.get(status, status))


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


@ui.page("/insights")
def insights_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Insights")
    cards, health = live._load_cards()
    ended = [c for c in cards if not c.live]
    seconds = insights.handle_seconds(ended)
    p50, p95 = insights.percentiles(seconds, 0.5, 0.95)
    mx = seconds[-1] if seconds else None
    cost = insights.cost_per_call(ended)
    today = insights.cost_per_call(insights.on_day(ended))
    with console_page(
        "/insights",
        "Insights",
        "Why calls do not book, how long they take, and which tools are slow. Computed "
        "from the call log; nothing is sampled.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
    ) as body:
        with body:
            with ui.element("div").classes("stat-grid"):
                live._stat(str(len(ended)), "calls ended")
                live._stat("—" if p50 is None else f"{p50:.0f} s", "p50 handle time")
                live._stat("—" if p95 is None else f"{p95:.0f} s", "p95 handle time")
                live._stat("—" if mx is None else f"{mx:.0f} s", "longest call")
                live._stat(
                    pricing.eur(cost.avg_list_eur),
                    "€/call (list)",
                    note=live._priced_note(cost),
                )
                live._stat(
                    pricing.eur(cost.avg_paid_eur),
                    "€/call (we pay)",
                    note="LLM is a Helmcode perk" if cost.perk else None,
                )
                live._stat(
                    pricing.eur(today.total_list_eur, 2) if today.priced else "—",
                    "€ today (list)",
                    note=f"{today.priced} calls" if today.priced else None,
                )
            if cost.unpriced:
                ui.label(
                    "Not in the price table, so left out of the averages: "
                    + ", ".join(cost.unpriced)
                ).classes("caption-sm")
            with ui.element("div").classes("cols-2"):
                with ui.element("div"):
                    with section("Why not booked", "by typed reason"):
                        bars(
                            insights.reasons(ended, REASON_LABELS),
                            empty="No refusal yet. Every refusal carries a reason and lands here.",
                        )
                with ui.element("div"):
                    with section("Outcomes", "ended calls"):
                        bars(
                            insights.outcomes(ended, explain.STATUS_LABEL),
                            empty="No call has ended yet.",
                        )
            with ui.element("div").classes("cols-2"):
                with ui.element("div"):
                    latency = insights.tool_latency(cards)
                    failures = insights.tool_failures(cards)
                    with section("Tool latency", "median per tool, slowest first"):
                        if not latency:
                            ui.label("No tool call yet.").classes("empty")
                        else:
                            table(
                                ("Tool", "What it does", "Median", "Calls", "Failed"),
                                [
                                    [
                                        name,
                                        explain.tool_description(name),
                                        live._ms(ms),
                                        n,
                                        failures.get(name, 0) or "",
                                    ]
                                    for name, ms, n in latency
                                ],
                                classes=("mono", "mute", "num", "num", "num"),
                            )
                with ui.element("div"):
                    with section("Calls by hour", "Europe/Madrid"):
                        hours(insights.calls_by_hour(cards))
        live._footer()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _g(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _catalogue() -> Any | None:
    client = make_clinic_client()
    try:
        return await client.catalogue()
    except Exception:
        return None
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _hm(value: Any) -> str:
    return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)


def _hours_text(entries: Any) -> str:
    """Opening hours (weekday 0..6, opens, closes) -> 'Mon–Fri 09:00–20:00 · Sat 09:00–14:00'."""
    spans: dict[str, list[int]] = {}
    order: list[str] = []
    for row in entries or []:
        day = _g(row, "weekday")
        if isinstance(day, int) and 0 <= day <= 6:
            key = f"{_hm(_g(row, 'opens'))}–{_hm(_g(row, 'closes'))}"
        elif isinstance(day, str):
            key = " · ".join(str(i) for i in (_g(row, "intervals", []) or []))
            day = DAYS.index(day[:3].capitalize()) if day[:3].capitalize() in DAYS else 0
        else:
            continue
        if key not in spans:
            spans[key] = []
            order.append(key)
        spans[key].append(day)
    parts = []
    for key in order:
        days = sorted(spans[key])
        label = DAYS[days[0]] if len(days) == 1 else f"{DAYS[days[0]]}–{DAYS[days[-1]]}"
        parts.append(f"{label} {key}")
    return " · ".join(parts) if parts else "—"


def _leave_text(leave: Any) -> str:
    rows = leave if isinstance(leave, list) else ([leave] if leave else [])
    parts = []
    for row in rows:
        start = _g(row, "date_from") or _g(row, "start")
        end = _g(row, "date_to") or _g(row, "end")
        reason = _g(row, "reason", "")
        parts.append(f"{start} → {end}" + (f" · {reason}" if reason else ""))
    return "; ".join(parts)


@ui.page("/settings")
async def settings_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Settings")
    cards, health = live._load_cards()
    cat = await _catalogue()
    source = (
        "live clinic API"
        if health and health.get("clinic") == "live"
        else "clinic fixtures (no platform key)"
    )
    with console_page(
        "/settings",
        "Clinic",
        "Sites, hours, doctors and closures, read from the clinic's EHR. The agent "
        "reasons with exactly this data.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
        controls=lambda: live._pill(f"Source · {source}", "ok" if cat else "bad", "mute"),
    ) as body:
        with body:
            if cat is None:
                with ui.element("div").classes("empty-state"):
                    ui.label("The clinic API did not answer").classes("t")
                    ui.label("Check the platform key and the base URL in Integrations.").classes(
                        "d"
                    )
            else:
                with ui.element("div").classes("stat-grid"):
                    live._stat(str(len(_g(cat, "locations", []))), "sites")
                    live._stat(str(len(_g(cat, "providers", []))), "doctors")
                    live._stat(str(len(_g(cat, "specialties", []))), "specialties")
                    live._stat(str(_g(cat, "patient_count", "—")), "patients in the directory")
                    live._stat(f"{_g(cat, 'slot_minutes', '—')} min", "slot length")
                with section("Sites", _g(cat, "clinic_name", "")):
                    table(
                        ("Site", "Address", "Hours", "Doctors", "Plans not accepted"),
                        [
                            [
                                _g(loc, "name"),
                                _g(loc, "address"),
                                _hours_text(_g(loc, "hours")),
                                len(_g(loc, "provider_ids", []) or []),
                                ", ".join(_g(loc, "insurer_ids_excluded", []) or []) or "none",
                            ]
                            for loc in _g(cat, "locations", [])
                        ],
                        classes=("", "mute", "mute", "num", "mute"),
                    )
                with section("Doctors"):
                    table(
                        ("Doctor", "Specialty", "Languages", "Sites", "Plans refused", "Leave"),
                        [
                            [
                                _g(p, "name"),
                                _g(p, "specialty_name"),
                                ", ".join(_g(p, "languages", []) or []),
                                ", ".join(_g(p, "location_ids", []) or []),
                                ", ".join(_g(p, "insurer_ids_refused", []) or []) or "none",
                                (_leave_text(_g(p, "leave")) if _g(p, "leave") else ""),
                            ]
                            for p in _g(cat, "providers", [])
                        ],
                        classes=("", "", "mute", "mute", "mute", "mute"),
                    )
                with ui.element("div").classes("cols-2"):
                    with ui.element("div"):
                        with section("Booking window"):
                            with ui.element("dl").classes("def"):
                                for k, v in (
                                    ("Bookable from", str(_g(cat, "bookable_from", "—"))),
                                    ("Bookable to", str(_g(cat, "bookable_to", "—"))),
                                    ("Max span", f"{_g(cat, 'max_span_days', '—')} days"),
                                    (
                                        "Closures",
                                        ", ".join(str(d) for d in _g(cat, "closure_days", []) or [])
                                        or "none",
                                    ),
                                ):
                                    ui.html(f"<dt>{k}</dt><dd>{live._escape(v)}</dd>")
                    with ui.element("div"):
                        with section("Team"):
                            with ui.element("dl").classes("def"):
                                ui.html("<dt>Signed in</dt><dd>team</dd>")
                                ui.html(
                                    "<dt>Access</dt><dd>password, set with VORTEX_OPS_PASSWORD</dd>"
                                )
        live._footer()


@ui.page("/settings/rules")
async def rules_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Rules")
    _cards, health = live._load_cards()
    cat = await _catalogue()
    with console_page(
        "/settings/rules",
        "Rules",
        "What the clinic refuses and why. Every refusal the agent submits names one of these.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
    ) as body:
        with body:
            if cat is None:
                ui.label("The clinic API did not answer.").classes("empty")
            else:
                with section("Refusal reasons", "the platform's vocabulary"):
                    table(
                        ("Reason", "Rule", "What the agent says"),
                        [
                            [
                                _g(r, "reason") or _g(r, "rule_id"),
                                _g(r, "description") or _g(r, "title"),
                                explain.reason_text(str(_g(r, "reason") or _g(r, "rule_id") or "")),
                            ]
                            for r in _g(cat, "restrictions", [])
                        ],
                        classes=("mono", "", "mute"),
                    )
                with section("Specialties", "age window and referral"):
                    table(
                        ("Specialty", "Min age", "Max age", "Referral", "Plans not covering"),
                        [
                            [
                                _g(s, "name"),
                                _age(_g(s, "min_age_months")),
                                _age(_g(s, "max_age_months")),
                                "required" if _g(s, "referral_required") else "no",
                                ", ".join(_g(s, "insurer_ids_excluded", []) or []) or "none",
                            ]
                            for s in _g(cat, "specialties", [])
                        ],
                        classes=("", "num", "num", "", "mute"),
                    )
                plans = _g(cat, "insurance_plans", []) or []
                specialties = _g(cat, "specialties", []) or []
                if plans and specialties:
                    with section("Insurance matrix", "plan × specialty"):
                        headers = ("Plan",) + tuple(str(_g(s, "name")) for s in specialties)
                        rows = []
                        for plan in plans:
                            pid = str(
                                _g(plan, "insurer_id")
                                or _g(plan, "plan_id")
                                or _g(plan, "id")
                                or ""
                            )
                            row: list[Any] = [str(_g(plan, "name") or pid)]
                            for s in specialties:
                                covered = pid in (_g(s, "insurer_ids", []) or []) and pid not in (
                                    _g(s, "insurer_ids_excluded", []) or []
                                )
                                row.append(
                                    (lambda covered=covered: None)
                                    if False
                                    else ("yes" if covered else "no")
                                )
                            rows.append(row)
                        with (
                            ui.element("div").classes("table-wrap"),
                            ui.element("table").classes("table matrix"),
                        ):
                            with ui.element("thead"), ui.element("tr"):
                                for head in headers:
                                    with ui.element("th"):
                                        ui.label(head)
                            with ui.element("tbody"):
                                for row in rows:
                                    with ui.element("tr"):
                                        with ui.element("td"):
                                            ui.label(str(row[0]))
                                        for cell in row[1:]:
                                            ui.element("td").classes(cell)
        live._footer()


def _age(months: Any) -> str:
    if months in (None, ""):
        return "—"
    try:
        m = int(months)
    except (TypeError, ValueError):
        return str(months)
    return f"{m // 12} y" if m % 12 == 0 else f"{m} mo"


@ui.page("/settings/integrations")
def integrations_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Integrations")
    _cards, health = live._load_cards()
    settings = get_settings()
    h = health or {}
    with console_page(
        "/settings/integrations",
        "Integrations",
        "Where the calls come from, where the clinic data lives, and which providers "
        "speak and listen.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
    ) as body:
        with body:
            with ui.element("div").classes("cols-2"):
                with ui.element("div"):
                    with section("Telephony", "Twilio Media Streams over WebSocket"):
                        with ui.element("dl").classes("def"):
                            for k, v in (
                                ("Socket path", str(h.get("ws_path") or settings.ws_path)),
                                ("Line", "up" if health else "down"),
                                ("Audio", "8 kHz µ-law, 20 ms frames"),
                                ("Concurrency", "one pipeline per socket"),
                            ):
                                ui.html(f"<dt>{k}</dt><dd>{live._escape(v)}</dd>")
                    ui.element("div").style("height:24px")
                    with section("Clinic data", "read-only EHR API"):
                        with ui.element("dl").classes("def"):
                            for k, v in (
                                (
                                    "Base URL",
                                    str(
                                        h.get("platform_api_base_url")
                                        or settings.platform_api_base_url
                                    ),
                                ),
                                (
                                    "Mode",
                                    str(
                                        h.get("clinic")
                                        or ("live" if settings.clinic_is_live else "fake")
                                    ),
                                ),
                                ("Endpoints", "directory, availability, appointments, catalogue"),
                            ):
                                ui.html(f"<dt>{k}</dt><dd>{live._escape(v)}</dd>")
                with ui.element("div"):
                    with section("Voice providers", "swapped with an environment variable"):
                        with ui.element("dl").classes("def"):
                            for k, v in (
                                ("Speech to text", f"Soniox {h.get('stt_model', '')}".strip()),
                                (
                                    "Language model",
                                    f"{h.get('llm_provider', '')} · {h.get('llm_model', '')}".strip(
                                        " ·"
                                    ),
                                ),
                                (
                                    "Text to speech",
                                    f"{h.get('tts_provider', '')} · {h.get('tts_model', '')}".strip(
                                        " ·"
                                    ),
                                ),
                                (
                                    "Languages spoken",
                                    ", ".join(h.get("tts_languages", []) or []) or "—",
                                ),
                                ("Voice mode", str(h.get("voice") or "—")),
                            ):
                                ui.html(f"<dt>{k}</dt><dd>{live._escape(v) or '—'}</dd>")
                    ui.element("div").style("height:24px")
                    with section("Console"):
                        with ui.element("dl").classes("def"):
                            for k, v in (
                                ("Reads calls from", callfeed.LINE_URL),
                                ("Public pages", "/wall, /call/{id} (phone numbers masked)"),
                            ):
                                ui.html(f"<dt>{k}</dt><dd>{live._escape(v)}</dd>")
        live._footer()


@ui.page("/settings/engineering")
def engineering_page() -> None:
    if not _guard():
        return
    ui.page_title("Vortex · Engineering")
    _cards, health = live._load_cards()
    with console_page(
        "/settings/engineering",
        "Engineering",
        "The evaluation harness behind the agent: tool logic, scripted conversations, "
        "the organisers' public cases, and the provider bench.",
        health=health,
        clinic=live.CLINIC_NAME,
        who=_who(),
    ) as body:
        with body:
            with section("Evals", "make evals"):
                live._evals_body()
            with section("Bench", "make evals-voice"):
                live._bench_body()
        live._footer()
