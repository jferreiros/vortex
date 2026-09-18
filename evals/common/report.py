"""The report: a markdown summary for CI and one HTML page for a screen.

Both are built from the latest run of every layer plus the diff against the
previous run and the accepted baseline. The page has to be readable in ten
seconds: verdict first, then what broke, then what got fixed, then the table.
"""

from __future__ import annotations

import functools
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.common.results import (
    BASELINES_DIR,
    RESULTS_DIR,
    Diff,
    RunResult,
    diff_runs,
    load_baseline,
    load_latest,
    load_previous,
)

LAYERS = ("logic", "conversation", "voice", "corpus")
LAYER_TITLES = {
    "logic": "Layer 1 · Logic (tools, no voice)",
    "conversation": "Layer 2 · Conversation (scripted callers, text)",
    "voice": "Layer 3 · Voice providers (latency, WER, cost)",
}

BADGE = {
    "pass": "🟢",
    "fail": "🔴",
    "error": "💥",
    "unverified": "🟡",
    "skipped": "⚪",
}


def _dur(ms: int) -> str:
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def _by_group(run: RunResult) -> list[tuple[str, int, int, int, int]]:
    """(group, solid passes, hollow, fail+error, other) per group, in case order."""
    order: list[str] = []
    rows: dict[str, list[int]] = {}
    for c in run.cases:
        g = c.group or "-"
        if g not in rows:
            order.append(g)
            rows[g] = [0, 0, 0, 0]
        if c.status == "pass" and c.hollow:
            rows[g][1] += 1
        elif c.status == "pass":
            rows[g][0] += 1
        elif c.status in ("fail", "error"):
            rows[g][2] += 1
        else:
            rows[g][3] += 1
    return [(g, *rows[g]) for g in order]


def _verdict_label(run: RunResult) -> str:
    return f"{run.verdict} · simulated" if run.summary.get("simulated") else run.verdict


def _wer(stack: dict[str, Any], key: str) -> str:
    v = (stack.get("wer") or {}).get(key)
    return "n/a" if v is None else f"{v * 100:.0f}%"


def _fmt_eur(value: float) -> str:
    return f"{value:.4f} €" if value < 0.01 else f"{value:.2f} €"


def _stamp(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def collect(
    results_dir: Path = RESULTS_DIR, baselines_dir: Path = BASELINES_DIR
) -> list[tuple[RunResult, Diff, Diff]]:
    out = []
    for layer in LAYERS:
        run = load_latest(layer, results_dir)
        if run is None:
            continue
        prev = diff_runs(run, load_previous(layer, results_dir), "previous")
        base = diff_runs(run, load_baseline(layer, baselines_dir), "baseline")
        out.append((run, prev, base))
    return out


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _md_diff(diff: Diff) -> list[str]:
    if not diff.reference_at:
        return [f"- vs {diff.against}: no reference yet"]
    if diff.empty:
        return [f"- vs {diff.against} ({_stamp(diff.reference_at)}): no change"]
    lines = [f"- vs {diff.against} ({_stamp(diff.reference_at)}):"]
    if diff.broke:
        lines.append(
            f"  - 🔴 broke ({len(diff.broke)}): " + ", ".join(f"`{i}`" for i in diff.broke)
        )
    if diff.fixed:
        lines.append(
            f"  - 🟢 fixed ({len(diff.fixed)}): " + ", ".join(f"`{i}`" for i in diff.fixed)
        )
    other = [c for c in diff.changed if c[0] not in diff.broke and c[0] not in diff.fixed]
    if other:
        lines.append(
            f"  - changed ({len(other)}): " + ", ".join(f"`{i}` {b} → {a}" for i, b, a in other)
        )
    if diff.new:
        lines.append(f"  - new ({len(diff.new)}): " + ", ".join(f"`{i}`" for i in diff.new))
    if diff.gone:
        lines.append(f"  - gone ({len(diff.gone)}): " + ", ".join(f"`{i}`" for i in diff.gone))
    return lines


def _md_layer(run: RunResult, prev: Diff, base: Diff) -> list[str]:
    t = run.to_json()["totals"]
    lines = [
        f"## {LAYER_TITLES.get(run.layer, run.layer)} — **{_verdict_label(run)}**",
        "",
        f"{_stamp(run.started_at)} · commit `{run.git.get('sha', '?')}`"
        + (" (dirty)" if run.git.get("dirty") == "yes" else "")
        + f" · {_dur(run.duration_ms)}"
        + (f" · cost {_fmt_eur(run.cost_eur)}" if run.cost_eur else ""),
        "",
        "| pass | hollow | fail | error | unverified | skipped |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {run.solid_passes} | {t['hollow']} | {t['fail']} | {t['error']} "
        f"| {t['unverified']} | {t['skipped']} |",
        "",
    ]
    mode_bits = [f"{k}={v}" for k, v in run.mode.items() if not isinstance(v, (list, dict))]
    if mode_bits:
        lines.append("Mode: " + ", ".join(mode_bits))
        lines.append("")
    for note in run.notes:
        lines.append(f"> {note}")
    if run.notes:
        lines.append("")
    lines.extend(_md_diff(prev))
    lines.extend(_md_diff(base))
    lines.append("")
    groups = _by_group(run)
    if len(groups) > 1 and run.layer != "voice":
        lines.append("| group | pass | hollow | fail | other |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for g, ok, hol, bad, other in groups:
            lines.append(f"| {g} | {ok} | {hol} | {bad} | {other} |")
        lines.append("")
    if run.layer == "voice" and run.summary.get("stacks"):
        lines.extend(_md_voice_table(run))
        lines.append("")
    failing = [c for c in run.cases if c.status in ("fail", "error")]
    if failing:
        lines.append("### What failed")
        lines.append("")
        for c in failing:
            head = f"- {BADGE[c.status]} `{c.id}`"
            if c.problem:
                head += f" (problem {c.problem})"
            lines.append(head)
            for d in c.details[:6]:
                lines.append(f"  - {d}")
        lines.append("")
    lines.append("<details><summary>All cases</summary>")
    lines.append("")
    lines.append("| | case | problem | ms | note |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for c in run.cases:
        badge = BADGE[c.status] + ("◌" if c.hollow and c.status == "pass" else "")
        note = c.details[0] if c.details else ""
        lines.append(
            f"| {badge} | `{c.id}` | {c.problem or ''} | {c.duration_ms} | {_md_escape(note)} |"
        )
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return lines


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")[:160]


def _md_voice_table(run: RunResult) -> list[str]:
    stacks = run.summary["stacks"]
    lines = [
        "| stack | e2e p50 | e2e p95 | STT final p50 | LLM TTFT p50 | TTS TTFB p50 "
        "| WER es | WER ca | WER gl | WER eu | WER noisy | €/call | € / 68 calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
        "| ---: |",
    ]
    for s in stacks:
        w = functools.partial(_wer, s)
        lines.append(
            f"| {s['name']} | {s['e2e_p50_ms']:.0f} ms | {s['e2e_p95_ms']:.0f} ms "
            f"| {s['stt_p50_ms']:.0f} ms | {s['llm_ttft_p50_ms']:.0f} ms "
            f"| {s['tts_ttfb_p50_ms']:.0f} ms "
            f"| {w('es')} | {w('ca')} | {w('gl')} | {w('eu')} | {w('noisy')} "
            f"| {s['cost_per_call_eur']:.3f} | {s['cost_68_calls_eur']:.2f} |"
        )
    if run.summary.get("simulated"):
        lines.append("")
        lines.append(
            "> **SIMULATED.** These numbers come from the fake provider. "
            "They prove the benchmark runs; they say nothing about real vendors."
        )
    return lines


def render_markdown(sections: list[tuple[RunResult, Diff, Diff]]) -> str:
    if not sections:
        return "# Vortex evals\n\nNo runs yet. `make evals` produces the first one.\n"
    overall = "PASS"
    for run, _, _ in sections:
        if run.verdict == "FAIL":
            overall = "FAIL"
        elif run.verdict == "UNVERIFIED" and overall == "PASS":
            overall = "UNVERIFIED"
    lines = [f"# Vortex evals — **{overall}**", ""]
    lines.append("| layer | verdict | pass | hollow | fail | error | unverified | broke | fixed |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for run, prev, _ in sections:
        t = run.to_json()["totals"]
        lines.append(
            f"| {run.layer} | **{_verdict_label(run)}** | {run.solid_passes} | {t['hollow']} "
            f"| {t['fail']} "
            f"| {t['error']} | {t['unverified']} | {len(prev.broke)} | {len(prev.fixed)} |"
        )
    lines.append("")
    lines.append(
        "hollow = passes only through contract stubs · broke/fixed = against the previous run"
    )
    lines.append("")
    for run, prev, base in sections:
        lines.extend(_md_layer(run, prev, base))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
:root{--bg:#0f1115;--card:#171a21;--fg:#e6e8ee;--mute:#8b93a7;--ok:#3ddc84;--bad:#ff5d5d;
--warn:#ffcc4d;--hollow:#8fd3ff;--line:#262b36;font-family:ui-sans-serif,system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif}
body{margin:0;background:var(--bg);color:var(--fg);font-size:15px}
main{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:34px;margin:0 0 6px}h2{font-size:20px;margin:28px 0 8px}
h3{font-size:15px;color:var(--mute);margin:18px 0 6px;text-transform:uppercase;
letter-spacing:.06em}
.verdict{display:inline-block;padding:4px 14px;border-radius:999px;font-weight:700;font-size:18px}
.PASS{background:rgba(61,220,132,.15);color:var(--ok)}.FAIL{background:rgba(255,93,93,.15);color:var(--bad)}
.UNVERIFIED,.EMPTY{background:rgba(255,204,77,.15);color:var(--warn)}
.sub{color:var(--mute);margin:4px 0 20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
margin:10px 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.card .n{font-size:30px;font-weight:700;line-height:1}
.card .l{color:var(--mute);font-size:12px;margin-top:4px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.hol{color:var(--hollow)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mute);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
code{background:#0b0d11;padding:1px 5px;border-radius:5px;font-size:12px}
.pill{display:inline-block;min-width:54px;text-align:center;border-radius:6px;padding:2px 6px;
font-size:12px;font-weight:700}
.p-pass{background:rgba(61,220,132,.18);color:var(--ok)}.p-fail{background:rgba(255,93,93,.18);color:var(--bad)}
.p-error{background:rgba(255,93,93,.3);color:#ffb3b3}.p-unverified{background:rgba(255,204,77,.18);color:var(--warn)}
.p-skipped{background:#2a2f3a;color:var(--mute)}.p-hollow{background:rgba(143,211,255,.15);color:var(--hollow)}
.note{background:rgba(255,204,77,.08);border-left:3px solid var(--warn);padding:8px 12px;
border-radius:6px;margin:8px 0;color:#f3e2b0}
.diff{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0}
.diff div{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:8px 12px;min-width:200px}
details{margin-top:10px}summary{cursor:pointer;color:var(--mute)}
.detail{color:var(--mute);font-size:12px;white-space:pre-wrap}
"""


def _h(text: Any) -> str:
    return html.escape(str(text))


def _pill(case: Any) -> str:
    cls = f"p-{case.status}"
    label = case.status
    if case.status == "pass" and case.hollow:
        cls, label = "p-hollow", "hollow"
    return f'<span class="pill {cls}">{label}</span>'


def _html_diff(diff: Diff) -> str:
    if not diff.reference_at:
        return (
            f"<div><b>vs {diff.against}</b><br><span class='detail'>no reference yet</span></div>"
        )
    if diff.empty:
        return (
            f"<div><b>vs {diff.against}</b> <span class='detail'>{_stamp(diff.reference_at)}</span>"
            "<br>no change</div>"
        )
    parts = [
        f"<div><b>vs {diff.against}</b> <span class='detail'>{_stamp(diff.reference_at)}</span>"
    ]
    if diff.broke:
        parts.append(
            f"<br><span class='bad'>broke {len(diff.broke)}</span>: "
            + ", ".join(f"<code>{_h(i)}</code>" for i in diff.broke)
        )
    if diff.fixed:
        parts.append(
            f"<br><span class='ok'>fixed {len(diff.fixed)}</span>: "
            + ", ".join(f"<code>{_h(i)}</code>" for i in diff.fixed)
        )
    other = [c for c in diff.changed if c[0] not in diff.broke and c[0] not in diff.fixed]
    if other:
        parts.append(
            "<br>changed: "
            + ", ".join(f"<code>{_h(i)}</code> {_h(b)} → {_h(a)}" for i, b, a in other)
        )
    if diff.new:
        parts.append(f"<br>new {len(diff.new)}")
    if diff.gone:
        parts.append(
            f"<br>gone {len(diff.gone)}: " + ", ".join(f"<code>{_h(i)}</code>" for i in diff.gone)
        )
    parts.append("</div>")
    return "".join(parts)


def _html_groups(run: RunResult) -> str:
    groups = _by_group(run)
    if len(groups) < 2 or run.layer == "voice":
        return ""
    cells = []
    for g, ok, hol, bad, other in groups:
        cells.append(
            f"<div><b>{_h(g)}</b><br><span class='ok'>{ok} pass</span> · "
            f"<span class='hol'>{hol} hollow</span> · <span class='bad'>{bad} fail</span>"
            + (f" · {other} other" if other else "")
            + "</div>"
        )
    return "<h3>By group</h3><div class='diff'>" + "".join(cells) + "</div>"


def _html_voice(run: RunResult) -> str:
    stacks = run.summary.get("stacks", [])
    if not stacks:
        return ""
    head = (
        "<tr><th>stack</th><th>e2e p50</th><th>e2e p95</th><th>STT final</th><th>LLM TTFT</th>"
        "<th>TTS TTFB</th><th>WER es</th><th>WER ca</th><th>WER gl</th><th>WER eu</th>"
        "<th>WER noisy</th><th>€/call</th><th>€/68 calls</th><th>€/weekend*</th></tr>"
    )
    rows = []
    for s in stacks:
        w = functools.partial(_wer, s)
        rows.append(
            f"<tr><td><b>{_h(s['name'])}</b><br>"
            f"<span class='detail'>{_h(s.get('describe', ''))}</span></td>"
            f"<td class='num'>{s['e2e_p50_ms']:.0f} ms</td>"
            f"<td class='num'>{s['e2e_p95_ms']:.0f} ms</td>"
            f"<td class='num'>{s['stt_p50_ms']:.0f} ms</td>"
            f"<td class='num'>{s['llm_ttft_p50_ms']:.0f} ms</td>"
            f"<td class='num'>{s['tts_ttfb_p50_ms']:.0f} ms</td>"
            f"<td class='num'>{w('es')}</td><td class='num'>{w('ca')}</td>"
            f"<td class='num'>{w('gl')}</td>"
            f"<td class='num'>{w('eu')}</td><td class='num'>{w('noisy')}</td>"
            f"<td class='num'>{s['cost_per_call_eur']:.3f}</td>"
            f"<td class='num'>{s['cost_68_calls_eur']:.2f}</td>"
            f"<td class='num'>{s.get('cost_weekend_eur', 0):.2f}</td></tr>"
        )
    foot = (
        "<p class='detail'>* weekend = the run-all count in evals/voice/pricing.yaml "
        "(full 68-call runs plus practice calls). Latencies are per turn: STT final = end of "
        "caller audio → final transcript; e2e = STT final + LLM TTFT + TTS TTFB, the delay the "
        "caller perceives before the agent starts to speak.</p>"
    )
    sim = (
        "<div class='note'><b>SIMULATED.</b> These numbers come from the fake provider. "
        "They prove the benchmark runs end to end; they say nothing about real vendors.</div>"
        if run.summary.get("simulated")
        else ""
    )
    return f"<h3>Provider matrix</h3>{sim}<table>{head}{''.join(rows)}</table>{foot}"


def _html_layer(run: RunResult, prev: Diff, base: Diff) -> str:
    t = run.to_json()["totals"]
    cards = [
        ("ok", run.solid_passes, "pass"),
        ("hol", t["hollow"], "hollow (stub)"),
        ("bad", t["fail"], "fail"),
        ("bad", t["error"], "error"),
        ("warn", t["unverified"], "unverified"),
        ("", t["skipped"], "skipped"),
    ]
    cards_html = "".join(
        f"<div class='card'><div class='n {cls}'>{n}</div><div class='l'>{label}</div></div>"
        for cls, n, label in cards
    )
    notes = "".join(f"<div class='note'>{_h(n)}</div>" for n in run.notes)
    mode = ", ".join(f"{k}={v}" for k, v in run.mode.items() if not isinstance(v, (list, dict)))
    failing = [c for c in run.cases if c.status in ("fail", "error")]
    failing_html = ""
    if failing:
        items = []
        for c in failing:
            det = "<br>".join(_h(d) for d in c.details[:6])
            prob = f" · problem {c.problem}" if c.problem else ""
            items.append(
                f"<tr><td>{_pill(c)}</td><td><code>{_h(c.id)}</code>{prob}</td>"
                f"<td class='detail'>{det}</td></tr>"
            )
        failing_html = "<h3>What failed</h3><table>" + "".join(items) + "</table>"
    rows = []
    for c in run.cases:
        det = _h(c.details[0]) if c.details else ""
        rows.append(
            f"<tr><td>{_pill(c)}</td><td><code>{_h(c.id)}</code></td>"
            f"<td class='num'>{c.problem or ''}</td>"
            f"<td class='num'>{c.duration_ms}</td><td class='detail'>{det}</td></tr>"
        )
    table = (
        "<details><summary>All cases (" + str(len(run.cases)) + ")</summary><table>"
        "<tr><th></th><th>case</th><th>problem</th><th>ms</th><th>note</th></tr>"
        + "".join(rows)
        + "</table></details>"
    )
    cost = f" · cost {_fmt_eur(run.cost_eur)}" if run.cost_eur else ""
    return (
        f"<h2>{_h(LAYER_TITLES.get(run.layer, run.layer))} "
        f"<span class='verdict {run.verdict}'>{_verdict_label(run)}</span></h2>"
        f"<div class='sub'>{_stamp(run.started_at)} · commit "
        f"<code>{_h(run.git.get('sha', '?'))}</code>"
        f"{' (dirty)' if run.git.get('dirty') == 'yes' else ''} · {_dur(run.duration_ms)}{cost}"
        f"{' · ' + _h(mode) if mode else ''}</div>"
        f"<div class='cards'>{cards_html}</div>{notes}"
        f"<div class='diff'>{_html_diff(prev)}{_html_diff(base)}</div>"
        f"{_html_groups(run)}"
        f"{_html_voice(run) if run.layer == 'voice' else ''}"
        f"{failing_html}{table}"
    )


def render_html(sections: list[tuple[RunResult, Diff, Diff]]) -> str:
    if not sections:
        body = "<h1>Vortex evals</h1><p>No runs yet.</p>"
        overall = "EMPTY"
    else:
        overall = "PASS"
        for run, _, _ in sections:
            if run.verdict == "FAIL":
                overall = "FAIL"
            elif run.verdict == "UNVERIFIED" and overall == "PASS":
                overall = "UNVERIFIED"
        latest = max(run.started_at for run, _, _ in sections)
        body = (
            f"<h1>Vortex evals <span class='verdict {overall}'>{overall}</span></h1>"
            f"<div class='sub'>latest run {_stamp(latest)} · "
            "hollow = green only through contract stubs · unverified = could not be checked</div>"
            + "".join(_html_layer(run, prev, base) for run, prev, base in sections)
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Vortex evals — {overall}</title><style>{_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def write_reports(
    results_dir: Path = RESULTS_DIR, baselines_dir: Path = BASELINES_DIR
) -> tuple[Path, Path]:
    sections = collect(results_dir, baselines_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    md = results_dir / "summary.md"
    page = results_dir / "report.html"
    md.write_text(render_markdown(sections))
    page.write_text(render_html(sections))
    (results_dir / "summary.json").write_text(
        json.dumps(
            {
                run.layer: {
                    "verdict": run.verdict,
                    "totals": run.to_json()["totals"],
                    "broke": prev.broke,
                    "fixed": prev.fixed,
                    "started_at": run.started_at,
                    "git": run.git,
                }
                for run, prev, _ in sections
            },
            indent=1,
        )
    )
    return md, page
