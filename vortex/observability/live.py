"""The Vortex console: ``/wall`` (Live, public), ``/`` (Calls, team),
``/call/{id}`` (one call, public), ``/evals`` and ``/bench`` (team).

Every screen follows DESIGN.md. ``design.css`` carries the tokens and the
components; ``board.css`` adds the Quasar overrides and the layouts. The words
on screen come from ``explain.py``. Add a class or a sentence there before you
add an inline style or a string here.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi.responses import HTMLResponse, JSONResponse
from nicegui import app, ui

from vortex.observability import auth, explain, insights
from vortex.observability.calllog import read_recent
from vortex.observability.demo import write_scripted_call
from vortex.observability.view import CallCard, build_calls, flatten_grouped
from vortex.observability.wall_timeline import build_timeline, call_summary, latest_intent
from vortex.settings import REPO_ROOT, get_settings

LINE_URL = os.environ.get("VORTEX_LINE_URL", "http://127.0.0.1:7860").rstrip("/")
BOARD_PORT = int(os.environ.get("VORTEX_BOARD_PORT", "8080"))
CLINIC_NAME = os.environ.get("VORTEX_CLINIC_NAME", "Clínica Arenal")
PRESENCE: dict[str, float] = {}
_HERE = Path(__file__).parent
DESIGN_CSS = (_HERE / "design.css").read_text(encoding="utf-8")
BOARD_CSS = (_HERE / "board.css").read_text(encoding="utf-8")
EVALS_SUMMARY = REPO_ROOT / "evals" / "results" / "summary.json"
#: The react-spring per-call "zoom" page (vortex/observability/wall-app/),
#: built by `npm run build`. /call/{id} above is the NiceGUI page; this is
#: an animated alternative at /call/{id}/zoom, additive and never required.
WALL_APP_DIST = _HERE / "wall-app" / "dist"

MADRID = ZoneInfo("Europe/Madrid")

#: A call with no event for this long is over, whatever the log says.
STALE_AFTER_S = 180

NAV_PUBLIC = (("Live", "/wall"), ("Console", "/"))

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _log_path() -> Path:
    return get_settings().calls_log_path


def _load_events() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    health: dict[str, Any] | None = None
    try:
        health = httpx.get(f"{LINE_URL}/health", timeout=0.35).json()
        grouped = (
            httpx.get(f"{LINE_URL}/calls", params={"limit": 800}, timeout=0.5)
            .json()
            .get("calls", {})
        )
        if isinstance(grouped, dict):
            return flatten_grouped(grouped), health
    except Exception:
        pass
    return read_recent(_log_path(), limit=800), health


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _is_live(card: CallCard) -> bool:
    if not card.live:
        return False
    last = _parse_ts(card.last_ts)
    if last is None:
        return True
    return (datetime.now(UTC) - last).total_seconds() < STALE_AFTER_S


def _load_cards() -> tuple[list[CallCard], dict[str, Any] | None]:
    events, health = _load_events()
    cards = build_calls(events)
    for card in cards:
        if card.live and not _is_live(card):
            card.ended = True
            card.reason = card.reason or "stale"
    return cards, health


def _feature(cards: list[CallCard]) -> CallCard | None:
    """The call the wall shows: the oldest live one, so the panel does not
    jump between sockets while a burst runs; else the newest ended call."""
    live = [c for c in cards if c.live]
    if live:
        return live[-1]
    return cards[0] if cards else None


def _prune_presence() -> list[str]:
    now = time.time()
    dead = [name for name, seen in PRESENCE.items() if now - seen > 20]
    for name in dead:
        PRESENCE.pop(name, None)
    return sorted(PRESENCE)


def _beat(name: str) -> None:
    clean = name.strip()[:24]
    if clean:
        PRESENCE[clean] = time.time()


async def _play_line() -> None:
    url = os.environ.get("VORTEX_WS_URL", "ws://127.0.0.1:7860/ws")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(REPO_ROOT / "scripts" / "fake_caller.py"),
        "--url",
        url,
        "--calls",
        "1",
        "--seconds",
        "0.6",
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    await proc.communicate()
    if proc.returncode != 0:
        ui.notify("The line did not answer. Start `make run` on 7860.", type="negative")
    else:
        ui.notify("Call sent to /ws", type="positive")


async def _replay(scenario: str) -> None:
    await write_scripted_call(_log_path(), scenario=scenario, delay_s=0.28)


def _client_ip() -> str:
    client = ui.context.client
    ip = getattr(client, "ip", None)
    return str(ip) if ip else "unknown"


def _ops_ok() -> bool:
    if not auth.must_authenticate():
        return True
    return bool(app.storage.user.get("ops"))


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _clock(value: str | None) -> str:
    stamp = _parse_ts(value)
    if stamp is None:
        return "—"
    return stamp.astimezone(MADRID).strftime("%H:%M:%S")


def _duration(card: CallCard) -> str:
    if card.duration_ms:
        secs = card.duration_ms / 1000
    else:
        start = _parse_ts(card.started_at)
        end = datetime.now(UTC) if card.live else _parse_ts(card.last_ts)
        if start is None or end is None:
            return "—"
        secs = max((end - start).total_seconds(), 0)
    return f"{int(secs // 60)}:{int(secs % 60):02d}"


def _ms(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f} ms" if value < 1000 else f"{value / 1000:.1f} s"


def _turn_time(card: CallCard, ts: str | None) -> str:
    """'21:38:13 +12.3s': wall clock and seconds since the call connected."""
    stamp = _parse_ts(ts)
    if stamp is None:
        return ""
    label = stamp.astimezone().strftime("%H:%M:%S")
    start = _parse_ts(card.started_at)
    if start is not None:
        delta = (stamp - start).total_seconds()
        if 0 <= delta < 3600:
            label += f" +{delta:.1f}s"
    return label


def _signature(cards: list[CallCard], health: dict[str, Any] | None, *extra: Any) -> tuple:
    """What a redraw depends on. A page whose log did not change redraws
    nothing; a page with a live call ticks once a second so durations move."""
    tick = int(time.time()) if any(c.live for c in cards) else None
    return (repr(cards), repr(health), tick, *extra)


def _caller(card: CallCard, *, public: bool = False) -> str:
    if card.patient_name:
        return card.patient_name
    if card.from_number:
        return insights.mask_phone(card.from_number) if public else card.from_number
    return "Unidentified patient"


def _status_dot(status: str) -> str:
    """Map a call status to a traffic-light dot. See DESIGN.md, Status."""
    if status == "live":
        return "live"
    if status in {"booked", "registered", "rescheduled", "cancelled"}:
        return "ok"
    if status in {"refused", "escalated"}:
        return "warn"
    return "off"


def _tool_dot(status: str) -> str:
    if status == "running":
        return "live"
    if status == "ok":
        return "ok"
    return "bad"


def _pretty(value: Any, limit: int = 600) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------


def _apply_chrome() -> None:
    ui.dark_mode(False)
    # Quasar paints its palette with !important inside a cascade layer, so the
    # only clean way to make its buttons black is to make its palette black.
    ui.colors(
        primary="#000000",
        secondary="#525252",
        accent="#000000",
        dark="#171717",
        positive="#27c93f",
        negative="#ff5f56",
        warning="#ffbd2e",
        info="#737373",
    )
    ui.add_css(DESIGN_CSS)
    ui.add_css(BOARD_CSS)
    ui.query("body").classes("shell")


def _dot(kind: str) -> None:
    ui.element("span").classes(f"dot {kind}")


def _pill(text: str, dot: str | None = None, extra: str = "") -> None:
    with ui.element("div").classes(f"pill {extra}".strip()):
        if dot:
            _dot(dot)
        ui.label(text)


def _line_pill(health: dict[str, Any] | None, *, short: bool = False) -> None:
    if health:
        detail = "" if short else f" · {health.get('voice')} / {health.get('clinic')}"
        _pill(f"Line up{detail}", "ok", "mute")
    else:
        _pill("Line down" if short else "Line down · reading the log", "bad", "mute")


def _nav(active: str, *, team: bool) -> ui.element:
    """The console nav. Returns the right-hand slot for page controls."""
    with ui.element("nav").classes("primary-nav"):
        ui.link("Vortex", "/" if team else "/wall").classes("brand")
        ui.label(CLINIC_NAME).classes("nav-mute")
        with ui.element("div").classes("tabs"):
            for label, path in NAV_PUBLIC:
                ui.link(label, path).classes("tab on" if path == active else "tab")
        ui.element("div").classes("grow")
        slot = ui.element("div").classes("row")
    return slot


def _footer() -> None:
    with ui.element("footer").classes("footer-section"):
        ui.label("Vortex · HackSpain 2026 · Prosper AI track")
        ui.label("Every id comes from the clinic API. Every refusal carries a typed reason.")
        ui.link("Repository", "https://github.com/jferreiros/vortex", new_tab=True)


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def _stat(n: str, label: str, dot: str | None = None) -> None:
    with ui.element("div").classes("stat"):
        with ui.element("div").classes("n row"):
            if dot:
                _dot(dot)
            ui.label(n)
        ui.label(label).classes("l")


def _kpis(cards: list[CallCard]) -> None:
    s = explain.stats_for(cards)
    rate = "—" if s.submit_rate is None else f"{s.submit_rate * 100:.0f}%"
    with ui.element("div").classes("stat-grid"):
        _stat(str(s.calls), "calls on the line")
        _stat(str(s.live), "on a call now", "live" if s.live else None)
        _stat(str(s.booked), "booked", "ok")
        _stat(str(s.refused), "no action, with a reason", "warn")
        _stat(str(s.escalated), "escalated to a human", "warn")
        _stat(rate, "ended with a submission")
        _stat(
            "—" if s.median_duration_s is None else f"{s.median_duration_s:.0f} s",
            "median handle time",
        )
        _stat(_ms(s.median_tool_ms), "median tool latency")


def _stages(card: CallCard | None) -> None:
    reached = explain.stage_of(card)
    live = bool(card and card.live)
    with ui.element("div").classes("stages"):
        for index, (_key, title, text) in enumerate(explain.STAGES, start=1):
            if live and index == max(reached, 1):
                state = "now"
            elif index <= reached:
                state = "done"
            else:
                state = ""
            with ui.element("div").classes(f"stage {state}".strip()):
                ui.label(f"0{index}").classes("n")
                with ui.element("div").classes("t"):
                    _dot({"done": "ok", "now": "live"}.get(state, "off"))
                    ui.label(title)
                ui.label(text).classes("d")


def _transcript(card: CallCard | None) -> None:
    with ui.element("div").classes("section-title"):
        ui.label("Transcript").classes("t")
        if card:
            ui.label(f"{len(card.turns)} turns · {_duration(card)}").classes("m")
    if not card or not card.turns:
        with ui.element("div").classes("empty-state"):
            ui.label("Nothing said yet").classes("t")
            ui.label("The transcript streams here as the call goes on.").classes("d")
        return
    for turn in card.turns:
        with ui.element("div").classes(f"turn {turn.role}"):
            ui.label("Patient" if turn.role == "user" else "Vortex").classes("who")
            ui.label(turn.text).classes("bubble")
            stamp = _turn_time(card, turn.ts)
            if stamp:
                ui.label(stamp).classes("caption-sm mono")
    if card.live:
        with ui.element("div").classes("turn assistant"):
            ui.label("Vortex").classes("who")
            with ui.element("div").classes("typing"):
                for _ in range(3):
                    ui.element("i")


def _decisions(card: CallCard | None, *, verbose: bool = False) -> None:
    with ui.element("div").classes("section-title"):
        ui.label("Decisions").classes("t")
        if card and card.tools:
            ui.label(f"{len(card.tools)} tool calls").classes("m")
    with ui.element("div").classes("terminal-card"):
        with ui.element("div").classes("terminal-traffic-lights"):
            for _ in range(3):
                ui.element("i")
        if not card or not card.tools:
            ui.label("No tool called yet. Every decision on the call shows here.").classes(
                "comment"
            )
            return
        with ui.element("div").classes("timeline"):
            for step in card.tools:
                with ui.element("div").classes("tl-row"):
                    _dot(_tool_dot(step.status))
                    with ui.element("div"):
                        with ui.element("div").classes("row").style("gap:0"):
                            ui.label(explain.tool_description(step.name)).classes("what")
                            ui.label(step.name).classes("tool")
                        endpoint = explain.tool_endpoint(step.name)
                        if verbose and endpoint:
                            ui.label(endpoint).classes("caption-sm mono")
                        said = explain.step_text(step)
                        bad = step.status == "fail" or said.startswith("Rejected")
                        ui.label(said).classes("said bad" if bad else "said")
                        if verbose:
                            with ui.expansion("Request and response").classes("raw"):
                                ui.label("args").classes("caption-sm")
                                ui.html(f"<pre>{_escape(_pretty(step.args))}</pre>")
                                ui.label("result").classes("caption-sm")
                                ui.html(f"<pre>{_escape(_pretty(step.error or step.result))}</pre>")
                    ui.label(_ms(step.ms) if step.ms is not None else step.status).classes("ms")


def _event_dot(event: dict[str, Any]) -> str:
    kind = str(event.get("kind") or "")
    if kind == "call.crashed":
        return "bad"
    if kind == "submit.result":
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        return "ok" if result.get("status") in {"submitted", "accepted"} else "warn"
    return "off"


def _lifecycle(card: CallCard) -> None:
    """The socket, the submission and the summary, with the raw log line under
    each. Together with Decisions and Transcript this replays the whole call."""
    events = [e for e in card.events if explain.is_lifecycle(e)]
    with ui.element("div").classes("section-title"):
        ui.label("Timeline").classes("t")
        ui.label(f"{len(events)} events · {len(card.events)} lines in the log").classes("m")
    with ui.element("div").classes("terminal-card"):
        with ui.element("div").classes("terminal-traffic-lights"):
            for _ in range(3):
                ui.element("i")
        if not events:
            ui.label("No lifecycle event yet. The socket handshake shows here.").classes("comment")
            return
        with ui.element("div").classes("timeline"):
            for event in events:
                with ui.element("div").classes("tl-row"):
                    _dot(_event_dot(event))
                    with ui.element("div"):
                        with ui.element("div").classes("row").style("gap:0"):
                            ui.label(explain.event_text(event)).classes("what")
                            ui.label(str(event.get("kind") or "?")).classes("tool")
                        detail = explain.event_detail(event)
                        if detail:
                            ui.label(detail).classes("said")
                        with ui.expansion("Raw event").classes("raw"):
                            ui.html(f"<pre>{_escape(_pretty(event, limit=4000))}</pre>")
                    ui.label(_turn_time(card, event.get("ts")) or "—").classes("ms")


def _outcome(card: CallCard | None) -> None:
    status = card.status if card else "ended"
    with ui.element("div").classes("outcome"):
        ui.label("Outcome").classes("label")
        with ui.element("div").classes("title"):
            _dot(_status_dot(status) if card else "off")
            ui.label(explain.outcome_title(card))
        ui.label(explain.outcome_text(card)).classes("text")
        if card and card.decline_reason:
            ui.label(card.decline_reason).classes("reason")
        rows = [(k, v) for k, v in explain.payload_rows(card) if k != "reason"] if card else []
        if rows:
            ui.element("div").style("height: 16px")
            for key, value in rows:
                with ui.element("div").classes("kv"):
                    ui.label(key)
                    ui.label(str(value)).classes("mono")


def _record(card: CallCard | None, *, public: bool = False) -> None:
    with ui.element("div").classes("section-title"):
        ui.label("Record").classes("t")
    ended = "on the call" if card and card.live else (card.reason if card else None)
    phone = card.from_number if card else None
    if public and phone:
        phone = insights.mask_phone(phone)
    rows = [
        ("Patient", card.patient_name if card else None),
        ("Phone", phone),
        ("Doctor", card.provider_name if card else None),
        ("Slot", card.slot if card else None),
        ("Submitted", card.submit_status if card else None),
        ("Route", card.submit_route if card else None),
        ("Ended", ended),
        ("Duration", _duration(card) if card else None),
        ("Started", _clock(card.started_at) if card else None),
        ("Call id", card.call_id if card else None),
    ]
    for label, value in rows:
        with ui.element("div").classes("kv"):
            ui.label(label)
            ui.label(value or "—").classes("mono")


def _call_panel(card: CallCard | None, *, verbose: bool, public: bool = False) -> None:
    _stages(card)
    ui.element("div").style("height: 24px")
    with ui.element("div").classes("grid3"):
        with ui.element("section").classes("col"):
            _transcript(card)
        with ui.element("section").classes("col"):
            _decisions(card, verbose=verbose)
            if verbose and card is not None:
                ui.element("div").style("height: 24px")
                _lifecycle(card)
        with ui.element("section").classes("col"):
            _outcome(card)
            ui.element("div").style("height: 24px")
            _record(card, public=public)


def _live_strip(cards: list[CallCard], featured: CallCard | None, *, public: bool = False) -> None:
    live = [c for c in cards if c.live]
    if len(live) < 2:
        return
    with ui.element("div").classes("section-title"):
        ui.label("On the line now").classes("t")
        ui.label(f"{len(live)} concurrent calls, one pipeline each").classes("m")
    with ui.element("div").classes("live-grid"):
        for card in live[:20]:
            on = featured is not None and card.call_id == featured.call_id
            with ui.link(target=f"/call/{card.call_id}").classes(
                "live-card on" if on else "live-card"
            ):
                with ui.element("div").classes("row"):
                    _dot("live")
                    ui.label(_caller(card, public=public)).classes("body-sm-strong")
                    ui.element("div").classes("grow")
                    ui.label(_duration(card)).classes("caption-sm tabular")
                stage = explain.stage_of(card)
                ui.label(explain.STAGES[max(stage - 1, 0)][1]).classes("caption-sm")
                last = card.turns[-1].text if card.turns else "…"
                ui.label(last).classes("last")


def _calls_table(
    cards: list[CallCard],
    *,
    public: bool = False,
    selected: str | None = None,
    on_pick=None,
    link: bool = False,
    limit: int = 40,
) -> None:
    if not cards:
        with ui.element("div").classes("empty-state"):
            ui.label("No calls yet").classes("t")
            ui.label("Press Play to dial the line, or wait for the platform.").classes("d")
        return
    with ui.element("table").classes("table"):
        with ui.element("thead"), ui.element("tr"):
            for head in (
                "Time",
                "Patient",
                "Outcome",
                "Why not booked",
                "Tools",
                "Duration",
                "Call id",
            ):
                with ui.element("th"):
                    ui.label(head)
        with ui.element("tbody"):
            for card in cards[:limit]:
                row = ui.element("tr").classes("pick on" if card.call_id == selected else "pick")
                if on_pick is not None:
                    row.on("click", lambda c=card: on_pick(c.call_id))
                elif link:
                    row.on("click", lambda c=card: ui.navigate.to(f"/call/{c.call_id}"))
                with row:
                    with ui.element("td").classes("mute num"):
                        ui.label(_clock(card.started_at))
                    with ui.element("td"):
                        ui.label(_caller(card, public=public))
                    with ui.element("td"), ui.element("div").classes("row"):
                        _dot(_status_dot(card.status))
                        ui.label(explain.STATUS_LABEL.get(card.status, card.status))
                    with ui.element("td").classes("mute"):
                        ui.label(card.decline_reason or "—")
                    with ui.element("td").classes("num"):
                        ui.label(str(len(card.tools)))
                    with ui.element("td").classes("num"):
                        ui.label(_duration(card))
                    with ui.element("td").classes("id"):
                        ui.label(card.call_id)


def _facts(health: dict[str, Any] | None) -> None:
    with ui.element("div").classes("facts"):
        if health:
            with ui.element("span"):
                ui.html(f"STT <b>Soniox {_escape(str(health.get('stt_model', '')))}</b>")
            with ui.element("span"):
                ui.html(
                    f"LLM <b>{_escape(str(health.get('llm_provider', '')))} · "
                    f"{_escape(str(health.get('llm_model', '')))}</b>"
                )
            with ui.element("span"):
                ui.html(f"TTS <b>{_escape(str(health.get('tts_provider', '')))}</b>")
        with ui.element("span"):
            ui.html("Hold time <b>zero, answered on connect</b>")
        with ui.element("span"):
            ui.html("Patient data <b>read from the clinic's EHR, never guessed</b>")
        with ui.element("span"):
            ui.html("Emergencies <b>escalated to a human, never booked</b>")
        with ui.element("span"):
            ui.html("Every refusal <b>carries the rule that applied</b>")
        with ui.element("span"):
            ui.html("Time <b>Europe/Madrid, to the minute</b>")


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------


@ui.page("/wall")
def wall_page() -> None:
    _apply_chrome()
    ui.page_title("Vortex · Live")
    stage = ui.element("div").classes("shell")
    rendered: dict[str, Any] = {"sig": None}

    def redraw() -> None:
        cards, health = _load_cards()
        sig = _signature(cards, health)
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        featured = _feature(cards)
        live_count = sum(1 for c in cards if c.live)
        stage.clear()
        with stage:
            slot = _nav("/wall", team=False)
            with slot:
                _line_pill(health)
                zoom_id = featured.call_id if featured else "demo"
                ui.link("Demo", f"/call/{zoom_id}/zoom", new_tab=True).classes("pill mute")
            with ui.element("main").classes("page"):
                with ui.element("div").classes("page-head"):
                    with ui.element("div"):
                        ui.label("Live").classes("title")
                        ui.label(
                            f"Inbound scheduling line for {CLINIC_NAME}. The platform dials our "
                            "socket and plays a patient. Vortex identifies the caller, applies the "
                            "clinic's rules and submits one action."
                        ).classes("sub")
                    if live_count:
                        with ui.element("div").classes("live-badge"):
                            _dot("live")
                            ui.label(f"{live_count} on the line" if live_count > 1 else "On a call")
                    else:
                        _pill("Idle · waiting for the next call", "off", "mute")
                _kpis(cards)
                ui.element("div").style("height: 32px")
                _live_strip(cards, featured, public=True)
                _call_panel(featured, verbose=False, public=True)
                ui.element("div").style("height: 48px")
                with ui.element("div").classes("section-title"):
                    ui.label("Recent calls").classes("t")
                    ui.label("Click a row for the full story").classes("m")
                _calls_table(cards, link=True, limit=12, public=True)
                ui.element("div").style("height: 32px")
                _facts(health)
            _footer()

    redraw()
    ui.timer(0.5, redraw)


@ui.page("/call/{call_id}")
def call_page(call_id: str) -> None:
    """One call, by id. Public. The same panel as Live, plus every request."""
    _apply_chrome()
    ui.page_title(f"Vortex · {call_id}")
    stage = ui.element("div").classes("shell")
    rendered: dict[str, Any] = {"sig": None}

    def redraw() -> None:
        cards, health = _load_cards()
        card = next((c for c in cards if c.call_id == call_id), None)
        sig = _signature(cards, health, call_id)
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        stage.clear()
        with stage:
            slot = _nav("", team=False)
            with slot:
                _line_pill(health)
                ui.link("Demo", f"/call/{call_id}/zoom", new_tab=True).classes("pill mute")
            with ui.element("main").classes("page"):
                with ui.element("div").classes("page-head"):
                    with ui.element("div"):
                        ui.link("← Live", "/wall").classes("caption-sm")
                        ui.label(
                            _caller(card, public=not _ops_ok()) if card else "Unknown call"
                        ).classes("title")
                        ui.label(call_id).classes("sub mono")
                    if card:
                        _pill(
                            explain.STATUS_LABEL.get(card.status, card.status),
                            _status_dot(card.status),
                            "dark" if card.live else "",
                        )
                if card is None:
                    with ui.element("div").classes("empty-state"):
                        ui.label("No call with this id yet").classes("t")
                        ui.label("It appears here as soon as the socket opens.").classes("d")
                else:
                    team = _ops_ok()
                    _call_panel(card, verbose=team, public=not team)
            _footer()

    redraw()
    ui.timer(0.6, redraw)


@app.get("/api/wall/timeline/{call_id}")
def wall_timeline_api(call_id: str) -> JSONResponse:
    """The chat+tool timeline the react-spring zoom page polls."""
    events, health = _load_events()
    items = build_timeline(events, call_id)
    intent = latest_intent(events, call_id)
    call = call_summary(events, call_id)
    call["submit_window_secs"] = get_settings().submit_window_secs
    return JSONResponse(
        {
            "call_id": call_id,
            "items": items,
            "intent": intent,
            "call": call,
            "line_up": health is not None,
        }
    )


if WALL_APP_DIST.exists():
    app.add_static_files("/wall-assets", str(WALL_APP_DIST))
    _WALL_INDEX_HTML = (WALL_APP_DIST / "index.html").read_text(encoding="utf-8")

    @app.get("/call/{call_id}/zoom")
    def call_zoom_page(call_id: str) -> HTMLResponse:
        """The react-spring zoom page: voice orb, live tool demo, extracted
        info with the rule behind each, final action.

        Built by ``npm run build`` in ``vortex/observability/wall-app/``. It
        reads its data from ``/api/wall/timeline/{call_id}`` above, client-side.
        Additive: ``/call/{call_id}`` (no ``/zoom``) stays the NiceGUI page.
        """
        del call_id  # the SPA reads the id itself from window.location
        return HTMLResponse(_WALL_INDEX_HTML)


# ---------------------------------------------------------------------------
# Team pages
# ---------------------------------------------------------------------------


def _login_form() -> None:
    with ui.element("main").classes("page"):
        with ui.element("div").classes("card login"):
            ui.label("Team sign-in").classes("heading-lg")
            ui.label("The public wall is at /wall. This side is for the team.").classes("body-sm")
            ui.element("div").style("height: 16px")
            password = ui.input(placeholder="password", password=True).props("dense outlined")
            password.classes("w-full")
            status = ui.label("").classes("error")

            def submit() -> None:
                ip = _client_ip()
                if not auth.login_allowed(ip):
                    status.set_text("Too many attempts. Wait ten minutes.")
                    return
                auth.record_login_attempt(ip)
                if auth.check_password(password.value or ""):
                    app.storage.user["ops"] = True
                    ui.navigate.to("/")
                    return
                status.set_text("Wrong password.")

            ui.button("Sign in", on_click=submit).props("unelevated no-caps").classes(
                "button-primary"
            )
            password.on("keydown.enter", submit)


def _logout() -> None:
    app.storage.user.pop("ops", None)
    ui.navigate.to("/")


FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "All"),
    ("live", "Live"),
    ("booked", "Booked"),
    ("refused", "No action"),
    ("escalated", "Escalated"),
    ("other", "Other"),
)


def _passes(card: CallCard, key: str) -> bool:
    if key == "all":
        return True
    if key == "other":
        return card.status in {"registered", "rescheduled", "cancelled", "ended"}
    return card.status == key


@ui.page("/calls")
def ops_page() -> None:
    _apply_chrome()
    ui.page_title("Vortex · Calls")
    if not _ops_ok():
        _login_form()
        return
    state: dict[str, Any] = {"id": None, "filter": "all"}
    holder: dict[str, Any] = {}

    def controls() -> None:
        holder["line_pill"] = ui.element("div")
        name = ui.input(placeholder="your name", value="joaquin").props("dense outlined")
        name.classes("mono").style("width:10rem")
        holder["name"] = name
        ui.button("Play a test call", on_click=_play_line).props("unelevated no-caps").classes(
            "button-primary"
        )
        ui.button("Replay booking", on_click=lambda: _replay("book")).props(
            "outline no-caps"
        ).classes("button-secondary")
        ui.button("Replay refusal", on_click=lambda: _replay("refuse")).props(
            "outline no-caps"
        ).classes("button-secondary")

    from vortex.observability.shell import console_page

    _cards0, health0 = _load_cards()
    with console_page(
        "/calls",
        "Calls",
        "Every call on the line, newest first. Pick one to see what the agent heard, "
        "what it checked and what it sent.",
        health=health0,
        clinic=CLINIC_NAME,
        who="team",
        controls=controls,
    ) as body:
        with body:
            people = ui.label().classes("caption-sm")
            chips = ui.element("div").classes("chip-row")
            with ui.element("div").classes("ops-grid"):
                left = ui.element("div")
                right = ui.element("div").classes("card card-compact")
    line_pill = holder["line_pill"]
    name = holder["name"]

    rendered: dict[str, Any] = {"sig": None}

    def pick(call_id: str) -> None:
        state["id"] = call_id
        redraw()

    def set_filter(key: str) -> None:
        state["filter"] = key
        redraw()

    def redraw() -> None:
        _beat(name.value or "joaquin")
        cards, health = _load_cards()
        shown = [c for c in cards if _passes(c, state["filter"])]
        if state["id"] is None and shown:
            state["id"] = shown[0].call_id
        card = next((c for c in shown if c.call_id == state["id"]), shown[0] if shown else None)
        names = _prune_presence()
        sig = _signature(cards, health, state["id"], state["filter"], tuple(names))
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        line_pill.clear()
        with line_pill:
            _line_pill(health)
        people.set_text("In the room · " + (" · ".join(names) if names else "nobody"))
        chips.clear()
        with chips:
            for key, label in FILTERS:
                count = sum(1 for c in cards if _passes(c, key))
                chip = ui.element("button").classes("chip on" if key == state["filter"] else "chip")
                chip.on("click", lambda k=key: set_filter(k))
                with chip:
                    ui.label(f"{label} {count}")
        left.clear()
        with left:
            _calls_table(shown, selected=state["id"], on_pick=pick, limit=60)
        right.clear()
        with right:
            if card is None:
                with ui.element("div").classes("empty-state"):
                    ui.label("Pick a call").classes("t")
                    ui.label("Its transcript, decisions and outcome show here.").classes("d")
            else:
                with ui.element("div").classes("page-head").style("margin-bottom:16px"):
                    with ui.element("div"):
                        ui.label(_caller(card)).classes("heading-md")
                        ui.link(card.call_id, f"/call/{card.call_id}").classes("caption-sm mono")
                    _pill(
                        explain.STATUS_LABEL.get(card.status, card.status),
                        _status_dot(card.status),
                        "dark" if card.live else "",
                    )
                _stages(card)
                ui.element("div").style("height: 16px")
                _outcome(card)
                ui.element("div").style("height: 16px")
                _decisions(card, verbose=True)
                ui.element("div").style("height: 16px")
                _lifecycle(card)
                ui.element("div").style("height: 16px")
                _transcript(card)

    redraw()
    ui.timer(0.6, redraw)


def _read_summary() -> dict[str, Any] | None:
    try:
        return json.loads(EVALS_SUMMARY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _team_page(path: str, title: str, sub: str, body) -> None:
    from vortex.observability.shell import console_page

    _apply_chrome()
    ui.page_title(f"Vortex · {title}")
    if not _ops_ok():
        _login_form()
        return
    _cards, health = _load_cards()
    with console_page(
        "/settings/engineering", title, sub, health=health, clinic=CLINIC_NAME, who="team"
    ) as content:
        with content:
            body()
    _footer()


_VERDICT_DOT = {"PASS": "ok", "FAIL": "bad", "UNVERIFIED": "warn"}


def _evals_body() -> None:
    summary = _read_summary()
    if not summary:
        with ui.element("div").classes("empty-state"):
            ui.label("No evals run yet").classes("t")
            ui.label("Run `make evals`. The scoreboard from summary.json shows here.").classes("d")
        return
    layers = {k: v for k, v in summary.items() if isinstance(v, dict)}
    with ui.element("div").classes("stat-grid"):
        for layer, data in layers.items():
            totals = data.get("totals", {})
            verdict = str(data.get("verdict", "?"))
            passed = totals.get("pass", 0)
            total = sum(v for v in totals.values() if isinstance(v, int))
            _stat(
                f"{passed}/{total}",
                f"{layer} · {verdict.lower()}",
                _VERDICT_DOT.get(verdict, "off"),
            )
    ui.element("div").style("height: 24px")
    with ui.element("table").classes("table"):
        with ui.element("thead"), ui.element("tr"):
            for head in ("Layer", "Verdict", "Broke", "Fixed", "Ran", "Commit"):
                with ui.element("th"):
                    ui.label(head)
        with ui.element("tbody"):
            for layer, data in layers.items():
                verdict = str(data.get("verdict", "?"))
                with ui.element("tr"):
                    with ui.element("td"):
                        ui.label(layer)
                    with ui.element("td"), ui.element("div").classes("row"):
                        _dot(_VERDICT_DOT.get(verdict, "warn"))
                        ui.label(verdict)
                    with ui.element("td").classes("num"):
                        ui.label(str(len(data.get("broke", []))))
                    with ui.element("td").classes("num"):
                        ui.label(str(len(data.get("fixed", []))))
                    with ui.element("td").classes("mute"):
                        ui.label(_clock(data.get("started_at")))
                    with ui.element("td").classes("id"):
                        ui.label(str((data.get("git") or {}).get("sha", "?"))[:10])


@ui.page("/evals")
def evals_page() -> None:
    _team_page(
        "/evals",
        "Evals",
        "Four layers: tool logic, scripted conversations, voice providers and the organisers' "
        "public cases. Green only counts when it is not a stub.",
        _evals_body,
    )


def _bench_body() -> None:
    summary = _read_summary()
    voice = summary.get("voice") if isinstance(summary, dict) else None
    if not isinstance(voice, dict):
        with ui.element("div").classes("empty-state"):
            ui.label("No provider benchmark yet").classes("t")
            ui.label(
                "Run `make evals-voice REAL=1`. Latency, WER and cost per stack show here."
            ).classes("d")
        return
    totals = voice.get("totals", {})
    with ui.element("div").classes("stat-grid"):
        _stat(str(totals.get("pass", 0)), "stacks within budget", "ok")
        _stat(str(totals.get("fail", 0)), "stacks over budget", "bad")
    ui.element("div").style("height: 16px")
    ui.label("Open evals/results/report.html for the full matrix.").classes("body-sm")


@ui.page("/bench")
def bench_page() -> None:
    _team_page(
        "/bench",
        "Bench",
        "STT, LLM and TTS latency, word error rate and cost per call, per provider stack.",
        _bench_body,
    )


def main() -> None:
    if auth.is_production() and not auth.ops_password():
        raise SystemExit("VORTEX_OPS_PASSWORD is required in production")
    ui.run(
        host="0.0.0.0",
        port=BOARD_PORT,
        title="Vortex",
        dark=False,
        reload=False,
        show=False,
        favicon="◈",
        storage_secret=auth.storage_secret(),
    )


# The clinic console (Overview, Agents, Patients, Insights, Settings) registers
# its pages on import. It imports this module, so it must come last.
from vortex.observability import console  # noqa: E402, F401

if __name__ in {"__main__", "__mp_main__"}:
    main()
