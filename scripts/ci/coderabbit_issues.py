"""Turn CodeRabbit's major findings into GitHub issues, one issue per finding.

The CLI writes its review to stdout. This reads that text, pulls out every
``major`` or ``critical`` finding, and opens an issue for each one that does
not already have it. It never closes an issue and never touches an assignee.

An issue is matched by its title, which carries the file, the line and the
headline. Running this twice on the same review therefore creates nothing the
second time.

    python scripts/ci/coderabbit_issues.py review.txt --pr 72 [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The CLI paints its output and links each finding with an OSC-8 escape.
ANSI = re.compile(r"(?:\x1B|\^)\[[0-9;?]*[A-Za-z]|(?:\x1B|\^)\]8;;[^\x07\a]*(?:\x07|\a|\^G)")
HEAD = re.compile(r"^\s{2}(critical|major|minor)\s+\[([^\]]+)\]\s*$")
# Two shapes, because the workflow strips the colour codes before we read the
# file. With the OSC-8 link intact the path lives in the vscode:// target and
# must be read from the raw line before ANSI strip; once stripped only the
# plain arrow line is left. Match either, link first.
LOC_LINK = re.compile(r"vortex/vortex/(.+?):(\d+)")
LOC_ARROW = re.compile(r"^\s*\u2192\s*(\S+?):(\d+(?:-\d+)?)\s*$")

# A finding against a fragment inside a design note is not a defect in the
# product. Filing those buries the real ones.
SKIP_PREFIXES = ("docs/",)
LABEL = "coderabbit"
WANTED = ("major", "critical")
PAGE_SIZE = 100


def parse(text: str) -> list[dict[str, str]]:
    # Location first from the raw line (OSC-8 URI), then strip for the body.
    raw_lines = text.splitlines()
    out: list[dict[str, str]] = []
    i = 0
    while i < len(raw_lines):
        clean = ANSI.sub("", raw_lines[i])
        head = HEAD.match(clean)
        if not head:
            i += 1
            continue
        severity, category = head.group(1), head.group(2)
        location, body = None, []
        i += 1
        while i < len(raw_lines) and not HEAD.match(ANSI.sub("", raw_lines[i])):
            clean = ANSI.sub("", raw_lines[i])
            if clean.strip().startswith("Review complete"):
                break
            found = LOC_LINK.search(raw_lines[i]) or LOC_ARROW.match(clean)
            if found:
                if location is None:
                    location = f"{found.group(1)}:{found.group(2)}"
            elif clean.strip() and "vscode://" not in clean:
                body.append(clean.strip())
            i += 1
        if severity in WANTED and not (location or "").startswith(SKIP_PREFIXES):
            out.append(
                {
                    "severity": severity,
                    "category": category,
                    "location": location or "?",
                    "title": body[0] if body else "(sin título)",
                    "body": "\n".join(body),
                }
            )
    return dedupe(out)


def dedupe(findings: list[dict[str, str]]) -> list[dict[str, str]]:
    """The CLI repeats a finding when it appears in more than one hunk."""
    seen, out = set(), []
    for f in findings:
        key = (f["location"], f["title"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


class LookupFailed(RuntimeError):
    """The list of filed issues could not be read, so none of it can be trusted."""


def existing_titles(repo: str) -> set[str]:
    """Every labelled title, all pages. A partial answer would file a duplicate."""
    done = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/issues?labels={LABEL}&state=all&per_page={PAGE_SIZE}",
            "--jq",
            '.[] | select(has("pull_request") | not) | .title',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        raise LookupFailed(done.stderr.strip() or f"gh api exited {done.returncode}")
    return {line for line in done.stdout.splitlines() if line.strip()}


def issue_title(f: dict[str, str]) -> str:
    return f"[CR] {f['title'].rstrip('.')} — {f['location']}"[:250]


def issue_body(f: dict[str, str], pr: str) -> str:
    return (
        f"**Hallazgo de CodeRabbit** ({f['severity']} · {f['category']})\n\n"
        f"**Dónde:** `{f['location']}`\n"
        f"**Origen:** PR #{pr}\n\n"
        f"---\n\n{f['body']}\n\n---\n\n"
        f"_Creada automáticamente desde la revisión de CodeRabbit de la PR #{pr}. "
        f"Si es un falso positivo, cierra la issue y di por qué._"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("review", type=Path, help="the CLI output, as saved by the workflow")
    ap.add_argument("--pr", required=True, help="the PR the review came from")
    ap.add_argument("--repo", default="jferreiros/vortex")
    ap.add_argument("--dry-run", action="store_true", help="print, create nothing")
    args = ap.parse_args()

    findings = parse(args.review.read_text(errors="replace"))
    if not findings:
        print("No major findings. Nothing to file.")
        return

    if args.dry_run:
        already: set[str] = set()
    else:
        try:
            already = existing_titles(args.repo)
        except LookupFailed as failure:
            print(f"could not list the issues already filed: {failure}", file=sys.stderr)
            raise SystemExit(1) from failure
    made = 0
    for f in findings:
        title = issue_title(f)
        if title in already:
            print(f"skip (already filed): {title}")
            continue
        if args.dry_run:
            print(f"would create: {title}")
            continue
        out = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                args.repo,
                "--title",
                title,
                "--body",
                issue_body(f, args.pr),
                "--label",
                LABEL,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode:
            print(f"could not create {title}: {out.stderr.strip()}", file=sys.stderr)
        else:
            print(f"created: {out.stdout.strip()}")
            made += 1
    print(f"{len(findings)} major finding(s), {made} new issue(s).")


if __name__ == "__main__":
    main()
