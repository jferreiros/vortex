"""Discord payload for an evals run. Counts and jokes; never prompts or keys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.common.results import RESULTS_DIR

WALL = "https://vortex.203.0.113.20.sslip.io/wall"

# Discord embed colors: red / amber / green.
_COLOUR = {"FAIL": 0xE23D4A, "UNVERIFIED": 0xEAB619, "PASS": 0x3DDC84}

_QUIP = {
    "FAIL": (
        "La clínica ha colgado. No es el WiFi: son los rojos de la tabla. "
        "Hollow = stubs aplaudiéndose. El jurado no pica."
    ),
    "UNVERIFIED": "Corrió, pero no pudo comprobarse. Cassette viejo o caso a medias.",
    "PASS": "Hoy sí coge el teléfono. Mira hollow: si no es cero, el verde es de mentira.",
}


def load_summary(results_dir: Path | None = None) -> dict[str, Any]:
    path = (results_dir or RESULTS_DIR) / "summary.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing. Run `make evals` first.")
    return json.loads(path.read_text())


def overall_verdict(summary: dict[str, Any]) -> str:
    verdicts = [str(block.get("verdict") or "EMPTY") for block in summary.values()]
    if any(v == "FAIL" for v in verdicts):
        return "FAIL"
    if any(v == "UNVERIFIED" for v in verdicts):
        return "UNVERIFIED"
    return "PASS" if verdicts else "EMPTY"


def _layer_line(name: str, block: dict[str, Any]) -> str:
    totals = block.get("totals") or {}
    solid = int(totals.get("pass") or 0) - int(totals.get("hollow") or 0)
    fail = int(totals.get("fail") or 0)
    hollow = int(totals.get("hollow") or 0)
    broke = len(block.get("broke") or [])
    fixed = len(block.get("fixed") or [])
    mark = {"PASS": "🟢", "FAIL": "🔴", "UNVERIFIED": "🟡"}.get(block.get("verdict"), "⚪")
    delta = ""
    if broke or fixed:
        delta = f" · 💔{broke} 💚{fixed}"
    return (
        f"{mark} **{name}** `{block.get('verdict')}` · "
        f"{solid} sólidos · {hollow} huecos · {fail} fail{delta}"
    )


def webhook_body(summary: dict[str, Any], *, wall: str = WALL) -> dict[str, Any]:
    """One embed the team can read in two seconds."""
    verdict = overall_verdict(summary)
    layers = []
    git = {}
    for name, block in summary.items():
        if not isinstance(block, dict):
            continue
        layers.append(_layer_line(name, block))
        git = block.get("git") or git
    sha = (git.get("sha") or "?")[:7]
    branch = git.get("branch") or "?"
    description = "\n".join(layers) if layers else "No hay capas en el summary."
    return {
        "username": "Vortex evals",
        "content": _QUIP.get(verdict, _QUIP["FAIL"]),
        "embeds": [
            {
                "title": f"Evals {verdict}",
                "url": wall,
                "color": _COLOUR.get(verdict, _COLOUR["FAIL"]),
                "description": description[:3900],
                "footer": {"text": f"{sha} · {branch} · muro {wall}"},
            }
        ],
    }


def pr_comment(summary: dict[str, Any]) -> str:
    """Markdown for the GitHub PR. Marker lets CI update in place."""
    verdict = overall_verdict(summary)
    lines = [
        "<!-- vortex-evals -->",
        f"## Evals — **{verdict}**",
        "",
        _QUIP.get(verdict, ""),
        "",
        "| layer | verdict | solid | hollow | fail | broke | fixed |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, block in summary.items():
        if not isinstance(block, dict):
            continue
        totals = block.get("totals") or {}
        solid = int(totals.get("pass") or 0) - int(totals.get("hollow") or 0)
        lines.append(
            f"| {name} | **{block.get('verdict')}** | {solid} | {totals.get('hollow', 0)} "
            f"| {totals.get('fail', 0)} | {len(block.get('broke') or [])} "
            f"| {len(block.get('fixed') or [])} |"
        )
    lines += [
        "",
        "hollow = pasó solo por `contract.stub_*`. broke/fixed = contra el run anterior.",
        "Esto no bloquea el merge (`gate` sigue siendo tests).",
        "Artefacto `evals-report` tiene el HTML.",
        "",
    ]
    return "\n".join(lines)
