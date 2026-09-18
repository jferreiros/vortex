"""Discord payload for an evals run. Counts and jokes; never prompts or keys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.common.results import RESULTS_DIR

WALL = "https://vortex.203.0.113.20.sslip.io/wall"

# Discord embed colors: red / amber / amber / green.
_COLOUR = {"FAIL": 0xE23D4A, "UNVERIFIED": 0xEAB619, "EMPTY": 0xEAB619, "PASS": 0x3DDC84}

_QUIP = {
    "FAIL": (
        "La clínica ha colgado. No es el WiFi: son los rojos de la tabla. "
        "Hollow = stubs aplaudiéndose. El jurado no pica."
    ),
    "UNVERIFIED": "Corrió, pero no pudo comprobarse. Cassette viejo o caso a medias.",
    "EMPTY": "No corrió ningún caso. Un verde aquí sería de mentira, así que no hay verde.",
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
    # A layer that ran no cases is EMPTY. It must not count as green.
    return "PASS" if any(v == "PASS" for v in verdicts) else "EMPTY"


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


BENCH_PAGE = "https://jferreiros.github.io/vortex/bench.html"

_BENCH_QUIP = {
    "change": "El bench dice que cambiemos de modelo. Discutidlo, no lo copiéis a ciegas.",
    "keep": "El bench confirma el enrutado actual. Hoy el .env tiene razón.",
    "empty": "Ningún modelo corrió. Falta una key.",
}


def _ms(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def bench_webhook_body(run: Any, *, page: str | None = None) -> dict[str, Any]:
    """One embed per bench run: a line per model, then the routing verdict."""
    page = page or BENCH_PAGE
    models = [m for m in (run.summary.get("models") or []) if m.get("status") == "ran"]
    skipped = [m for m in (run.summary.get("models") or []) if m.get("status") != "ran"]
    routing = run.summary.get("routing") or {}
    rec = routing.get("recommended") or {}
    cur = routing.get("current") or {}
    lines = []
    for m in models:
        rate = m["weighted_pass_rate"]
        mark = "🟢" if rate >= 0.8 else ("🟡" if rate >= 0.5 else "🔴")
        cost = m.get("list_cost_per_call_eur")
        cost_txt = "perk" if m.get("perk") else ("n/a" if cost is None else f"{cost:.3f} €/call")
        lines.append(
            f"{mark} **{m['id']}** · {m['pass']}/{m['scenarios']} ({rate * 100:.0f}% pond.) · "
            f"p50 {_ms(m['llm_p50_ms'])} · p95 {_ms(m['llm_p95_ms'])} · {cost_txt}"
        )
    if skipped:
        lines.append("⚪ sin key: " + ", ".join(m["id"] for m in skipped))
    verdict = "empty"
    if rec:
        lines.append("")
        for role, block in rec.items():
            now = cur.get(role, "?")
            if block["id"] != now:
                verdict = "change" if verdict != "change" else verdict
                lines.append(f"**{role}**: ahora `{now}` → bench dice `{block['id']}`")
            else:
                verdict = "keep" if verdict == "empty" else verdict
                lines.append(f"**{role}**: `{now}` se queda")
    sha = (run.git.get("sha") or "?")[:7]
    branch = run.git.get("branch") or "?"
    mode = run.mode or {}
    colour = {"change": 0xEAB619, "keep": 0x3DDC84, "empty": 0xE23D4A}[verdict]
    return {
        "username": "Vortex bench",
        "content": _BENCH_QUIP[verdict],
        "embeds": [
            {
                "title": f"Bench · {len(models)} modelos · {mode.get('scenarios', '?')} escenarios"
                + (f" · pass^{mode['repeat']}" if mode.get("repeat", 1) > 1 else ""),
                "url": page,
                "color": colour,
                "description": "\n".join(lines)[:3900] or "Nada que contar.",
                "footer": {"text": f"{sha} · {branch} · {page}"},
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
