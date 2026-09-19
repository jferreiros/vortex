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
from vortex.line import voice_config
from vortex.observability import auth, callfeed, explain, insights, pricing, store
from vortex.observability import calendar as cal
from vortex.observability.business_insights import business_insights
from vortex.observability.demo import replay_cancellation_demo, write_scripted_call
from vortex.observability.home_overview import home_overview, load_synthetic_cards, occupancy
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
    # out of the read the way the old 800-event tail did.
    events, _health, source = _load_events(
        f"insights:{days}", since=cutoff, cache_ttl=callfeed.INSIGHTS_CACHE_TTL_S
    )
    cards = build_calls(events)
    in_range = [c for c in cards if (started := _card_started(c)) and started >= cutoff]
    payload = business_insights(in_range, now=now)
    payload["range_days"] = days
    payload["source"] = source
    return JSONResponse(payload)


# ---- Call analytics (SQLite store) ------------------------------------------
# Everything below in this region is additive for feat/clinic-analytics.
# logs/calls.jsonl stays the source of truth; ``store.ingest`` keeps a
# rebuildable SQLite projection (logs/calls.db) tailed up to date — the
# offset lives in the DB, so this is a few new lines on a poll, a full scan
# only on first boot.


def _analytics_paths() -> tuple[Path, Path]:
    log_path = _log_path()
    return log_path, store.default_db_path(log_path)


def _ingest_analytics() -> dict[str, Any] | None:
    """Cheap tail ingest. A failure must never take the board down — the
    endpoint then serves whatever the DB already holds."""
    try:
        log_path, db_path = _analytics_paths()
        return store.ingest(log_path, db_path)
    except Exception as exc:
        log.warning("analytics ingest failed: %s", exc)
        return None


@app.get("/api/wall/analytics")
def wall_analytics_api(days: int = 30) -> JSONResponse:
    """Hamming-style call aggregates for the Insights analytics section:
    status mix, duration histogram, talk ratio, words per turn, TTFB and
    tool-latency p50/p95, the intent->action funnel and €/call — all read off
    logs/calls.db after a cheap tail ingest, so the numbers are never stale.
    Calls without ``turn.metrics`` events degrade to word-count proxies; the
    payload's ``metrics`` block says how many calls were measured."""
    days = min((7, 30, 90), key=lambda d: abs(d - days))
    ingest_stats = _ingest_analytics()
    _log, db_path = _analytics_paths()
    payload = store.analytics(db_path, days)
    payload["range_days"] = days
    if ingest_stats is not None:
        payload["ingest"] = ingest_stats
    return JSONResponse(payload)


# ---- end of call analytics region -------------------------------------------


def _sync_clinic(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("clinic client did not complete synchronously")


def _sync_catalogue() -> Any:
    return _sync_clinic(FakeClinicClient().catalogue())


def _ensure_agenda() -> None:
    """Load catalogue, directory and appointments through the clinic client."""
    global _AGENDA_CATALOGUE, _AGENDA_PATIENTS, _AGENDA_BOOKINGS
    if _AGENDA_CATALOGUE is not None and _AGENDA_PATIENTS is not None:
        return
    pack = cal.SYNTHETIC_DATA_DIR
    data_dir = pack if (pack / "patients.json").exists() else None
    pack_client = FakeClinicClient(data_dir=data_dir) if data_dir is not None else None
    api_client = FakeClinicClient()
    _AGENDA_CATALOGUE = _sync_clinic(api_client.catalogue())
    records = _sync_clinic((pack_client or api_client).directory())
    seen = {row.patient_id for row in records}
    for row in _sync_clinic(api_client.directory()):
        if row.patient_id not in seen:
            records.append(row)
            seen.add(row.patient_id)
    _AGENDA_PATIENTS = cal.patient_index_from_records(records)
    _AGENDA_BOOKINGS = cal.load_agenda_bookings(_AGENDA_CATALOGUE)


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
    calendars = cal.build_calendars(catalogue, _AGENDA_BOOKINGS or {})
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


#: The Home page's own numbers never come from the live line: the pack is a
#: fixed corpus of eval calls, cached for the life of the process the same
#: way the React app's build is.
_HOME_CARDS_CACHE: list[CallCard] | None = None


def _home_cards() -> list[CallCard]:
    global _HOME_CARDS_CACHE
    if _HOME_CARDS_CACHE is None:
        _HOME_CARDS_CACHE = load_synthetic_cards()
    return _HOME_CARDS_CACHE


@app.get("/api/wall/home-overview")
def wall_home_overview_api() -> JSONResponse:
    """Stats, hourly and daily volume for the Home page — read straight off
    ``synthetic-data/`` (see ``home_overview.py``), never a per-render mock."""
    return JSONResponse(home_overview(_home_cards()))


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


def main() -> None:
    if auth.is_production() and not auth.ops_password():
        raise SystemExit("VORTEX_OPS_PASSWORD is required in production")
    _precompute_wall_cache()
    _ingest_analytics()  # warm logs/calls.db once; polls then tail it cheaply
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
