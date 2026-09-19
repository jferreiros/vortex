"""The Live flow: the call in progress as three acts, on a dark canvas.

``/wall/flow`` is public and made for a projector. ``/calls/live`` is the same
page inside the team console. Both render incrementally: a turn or a tool
call is appended when it happens and never rebuilt, so cards enter once, the
speaker pulses, the current stage glows and the verdict lands once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nicegui import ui

from vortex.observability import explain, live
from vortex.observability.view import CallCard, ToolStep

LIVE_CSS = (Path(__file__).with_name("live.css")).read_text(encoding="utf-8")

_STAGE_OF_TOOL = {
    **dict.fromkeys(("find_patient", "validate_national_id", "build_registration"), 2),
    **dict.fromkeys(
        (
            "find_provider",
            "resolve_date",
            "check_eligibility",
            "find_slots",
            "list_appointments",
            "prepare_booking",
            "prepare_reschedule",
            "prepare_cancel",
            "triage",
            "nearest_location",
        ),
        3,
    ),
    "submit_action": 4,
}


def _stage_for(step: ToolStep) -> int:
    return _STAGE_OF_TOOL.get(step.name, 3)


@dataclass
class ToolView:
    card: ui.element
    dot: ui.element
    said: ui.element
    ms: ui.element
    status: str


@dataclass
class Scene:
    """Everything the page keeps between ticks."""

    call_id: str | None = None
    turns: int = 0
    tools: list[ToolView] = field(default_factory=list)
    stage: int = -1
    verdict_key: tuple | None = None
    last_speaker: ui.element | None = None
    foot_sig: tuple | None = None
    head_sig: tuple | None = None
    convo: ui.element | None = None
    nodes: list[ui.element] = field(default_factory=list)
    node_cards: list[ui.element] = field(default_factory=list)
    verdict: ui.element | None = None
    record: ui.element | None = None
    stage_box: ui.element | None = None
    waiting: ui.element | None = None


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def _sound_bars() -> ui.element:
    bars = ui.element("span").classes("bars-live")
    with bars:
        for _ in range(4):
            ui.element("i")
    return bars


def _say(convo: ui.element, role: str, text: str, when: str) -> ui.element:
    with convo:
        say = ui.element("div").classes(f"say {role}")
        with say:
            with ui.element("div").classes("avatar"):
                ui.label("PT" if role == "user" else "VX")
            with ui.element("div").classes("bubble-wrap"):
                ui.label(text).classes("bubble")
                with ui.element("div").classes("who row").style("gap:0"):
                    ui.label(
                        ("Patient" if role == "user" else "Vortex") + (f" · {when}" if when else "")
                    )
    return say


def _tool_card(container: ui.element, step: ToolStep) -> ToolView:
    with container:
        card = ui.element("div").classes(f"tcard {_tool_state(step)}")
        with card:
            dot = ui.element("span").classes(f"dot {live._tool_dot(step.status)}")
            with ui.element("div"):
                with ui.element("div").classes("row").style("gap:0"):
                    ui.label(explain.tool_description(step.name)).classes("what")
                    ui.label(step.name).classes("tool")
                said = ui.label(explain.step_text(step)).classes(_said_class(step))
            ms = ui.label(_ms_text(step)).classes("ms")
    return ToolView(card=card, dot=dot, said=said, ms=ms, status=step.status)


def _tool_state(step: ToolStep) -> str:
    return {"running": "running", "fail": "failed"}.get(step.status, "done")


def _said_class(step: ToolStep) -> str:
    text = explain.step_text(step)
    return "said bad" if step.status == "fail" or text.startswith("Rejected") else "said"


def _ms_text(step: ToolStep) -> str:
    if step.status == "running":
        return "running"
    return live._ms(step.ms) if step.ms is not None else step.status


def _update_tool(view: ToolView, step: ToolStep) -> None:
    if view.status == step.status:
        return
    view.status = step.status
    view.card.classes(remove="running failed done", add=_tool_state(step))
    view.dot.classes(remove="live ok bad off", add=live._tool_dot(step.status))
    view.said.set_text(explain.step_text(step))
    view.said.classes(remove="bad", add="bad" if _said_class(step).endswith("bad") else "")
    view.ms.set_text(_ms_text(step))


def _node_state(index: int, reached: int, is_live: bool) -> str:
    if is_live and index == max(reached, 1):
        return "now"
    if index <= reached:
        return "done"
    return "off"


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def _skeleton(scene: Scene, *, public: bool) -> tuple[ui.element, ui.element, ui.element]:
    """The static frame. Returns (head_state_slot, stage, foot)."""
    root = ui.element("div").classes("livepage")
    with root:
        with ui.element("header").classes("live-head"):
            ui.link("Vortex", "/wall/flow" if public else "/").classes("brand")
            ui.label(live.CLINIC_NAME).classes("clinic")
            state_slot = ui.element("div").classes("row")
            ui.element("div").classes("grow")
            meta = ui.element("div").classes("row")
            with meta:
                if public:
                    ui.link("Console", "/").classes("pill mute")
                else:
                    ui.link("Open the wall ↗", "/wall/flow", new_tab=True).classes("pill mute")
        stage = ui.element("div").classes("live-body")
        foot = ui.element("footer").classes("live-foot")
    return state_slot, stage, foot


def _build_stage(scene: Scene, card: CallCard, *, public: bool) -> None:
    """Draw the three acts for a call from scratch. Called once per call."""
    assert scene.stage_box is not None
    scene.stage_box.clear()
    scene.tools = []
    scene.nodes = []
    scene.node_cards = []
    scene.turns = 0
    scene.stage = -1
    scene.verdict_key = None
    scene.last_speaker = None
    with scene.stage_box:
        with ui.element("div").classes("live-stage"):
            with ui.element("section").classes("act"):
                with ui.element("div").classes("act-title"):
                    ui.label("Conversation").classes("t")
                    scene.convo_meta = ui.label("").classes("m")
                scene.convo = ui.element("div").classes("convo")
            with ui.element("section").classes("act"):
                with ui.element("div").classes("act-title"):
                    ui.label("Workflow").classes("t")
                    scene.flow_meta = ui.label("").classes("m")
                with ui.element("div").classes("flow"):
                    for index, (_key, title, text) in enumerate(explain.STAGES, start=1):
                        node = ui.element("div").classes("node off")
                        with node:
                            with ui.element("div").classes("knot"):
                                ui.element("i")
                            with ui.element("div").classes("stage-name"):
                                ui.label(f"0{index}").classes("n")
                                ui.label(title)
                            ui.label(text).classes("stage-text")
                            cards = ui.element("div").classes("cards")
                        scene.nodes.append(node)
                        scene.node_cards.append(cards)
            with ui.element("section").classes("act"):
                with ui.element("div").classes("act-title"):
                    ui.label("Outcome").classes("t")
                scene.verdict = ui.element("div").classes("verdict-card")
                scene.record = ui.element("div").classes("record-live")
    _sync(scene, card, public=public)


def _sync(scene: Scene, card: CallCard, *, public: bool) -> None:
    """Append what is new, update what changed. Never rebuild."""
    assert scene.convo is not None and scene.verdict is not None and scene.record is not None
    is_live = card.live

    # Turns: append the new ones; the newest one speaks.
    for turn in card.turns[scene.turns :]:
        say = _say(scene.convo, turn.role, turn.text, live._turn_time(card, turn.ts))
        if scene.last_speaker is not None:
            scene.last_speaker.classes(remove="speaking")
        scene.last_speaker = say
    scene.turns = len(card.turns)
    if scene.last_speaker is not None:
        if is_live:
            scene.last_speaker.classes(add="speaking")
        else:
            scene.last_speaker.classes(remove="speaking")
    scene.convo_meta.set_text(f"{len(card.turns)} turns · {live._duration(card)}")

    # Tools: append new cards under their stage, update the ones that finished.
    for index, step in enumerate(card.tools):
        if index < len(scene.tools):
            _update_tool(scene.tools[index], step)
        else:
            container = scene.node_cards[_stage_for(step) - 1]
            scene.tools.append(_tool_card(container, step))
    scene.flow_meta.set_text(f"{len(card.tools)} tool calls")

    # Stage nodes.
    reached = explain.stage_of(card)
    key = (reached, is_live)
    if key != (scene.stage, getattr(scene, "stage_live", None)):
        scene.stage = reached
        scene.stage_live = is_live
        for index, node in enumerate(scene.nodes, start=1):
            node.classes(remove="now done off", add=_node_state(index, reached, is_live))

    # Verdict: rebuild only when what it says changes.
    status = card.status
    vkey = (
        status,
        card.action_kind,
        card.decline_reason,
        tuple(explain.payload_rows(card)),
        explain.submitted(card),
        is_live,
    )
    if vkey != scene.verdict_key:
        landed = scene.verdict_key is not None and not is_live
        scene.verdict_key = vkey
        scene.verdict.clear()
        scene.verdict.classes(remove="landed", add="landed" if landed else "")
        with scene.verdict:
            ui.label("Outcome").classes("label")
            with ui.element("div").classes("title"):
                ui.element("span").classes(f"dot {live._status_dot(status)}")
                ui.label(explain.outcome_title(card))
            ui.label(explain.outcome_text(card)).classes("text")
            if card.decline_reason:
                ui.label(card.decline_reason).classes("reason")
            rows = [(k, v) for k, v in explain.payload_rows(card) if k != "reason"]
            if rows:
                ui.element("div").style("height: 12px")
                for k, v in rows:
                    with ui.element("div").classes("kv"):
                        ui.label(k)
                        ui.label(str(v)).classes("mono")

    # Record: cheap to rebuild, small.
    phone = card.from_number
    if public and phone:
        phone = live.insights.mask_phone(phone)
    rows = (
        ("Patient", card.patient_name),
        ("Phone", phone),
        ("Doctor", card.provider_name),
        ("Slot", card.slot),
        ("Submitted", card.submit_status),
        ("Duration", live._duration(card)),
        ("Call id", card.call_id),
    )
    rkey = tuple(rows)
    if rkey != getattr(scene, "record_key", None):
        scene.record_key = rkey
        scene.record.clear()
        with scene.record:
            for label, value in rows:
                with ui.element("div").classes("kv"):
                    ui.label(label)
                    ui.label(value or "—").classes("mono")


def _waiting(scene: Scene) -> None:
    assert scene.stage_box is not None
    scene.stage_box.clear()
    scene.call_id = None
    with scene.stage_box, ui.element("div").classes("waiting"):
        ui.label("Waiting for the next call").classes("t")
        ui.label(
            "The platform dials our socket. The conversation, every decision and the "
            "outcome land here as they happen."
        ).classes("d")


def _head(
    state_slot: ui.element, cards: list[CallCard], health: dict[str, Any] | None, scene: Scene
) -> None:
    live_count = sum(1 for c in cards if c.live)
    sig = (live_count, health is not None)
    if sig == scene.head_sig:
        return
    scene.head_sig = sig
    state_slot.clear()
    with state_slot:
        if live_count:
            with ui.element("div").classes("state on"):
                ui.element("span").classes("dot")
                ui.label(f"{live_count} on the line" if live_count > 1 else "On a call")
        else:
            with ui.element("div").classes("state"):
                ui.element("span").classes("dot off")
                ui.label("Idle")
        ui.label("line up" if health else "line down").classes("meta")


def _foot(
    foot: ui.element,
    cards: list[CallCard],
    featured: CallCard | None,
    scene: Scene,
    *,
    public: bool,
) -> None:
    live_calls = [c for c in cards if c.live]
    stats = explain.stats_for(cards)
    sig = (
        tuple(c.call_id for c in live_calls),
        stats.calls,
        stats.booked,
        stats.refused,
        stats.escalated,
    )
    if sig == scene.foot_sig:
        return
    scene.foot_sig = sig
    foot.clear()
    with foot:
        ui.label("On the line").classes("k")
        if not live_calls:
            ui.label("nobody right now").classes("k")
        for c in live_calls[:12]:
            on = featured is not None and c.call_id == featured.call_id
            with ui.link(target=f"/call/{c.call_id}").classes(
                "line-chip on" if on else "line-chip"
            ):
                ui.element("span").classes("dot live")
                ui.label(live._caller(c, public=public))
                ui.label(explain.STAGES[max(explain.stage_of(c) - 1, 0)][1]).classes("k")
        with ui.element("div").classes("stats"):
            for n, label in (
                (str(stats.calls), "calls today"),
                (str(stats.booked), "booked"),
                (str(stats.refused), "no action"),
                (str(stats.escalated), "escalated"),
            ):
                with ui.element("div").classes("stat-mini"):
                    ui.label(n).classes("n")
                    ui.label(label).classes("l")


def _page(*, public: bool) -> None:
    live._apply_chrome()
    ui.add_css(LIVE_CSS)
    ui.query("body").classes("theme-live")
    ui.page_title("Vortex · Live")
    scene = Scene()
    state_slot, stage, foot = _skeleton(scene, public=public)
    scene.stage_box = stage

    def tick() -> None:
        cards, health = live._load_cards()
        featured = live._feature(cards)
        _head(state_slot, cards, health, scene)
        if featured is None:
            if (
                scene.call_id is not None
                or scene.stage_box is not None
                and not scene.stage_box.default_slot.children
            ):
                _waiting(scene)
        elif featured.call_id != scene.call_id:
            scene.call_id = featured.call_id
            _build_stage(scene, featured, public=public)
        else:
            _sync(scene, featured, public=public)
        _foot(foot, cards, featured, scene, public=public)

    tick()
    ui.timer(0.4, tick)


@ui.page("/wall/flow")
def wall_page() -> None:
    _page(public=True)


@ui.page("/calls/live")
def calls_live_page() -> None:
    if not live._ops_ok():
        live._apply_chrome()
        live._login_form()
        return
    _page(public=False)
