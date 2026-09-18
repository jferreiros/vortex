"""The live view: ``/`` for the team, ``/wall`` for the jury.

Every screen follows DESIGN.md. ``design.css`` carries the tokens and the
components; ``board.css`` adds the Quasar overrides and the two layouts.
Add a class from those files before you add an inline style here.
"""

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
                            detail = step.error or _json_preview(step.result or step.args)
                            if detail:
                                ui.label(detail).classes("meta")
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

    def redraw() -> None:
        events, health = _load_events()
        cards = build_calls(events)
        stage.clear()
        with stage:
            _wall_body(_feature(cards), health)

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
                ui.label(f"{card.action_kind or 'sin acción'} · {len(card.tools)} tools").classes(
                    "sub"
                )
            ui.label(STATUS_LABEL.get(card.status, card.status)).classes("pill mute")


def _ops_detail(card: CallCard | None) -> None:
    if card is None:
        ui.label("Elegí una llamada.").classes("empty")
        return
    ui.label(card.call_id).classes("detail-id")
    ui.label(card.patient_name or "Sin identificar").classes("detail-name")
    for turn in card.turns:
        with ui.element("div").classes("detail-turn"):
            ui.html(f"<b>{'Paciente' if turn.role == 'user' else 'Agente'}</b>")
            ui.label(turn.text)
    ui.separator().style("margin:16px 0")
    for step in card.tools:
        with ui.element("div").classes("detail-tool row"):
            _dot(_tool_dot(step.status))
            ui.label(step.name)


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
