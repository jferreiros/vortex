"""Push docs/tasks.json to GitHub issues, labels and milestones.

The board at docs/tasks.html reads the same file, so the page and the issues
never disagree. Run it after you edit a task:

    make tasks                  # create what is missing, update what changed
    make tasks ARGS=--dry-run   # print the plan, touch nothing

Matching is by the ``[T14]`` prefix in the issue title, so the script is safe to
run twice. It never closes an issue and never changes an assignee: who took a
task is decided in GitHub, not here.

Needs the ``gh`` CLI, logged in with write access to the repo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "docs" / "tasks.json"

LANE_COLOURS = {
    "linea": "2457C5",
    "conv": "8B3FA8",
    "ident": "178A5E",
    "agenda": "C4760F",
    "reglas": "C7304F",
    "todos": "4E5966",
}
KIND_COLOURS = {"infra": "7A8592", "demo": "9A4B0B", "reto": "D3D9E0"}
# Each wave's milestone closes at its checkpoint. HackSpain 2026 is 18-20 Sep.
WAVE_DUE = {
    "w0": "2026-09-19T04:00:00Z",
    "w1": "2026-09-19T08:00:00Z",
    "w2": "2026-09-19T08:00:00Z",
    "w3": "2026-09-19T08:00:00Z",
    "w4": "2026-09-19T21:00:00Z",
    "w5": "2026-09-20T04:00:00Z",
    "w6": "2026-09-19T21:00:00Z",
}


def gh(*args: str, check: bool = True) -> str:
    """Run gh and return stdout. Raises with gh's own message on failure."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}\n{proc.stderr.strip()}")
    return proc.stdout


def api(path: str, method: str = "GET", **fields: Any) -> Any:
    args = ["api", "-X", method, path]
    for key, value in fields.items():
        args += ["-f", f"{key}={value}"]
    out = gh(*args)
    return json.loads(out) if out.strip() else None


def paged(path: str) -> list[dict[str, Any]]:
    """Every page of a list endpoint, flattened."""
    out = gh("api", "--paginate", "--slurp", path)
    return [item for page in json.loads(out or "[]") for item in page]


def wave_title(wave: dict[str, Any]) -> str:
    """The milestone title for a wave. Unique: three waves share a label."""
    return f"{wave['label']} · {wave['title']}"


def ensure_labels(repo: str, data: dict[str, Any], dry: bool) -> None:
    existing = {label["name"] for label in paged(f"repos/{repo}/labels?per_page=100")}
    wanted: list[tuple[str, str, str]] = []
    for key, lane in data["lanes"].items():
        wanted.append(
            (lane["name"], LANE_COLOURS[key], f"Carril {lane['name']} — {lane['folder']}")
        )
    wanted.append(
        ("infra", KIND_COLOURS["infra"], "Fontanería. No puntúa sola, lo desbloquea todo")
    )
    wanted.append(("demo", KIND_COLOURS["demo"], "Para el jurado del domingo"))
    for name, colour, description in wanted:
        if name in existing:
            continue
        print(f"  label + {name}")
        if not dry:
            api(f"repos/{repo}/labels", "POST", name=name, color=colour, description=description)


def ensure_milestones(repo: str, data: dict[str, Any], dry: bool) -> dict[str, int]:
    existing = {
        milestone["title"]: milestone["number"]
        for milestone in paged(f"repos/{repo}/milestones?state=all&per_page=100")
    }
    numbers: dict[str, int] = {}
    for wave in data["waves"]:
        title = wave_title(wave)
        if title in existing:
            numbers[wave["id"]] = existing[title]
            continue
        print(f"  milestone + {title}")
        if dry:
            continue
        created = api(
            f"repos/{repo}/milestones",
            "POST",
            title=title,
            description=f"{wave['deadline']} — {wave['goal']}",
            due_on=WAVE_DUE[wave["id"]],
        )
        numbers[wave["id"]] = created["number"]
    return numbers


def body_for(task: dict[str, Any], data: dict[str, Any], numbers: dict[str, int]) -> str:
    lane = data["lanes"][task["lane"]]
    wave = next(w for w in data["waves"] if w["id"] == task["wave"])
    # Bare "#3" would link to issue 3, so problem numbers stay unprefixed.
    problems = ", ".join(str(p) for p in task["problems"]) or "—"
    if task["weight"]:
        # weight is per case; a Run All dials four private cases per problem.
        at_stake = task["weight"] * data.get("cases_per_run", 4)
        problems += f" · peso {task['weight']}, hasta {at_stake} pts por corrida"
    blocked = ", ".join(f"#{numbers[dep]}" if dep in numbers else dep for dep in task["blocked_by"])
    files = " · ".join(f"`{f}`" for f in task["files"]) or "—"

    return "\n".join(
        [
            f"**Terminado cuando** {task['done']}",
            "",
            f"**Por qué** {task['why']}",
            "",
            "| | |",
            "| --- | --- |",
            f"| Carril | {lane['name']} — `{lane['folder']}` |",
            f"| Bloque | {wave['label']} · {wave['title']} — {wave['deadline']} |",
            f"| Retos | {problems} |",
            f"| Tamaño | {task['size']} |",
            f"| Espera a | {blocked or '—'} |",
            f"| Archivos | {files} |",
            "",
            "Se coge asignándote esta issue. Una a la vez.",
            "",
            f"[Tablero]({data['board_url']}) · fuente `docs/tasks.json`, "
            "edítala ahí y lanza `make tasks`.",
        ]
    )


def sync(repo: str, dry: bool) -> int:
    data = json.loads(TASKS.read_text(encoding="utf-8"))
    print(f"{len(data['tasks'])} tareas · {repo}" + (" · DRY RUN" if dry else ""))

    ensure_labels(repo, data, dry)
    milestones = ensure_milestones(repo, data, dry)

    issues = paged(f"repos/{repo}/issues?state=all&per_page=100")
    by_task: dict[str, dict[str, Any]] = {}
    for issue in issues:
        if issue.get("pull_request"):
            continue
        title = issue.get("title", "")
        if title.startswith("[") and "]" in title:
            by_task[title[1 : title.index("]")]] = issue

    numbers = {task_id: issue["number"] for task_id, issue in by_task.items()}
    created = updated = unchanged = 0

    for task in data["tasks"]:
        wave = next(w for w in data["waves"] if w["id"] == task["wave"])
        title = f"[{task['id']}] {task['title']}"
        labels = [data["lanes"][task["lane"]]["name"]]
        if task["kind"] in ("infra", "demo"):
            labels.append(task["kind"])
        body = body_for(task, data, numbers)
        issue = by_task.get(task["id"])

        if issue is None:
            print(f"  + {title}")
            created += 1
            if dry:
                continue
            args = [
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                title,
                "--body",
                body,
                "--milestone",
                wave_title(wave),
            ]
            for label in labels:
                args += ["--label", label]
            url = gh(*args).strip()
            numbers[task["id"]] = int(url.rstrip("/").rsplit("/", 1)[-1])
            continue

        same_title = issue["title"] == title
        same_body = (issue.get("body") or "").strip() == body.strip()
        same_labels = {lab["name"] for lab in issue.get("labels", [])} >= set(labels)
        if same_title and same_body and same_labels:
            unchanged += 1
            continue

        print(f"  ~ {title}")
        updated += 1
        if dry:
            continue
        args = [
            "issue",
            "edit",
            str(issue["number"]),
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
        ]
        for label in labels:
            args += ["--add-label", label]
        if task["wave"] in milestones:
            args += ["--milestone", wave_title(wave)]
        gh(*args)

    print(f"\ncreadas {created} · actualizadas {updated} · sin cambios {unchanged}")
    print(f"Tablero: {data['board_url']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="owner/name; defaults to docs/tasks.json")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = parser.parse_args()
    repo = args.repo or json.loads(TASKS.read_text(encoding="utf-8"))["repo"]
    try:
        return sync(repo, args.dry_run)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
