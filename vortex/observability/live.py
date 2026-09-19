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
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from nicegui import app, ui

from vortex.clinic.client import FakeClinicClient
from vortex.line import personalities, voice_config
from vortex.observability import auth, callfeed, explain, insights, pricing
from vortex.observability import calendar as cal
from vortex.observability.business_insights import business_insights, is_real_call
from vortex.observability.demo import replay_cancellation_demo, write_scripted_call
from vortex.observability.home_overview import WINDOW_DAYS as HOME_WINDOW_DAYS
from vortex.observability.home_overview import home_overview
from vortex.observability.home_pack import occupancy
from vortex.observability.icons import icon
from vortex.observability.view import CallCard, build_calls
from vortex.observability.wall_timeline import build_timeline, call_summary, latest_intent
from vortex.settings import REPO_ROOT, get_settings

log = logging.getLogger("vortex.observability")

BOARD_PORT = int(os.environ.get("VORTEX_BOARD_PORT", "8080"))
CLINIC_NAME = os.environ.get("VORTEX_CLINIC_NAME", "Clínica Arenal")
PRESENCE: dict[str, float] = {}
_HERE = Path(__file__).parent
DESIGN_CSS = (_HERE / "design.css").read_text(encoding="utf-8")
BOARD_CSS = (_HERE / "board.css").read_text(encoding="utf-8")
EVALS_SUMMARY = REPO_ROOT / "evals" / "results" / "summary.json"
#: The React app (vortex/wall/) — landing page, Clinic View and the
#: react-spring per-call "zoom" page — built by `npm run build`. /call/{id}
#: above is the NiceGUI page; /call/{id}/zoom below serves this app's
#: index.html and it takes over routing client-side from there. Additive,
#: never required: /call/{id} keeps working with no build present.
WALL_APP_DIST = REPO_ROOT / "vortex" / "wall" / "dist"
#: Source art for the app — not part of the Vite build, served straight off
#: disk. vortex/wall/media/avatar2d.png -> GET /wall/avatar2d.
WALL_MEDIA_DIR = REPO_ROOT / "vortex" / "wall" / "media"
#: The persona portraits, one SVG per personality (the filename is the
#: persona's ``avatar`` field). Served by GET /wall/personalities/{file}.
PERSONALITY_MEDIA_DIR = WALL_MEDIA_DIR / "personalities"

MADRID = ZoneInfo("Europe/Madrid")

#: A call with no event for this long is over, whatever the log says.
STALE_AFTER_S = 180

NAV_PUBLIC = (("Live", "/wall"), ("Calendar", "/calendar"), ("Console", "/"))

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _log_path() -> Path:
    return get_settings().calls_log_path


#: Where the events a screen draws come from lives in ``callfeed`` (a leaf
#: module, so it is importable in tests without pulling in these pages): the
#: line's /calls first, then the last good fetch, then this process's own
#: calls.jsonl — which in production is the line's log volume mounted into
#: the board, not an empty private one.


def _load_events(
    scope: str = "recent",
    *,
    since: datetime | None = None,
    cache_ttl: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict]:
    return callfeed.load_events(scope, _log_path(), since=since, cache_ttl=cache_ttl)


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


def _build_cards() -> tuple[list[CallCard], dict[str, Any] | None]:
    events, health, _source_info = _load_events("recent")
    cards = build_calls(events)
    for card in cards:
        if card.live and not _is_live(card):
            card.ended = True
            card.reason = card.reason or "stale"
    return cards, health


#: (log path, monotonic stamp, cards, health). One load feeds every open tab.
_cards_cache: tuple[str, float, list[CallCard], dict[str, Any] | None] | None = None
_cards_task: asyncio.Task[tuple[list[CallCard], dict[str, Any] | None]] | None = None
#: A redraw ticks about twice a second, so a load older than this is worth
#: repeating and anything newer is what the previous tick already read.
CARDS_TTL_S = 0.5


def _fresh_cards(key: str) -> tuple[list[CallCard], dict[str, Any] | None] | None:
    cached = _cards_cache
    if cached is None or cached[0] != key or time.monotonic() - cached[1] > CARDS_TTL_S:
        return None
    return cached[2], cached[3]


def _load_cards() -> tuple[list[CallCard], dict[str, Any] | None]:
    """The cards, for a page being built. Blocks; call it once per render."""
    global _cards_cache
    key = str(_log_path())
    fresh = _fresh_cards(key)
    if fresh is not None:
        return fresh
    cards, health = _build_cards()
    _cards_cache = (key, time.monotonic(), cards, health)
    return cards, health


async def _load_cards_async() -> tuple[list[CallCard], dict[str, Any] | None]:
    """The same cards for a redraw: one load per TTL for the whole board, in a
    worker thread. ``_build_cards`` makes two HTTP calls and reads the log, and
    a redraw runs on the event loop with every other client's redraw."""
    global _cards_cache, _cards_task
    key = str(_log_path())
    fresh = _fresh_cards(key)
    if fresh is not None:
        return fresh
    task = _cards_task
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.create_task(asyncio.to_thread(_build_cards))
        _cards_task = task
    cards, health = await task
    _cards_cache = (key, time.monotonic(), cards, health)
    return cards, health


def _feature(cards: list[CallCard]) -> CallCard | None:
    return explain.featured_call(cards)


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
    try:
        await write_scripted_call(_log_path(), scenario=scenario, delay_s=0.28)
    except OSError:
        # In production the board mounts the line's log read-only — scripted
        # calls are a local demo tool, not something to mix into live metrics.
        ui.notify("The call log is read-only here — replay demos locally.", type="warning")


async def _replay_cancellations() -> None:
    try:
        await replay_cancellation_demo(_log_path())
    except FileNotFoundError:
        ui.notify(
            "synthetic-data/logs/cancellation_demo.jsonl is missing — "
            "regenerate it with scripts/make_cancellation_pack.py",
            type="warning",
        )
    except OSError:
        # In production the board mounts the line's log read-only — scripted
        # calls are a local demo tool, not something to mix into live metrics.
        ui.notify("The call log is read-only here — replay demos locally.", type="warning")


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
    label = stamp.astimezone(MADRID).strftime("%H:%M:%S")
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


def _stat(n: str, label: str, dot: str | None = None, note: str | None = None) -> None:
    with ui.element("div").classes("stat"):
        with ui.element("div").classes("n row"):
            if dot:
                _dot(dot)
            ui.label(n)
        ui.label(label).classes("l")
        if note:
            ui.label(note).classes("l")


def _priced_note(cost: insights.CostSummary) -> str | None:
    """'2 of 3 calls priced', only when some call had a leg with no price."""
    if not cost.metered or cost.priced == cost.metered:
        return None
    return f"{cost.priced} of {cost.metered} calls priced"


def _kpis(cards: list[CallCard]) -> None:
    s = explain.stats_for(cards)
    rate = "—" if s.submit_rate is None else f"{s.submit_rate * 100:.0f}%"
    cost = insights.cost_per_call(cards)
    with ui.element("div").classes("stat-grid"):
        _stat(str(s.calls), explain.KPI_LABEL["calls"])
        _stat(str(s.live), explain.KPI_LABEL["live"], "live" if s.live else None)
        _stat(str(s.booked), explain.KPI_LABEL["booked"], "ok")
        _stat(str(s.refused), explain.KPI_LABEL["refused"], "warn")
        _stat(str(s.escalated), explain.KPI_LABEL["escalated"], "warn")
        _stat(rate, explain.KPI_LABEL["submitted"])
        _stat(
            "—" if s.median_duration_s is None else f"{s.median_duration_s:.0f} s",
            explain.KPI_LABEL["handle"],
        )
        _stat(_ms(s.median_tool_ms), explain.KPI_LABEL["tool"])
        # Ninth tile: the grid is auto-fit minmax(140px, 1fr), so it wraps to
        # a second row on a narrow screen instead of squeezing the other eight.
        _stat(pricing.eur(cost.avg_list_eur, 3), explain.KPI_LABEL["cost"], note=_priced_note(cost))


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
    with ui.element("div").classes("transcript"):
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
        if card and card.decline_reason and card.status in {"refused", "escalated", "ended"}:
            ui.label(card.decline_reason).classes("reason")
        rows = [(k, v) for k, v in explain.payload_rows(card) if k != "reason"] if card else []
        if rows:
            ui.element("div").style("height: 16px")
            for key, value in rows:
                with ui.element("div").classes("kv"):
                    ui.label(key)
                    ui.label(str(value)).classes("mono")


def _cost_rows(card: CallCard | None) -> list[tuple[str, str | None]]:
    """What this call cost, leg by leg. Empty when the call was never metered.

    Cost is not patient data, so the public page shows these rows too: the
    jury's question is what one answered call costs, and the answer belongs
    next to the call it came from.
    """
    cost = pricing.price_call(card.usage if card else None)
    if not cost.metered:
        return []
    partial = " · partial" if cost.partial else ""
    llm = f"{pricing.count(cost.llm_tokens_in)} in / {pricing.count(cost.llm_tokens_out)} out"
    llm += f" · {pricing.eur(cost.llm_list_eur)} list"
    if cost.perk:
        llm += " · perk"
    return [
        ("Cost (list)", f"{pricing.eur(cost.total_list_eur)}{partial}"),
        ("Cost (we pay)", f"{pricing.eur(cost.total_eur)}{partial}"),
        ("STT", f"{cost.stt_seconds:.1f} s · {pricing.eur(cost.stt_eur)}"),
        ("LLM", llm),
        ("TTS", f"{pricing.count(cost.tts_characters)} chars · {pricing.eur(cost.tts_eur)}"),
    ]


def _record(card: CallCard | None, *, public: bool = False) -> None:
    with ui.element("div").classes("section-title"):
        ui.label("Record").classes("t")
    ended = "on the call" if card and card.live else (card.reason if card else None)
    phone = card.from_number if card else None
    if public and phone:
        phone = insights.mask_phone(phone)
    rows: list[tuple[str, str | None]] = [
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
        *_cost_rows(card),
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


def _workflow_card(beat: explain.Beat, card: CallCard | None) -> None:
    classes = f"wf-card {beat.kind}"
    if beat.speaking:
        classes += " speaking"
    with ui.element("article").classes(classes):
        with ui.element("div").classes("wf-meta"):
            if beat.kind in {"patient", "agent", "tool", "start", "submit"}:
                icon(beat.kind)
            else:
                _dot(beat.dot)
            ui.label(beat.title).classes("wf-who")
            if beat.tool:
                ui.label(beat.tool).classes("command-tag")
            ui.element("div").classes("grow")
            if beat.ms is not None:
                ui.label(_ms(beat.ms)).classes("caption-sm")
            elif card is not None:
                stamp = _turn_time(card, beat.ts)
                if stamp:
                    ui.label(stamp).classes("caption-sm mono")
        ui.label(beat.text).classes("wf-text")


def _workflow_panel(card: CallCard | None, *, public: bool = False) -> None:
    """The jury demo: one card per turn and tool, pulsing while someone speaks."""
    beats = explain.workflow_beats(card)
    reached = explain.stage_of(card)
    with ui.element("div").classes("wf-head"):
        with ui.element("div"):
            ui.label(_caller(card, public=public) if card else "Waiting for a call").classes(
                "heading-md"
            )
            stage_text = explain.STAGES[max(reached - 1, 0)][1] if reached else "Listen"
            if card and card.live:
                ui.label(f"{stage_text} · {_duration(card)}").classes("caption-sm")
            elif card:
                ui.label(explain.outcome_title(card)).classes("caption-sm")
        if card and card.live:
            with ui.element("div").classes("live-badge"):
                _dot("live")
                ui.label("Speaking" if any(beat.speaking for beat in beats) else "On a call")
        elif card:
            _pill(explain.outcome_title(card), _status_dot(card.status))
    if not beats:
        with ui.element("div").classes("empty-state"):
            ui.label("No call on the line").classes("t")
            ui.label("The next inbound call builds this workflow card by card.").classes("d")
        return
    stream = [beat for beat in beats if beat.kind != "outcome"]
    ending = next((beat for beat in beats if beat.kind == "outcome"), None)
    with ui.element("div").classes("wf-layout"):
        with ui.element("div").classes("workflow"):
            for beat in stream:
                _workflow_card(beat, card)
        with ui.element("aside").classes("wf-side"):
            if ending is not None:
                with ui.element("div").classes("outcome"):
                    ui.label("Outcome").classes("label")
                    with ui.element("div").classes("title"):
                        _dot(ending.dot)
                        ui.label(ending.title)
                    ui.label(ending.text).classes("text")
                    if (
                        card
                        and card.decline_reason
                        and card.status
                        in {
                            "refused",
                            "escalated",
                            "ended",
                        }
                    ):
                        ui.label(card.decline_reason).classes("reason")
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
    with ui.element("div").classes("table-wrap"), ui.element("table").classes("table"):
        with ui.element("thead"), ui.element("tr"):
            for head, extra in (
                ("Time", ""),
                ("Patient", ""),
                ("Outcome", ""),
                ("Why not booked", ""),
                ("Tools", "narrow-hide"),
                ("Duration", "narrow-hide"),
                ("€", "narrow-hide"),
                ("Call id", "narrow-hide"),
            ):
                with ui.element("th").classes(extra):
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
                        why = (
                            explain.reason_text(card.decline_reason) or "—"
                            if card.status in {"refused", "escalated", "ended"}
                            else "—"
                        )
                        ui.label(why)
                    with ui.element("td").classes("num narrow-hide"):
                        ui.label(str(len(card.tools)))
                    with ui.element("td").classes("num narrow-hide"):
                        ui.label(_duration(card))
                    with ui.element("td").classes("num narrow-hide"):
                        # List price, three decimals. An em dash means the call
                        # was never metered, not that it was free.
                        cost = pricing.price_call(card.usage)
                        ui.label(pricing.eur(cost.total_list_eur, 3) if cost.metered else "—")
                    with ui.element("td").classes("id narrow-hide"):
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


@ui.page("/wall/classic")
async def wall_page() -> None:
    """The original NiceGUI projector view: three columns, ten-second read
    from across the room. Superseded as the public entry by the React app
    (vortex/wall/) now mounted at /wall itself, kept here as a fallback/
    reference — nothing about it changed, only its address.
    """
    _apply_chrome()
    ui.page_title("Vortex · Live")
    stage = ui.element("div").classes("shell")
    rendered: dict[str, Any] = {"sig": None}

    async def redraw() -> None:
        cards, health = await _load_cards_async()
        sig = _signature(cards, health)
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        featured = _feature(cards)
        live_count = sum(1 for c in cards if c.live)
        stage.clear()
        with stage:
            slot = _nav("/wall/classic", team=False)
            with slot:
                _line_pill(health)
            with ui.element("main").classes("page"):
                with ui.element("div").classes("page-head"):
                    with ui.element("div"):
                        ui.label("Live").classes("title")
                        ui.label(explain.wall_sub(CLINIC_NAME)).classes("sub")
                    if live_count:
                        with ui.element("div").classes("live-badge"):
                            _dot("live")
                            ui.label(f"{live_count} on the line" if live_count > 1 else "On a call")
                    else:
                        _pill("Idle · waiting for the next call", "off", "mute")
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

    await redraw()
    ui.timer(0.5, redraw)


@ui.page("/call/{call_id}")
async def call_page(call_id: str) -> None:
    """One call, by id. Public. The same panel as Live, plus every request."""
    _apply_chrome()
    ui.page_title(f"Vortex · {call_id}")
    stage = ui.element("div").classes("shell")
    rendered: dict[str, Any] = {"sig": None}

    async def redraw() -> None:
        cards, health = await _load_cards_async()
        card = next((c for c in cards if c.call_id == call_id), None)
        sig = _signature(cards, health, call_id)
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        stage.clear()
        with stage:
            # Session flag only. _ops_ok() is true when auth is off, and this route is public.
            team = bool(app.storage.user.get("ops"))
            slot = _nav("", team=False)
            with slot:
                _line_pill(health)
            with ui.element("main").classes("page"):
                with ui.element("div").classes("page-head"):
                    with ui.element("div"):
                        ui.link("← Live", "/wall").classes("caption-sm")
                        ui.label(
                            _caller(card, public=not team) if card else "Unknown call"
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
                    _call_panel(card, verbose=team, public=not team)
            _footer()

    await redraw()
    ui.timer(0.6, redraw)


@app.get("/api/wall/timeline/{call_id}")
def wall_timeline_api(call_id: str) -> JSONResponse:
    """The chat+tool timeline the react-spring zoom page polls."""
    events, health, _source_info = _load_events("recent")
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


def _card_started(card: CallCard) -> datetime | None:
    if not card.started_at:
        return None
    try:
        stamp = datetime.fromisoformat(card.started_at)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


@app.get("/api/wall/business-insights")
def wall_business_insights_api(days: int = 30) -> JSONResponse:
    """Unavailability reasons, doctor ranking, the demand/supply heatmap and
    cancellation recovery for the Insights page's "7 / 30 / 90 días" pills.
    ``days`` is one of those three; anything else is clamped to the nearest.
    """
    days = min((7, 30, 90), key=lambda d: abs(d - days))
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    # Ask the line for every call started inside the window — a fetch bounded
    # by date, so a busy day's worth of events can never push an in-range call
    # out of the read the way the old 800-event tail did. Bounded by date, so
    # this (like the Agenda roster) prefers the hosted Supabase log first.
    events, _health, source = _load_events(
        f"insights:{days}", since=cutoff, cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S
    )
    cards = build_calls(events)
    in_range = [c for c in cards if (started := _card_started(c)) and started >= cutoff]
    # Same roster the Agenda page shows, not one rebuilt per window: a
    # provider is a lasting fact about the clinic, so a doctor the log saw
    # outside this "days" cut still belongs on it (_ensure_agenda's own
    # AGENDA_ROSTER_DAYS is wider on purpose). Without this, a specialty
    # the offline fixtures never modelled at all (there is no gynaecologist
    # in vortex/clinic/fixtures.py) reads as "0 médicos" while its real,
    # log-sourced demand still shows a non-zero occupancy.
    _ensure_agenda()
    payload = business_insights(in_range, now=now, catalogue=_AGENDA_CATALOGUE)
    payload["range_days"] = days
    payload["source"] = source
    return JSONResponse(payload)


def _sync_clinic(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("clinic client did not complete synchronously")


def _sync_catalogue() -> Any:
    return _sync_clinic(FakeClinicClient().catalogue())


#: How far back to read the log for the roster. Wider than the Home window
#: because a provider record is a lasting fact about the clinic, so an older
#: call that happened to look one up is still the best source for it.
AGENDA_ROSTER_DAYS = 30


def _ensure_agenda() -> None:
    """Load catalogue, directory and appointments through the clinic client."""
    global _AGENDA_CATALOGUE, _AGENDA_PATIENTS
    if _AGENDA_CATALOGUE is not None and _AGENDA_PATIENTS is not None:
        return
    pack = cal.SYNTHETIC_DATA_DIR
    data_dir = pack if (pack / "patients.json").exists() else None
    pack_client = FakeClinicClient(data_dir=data_dir) if data_dir is not None else None
    api_client = FakeClinicClient()
    _AGENDA_CATALOGUE = _sync_clinic(api_client.catalogue())
    # Offline that catalogue is fixtures, which know seven of the clinic's
    # twelve doctors. The call log carries the platform's own records for the
    # rest, so fold them in before any grid is built off it.
    events, _health, _source = _load_events(
        f"agenda:{AGENDA_ROSTER_DAYS}",
        since=datetime.now(UTC) - timedelta(days=AGENDA_ROSTER_DAYS),
        cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S,
    )
    _AGENDA_CATALOGUE = cal.catalogue_with_log_roster(_AGENDA_CATALOGUE, events)
    records = _sync_clinic((pack_client or api_client).directory())
    seen = {row.patient_id for row in records}
    for row in _sync_clinic(api_client.directory()):
        if row.patient_id not in seen:
            records.append(row)
            seen.add(row.patient_id)
    _AGENDA_PATIENTS = cal.patient_index_from_records(records)
    # Bookings are deliberately not loaded here: they are the one part of the
    # agenda that changes while the board runs, and ``_agenda_bookings_live``
    # owns them on its own TTL.
    # Real callers are not in the offline directory, so their visits would show
    # an id where a name belongs. The database carries whatever name the call
    # that booked them established; the directory still wins where it knows.
    rows, _call_ids = cal.load_database_agenda()
    for patient_id, brief in cal.patient_index_from_rows(rows).items():
        _AGENDA_PATIENTS.setdefault(patient_id, brief)


_AGENDA_CATALOGUE = None
_AGENDA_PATIENTS: dict[str, Any] | None = None
_AGENDA_BOOKINGS: dict[Any, Any] | None = None


@app.get("/api/wall/agenda-options")
def wall_agenda_options_api() -> JSONResponse:
    """Doctors, sites, specialties and appointment types for the diary dropdowns."""
    global _AGENDA_CATALOGUE
    if _AGENDA_CATALOGUE is None:
        _ensure_agenda()
    return JSONResponse(cal.agenda_options(_AGENDA_CATALOGUE))


@app.get("/api/wall/doctor-suggest")
def wall_doctor_suggest_api(q: str = "") -> JSONResponse:
    """Name typeahead. Empty query returns an empty list, never the full roster."""
    global _AGENDA_CATALOGUE
    if _AGENDA_CATALOGUE is None:
        _ensure_agenda()
    calendars = cal.build_calendars(_AGENDA_CATALOGUE, {})
    return JSONResponse(cal.suggest_doctors(calendars, q))


@app.get("/api/wall/doctor-agenda")
def wall_doctor_agenda_api(
    name: str = "",
    specialty: str = "",
    week: str | None = None,
    month: str | None = None,
    today: str | None = None,
) -> JSONResponse:
    """Month grid of booked visits. Doctor is optional; specialty is enough."""
    global _AGENDA_CATALOGUE, _AGENDA_PATIENTS, _AGENDA_BOOKINGS
    _ensure_agenda()
    catalogue = _AGENDA_CATALOGUE
    if today:
        try:
            today_date = date.fromisoformat(today)
        except ValueError:
            today_date = datetime.now(ZoneInfo("Europe/Madrid")).date()
    else:
        today_date = datetime.now(ZoneInfo("Europe/Madrid")).date()
    week_date = None
    if week:
        try:
            week_date = date.fromisoformat(week)
        except ValueError:
            week_date = None
    month_date = None
    if month:
        raw = month.strip()
        if len(raw) == 7:
            raw = f"{raw}-01"
        try:
            month_date = date.fromisoformat(raw)
        except ValueError:
            month_date = None
    calendars = cal.build_calendars(catalogue, _agenda_bookings_live())
    payload = cal.clinic_agenda(
        calendars,
        _AGENDA_PATIENTS,
        name=name,
        specialty_id=specialty,
        today=today_date,
        week=week_date,
        month=month_date,
        location_names={loc.location_id: loc.name for loc in catalogue.locations},
        type_names={item.appointment_type_id: item.name for item in catalogue.appointment_types},
        type_durations={
            item.appointment_type_id: item.duration_minutes for item in catalogue.appointment_types
        },
        plan_names={plan.insurer_id: plan.name for plan in catalogue.insurance_plans},
    )
    return JSONResponse(payload)


# ---- Wall cancellations ----------------------------------------------------
# The Horarios page's "Cancelar" buttons land here. The data layer is
# ``database/`` (the control centre's own store): one ``wall_cancellations``
# row per freed slot, plus a status flip on ``appointments`` when the
# appointment exists there — the same ``cancelled`` a phone cancellation
# writes through ``database/hooks.py``. Reads then drop those slots via
# ``cal.drop_cancelled``, so a cancelled visit simply shows as a free slot,
# the same thing a CANCEL replayed from the call log does. Every cancelled
# visit with a patient on it also lands in the rebooking queue
# (``rebooking.sqlite3`` next to the product DB) as a pending ``reschedule``
# — the outbound dialer calls the patient back for a new slot once the line
# can dial out. Nothing is submitted anywhere: the clinic's own diary is the
# system of record here.


def _wall_db_path() -> Path:
    return get_settings().product_db_path


def _wall_cancelled_keys() -> set[cal.BookingKey]:
    """The slots the control centre cancelled by hand, as diary keys."""
    from database import db  # late import, same as vortex/line/submit.py's

    keys: set[cal.BookingKey] = set()
    try:
        conn = db.connect(_wall_db_path())
        try:
            rows = db.list_wall_cancellations(conn)
        finally:
            conn.close()
    except Exception:
        # A missing/unwritable store must never blank the diary.
        log.exception("wall_cancellations read failed; agenda shows every slot")
        return keys
    for row in rows:
        key = cal.cancel_key(row.provider_id, row.site_id, row.slot_start)
        if key is not None:
            keys.add(key)
    return keys


#: How long a diary read is reused. The catalogue and the roster beside it
#: stay cached for the process — a provider's schedule is not what changes —
#: but the bookings are a database read, and the database gains rows while the
#: board runs. Caching those for the process life would leave the Agenda
#: showing whatever the diary held when the first tab opened.
AGENDA_BOOKINGS_TTL_S = 30.0

_AGENDA_BOOKINGS_AT = 0.0


def _agenda_bookings_live() -> dict[cal.BookingKey, cal.Booking]:
    """The current bookings minus the slots the wall already cancelled."""
    global _AGENDA_BOOKINGS, _AGENDA_BOOKINGS_AT
    _ensure_agenda()
    stale = (time.monotonic() - _AGENDA_BOOKINGS_AT) > AGENDA_BOOKINGS_TTL_S
    if _AGENDA_BOOKINGS is None or stale:
        _AGENDA_BOOKINGS = cal.load_agenda_bookings(_AGENDA_CATALOGUE)
        _AGENDA_BOOKINGS_AT = time.monotonic()
    return cal.drop_cancelled(_AGENDA_BOOKINGS or {}, _wall_cancelled_keys())


def _rebooking_store_path() -> Path:
    """The reschedule-callback queue file: ``rebooking.sqlite3`` next to the
    product DB (``logs/`` locally, the board's writable volume in deploy —
    same place a real outbound dialer would read it from)."""
    return _wall_db_path().with_name("rebooking.sqlite3")


def _enqueue_rebookings(bookings: list[cal.Booking]) -> int:
    """One pending ``rebooking_requests`` row per cancelled visit — the queue
    ``vortex/diary/rebooking.py``'s watcher re-checks and the line's outbound
    dialer will drain once it can place calls. A failed queue must not roll
    back a cancel that already committed, so this logs and degrades to 0
    instead of propagating."""
    from vortex.diary import rebooking  # late import, same as database/ below

    today = datetime.now(MADRID).date()
    try:
        store = rebooking.RebookingStore(_rebooking_store_path())
    except Exception:
        log.exception("rebooking queue unavailable; cancelled slots stay cancelled")
        return 0
    queued = 0
    for booking in bookings:
        request = rebooking.wall_cancel_request(
            provider_id=booking.provider_id,
            location_id=booking.location_id,
            slot_start=booking.start,
            patient_id=booking.patient_id,
            appointment_id=booking.appointment_id or None,
            today=today,
        )
        if request is None:
            continue  # no patient on the visit — nobody to call back
        try:
            store.add(request)
            queued += 1
        except Exception:
            log.exception("rebooking enqueue failed for slot %s", booking.start.isoformat())
    return queued


def _parse_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None


def _cancel_range_args(
    payload: Any,
) -> tuple[str, date | None, date | None, str | None]:
    """Shared validation for the two range routes. ``from`` > ``to`` is a
    slips-of-the-mouse case, not an error — the range swaps ends."""
    if not isinstance(payload, dict):
        return "", None, None, "bad_request"
    provider_id = str(payload.get("provider_id") or "").strip()
    day_from = _parse_day(payload.get("from"))
    day_to = _parse_day(payload.get("to"))
    if not provider_id:
        return provider_id, day_from, day_to, "missing_doctor"
    if day_from is None or day_to is None:
        return provider_id, day_from, day_to, "missing_dates"
    if day_from > day_to:
        day_from, day_to = day_to, day_from
    return provider_id, day_from, day_to, None


def _cancel_targets(
    provider_id: str, day_from: date, day_to: date
) -> tuple[str, list[cal.Booking]]:
    """One doctor's still-booked slots inside the range — the exact set a
    range cancel frees, so preview and confirm can never disagree on what
    "all appointments in the range" means."""
    _ensure_agenda()
    catalogue = _AGENDA_CATALOGUE
    provider = next((p for p in catalogue.providers if p.provider_id == provider_id), None)
    if provider is None:
        return "", []
    hits = [
        booking
        for booking in _agenda_bookings_live().values()
        if booking.provider_id == provider_id
        and day_from <= booking.start.astimezone(MADRID).date() <= day_to
    ]
    return provider.name, sorted(hits, key=lambda booking: booking.start)


def _cancel_sample(bookings: list[cal.Booking], limit: int = 8) -> list[dict[str, str]]:
    """The first few affected visits, for the modal's "this is what goes" list."""
    patients = _AGENDA_PATIENTS or {}
    sample = []
    for booking in bookings[:limit]:
        person = patients.get(booking.patient_id)
        start = booking.start.astimezone(MADRID)
        sample.append(
            {
                "date": start.date().isoformat(),
                "time": start.strftime("%H:%M"),
                "full_name": (person.full_name if person else "") or "Cita",
            }
        )
    return sample


@app.post("/api/wall/agenda/cancel-preview")
async def wall_cancel_preview_api(request: Request) -> JSONResponse:
    """The count (and a sample) a range cancel would free — the number the
    modal shows before its explicit confirm. Writes nothing."""
    provider_id, day_from, day_to, err = _cancel_range_args(await request.json())
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    doctor, hits = _cancel_targets(provider_id, day_from, day_to)
    if not doctor:
        return JSONResponse({"ok": False, "error": "unknown_doctor"}, status_code=404)
    return JSONResponse(
        {
            "ok": True,
            "doctor": doctor,
            "count": len(hits),
            "sample": _cancel_sample(hits),
        }
    )


@app.post("/api/wall/agenda/cancel")
async def wall_cancel_range_api(request: Request) -> JSONResponse:
    """Batch cancel: every booked slot of one doctor inside [from, to]."""
    provider_id, day_from, day_to, err = _cancel_range_args(await request.json())
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    doctor, hits = _cancel_targets(provider_id, day_from, day_to)
    if not doctor:
        return JSONResponse({"ok": False, "error": "unknown_doctor"}, status_code=404)
    from database import db

    patients = _AGENDA_PATIENTS or {}
    with db.connection(_wall_db_path()) as conn:
        for booking in hits:
            person = patients.get(booking.patient_id)
            db.insert_wall_cancellation(
                conn,
                provider_id=booking.provider_id,
                site_id=booking.location_id,
                slot_start=booking.start.astimezone(MADRID).isoformat(),
                appointment_id=booking.appointment_id or None,
                patient_name=person.full_name if person else None,
                provider_name=doctor,
            )
        touched = db.cancel_appointment_rows(
            conn, provider_id=provider_id, day_from=day_from, day_to=day_to
        )
    queued = _enqueue_rebookings(hits)
    return JSONResponse(
        {
            "ok": True,
            "doctor": doctor,
            "cancelled": len(hits),
            "appointments_updated": len(touched),
            "rebookings_queued": queued,
        }
    )


@app.post("/api/wall/appointments/cancel")
async def wall_cancel_visit_api(request: Request) -> JSONResponse:
    """Single cancel from a visit's detail view. The body names the slot the
    way the diary keys it — provider + site + minute — and the server takes
    every other fact (patient, appointment id) from the booking itself."""
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "bad_request"}, status_code=400)
    provider_id = str(payload.get("provider_id") or "").strip()
    location_id = str(payload.get("location_id") or "").strip()
    key = cal.cancel_key(provider_id, location_id, payload.get("slot_start"))
    if key is None:
        return JSONResponse({"ok": False, "error": "bad_slot"}, status_code=400)
    booking = _agenda_bookings_live().get(key)
    if booking is None:
        # Free already (or never booked, or cancelled earlier) — a wall cancel
        # must never mint a row for a slot nothing was on.
        return JSONResponse({"ok": False, "error": "not_booked"}, status_code=409)
    catalogue = _AGENDA_CATALOGUE
    provider = next((p for p in catalogue.providers if p.provider_id == provider_id), None)
    person = (_AGENDA_PATIENTS or {}).get(booking.patient_id)
    from database import db

    with db.connection(_wall_db_path()) as conn:
        db.insert_wall_cancellation(
            conn,
            provider_id=provider_id,
            site_id=location_id,
            slot_start=booking.start.astimezone(MADRID).isoformat(),
            appointment_id=booking.appointment_id or None,
            patient_name=person.full_name if person else None,
            provider_name=provider.name if provider else None,
        )
        touched = db.cancel_appointment_row(
            conn,
            appointment_id=booking.appointment_id or None,
            provider_id=provider_id,
            slot_start=booking.start.astimezone(MADRID).isoformat(),
        )
    queued = _enqueue_rebookings([booking])
    return JSONResponse({"ok": True, "appointment_updated": touched, "rebookings_queued": queued})


def _home_cards() -> tuple[list[CallCard], dict]:
    """The real calls of the last ``HOME_WINDOW_DAYS`` days, and their source.

    Bounded by start date rather than by an event tail for the same reason
    the Insights fetch is: a tail cut can split a call and drop its
    ``call.started``. ``is_real_call`` then removes the eval probes and
    scripted demo calls that share this log.

    Not cached for the life of the process: ``home_overview`` buckets against
    a live clock, so cards fixed at start-up would report a stale "today"
    from the moment the day rolled over.
    """
    cutoff = datetime.now(UTC) - timedelta(days=HOME_WINDOW_DAYS)
    events, _health, source = _load_events(
        f"home:{HOME_WINDOW_DAYS}", since=cutoff, cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S
    )
    return [c for c in build_calls(events) if is_real_call(c)], source


@app.get("/api/wall/home-overview")
def wall_home_overview_api() -> JSONResponse:
    """Today's diary activity for the Home page, off the line's own call log.

    ``source`` rides along so a page of zeros can be told apart from a feed
    that degraded to stale or empty data.
    """
    cards, source = _home_cards()
    payload = home_overview(cards, now=datetime.now(UTC))
    payload["source"] = source
    return JSONResponse(payload)


@app.get("/api/wall/live-calls")
def wall_live_calls_api() -> JSONResponse:
    """Calls in progress right now, for the Live Calls page and Home's rail.

    Reads the same "recent" feed every other live card on the board does
    (``_load_cards`` -> ``callfeed.load_events``): the line's own ``/calls``
    first so an in-flight call shows before anything else could have heard
    of it, the hosted Supabase log as the automatic fallback when the line
    itself is unreachable, then this process's local JSONL last. No
    JSONL-only or fixtures-only path here to begin with — this endpoint
    replaces the page's ``PLACEHOLDER_CALLS`` mock, not a JSONL reader.
    """
    cards, _health = _load_cards()
    live = [c for c in cards if c.live and is_real_call(c)]
    calls = [
        {
            "id": c.call_id,
            "patient": c.patient_name or "Sin identificar",
            "phase": explain.STAGES[max(explain.stage_of(c) - 1, 0)][1],
            "status": c.status,
            "duration": _duration(c),
            # Every socket connection is inbound (the platform only ever
            # dials us — see .claude/skills/call-contract); the only
            # outbound calls this product places are confirmation calls,
            # which do not carry a live turn-by-turn transcript the same
            # way and are not shown on this "in progress right now" list.
            "direction": "inbound",
            "phone": c.from_number or "",
        }
        for c in live
    ]
    return JSONResponse({"calls": calls})


@app.get("/api/wall/occupancy")
def wall_occupancy_api(site: str = "", specialty: str = "") -> JSONResponse:
    """Occupancy calendar for the Home page's site/specialty filters — read
    straight off ``wall-cache/occupancy.json``, precomputed at start-up."""
    return JSONResponse(occupancy(site=site, specialty=specialty))


# ---- "Voz del agente" settings ---------------------------------------------
# The card's store lives on the line (a voiceconfig.db next to its calls log);
# the board only has that volume read-only, so these proxy to the line's API.
# When the line is down the GET falls back to defaults so the page still loads.


@app.get("/api/wall/voice-config")
async def wall_voice_config() -> JSONResponse:
    try:
        r = httpx.get(f"{callfeed.LINE_URL}/voice-config", timeout=callfeed.LINE_HEALTH_TIMEOUT_S)
        if r.status_code == 200:
            return JSONResponse(r.json())
    except Exception as exc:
        log.warning("voice-config fetch failed: %s", exc)
    return JSONResponse(voice_config.DEFAULTS)


@app.put("/api/wall/voice-config")
async def wall_voice_config_put(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        r = httpx.put(f"{callfeed.LINE_URL}/voice-config", json=payload, timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@app.post("/api/wall/voice-preview")
async def wall_voice_preview(request: Request) -> Response:
    """The Try button: streams back the line's MP3 of the greeting."""
    payload = await request.json()
    try:
        r = httpx.post(f"{callfeed.LINE_URL}/voice-preview", json=payload, timeout=20)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)
    if r.status_code == 200:
        return Response(content=r.content, media_type="audio/mpeg")
    try:
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception:
        return JSONResponse({"error": r.text}, status_code=r.status_code)


# ---- "Personalidades" picker -------------------------------------------------
# Same arrangement as the voice card: the personas live on the line (a
# personalities.db next to its calls log) and the board only has that volume
# read-only, so these proxy to the line's API. When the line is down the GET
# falls back to the seed personas, flagged ``offline`` so the page can say so
# and grey out the buttons instead of pretending a write will land.


@app.get("/api/wall/personalities")
async def wall_personalities() -> JSONResponse:
    try:
        r = httpx.get(f"{callfeed.LINE_URL}/personalities", timeout=callfeed.LINE_HEALTH_TIMEOUT_S)
        if r.status_code == 200:
            return JSONResponse(r.json())
    except Exception as exc:
        log.warning("personalities fetch failed: %s", exc)
    return JSONResponse(
        {
            "items": personalities.DEFAULTS,
            "active": personalities.DEFAULTS[0]["slug"],
            "offline": True,
            **personalities.catalog(),
        }
    )


@app.post("/api/wall/personalities")
async def wall_personality_create(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        r = httpx.post(f"{callfeed.LINE_URL}/personalities", json=payload, timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@app.get("/api/wall/personalities/{slug}")
async def wall_personality(slug: str) -> JSONResponse:
    try:
        r = httpx.get(
            f"{callfeed.LINE_URL}/personalities/{slug}", timeout=callfeed.LINE_HEALTH_TIMEOUT_S
        )
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@app.put("/api/wall/personalities/{slug}")
async def wall_personality_put(slug: str, request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        r = httpx.put(f"{callfeed.LINE_URL}/personalities/{slug}", json=payload, timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@app.post("/api/wall/personalities/{slug}/activate")
async def wall_personality_activate(slug: str) -> JSONResponse:
    try:
        r = httpx.post(f"{callfeed.LINE_URL}/personalities/{slug}/activate", timeout=5)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse({"error": f"line unreachable: {exc}"}, status_code=502)


@app.get("/wall/personalities/{filename}")
def wall_personality_art(filename: str) -> Response:
    """One persona portrait, straight off disk like the avatar routes above.

    The stored filename is validated on the way in (no separators), but this
    resolves it inside the folder anyway and refuses anything that lands
    outside it or is not an SVG: a hand-edited db row must not read /etc.
    """
    path = (PERSONALITY_MEDIA_DIR / filename).resolve()
    if path.suffix.lower() != ".svg" or not path.is_relative_to(PERSONALITY_MEDIA_DIR.resolve()):
        return JSONResponse({"error": "no such portrait"}, status_code=404)
    if not path.is_file():
        return JSONResponse({"error": "no such portrait"}, status_code=404)
    return FileResponse(path, media_type="image/svg+xml")


@app.get("/wall/avatar2d")
def wall_avatar2d() -> FileResponse:
    """The 2D avatar art, served as a plain image — not wrapped in a page —
    so it can be linked or embedded directly. Source: vortex/wall/media/.
    """
    return FileResponse(WALL_MEDIA_DIR / "avatar2d.png", media_type="image/png")


@app.get("/wall/avatar2d-animated")
def wall_avatar2d_animated() -> FileResponse:
    """The animated version: a self-contained SVG (transparent background,
    CSS keyframes baked in — float, head bob, blink, clipboard sway) used
    as the landing page's hero avatar.
    """
    return FileResponse(WALL_MEDIA_DIR / "avatar2d_animated.svg", media_type="image/svg+xml")


@app.get("/wall/vorty-face")
def wall_vorty_face() -> FileResponse:
    """A static, cropped-to-the-head SVG (no animation) used as Vorty's
    chat avatar — e.g. the Live Call transcript.
    """
    return FileResponse(WALL_MEDIA_DIR / "vorty-face.svg", media_type="image/svg+xml")


@app.get("/wall/vorty-face-no-headphones")
def wall_vorty_face_bare() -> FileResponse:
    """The same head without the headset, so an accessory overlay can sit on top."""
    return FileResponse(WALL_MEDIA_DIR / "vorty-face-no-headphones.svg", media_type="image/svg+xml")


@app.get("/wall/accessories/{filename}")
def wall_vorty_accessory(filename: str) -> Response:
    """One Vorty accessory SVG, stacked over the bare face on a persona card."""
    folder = (WALL_MEDIA_DIR / "accessories" / "animated").resolve()
    path = (folder / filename).resolve()
    if path.suffix.lower() != ".svg" or not path.is_relative_to(folder) or not path.is_file():
        return JSONResponse({"error": "no such accessory"}, status_code=404)
    return FileResponse(path, media_type="image/svg+xml")


@app.get("/wall", response_model=None)
def wall_entry() -> Response:
    """The public URL (see README's production table): the React app
    (vortex/wall/) — landing page, then client-side into the Clinic View —
    if it has been built. Falls back to the classic NiceGUI projector view
    so this address never 404s for the jury just because a deploy skipped
    ``npm run build``.
    """
    index = WALL_APP_DIST / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return RedirectResponse("/wall/classic")


if WALL_APP_DIST.exists():
    app.add_static_files("/wall-assets", str(WALL_APP_DIST))
    _WALL_INDEX_HTML = (WALL_APP_DIST / "index.html").read_text(encoding="utf-8")

    @app.get("/call/{call_id}/zoom")
    def call_zoom_page(call_id: str) -> HTMLResponse:
        """The React app's per-call view: voice orb, live tool demo, extracted
        info with the rule behind each, final action. Also the app's SPA
        entry point — with no call_id of interest (e.g. /call/demo/zoom) it
        opens on the landing page instead, then routes client-side from there
        into the Clinic View.

        Built by ``npm run build`` in ``vortex/wall/``. It reads its data
        from ``/api/wall/timeline/{call_id}`` above, client-side.
        Additive: ``/call/{call_id}`` (no ``/zoom``) stays the NiceGUI page.
        """
        del call_id  # the SPA reads the id itself from window.location
        return HTMLResponse(_WALL_INDEX_HTML)


# ---------------------------------------------------------------------------
# Team pages
# ---------------------------------------------------------------------------


def _login_form() -> None:
    slot = _nav("/", team=False)
    with slot:
        ui.link("Open the wall", "/wall").classes("pill mute")
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
            ui.link("Open the wall", "/wall").classes("button-secondary")
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
async def ops_page() -> None:
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
        ui.button("Replay cancellations", on_click=_replay_cancellations).props(
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

    async def pick(call_id: str) -> None:
        state["id"] = call_id
        await redraw()

    async def set_filter(key: str) -> None:
        state["filter"] = key
        await redraw()

    async def redraw() -> None:
        _beat(name.value or "joaquin")
        cards, health = await _load_cards_async()
        shown = [c for c in cards if _passes(c, state["filter"])]
        if state["id"] is None and shown:
            featured = explain.featured_call(shown)
            state["id"] = featured.call_id if featured is not None else shown[0].call_id
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

    await redraw()
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


def _precompute_wall_cache() -> None:
    """Refresh ``wall-cache/occupancy.json`` off the clinic API's own GETs
    before serving the first request — see ``scripts/precompute_wall_cache.py``.
    Run as a subprocess, the same way ``_play_line`` shells out to
    ``scripts/fake_caller.py``: it's a standalone script, not a package
    import, and a slow or failing fetch should delay start-up, never crash
    the board — the Home page just shows an empty occupancy card until the
    next successful run."""
    script = REPO_ROOT / "scripts" / "precompute_wall_cache.py"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    if result.returncode == 0:
        print(result.stdout.strip())
    else:
        print(f"wall-cache precompute failed, keeping any existing file: {result.stderr.strip()}")


#: How often the board rebuilds its product database from the call log.
#: Nothing else will ever put a real call in it: ``database/hooks.py`` writes
#: forward-only from the line's own process, into the line's own file, and
#: ``deploy/compose.yml`` gives the board a separate writable volume (the log
#: is the only thing the two share, mounted read-only). So without this the
#: Agenda would only ever hold whatever the last manual backfill put there.
#: A timer is safe because the backfill is idempotent by construction.
PRODUCT_DB_REFRESH_S = 120.0


def _backfill_product_db() -> None:
    """Turn the call log's landed actions into product-database rows.

    Subprocess for the same reasons ``_precompute_wall_cache`` gives: it is a
    standalone script rather than a package import, and a slow or failing run
    must never take the board down — the Agenda simply keeps the rows it
    already has until the next run succeeds.
    """
    script = REPO_ROOT / "database" / "scripts" / "backfill_from_logs.py"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    if result.returncode == 0:
        print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "backfill: ok")
    else:
        print(f"product-db backfill failed, keeping existing rows: {result.stderr.strip()}")


async def _refresh_product_db_forever() -> None:
    while True:
        await asyncio.sleep(PRODUCT_DB_REFRESH_S)
        await asyncio.to_thread(_backfill_product_db)


def _start_product_db_refresh() -> None:
    """Launch the refresh loop on the server's own event loop.

    A sync start-up handler that creates the task, rather than an async one:
    NiceGUI awaits an async handler, and a loop that never returns would hang
    start-up instead of running beside it.
    """
    asyncio.create_task(_refresh_product_db_forever())


def main() -> None:
    if auth.is_production() and not auth.ops_password():
        raise SystemExit("VORTEX_OPS_PASSWORD is required in production")
    _precompute_wall_cache()
    # Registered here rather than at import time so tests and any other
    # importer of this module never start a background subprocess loop.
    _backfill_product_db()
    app.on_startup(_start_product_db_refresh)
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
# The doctor calendar (/calendar) registers its page on import; it reuses this
# module's chrome, so it comes after everything above is defined. liveflow is
# the workflow projector page (/wall/flow public, /calls/live for the team).
from vortex.observability import calendar_view, console, liveflow  # noqa: E402, F401

if __name__ in {"__main__", "__mp_main__"}:
    main()
