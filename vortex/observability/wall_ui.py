"""NiceGUI rendering for the public jury overview and call placeholder."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

from nicegui import ui

from vortex.observability.wall import (
    PHASE_DESCRIPTIONS,
    Phase,
    WallCall,
    format_duration,
    group_by_phase,
    historical_stats,
)

LANGUAGES = {
    "es": "Castellano",
    "ca": "Catalán",
    "eu": "Euskera",
    "gl": "Gallego",
    "en": "Inglés",
    "fr": "Francés",
    "pt": "Portugués",
}


def call_url(call_id: str) -> str:
    return "/wall/call?" + urlencode({"call_id": call_id})


def _header(line_up: bool) -> None:
    with ui.element("header").classes("top jury-top"):
        ui.link("VORTEX / CLÍNICA ARENAL", "/wall").classes("brand jury-link")
        ui.label("Prosper AI · vista del jurado").classes("jury-muted")
        ui.element("div").style("flex:1")
        with ui.element("div").classes("pill"):
            ui.element("span").classes(f"dot {'up' if line_up else 'down'}")
            ui.label("En directo" if line_up else "Sin conexión · datos del log local")


def _metric(label: str, value: str, detail: str) -> None:
    with ui.element("div").classes("card jury-metric"):
        ui.label(label).classes("kicker")
        ui.label(value).classes("jury-metric-value mono")
        ui.label(detail).classes("jury-muted")


def _distribution(title: str, counts: Mapping[str, int], *, languages: bool = False) -> None:
    with ui.element("section").classes("card"):
        ui.label(title).classes("kicker")
        total = sum(counts.values())
        if not total:
            ui.label("Sin datos todavía").classes("empty")
            return
        for label, count in counts.items():
            display = LANGUAGES.get(label, label) if languages else label
            with ui.element("div").classes("jury-bar-row"):
                with ui.element("div").classes("jury-bar-label"):
                    ui.label(display)
                    ui.label(str(count)).classes("mono")
                ui.linear_progress(value=count / total, show_value=False).props(
                    'color="blue-5" track-color="grey-9"'
                )


def _call_tile(call: WallCall) -> None:
    card = call.card
    with ui.link(target=call_url(card.call_id)).classes("jury-call jury-link"):
        ui.label(card.patient_name or "Paciente por identificar").classes("jury-call-name")
        ui.label(card.call_id).classes("mono jury-call-id")
        with ui.element("div").classes("jury-call-meta"):
            ui.label(format_duration(call.duration_seconds())).classes("mono")
            ui.label(LANGUAGES.get(call.language, call.language or "Idioma sin detectar"))
        if call.phase == Phase.FINISHED:
            ui.label(call.result_label).classes("jury-outcome mono")
            ui.label(f"Submit: {card.submit_status or 'sin envío confirmado'}").classes(
                "jury-muted"
            )
        elif not call.explicit_state:
            ui.label("Estado deducido de eventos").classes("jury-muted")
        if card.voice in {"demo", "stub"} or card.submit_status == "dry_run":
            ui.label("SIMULACIÓN").classes("pill")


def render_dashboard(calls: list[WallCall], line_up: bool) -> None:
    _header(line_up)
    stats = historical_stats(calls)
    groups = group_by_phase(calls)
    with ui.element("main").classes("jury-main"):
        with ui.element("section").classes("jury-hero"):
            with ui.element("div"):
                ui.label("LLAMADAS EN CURSO").classes("kicker")
                ui.label(str(stats.active)).classes("jury-active-count mono")
            with ui.element("div"):
                ui.label("Cada llamada, en su estado actual").classes("jury-title")
                ui.label("Selecciona una tarjeta para abrir el detalle de la llamada.").classes(
                    "jury-muted"
                )
                ui.label(
                    "Estados deducidos de las herramientas salvo estado explícito del orquestador."
                ).classes("jury-muted")
                if not line_up:
                    ui.label(
                        "Sin conexión con Line: el contador refleja el último estado registrado."
                    ).classes("jury-notice")

        with ui.element("section").classes("jury-states"):
            for phase, phase_calls in groups.items():
                with ui.element("section").classes(f"jury-state state-{phase.value.lower()}"):
                    with ui.element("div").classes("jury-state-heading"):
                        ui.label(phase.value).classes("mono")
                        ui.label(str(len(phase_calls))).classes("pill")
                    ui.label(PHASE_DESCRIPTIONS[phase]).classes("jury-state-description")
                    with ui.element("div").classes("jury-state-calls"):
                        if not phase_calls:
                            ui.label("Sin llamadas").classes("jury-state-empty")
                        for call in phase_calls:
                            _call_tile(call)

        with ui.element("section").classes("jury-history"):
            ui.label("ESTADÍSTICAS HISTÓRICAS").classes("jury-title")
            ui.label("Calculadas sobre las llamadas finalizadas del historial disponible.").classes(
                "jury-muted"
            )
            with ui.element("div").classes("jury-metrics"):
                _metric("Finalizadas", str(stats.completed), "Las llamadas activas no se incluyen")
                rate = f"{stats.pass_rate:.0%}" if stats.pass_rate is not None else "—"
                _metric(
                    "Tasa de acierto",
                    rate,
                    f"{stats.passed}/{stats.evaluated} evaluadas · {stats.completed} finalizadas"
                    if stats.evaluated
                    else "Sin veredictos de Prosper registrados",
                )
                _metric(
                    "Duración media", format_duration(stats.average_seconds), "Tiempo de llamada"
                )
                _metric(
                    "Envío aceptado",
                    str(stats.accepted),
                    f"No equivale a acierto · {stats.simulated} llamadas simuladas",
                )
            with ui.element("div").classes("jury-distributions"):
                _distribution("Resultados de las llamadas", stats.outcomes)
                _distribution("Idiomas detectados", stats.languages, languages=True)
                _distribution("Motivos de rechazo / derivación", stats.reasons)
            ui.label(
                "Resultados: acciones aceptadas o simuladas; una llamada puede tener varias. "
                "Los reintentos no duplican el recuento."
            ).classes("jury-muted")


def render_call_placeholder(call_id: str, call: WallCall | None, line_up: bool) -> None:
    _header(line_up)
    with ui.element("main").classes("jury-main"):
        ui.link("← Volver a las llamadas", "/wall").classes("jury-link jury-back")
        ui.label("Detalle de llamada").classes("jury-title")
        ui.label(call_id).classes("mono jury-detail-id")
        if call is None:
            ui.label(
                "Todavía no hay eventos para esta llamada en el historial disponible."
            ).classes("jury-notice")
        else:
            with ui.element("div").classes("jury-metrics"):
                _metric("Estado actual", call.phase.value, PHASE_DESCRIPTIONS[call.phase])
                _metric("Paciente", call.card.patient_name or "Por identificar", call.card.call_id)
                _metric(
                    "Duración",
                    format_duration(call.duration_seconds()),
                    "Finalizada" if call.card.ended else "En curso según el registro",
                )
                _metric(
                    "Resultado",
                    call.result_label if call.card.ended else "Pendiente",
                    f"Submit: {call.card.submit_status or 'pendiente'}",
                )
        with ui.element("section").classes("jury-placeholder"):
            ui.icon("graphic_eq", size="56px").classes("jury-muted")
            ui.label("Vista de la llamada en directo").classes("jury-title")
            ui.label("PLACEHOLDER").classes("pill")
            ui.label(
                "Aquí se integrarán la transcripción en tiempo real, "
                "la ficha del paciente y la actividad del agente."
            ).classes("jury-muted")
