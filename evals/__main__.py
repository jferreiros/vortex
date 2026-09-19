"""``python -m evals`` — the one entry point.

    python -m evals logic                 # layer 1, seconds, no keys
    python -m evals conversation          # layer 2, scripted callers, no keys (rules brain)
    python -m evals conversation --brain openai --repeat 3   # the real model, pass^3
    python -m evals voice                 # layer 3, fake provider unless --real
    python -m evals corpus                # layer 4, the organisers' own 73 cases
    python -m evals corpus --judge-log logs/calls.jsonl   # score real practice calls
    python -m evals voice --real --max-eur 1.00
    python -m evals bench                 # layer 5, every candidate model, one matrix
    python -m evals bench --models helmcode/qwen3.6,helmcode/deepseek-v4-flash --repeat 3
    python -m evals publish               # push the latest runs to the bench-results branch
    python -m evals ci                    # layers 1 + 2, report, exit 1 on failure
    python -m evals report                # rebuild summary.md / report.html
    python -m evals accept [layer]        # promote latest run(s) to the baseline

Every run writes evals/results/<layer>/latest.json and refreshes
evals/results/summary.md and report.html.
"""

from __future__ import annotations

import argparse
import json
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


def cmd_corpus(args: argparse.Namespace) -> int:
    from evals.corpus.runner import run_sync

    if args.coverage:
        from evals.corpus.coverage import print_report

        print_report()
        return 0
    run = run_sync(
        only=args.only,
        judge_log=args.judge_log,
        case_id=args.case,
        verify_roster=args.verify_roster,
        results_dir=args.results_dir,
    )
    return _finish(run, args.results_dir)


def cmd_replay(args: argparse.Namespace) -> int:
    from evals.common.replay import BudgetExceeded, render_score, run_sync

    try:
        run = run_sync(
            only=args.only,
            model=args.model,
            concurrency=args.concurrency,
            max_eur=args.max_eur,
            max_turns=args.turns,
            results_dir=args.results_dir,
        )
    except (BudgetExceeded, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2
    save_run(run, args.results_dir)
    mode = ", ".join(f"{k}={v}" for k, v in run.mode.items() if not isinstance(v, (list, dict)))
    print(f"[{run.layer}] {mode} · {_dur(run.duration_ms)}")
    for note in run.notes:
        print(f"  note: {note}")
    print()
    print(render_score(run.summary["score"]))
    print()
    failed = [c for c in run.cases if c.status in ("fail", "error")]
    if failed:
        print(f"{len(failed)} case(s) did not pass; the closest accepted answer:")
        for c in failed[:12]:
            print(f"  {c.status:5s} {c.id}")
            for d in c.details[:3]:
                print(f"        {d}")
        if len(failed) > 12:
            print(f"        ... and {len(failed) - 12} more (evals/results/replay/latest.json)")
    return 0


def cmd_ci(args: argparse.Namespace) -> int:
    from evals.conversation.runner import run_sync as run_conversation
    from evals.corpus.runner import run_sync as run_corpus
    from evals.logic.runner import run_sync as run_logic

    logic = run_logic(results_dir=args.results_dir)
    save_run(logic, args.results_dir)
    conv = run_conversation(brain=args.brain, results_dir=args.results_dir)
    save_run(conv, args.results_dir)
    corpus = run_corpus(results_dir=args.results_dir)
    save_run(corpus, args.results_dir)
    md, page = write_reports(args.results_dir)
    for run in (logic, conv, corpus):
        _print_summary(run)
    print(f"report: {md}  ·  {page}")
    runs = (logic, conv, corpus)
    failed = any(r.verdict == "FAIL" for r in runs)
    if args.strict and any(r.verdict == "UNVERIFIED" for r in runs):
        failed = True
    return 1 if failed else 0


def cmd_bench(args: argparse.Namespace) -> int:
    from evals.bench.runner import BudgetExceeded, run_sync

    try:
        run = run_sync(
            models=args.models.split(",") if args.models else None,
            only=args.only,
            repeat=args.repeat,
            max_eur=args.max_eur,
            concurrency=args.concurrency,
            include_paid=args.include_paid,
            record=args.record,
            results_dir=args.results_dir,
        )
    except BudgetExceeded as exc:
        print(f"refused: {exc}")
        return 2
    save_run(run, args.results_dir)
    md, page = write_reports(args.results_dir)
    _print_summary(run)
    from evals.common.report import bench_table

    print()
    print(bench_table(run))
    routing = run.summary.get("routing", {})
    for role, rec in (routing.get("recommended") or {}).items():
        current = (routing.get("current") or {}).get(role, "?")
        mark = "→ change" if rec["id"] != current else "= keep"
        print(f"{role:13s} now {current}  bench says {rec['id']}  {mark}: {rec['reason']}")
    print(f"report: {md}  ·  {page}")
    # A bench with failing models is a result, not a failure of the bench.
    return 0 if any(b.get("status") == "ran" for b in run.summary.get("models", [])) else 1


def cmd_publish(args: argparse.Namespace) -> int:
    from evals.bench.publish import publish

    outcome = publish(
        results_dir=args.results_dir,
        branch=args.branch,
        remote=args.remote,
        layers=args.layers.split(",") if args.layers else None,
        dry_run=args.dry_run,
        message=args.message,
    )
    for line in outcome.lines:
        print(line)
    return 0 if outcome.ok else 1


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


def cmd_discord(args: argparse.Namespace) -> int:
    from evals.common.discord_msg import load_summary, pr_comment, webhook_body

    if args.bench:
        from evals.common.discord_msg import bench_webhook_body
        from evals.common.results import load_latest

        run = load_latest("bench", args.results_dir)
        if run is None:
            raise FileNotFoundError("no bench run yet; run `python -m evals bench` first")
        print(json.dumps(bench_webhook_body(run, page=args.page), ensure_ascii=False))
        return 0
    summary = load_summary(args.results_dir)
    if args.pr:
        print(pr_comment(summary))
        return 0
    print(json.dumps(webhook_body(summary), ensure_ascii=False))
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

    p = sub.add_parser("corpus", help="layer 4: the published roster and its documented surface")
    p.add_argument("--only", help="substring filter on case or probe ids")
    p.add_argument("--judge-log", type=Path, default=None, help="score the calls in this JSONL log")
    p.add_argument(
        "--case",
        default=None,
        help="the public case every call in the log dialled, when the number cannot say",
    )
    p.add_argument(
        "--coverage", action="store_true", help="print the points-at-stake table and exit"
    )
    p.add_argument(
        "--verify-roster",
        action="store_true",
        help="check every published answer against the clinic snapshot",
    )
    p.set_defaults(fn=cmd_corpus)

    p = sub.add_parser("replay", help="the official cases through the agent, on the real snapshot")
    p.add_argument("--only", help="substring filter on case ids or problem ids")
    p.add_argument("--model", default=None, help="provider/model id; default: the deployed one")
    p.add_argument("--concurrency", type=int, default=12, help="cases in flight")
    p.add_argument("--max-eur", type=float, default=1.0, help="refuse a run estimated above this")
    p.add_argument("--turns", type=int, default=24, help="caller turns per case before hang-up")
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("bench", help="layer 5: every candidate model on the same scenarios")
    p.add_argument("--models", default=None, help="comma-separated provider/model ids")
    p.add_argument("--only", help="substring filter on scenario ids")
    p.add_argument("--repeat", type=int, default=1, help="runs per scenario; reports pass^k")
    p.add_argument("--max-eur", type=float, default=1.0, help="refuse a run estimated above this")
    p.add_argument("--concurrency", type=int, default=3, help="scenarios in flight per model")
    p.add_argument("--include-paid", action="store_true", help="also the prepaid-credit models")
    p.add_argument("--record", action="store_true", help="save model answers as cassettes")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("publish", help="push the latest run(s) to the results branch")
    p.add_argument("--branch", default="bench-results")
    p.add_argument("--remote", default="origin")
    p.add_argument(
        "--layers", default=None, help="comma-separated; default: every layer with a run"
    )
    p.add_argument("--message", default=None, help="commit message")
    p.add_argument("--dry-run", action="store_true", help="build the commit, do not push")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("ci", help="layers 1 + 2 + 4, report, exit 1 on any failure")
    p.add_argument("--brain", default="auto")
    p.add_argument("--strict", action="store_true", help="also fail on unverified")
    p.set_defaults(fn=cmd_ci)

    p = sub.add_parser("report", help="rebuild the summary from the latest runs")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("accept", help="promote the latest run(s) to the baseline")
    p.add_argument("layer", nargs="?", choices=LAYERS)
    p.set_defaults(fn=cmd_accept)

    p = sub.add_parser("discord", help="JSON embed (or --pr markdown) from the latest summary")
    p.add_argument("--pr", action="store_true", help="print the GitHub PR comment instead")
    p.add_argument("--bench", action="store_true", help="the bench embed from the latest bench run")
    p.add_argument("--page", default=None, help="URL the bench embed links to")
    p.set_defaults(fn=cmd_discord)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
