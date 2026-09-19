#!/usr/bin/env python3
"""Login to Prosper dashboard and POST Run All. Creds from vortex .env."""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_CANDIDATES = [
    ROOT / ".env",
    Path("/home/factory/.config/vortex/prosper-dashboard.env"),
]
DEFAULT_TEAM = "fcafdedd-29b6-4961-91f8-21da7844f73f"
DEFAULT_ENDPOINT = "wss://line.203.0.113.20.sslip.io/ws"


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in ENV_CANDIDATES:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.startswith("PROSPER_") or key == "PLATFORM_API_BASE_URL":
                out[key] = value.strip().strip('"').strip("'")
    return out


def notify(text: str) -> None:
    script = ROOT / "scripts" / "notify-discord.sh"
    if script.is_file():
        os.spawnl(os.P_WAIT, "/bin/bash", "bash", str(script), text)


class Prosper:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/leaderboard"
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base}{path}", data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(req, timeout=60) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:500]
            raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def main() -> int:
    env = load_env()
    email = env.get("PROSPER_DASHBOARD_EMAIL")
    password = env.get("PROSPER_DASHBOARD_PASSWORD")
    base = env.get("PLATFORM_API_BASE_URL", "https://hackspain.getprosperapp.com")
    team_id = env.get("PROSPER_TEAM_ID", DEFAULT_TEAM)
    endpoint = env.get("PROSPER_ENDPOINT", DEFAULT_ENDPOINT)
    assert email and password, "missing PROSPER_DASHBOARD_EMAIL/PASSWORD"

    api = Prosper(base)
    print("Signing in…", flush=True)
    session = api.request("POST", "/api/session", {"email": email, "password": password})
    assert session.get("viewer", {}).get("team_id"), session
    print("team", session["viewer"]["team_id"], flush=True)

    team = api.request("GET", f"/api/teams/{team_id}")
    current = (team.get("integration") or {}).get("endpoint") or ""
    if current != endpoint:
        print(f"Setting endpoint → {endpoint} (was: {current})", flush=True)
        api.request("PUT", "/api/endpoint", {"endpoint": endpoint})

    deadline = time.time() + 3600
    while time.time() < deadline:
        team = api.request("GET", f"/api/teams/{team_id}")
        el = team["eligibility"]
        if not el.get("active_run"):
            wait = int(el.get("private_wait") or 0)
            if wait > 0:
                print(f"private_wait={wait}s — sleeping…", flush=True)
                time.sleep(min(wait + 5, 120))
                continue
            break
        print("active_run=true — waiting 30s…", flush=True)
        time.sleep(30)
    else:
        notify("Run All blocked: active_run still true after 1h")
        return 1

    print("POST /api/runs (Run All)…", flush=True)
    run = None
    for attempt in range(12):
        try:
            run = api.request("POST", "/api/runs", {})
            break
        except RuntimeError as exc:
            msg = str(exc)
            if "429" in msg or "cooldown" in msg.lower():
                team = api.request("GET", f"/api/teams/{team_id}")
                wait = int(team["eligibility"].get("private_wait") or 60)
                print(f"cooldown 429 — sleep {wait}s (attempt {attempt + 1})", flush=True)
                notify(f"Run All cooldown · wait {wait}s")
                time.sleep(min(max(wait, 30), 300))
                continue
            raise
    if run is None:
        notify("Run All failed: cooldown never cleared")
        return 1
    run_id = run.get("run_id") or ""
    assert run_id, run
    print(json.dumps(run), flush=True)
    notify(f"Prosper **Run All** queued · `{run_id}` · endpoint `{endpoint}`")

    settle_deadline = time.time() + 5400
    while time.time() < settle_deadline:
        team = api.request("GET", f"/api/teams/{team_id}")
        Path("/tmp/prosper-team-latest.json").write_text(json.dumps(team, indent=2))
        stats = team["stats"]
        active = team["eligibility"]["active_run"]
        latest = (team.get("runs") or [{}])[0]
        print(
            f"best={stats.get('best_points')} rank={stats.get('rank')} "
            f"active={active} latest_state={latest.get('state')}",
            flush=True,
        )
        if not active:
            best = stats.get("best_points")
            Path("/tmp/prosper-best-points.txt").write_text(str(best))
            Path("/tmp/prosper-team-latest.json").write_text(json.dumps(team, indent=2))
            notify(
                f"Run All **settled** · best **{best}** pts · "
                f"rank **{stats.get('rank')}** · last state `{latest.get('state')}` · `{run_id}`"
            )
            print(f"SETTLED best={best} rank={stats.get('rank')}")
            return 0
        time.sleep(45)

    notify(f"Run All still active after 90m · `{run_id}` — check dashboard")
    return 1


if __name__ == "__main__":
    sys.exit(main())
