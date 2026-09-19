#!/usr/bin/env python3
"""Fetch vortex Prosper team stats (best points, dump JSON)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from importlib.machinery import SourceFileLoader

pra = SourceFileLoader(
    "prosper_run_all", str(ROOT / "scripts" / "prosper-run-all.py")
).load_module()


def team() -> dict:
    env = pra.load_env()
    api = pra.Prosper(env["PLATFORM_API_BASE_URL"])
    api.request(
        "POST",
        "/api/session",
        {
            "email": env["PROSPER_DASHBOARD_EMAIL"],
            "password": env["PROSPER_DASHBOARD_PASSWORD"],
        },
    )
    return api.request("GET", f"/api/teams/{env['PROSPER_TEAM_ID']}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--best", action="store_true")
    p.add_argument("--write", metavar="FILE")
    p.add_argument("--dump", metavar="FILE")
    args = p.parse_args()
    data = team()
    best = float((data.get("stats") or {}).get("best_points") or 0)
    if args.write:
        Path(args.write).write_text(str(best))
    if args.dump:
        Path(args.dump).write_text(json.dumps(data, indent=2))
    if args.best or not (args.write or args.dump):
        print(best)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
