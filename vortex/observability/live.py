from __future__ import annotations

import asyncio
import os
import sys
import time
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
CSS = (Path(__file__).with_name("board.css")).read_text(encoding="utf-8")

STATUS_PILL = {
    "live": "live",
    "booked": "booked",
    "registered": "registered",
    "rescheduled": "rescheduled",
    "cancelled": "cancelled",
    "refused": "refused",
    "escalated": "escalated",
    "ended": "ended",
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


def _login_form() -> None:
    with ui.element("div").classes("ops"):
        with ui.element("div").classes("card").style("max-width:360px;margin:12vh auto"):
            ui.label("Vortex ops").classes("brand")
            ui.label("Solo el equipo. El wall público está en /wall.").classes("empty")
            password = ui.input(placeholder="contraseña", password=True).props(
                "dense dark outlined"
            )
            status = ui.label("").style("color:var(--bad);font-size:12px;margin-top:8px")

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

            ui.button("Entrar", on_click=submit).props("unelevated color=primary")
            password.on("keydown.enter", submit)


def _logout() -> None:
    app.storage.user.pop("ops", None)
    ui.navigate.to("/")


def _apply_chrome() -> None:
    ui.dark_mode(True)
    ui.add_css(CSS)
    ui.query("body").classes("shell")


def _status_class(status: str) -> str:
    if status == "live":
        return "live"
    if status in {"booked", "registered", "rescheduled", "cancelled"}:
        return "ok"
    if status in {"refused", "escalated"}:
        return "warn"
    return ""


def _tool_dot(status: str) -> str:
    if status == "running":
        return "live"
    if status == "ok":
        return "up"
    return "down"


def _json_preview(value: Any, limit: int = 88) -> str:
    text = "" if value is None else str(value)
    if isinstance(value, dict):
        keys = ", ".join(f"{k}" for k in list(value)[:4])
        text = keys or "{}"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _wall_body(card: CallCard | None, line_up: bool) -> None:
    with ui.element("div").classes("top"):
        ui.label("Clínica Arenal").classes("brand")
        if card and card.live:
            with ui.element("div").classes("pill live"):
                ui.element("span").classes("dot live")
                ui.label("En llamada")
        elif card:
            with ui.element("div").classes(f"pill {STATUS_PILL.get(card.status, 'ended')}"):
                ui.element("span").classes(f"dot {_tool_dot('ok')}")
                ui.label(card.status)
        else:
            with ui.element("div").classes("pill"):
                ui.element("span").classes("dot down")
                ui.label("En espera")
        ui.label("Vortex · Prosper AI").classes("pill")
        ui.element("div").style("flex:1")
        with ui.element("div").classes("pill"):
            ui.element("span").classes(f"dot {'up' if line_up else 'down'}")
            ui.label("line up" if line_up else "line down")
        if card:
            ui.label(card.call_id).classes("pill mono")

    with ui.element("div").classes("grid3"):
        with ui.element("div").classes("col"):
            ui.label("Transcripción").classes("kicker")
            if not card or not card.turns:
                ui.label("Silencio. Play en /ops o una llamada real.").classes("empty")
            for turn in card.turns if card else []:
                with ui.element("div").classes(f"turn {turn.role}"):
                    ui.label("Paciente" if turn.role == "user" else "Agente").classes("who")
                    ui.label(turn.text).classes("bubble")

        with ui.element("div").classes("col"):
            ui.label("Orquestación").classes("kicker")
            if not card or not card.tools:
                ui.label("Aún no hay tools.").classes("empty")
            for step in card.tools if card else []:
                with ui.element("div").classes("step"):
                    ui.element("span").classes(f"dot {_tool_dot(step.status)}")
                    with ui.element("div"):
                        ui.label(step.name).classes("name mono")
                        detail = step.error or _json_preview(step.result or step.args)
                        if detail:
                            ui.label(detail).classes("meta mono")
                    ms = f"{step.ms:.0f} ms" if step.ms is not None else step.status
                    ui.label(ms).classes("mono").style("color: var(--muted); font-size: 11px")

        with ui.element("div").classes("col"):
            ui.label("Ficha").classes("kicker")
            rows = [
                ("Paciente", card.patient_name if card else "—"),
                ("Teléfono", card.from_number if card else "—"),
                ("Médico", card.provider_name if card else "—"),
                ("Hueco", card.slot if card else "—"),
                ("Acción", card.action_kind if card else "—"),
                ("Submit", card.submit_status if card else "—"),
                ("Regla", card.decline_reason if card else "—"),
            ]
            for label, value in rows:
                with ui.element("div").classes("chart-row"):
                    ui.label(label)
                    ui.label(value or "—").classes("mono")
            status = card.status if card else "ended"
            ui.label(status.replace("-", " ")).classes(f"verdict {_status_class(status)}")


def _ops_list(cards: list[CallCard], selected_id: str | None, on_pick) -> None:
    if not cards:
        ui.label("No hay llamadas. Play dispara fake_caller contra :7860.").classes("empty")
        return
    for card in cards[:40]:
        classes = "call-row on" if card.call_id == selected_id else "call-row"
        with ui.element("div").classes(classes).on("click", lambda c=card: on_pick(c.call_id)):
            ui.element("span").classes(f"dot {_tool_dot('running' if card.live else 'ok')}")
            with ui.element("div"):
                ui.label(card.patient_name or card.from_number or card.call_id).style(
                    "font-weight:600;font-size:13px"
                )
                ui.label(f"{card.action_kind or 'sin acción'} · {len(card.tools)} tools").classes(
                    "mono"
                ).style("color:var(--muted);font-size:11px")
            ui.label(card.status).classes(f"pill {STATUS_PILL.get(card.status, 'ended')}")


def _ops_detail(card: CallCard | None) -> None:
    if card is None:
        ui.label("Elegí una llamada.").classes("empty")
        return
    ui.label(card.call_id).classes("mono").style("font-size:12px;color:var(--muted)")
    ui.label(card.patient_name or "Sin identificar").style(
        "font-size:22px;font-weight:700;margin:6px 0 12px"
    )
    for turn in card.turns:
        who = "PACIENTE" if turn.role == "user" else "AGENTE"
        ui.label(f"{who}  {turn.text}").style("font-size:13px;margin:6px 0;line-height:1.4")
    ui.separator().style("margin:12px 0;background:var(--line)")
    for step in card.tools:
        flag = {"running": "…", "ok": "ok", "fail": "fail"}[step.status]
        ui.label(f"{flag}  {step.name}").classes("mono").style("font-size:12px;margin:4px 0")


@ui.page("/wall")
def wall_page() -> None:
    _apply_chrome()
    ui.page_title("Vortex · wall")
    stage = ui.element("div").classes("shell")

    def redraw() -> None:
        events, health = _load_events()
        cards = build_calls(events)
        stage.clear()
        with stage:
            _wall_body(_feature(cards), health is not None)

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

    def redraw() -> None:
        events, health = _load_events()
        cards = build_calls(events)
        card = next((c for c in cards if c.call_id == call_id), None)
        stage.clear()
        with stage:
            _wall_body(card, health is not None)

    redraw()
    ui.timer(0.4, redraw)


@ui.page("/")
def ops_page() -> None:
    _apply_chrome()
    ui.page_title("Vortex · ops")
    if not _ops_ok():
        _login_form()
        return
    selected = {"id": None}
    name_box = {"value": "joaquin"}

    with ui.element("div").classes("top"):
        ui.link("OPS", "/").classes("brand").style("text-decoration:none;color:inherit")
        ui.link("WALL", "/wall").classes("pill").style("text-decoration:none")
        ui.link("EVALS", "/evals").classes("pill").style("text-decoration:none")
        ui.link("BENCH", "/bench").classes("pill").style("text-decoration:none")
        line_pill = ui.element("div").classes("pill")
        ui.element("div").style("flex:1")
        name = ui.input(placeholder="tu nombre", value="joaquin").props("dense dark outlined")
        name.classes("mono")
        name.style("width:11rem")
        ui.button("Play", on_click=_play_line).props("unelevated color=primary")
        ui.button("Replay book", on_click=lambda: _replay("book")).props("outline")
        ui.button("Replay refuse", on_click=lambda: _replay("refuse")).props("outline")
        ui.button("Salir", on_click=_logout).props("flat")

    with ui.element("div").classes("ops"):
        people = (
            ui.label().classes("mono").style("color:var(--muted);font-size:12px;margin-bottom:12px")
        )
        with ui.element("div").classes("ops-grid"):
            left = ui.element("div").classes("card")
            right = ui.element("div").classes("card")

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
        line_up = health is not None
        line_pill.clear()
        with line_pill:
            mode = ""
            if health:
                mode = f" · {health.get('voice')}/{health.get('clinic')}"
            ui.element("span").classes(f"dot {'up' if line_up else 'down'}")
            ui.label(("line up" + mode) if line_up else "line down · JSONL")
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


def _private_stub(title: str, body: str) -> None:
    _apply_chrome()
    ui.page_title(f"Vortex · {title}")
    if not _ops_ok():
        _login_form()
        return
    with ui.element("div").classes("top"):
        ui.link("OPS", "/").classes("brand").style("text-decoration:none;color:inherit")
        ui.link("WALL", "/wall").classes("pill").style("text-decoration:none")
        ui.link("EVALS", "/evals").classes("pill").style("text-decoration:none")
        ui.link("BENCH", "/bench").classes("pill").style("text-decoration:none")
    with ui.element("div").classes("ops"):
        with ui.element("div").classes("card"):
            ui.label(title).classes("brand")
            ui.label(body).classes("empty")


@ui.page("/evals")
def evals_page() -> None:
    _private_stub(
        "Evals",
        "Aquí van los casos del leaderboard cuando la plataforma abra el run. Privado del equipo.",
    )


@ui.page("/bench")
def bench_page() -> None:
    _private_stub(
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
        dark=True,
        reload=False,
        show=False,
        favicon="◈",
        storage_secret=auth.storage_secret(),
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
