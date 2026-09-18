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
import json
import re
import subprocess
import sys
from pathlib import Path

# The CLI paints its output and links each finding with an OSC-8 escape.
ANSI = re.compile(r"(?:\x1B|\^)\[[0-9;?]*[A-Za-z]|(?:\x1B|\^)\]8;;[^\x07\a]*(?:\x07|\a|\^G)")
HEAD = re.compile(r"^\s{2}(critical|major|minor)\s+\[([^\]]+)\]\s*$")
# The link holds the only unescaped copy of the path: .../vortex/vortex/<path>:<line>
LOC = re.compile(r"vortex/vortex/(.+?):(\d+)")
LABEL = "coderabbit"
WANTED = ("major", "critical")


def parse(text: str) -> list[dict[str, str]]:
    lines = ANSI.sub("", text).splitlines()
    out: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        head = HEAD.match(lines[i])
        if not head:
            i += 1
            continue
        severity, category = head.group(1), head.group(2)
        location, body = None, []
        i += 1
        while i < len(lines) and not HEAD.match(lines[i]):
            if lines[i].strip().startswith("Review complete"):
                break
            found = LOC.search(lines[i])
            if found and location is None:
                location = f"{found.group(1)}:{found.group(2)}"
            elif lines[i].strip() and "vscode://" not in lines[i]:
                body.append(lines[i].strip())
            i += 1
        if severity in WANTED:
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


def existing_titles(repo: str) -> set[str]:
    raw = (
        subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                repo,
                "--label",
                LABEL,
                "--state",
                "all",
                "--limit",
                "200",
                "--json",
                "title",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        or "[]"
    )
    return {i["title"] for i in json.loads(raw)}


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

    already = set() if args.dry_run else existing_titles(args.repo)
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
