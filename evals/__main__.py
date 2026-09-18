"""``python -m evals`` — the one entry point.

    python -m evals logic                 # layer 1, seconds, no keys
    python -m evals conversation          # layer 2, scripted callers, no keys (rules brain)
    python -m evals conversation --brain openai --repeat 3   # the real model, pass^3
    python -m evals voice                 # layer 3, fake provider unless --real
    python -m evals voice --real --max-eur 1.00
    python -m evals ci                    # layers 1 + 2, report, exit 1 on failure
    python -m evals report                # rebuild summary.md / report.html
    python -m evals accept [layer]        # promote latest run(s) to the baseline

Every run writes evals/results/<layer>/latest.json and refreshes
evals/results/summary.md and report.html.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.common.report import LAYERS, write_reports
from evals.common.results import RESULTS_DIR, RunResult, accept_baseline, save_run


def _dur(ms: int) -> str:
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def _print_summary(run: RunResult) -> None:
    t = run.to_json()["totals"]
    print(
        f"[{run.layer}] {run.verdict}: {run.solid_passes} pass, {t['hollow']} hollow, "
        f"{t['fail']} fail, {t['error']} error, {t['unverified']} unverified, "
        f"{t['skipped']} skipped · {_dur(run.duration_ms)}"
        + (f" · {run.cost_eur:.4f} €" if run.cost_eur else "")
    )
    for note in run.notes:
        print(f"  note: {note}")
    for c in run.cases:
        if c.status in ("fail", "error", "unverified"):
            print(f"  {c.status:10s} {c.id}")
            for d in c.details[:4]:
                print(f"             {d}")


def _finish(run: RunResult, results_dir: Path) -> int:
    save_run(run, results_dir)
    md, page = write_reports(results_dir)
    _print_summary(run)
    print(f"report: {md}  ·  {page}")
    return 0 if run.verdict in ("PASS", "UNVERIFIED") else 1


def cmd_logic(args: argparse.Namespace) -> int:
    from evals.logic.runner import run_sync

    run = run_sync(only=args.only, results_dir=args.results_dir)
    return _finish(run, args.results_dir)


def cmd_conversation(args: argparse.Namespace) -> int:
    from evals.conversation.runner import run_sync

    run = run_sync(
        only=args.only,
        brain=args.brain,
        model=args.model,
        repeat=args.repeat,
        record=args.record,
        results_dir=args.results_dir,
    )
    return _finish(run, args.results_dir)


def cmd_voice(args: argparse.Namespace) -> int:
    from evals.voice.runner import run_sync

    run = run_sync(
        real=args.real,
        stacks=args.stacks,
        max_eur=args.max_eur,
        languages=args.languages,
        results_dir=args.results_dir,
    )
    return _finish(run, args.results_dir)


def cmd_ci(args: argparse.Namespace) -> int:
    from evals.conversation.runner import run_sync as run_conversation
    from evals.logic.runner import run_sync as run_logic

    logic = run_logic(results_dir=args.results_dir)
    save_run(logic, args.results_dir)
    conv = run_conversation(brain=args.brain, results_dir=args.results_dir)
    save_run(conv, args.results_dir)
    md, page = write_reports(args.results_dir)
    _print_summary(logic)
    _print_summary(conv)
    print(f"report: {md}  ·  {page}")
    failed = any(r.verdict == "FAIL" for r in (logic, conv))
    if args.strict and any(r.verdict == "UNVERIFIED" for r in (logic, conv)):
        failed = True
    return 1 if failed else 0


def cmd_report(args: argparse.Namespace) -> int:
    md, page = write_reports(args.results_dir)
    print(md.read_text())
    print(f"report: {md}  ·  {page}")
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    layers = [args.layer] if args.layer else list(LAYERS)
    for layer in layers:
        target = accept_baseline(layer, args.results_dir)
        print(f"{layer}: {'accepted -> ' + str(target) if target else 'no latest run to accept'}")
    write_reports(args.results_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("logic", help="layer 1: tool cases, no voice, no model")
    p.add_argument("--only", help="substring filter on case ids")
    p.set_defaults(fn=cmd_logic)

    p = sub.add_parser("conversation", help="layer 2: scripted callers as text")
    p.add_argument("--only")
    p.add_argument("--brain", default="auto", help="auto | rules | openai | replay")
    p.add_argument("--model", default=None, help="OpenAI model for --brain openai")
    p.add_argument("--repeat", type=int, default=1, help="runs per scenario; reports pass^k")
    p.add_argument("--record", action="store_true", help="save model answers as a cassette")
    p.set_defaults(fn=cmd_conversation)

    p = sub.add_parser("voice", help="layer 3: provider benchmark (spends money with --real)")
    p.add_argument("--real", action="store_true", help="call real providers; needs keys")
    p.add_argument("--stacks", default=None, help="comma-separated stack names from pricing.yaml")
    p.add_argument("--max-eur", type=float, default=0.50, help="refuse a run estimated above this")
    p.add_argument("--languages", default=None, help="comma-separated: es,ca,gl,eu")
    p.set_defaults(fn=cmd_voice)

    p = sub.add_parser("ci", help="layers 1 + 2, report, exit 1 on any failure")
    p.add_argument("--brain", default="auto")
    p.add_argument("--strict", action="store_true", help="also fail on unverified")
    p.set_defaults(fn=cmd_ci)

    p = sub.add_parser("report", help="rebuild the summary from the latest runs")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("accept", help="promote the latest run(s) to the baseline")
    p.add_argument("layer", nargs="?", choices=LAYERS)
    p.set_defaults(fn=cmd_accept)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
