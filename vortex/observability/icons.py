"""Ink icons for the console. Sixteen pixels, currentColor, no hue."""

from __future__ import annotations

from nicegui import ui

#: Stroke paths, viewBox 0 0 24 24. Keys are the nav and workflow names.
PATHS: dict[str, str] = {
    "mark": "M12 3l9 9-9 9-9-9z",
    "overview": "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    "agents": (
        "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"
        "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8"
        "M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"
    ),
    "calls": ("M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM10 18h4"),
    "live": "M12 12h.01M8.5 8.5a5 5 0 0 1 7 0M5.5 5.5a9 9 0 0 1 13 0",
    "patients": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM6 21a6 6 0 0 1 12 0",
    "insights": "M4 20V10M10 20V4M16 20v-7M22 20H2",
    "settings": "M4 7h16M4 17h16M8 5v4M16 15v4",
    "wall": "M3 5h18v14H3zM3 9h18",
    "patient": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM6 21a6 6 0 0 1 12 0",
    "agent": "M12 3v3M12 18v3M3 12h3M18 12h3M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    "tool": "M12 3l9 5v8l-9 5-9-5V8zM12 12l9-5M12 12v10M12 12L3 7",
    "submit": "M7 17L17 7M10 7h7v7",
    "start": "M12 7v5M8 12h8M9 16v3M15 16v3",
}

NAV: dict[str, str] = {
    "/": "overview",
    "/agents": "agents",
    "/calls": "calls",
    "/calls/live": "live",
    "/patients": "patients",
    "/insights": "insights",
    "/settings": "settings",
}


def icon(name: str) -> None:
    path = PATHS[name]
    svg = ui.element("svg").classes("icon")
    svg._props["viewBox"] = "0 0 24 24"
    svg._props["aria-hidden"] = "true"
    with svg:
        node = ui.element("path")
        node._props["d"] = path
