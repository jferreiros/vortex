"""The live view: ``/`` for the team, ``/wall`` for the jury.

Every screen follows DESIGN.md. ``design.css`` carries the tokens and the
components; ``board.css`` adds the Quasar overrides and the two layouts.
Add a class from those files before you add an inline style here.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from nicegui import app, ui

from vortex.observability import auth
from vortex.observability.calllog import read_recent
from vortex.observability.demo import write_scripted_call
from vortex.observability.view import CallCard, build_calls, flatten_grouped
from vortex.settings import REPO_ROOT, get_settings

LINE_URL = os.environ.get("VORTEX_LINE_URL", "http://127.0.0.1:7860").rstrip("/")
BOARD_PORT = int(os.environ.get("VORTEX_BOARD_PORT", "8080"))
PRESENCE: dict[str, float] = {}
_HERE = Path(__file__).parent
DESIGN_CSS = (_HERE / "design.css").read_text(encoding="utf-8")
BOARD_CSS = (_HERE / "board.css").read_text(encoding="utf-8")

NAV_LINKS = (("Ops", "/"), ("Wall", "/wall"), ("Evals", "/evals"), ("Bench", "/bench"))

STATUS_LABEL = {
    "live": "En llamada",
    "booked": "Cita reservada",
    "registered": "Paciente registrado",
    "rescheduled": "Cita movida",
    "cancelled": "Cita anulada",
    "refused": "Sin acción",
    "escalated": "Escalada",
    "ended": "Terminada",
}


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


def _feature(cards: list[CallCard]) -> CallCard | None:
    live = next((c for c in cards if c.live), None)
    return live or (cards[0] if cards else None)


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
        ui.notify("Line no contestó. Arrancá `make run` en 7860.", type="negative")
    else:
        ui.notify("Llamada enviada a /ws", type="positive")


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
# Shared chrome
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


def _json_preview(value: Any, limit: int = 88) -> str:
    text = "" if value is None else str(value)
    if isinstance(value, dict):
        keys = ", ".join(f"{k}" for k in list(value)[:4])
        text = keys or "{}"
    return text if len(text) <= limit else text[: limit - 1] + "…"


# Which clinic endpoint each tool hits. Same map as scripts/call_rundown.py.
TOOL_ENDPOINTS = {
    "find_patient": "GET /api/v1/directory · +GET /patients/{id}/appointments?when=past",
    "validate_national_id": "local · DNI/NIE check letter",
    "build_registration": "GET /api/v1/clinic",
    "resolve_date": "GET /api/v1/clinic",
    "find_slots": "GET /api/v1/availability",
    "list_appointments": "GET /patients/{id}/appointments",
    "prepare_booking": "GET /api/v1/clinic + GET /api/v1/availability",
    "prepare_reschedule": "GET /patients/{id}/appointments + /availability",
    "prepare_cancel": "GET /patients/{id}/appointments",
    "check_eligibility": "GET /api/v1/availability + GET /api/v1/clinic",
    "triage": "local · symptom rules",
    "nearest_location": "local · site distances",
    "find_provider": "GET /api/v1/clinic",
    "submit_action": "POST /api/v1/submit/<route>",
}


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _short_json(value: Any, limit: int = 110) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _turn_time(card: CallCard, ts: str | None) -> str:
    """'21:38:13 +12.3s' — wall clock and seconds since the call connected."""
    if not ts:
        return ""
    try:
        stamp = datetime.fromisoformat(str(ts))
    except ValueError:
        return ""
    label = stamp.strftime("%H:%M:%S")
    if card.started_at:
        try:
            delta = (stamp - datetime.fromisoformat(str(card.started_at))).total_seconds()
            if 0 <= delta < 3600:
                label += f" +{delta:.1f}s"
        except ValueError:
            pass
    return label


def _duration(card: CallCard) -> str:
    if card.duration_ms is None:
        return "—"
    return f"{card.duration_ms / 1000:.1f}s"


def _line_pill(health: dict[str, Any] | None, *, detail: bool = False) -> None:
    with ui.element("div").classes("pill mute"):
        _dot("ok" if health else "bad")
        if health and detail:
            ui.label(f"line · {health.get('voice')}/{health.get('clinic')}")
        else:
            ui.label("line up" if health else "line down")


def _status_pill(card: CallCard | None) -> None:
    if card is None:
        with ui.element("div").classes("pill mute"):
            _dot("off")
            ui.label("En espera")
        return
    if card.live:
        with ui.element("div").classes("pill dark"):
            _dot("live")
            ui.label(STATUS_LABEL["live"])
        return
    with ui.element("div").classes("pill"):
        _dot(_status_dot(card.status))
        ui.label(STATUS_LABEL.get(card.status, card.status))


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def _login_form() -> None:
    with ui.element("div").classes("ops"):
        with ui.element("div").classes("card login"):
            ui.label("Vortex ops").classes("heading-lg")
            ui.label("Solo el equipo. El wall público está en /wall.").classes("body-sm")
            ui.element("div").style("height: 16px")
            password = ui.input(placeholder="contraseña", password=True).props("dense outlined")
            password.classes("w-full")
            status = ui.label("").classes("error")

            def submit() -> None:
                ip = _client_ip()
                if not auth.login_allowed(ip):
                    status.set_text("Demasiados intentos. Esperá 10 minutos.")
                    return
                auth.record_login_attempt(ip)
                if auth.check_password(password.value or ""):
                    app.storage.user["ops"] = True
                    ui.navigate.to("/")
                    return
                status.set_text("No.")

            ui.button("Entrar", on_click=submit).props("unelevated no-caps").classes(
                "button-primary"
            )
            password.on("keydown.enter", submit)


def _logout() -> None:
    app.storage.user.pop("ops", None)
    ui.navigate.to("/")


# ---------------------------------------------------------------------------
# Wall
# ---------------------------------------------------------------------------


def _wall_body(card: CallCard | None, health: dict[str, Any] | None) -> None:
    with ui.element("header").classes("wall-head"):
        ui.label("Clínica Arenal").classes("clinic")
        _status_pill(card)
        ui.element("div").classes("grow")
        ui.label("Vortex · Prosper AI").classes("pill mute")
        _line_pill(health)
        if card:
            ui.label(card.call_id).classes("pill mute mono")

    with ui.element("div").classes("grid3"):
        with ui.element("section").classes("col"):
            ui.label("Transcripción").classes("kicker")
            if not card or not card.turns:
                ui.label("Silencio. Play en /ops o una llamada real.").classes("empty")
            for turn in card.turns if card else []:
                with ui.element("div").classes(f"turn {turn.role}"):
                    ui.label("Paciente" if turn.role == "user" else "Agente").classes("who")
                    ui.label(turn.text).classes("bubble")
                    stamp = _turn_time(card, turn.ts) if card else ""
                    if stamp:
                        ui.label(stamp).classes("caption-sm mono")

        with ui.element("section").classes("col"):
            ui.label("Orquestación").classes("kicker")
            with ui.element("div").classes("terminal-card"):
                with ui.element("div").classes("terminal-traffic-lights"):
                    for _ in range(3):
                        ui.element("i")
                if not card or not card.tools:
                    ui.label("Aún no hay tools.").classes("comment")
                for step in card.tools if card else []:
                    with ui.element("div").classes("step"):
                        _dot(_tool_dot(step.status))
                        with ui.element("div"):
                            ui.label(step.name).classes("name")
                            endpoint = TOOL_ENDPOINTS.get(step.name)
                            if endpoint:
                                ui.label(endpoint).classes("meta")
                            if step.name == "submit_action" and step.args:
                                route = (step.args or {}).get("route", "")
                                ui.label(f"body → /api/v1/submit/{route}").classes("meta")
                                ui.label(_short_json(step.args.get("body"))).classes("meta")
                            elif step.args:
                                ui.label(f"in {_short_json(step.args)}").classes("meta")
                            if step.error:
                                ui.label(f"error {step.error}").classes("meta")
                            if step.result:
                                ui.label(f"out {_short_json(step.result)}").classes("meta")
                        ms = f"{step.ms:.0f} ms" if step.ms is not None else step.status
                        ui.label(ms).classes("ms")

        with ui.element("section").classes("col"):
            ui.label("Ficha").classes("kicker")
            rows = [
                ("Paciente", card.patient_name if card else "—"),
                ("Teléfono", card.from_number if card else "—"),
                ("Médico", card.provider_name if card else "—"),
                ("Hueco", card.slot if card else "—"),
                ("Acción", card.action_kind if card else "—"),
                ("Submit", card.submit_status if card else "—"),
                ("Regla", card.decline_reason if card else "—"),
                ("Duración", _duration(card) if card else "—"),
            ]
            for label, value in rows:
                with ui.element("div").classes("kv"):
                    ui.label(label)
                    ui.label(value or "—").classes("mono")
            status = card.status if card else "ended"
            with ui.element("div").classes("verdict"):
                _dot(_status_dot(status))
                ui.label(STATUS_LABEL.get(status, status))


@ui.page("/wall")
def wall_page() -> None:
    _apply_chrome()
    ui.page_title("Vortex · wall")
    stage = ui.element("div").classes("shell")
    rendered = {"sig": None}

    def redraw() -> None:
        events, health = _load_events()
        cards = build_calls(events)
        card = _feature(cards)
        sig = (repr(events), repr(health))
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        stage.clear()
        with stage:
            _wall_body(card, health)

    redraw()
    ui.timer(0.4, redraw)


@ui.page("/call/{call_id}")
def call_page(call_id: str) -> None:
    """One call, by id — public, same chrome and body as /wall.

    Unlike /wall (always the live/most-recent call), this looks up a specific
    call_id. An id that matches nothing yet renders _wall_body's own empty
    state — that *is* the placeholder, no separate one needed.
    """
    _apply_chrome()
    ui.page_title(f"Vortex · {call_id}")
    stage = ui.element("div").classes("shell")
    rendered = {"sig": None}

    def redraw() -> None:
        events, health = _load_events()
        cards = build_calls(events)
        card = next((c for c in cards if c.call_id == call_id), None)
        sig = (call_id, repr(events), repr(health))
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        stage.clear()
        with stage:
            _wall_body(card, health)

    redraw()
    ui.timer(0.4, redraw)


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------


def _ops_list(cards: list[CallCard], selected_id: str | None, on_pick) -> None:
    if not cards:
        ui.label("No hay llamadas. Play dispara fake_caller contra :7860.").classes("empty")
        return
    for card in cards[:40]:
        classes = "call-row on" if card.call_id == selected_id else "call-row"
        with ui.element("div").classes(classes).on("click", lambda c=card: on_pick(c.call_id)):
            _dot(_status_dot(card.status))
            with ui.element("div"):
                ui.label(card.patient_name or card.from_number or card.call_id).classes("title")
                ui.label(
                    f"{card.action_kind or 'sin acción'} · {len(card.tools)} tools · "
                    f"{_duration(card)}"
                ).classes("sub")
            ui.label(STATUS_LABEL.get(card.status, card.status)).classes("pill mute")


def _replay_items(card: CallCard) -> list[tuple[str, dict[str, Any]]]:
    """Merge each tool.called/submit.sent with its result into one item.

    Turns keep their own kind so the caller can route them to the transcript
    column; everything else stays in chronological order for the trace.
    """
    items: list[tuple[str, dict[str, Any]]] = []
    open_tools: dict[str, dict[str, Any]] = {}
    open_submit: dict[str, Any] | None = None
    for ev in card.events:
        kind = ev.get("kind", "")
        if kind in {"turn.user", "turn.assistant"}:
            items.append(("turn", ev))
        elif kind == "tool.called":
            open_tools[ev.get("tool", "")] = ev
        elif kind in {"tool.returned", "tool.failed"}:
            called = open_tools.pop(ev.get("tool", ""), None)
            items.append(("tool", {"called": called, "result": ev}))
        elif kind == "submit.sent":
            open_submit = ev
        elif kind == "submit.result":
            items.append(("submit", {"sent": open_submit, "result": ev}))
            open_submit = None
        else:
            items.append(("life", ev))
    for ev in open_tools.values():
        items.append(("tool", {"called": ev, "result": None}))
    if open_submit:
        items.append(("submit", {"sent": open_submit, "result": None}))
    return items


def _life_line(card: CallCard, ev: dict[str, Any]) -> None:
    kind = ev.get("kind", "?")
    bits = [kind]
    for key in ("stream_sid", "voice", "clinic", "reason", "why", "key"):
        if ev.get(key):
            bits.append(f"{key}={ev[key]}")
    if kind == "call.ended":
        bits.append(f"frames={ev.get('frames_in', '?')}→{ev.get('frames_out', '?')}")
    if kind == "call.crashed" and ev.get("error"):
        bits.append(str(ev["error"])[:120])
    with ui.element("div").classes("step"):
        _dot("off")
        with ui.element("div"):
            ui.label(" ".join(bits)).classes("meta")
        ui.label(_turn_time(card, ev.get("ts"))).classes("ms")


def _ops_detail(card: CallCard | None) -> None:
    if card is None:
        ui.label("Elegí una llamada.").classes("empty")
        return
    ui.label(f"{card.call_id} · {_duration(card)} · {card.status}").classes("detail-id")
    ui.label(card.patient_name or "Sin identificar").classes("detail-name")
    with ui.element("div").classes("replay-grid"):
        with ui.element("section").classes("col"):
            ui.label("Transcripción").classes("kicker")
            if not card.turns:
                ui.label("Sin turnos.").classes("empty")
            for turn in card.turns:
                with ui.element("div").classes(f"turn {turn.role}"):
                    ui.label("Paciente" if turn.role == "user" else "Agente").classes("who")
                    ui.label(turn.text).classes("bubble")
                    stamp = _turn_time(card, turn.ts)
                    if stamp:
                        ui.label(stamp).classes("caption-sm mono")

        with ui.element("section").classes("col"):
            ui.label("Orquestación").classes("kicker")
            with ui.element("div").classes("terminal-card"):
                seen = False
                for kind, item in _replay_items(card):
                    if kind == "turn":
                        continue
                    seen = True
                    if kind == "tool":
                        _ops_tool_step(card, item)
                    elif kind == "submit":
                        _ops_submit_step(card, item)
                    else:
                        _life_line(card, item)
                if not seen:
                    ui.label("Aún no hay tools.").classes("comment")

        with ui.element("section").classes("col"):
            ui.label("Ficha").classes("kicker")
            rows = [
                ("Paciente", card.patient_name),
                ("Teléfono", card.from_number),
                ("Médico", card.provider_name),
                ("Hueco", card.slot),
                ("Acción", card.action_kind),
                ("Submit", card.submit_status),
                ("Regla", card.decline_reason),
                ("Duración", _duration(card)),
            ]
            for label, value in rows:
                with ui.element("div").classes("kv"):
                    ui.label(label)
                    ui.label(value or "—").classes("mono")
            with ui.element("div").classes("verdict"):
                _dot(_status_dot(card.status))
                ui.label(STATUS_LABEL.get(card.status, card.status))


def _ops_tool_step(card: CallCard, item: dict[str, Any]) -> None:
    called, res = item["called"], item["result"]
    name = (called or res or {}).get("tool", "tool")
    status = (
        "ok"
        if res and res.get("kind") == "tool.returned"
        else ("bad" if res else "running")
    )
    args = (called or {}).get("args")
    result = (res or {}).get("result")
    with ui.element("div").classes("step"):
        _dot(_tool_dot(status))
        with ui.element("div"):
            ui.label(name).classes("name")
            endpoint = TOOL_ENDPOINTS.get(name)
            if endpoint:
                ui.label(endpoint).classes("meta")
            if args:
                ui.label(f"in {_short_json(args, 220)}").classes("meta")
            if result is not None:
                ui.label(f"out {_short_json(result, 220)}").classes("meta")
            if res and res.get("error"):
                ui.label(f"error {res['error']}").classes("meta")
            if args or result is not None:
                payload = _json_block({"in": args, "out": result})
                with ui.expansion("json").props("dense").classes("caption-sm"):
                    ui.html(f"<pre class='mono caption-sm'>{payload}</pre>")
        ms = res.get("ms") if res else None
        stamp = _turn_time(card, (res or called or {}).get("ts"))
        ui.label(f"{ms:.0f} ms" if ms is not None else stamp or status).classes("ms")


def _ops_submit_step(card: CallCard, item: dict[str, Any]) -> None:
    sent, res = item["sent"], item["result"]
    route = (sent or res or {}).get("route", "")
    data = (res or {}).get("result")
    data = data if isinstance(data, dict) else {}
    status = data.get("status") or ("running" if res is None else str(data or ""))
    with ui.element("div").classes("step"):
        _dot("ok" if status == "submitted" else "warn" if status == "dry_run" else "bad")
        with ui.element("div"):
            ui.label(f"submit → /api/v1/submit/{route}").classes("name")
            if res:
                http_status = data.get("http_status")
                detail = data.get("detail", "")
                ui.label(
                    f"{status}"
                    + (f" · http {http_status}" if http_status else "")
                    + (f" · {detail}" if detail else "")
                ).classes("meta")
            payload = (sent or res or {}).get("payload")
            if payload is not None:
                with ui.expansion("body").props("dense").classes("caption-sm"):
                    ui.html(f"<pre class='mono caption-sm'>{_json_block(payload)}</pre>")
        ui.label(_turn_time(card, (res or sent or {}).get("ts"))).classes("ms")


def _nav(active: str) -> ui.element:
    """The team nav. Returns the right-hand slot for page controls."""
    with ui.element("nav").classes("primary-nav"):
        ui.link("Vortex", "/").classes("brand")
        for label, path in NAV_LINKS:
            ui.link(label, path).classes("pill" if path == active else "nav-mute")
        ui.element("div").classes("grow")
        slot = ui.element("div").classes("row")
    return slot


@ui.page("/")
def ops_page() -> None:
    _apply_chrome()
    ui.page_title("Vortex · ops")
    if not _ops_ok():
        _login_form()
        return
    selected = {"id": None}
    name_box = {"value": "joaquin"}

    slot = _nav("/")
    with slot:
        line_pill = ui.element("div")
        name = ui.input(placeholder="tu nombre", value="joaquin").props("dense outlined")
        name.classes("mono").style("width:11rem")
        ui.button("Play", on_click=_play_line).props("unelevated no-caps").classes("button-primary")
        ui.button("Replay book", on_click=lambda: _replay("book")).props("outline no-caps").classes(
            "button-secondary"
        )
        ui.button("Replay refuse", on_click=lambda: _replay("refuse")).props(
            "outline no-caps"
        ).classes("button-secondary")
        ui.button("Salir", on_click=_logout).props("flat no-caps").classes("button-quiet")

    with ui.element("div").classes("ops"):
        people = ui.label().classes("presence")
        with ui.element("div").classes("ops-grid"):
            left = ui.element("div").classes("card card-compact")
            right = ui.element("div").classes("card card-compact")

    rendered = {"sig": None}

    def pick(call_id: str) -> None:
        selected["id"] = call_id
        redraw()

    def redraw() -> None:
        name_box["value"] = name.value or "joaquin"
        _beat(name_box["value"])
        events, health = _load_events()
        cards = build_calls(events)
        if selected["id"] is None and cards:
            selected["id"] = cards[0].call_id
        card = next((c for c in cards if c.call_id == selected["id"]), cards[0] if cards else None)
        sig = (selected["id"], repr(events), repr(health))
        if sig == rendered["sig"]:
            return
        rendered["sig"] = sig
        line_pill.clear()
        with line_pill:
            _line_pill(health, detail=True)
        names = _prune_presence()
        people.set_text("en sala · " + (" · ".join(names) if names else "nadie"))
        left.clear()
        with left:
            ui.label("Llamadas").classes("kicker")
            _ops_list(cards, selected["id"], pick)
        right.clear()
        with right:
            ui.label("Detalle").classes("kicker")
            _ops_detail(card)

    redraw()
    ui.timer(0.45, redraw)


def _private_stub(path: str, title: str, body: str) -> None:
    _apply_chrome()
    ui.page_title(f"Vortex · {title}")
    if not _ops_ok():
        _login_form()
        return
    _nav(path)
    with ui.element("div").classes("ops"):
        with ui.element("div").classes("card"):
            ui.label(title).classes("heading-lg")
            ui.label(body).classes("body-md")


@ui.page("/evals")
def evals_page() -> None:
    _private_stub(
        "/evals",
        "Evals",
        "Aquí van los casos del leaderboard cuando la plataforma abra el run. Privado del equipo.",
    )


@ui.page("/bench")
def bench_page() -> None:
    _private_stub(
        "/bench",
        "Bench",
        "Métricas de STT/LLM/TTS y tasa de submit. Se llena cuando line/ empiece a marcar timings.",
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


if __name__ in {"__main__", "__mp_main__"}:
    main()
