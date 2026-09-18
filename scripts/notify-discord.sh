#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${DISCORD_WEBHOOK_URL:-}" && -f "$ROOT/.env" ]]; then
  DISCORD_WEBHOOK_URL="$(python3 -c '
from pathlib import Path
import sys
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith("DISCORD_WEBHOOK_URL=") and "https://" in line:
        print(line.split("=", 1)[1].strip().strip("\"'\''"))
        break
' "$ROOT/.env")"
  export DISCORD_WEBHOOK_URL
fi
if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "DISCORD_WEBHOOK_URL is not set" >&2
  exit 1
fi

mode="text"
if [[ "${1:-}" == "--evals" ]]; then
  mode="evals"
  shift
elif [[ "${1:-}" == "--json" ]]; then
  mode="json"
  shift
fi

export DISCORD_WEBHOOK_URL
export ROOT
export MODE="$mode"
export TEXT="${1:-}"

python3 -c '
import json, os, subprocess, sys, urllib.request
from pathlib import Path

url = os.environ["DISCORD_WEBHOOK_URL"]
mode = os.environ["MODE"]
root = Path(os.environ["ROOT"])
if mode == "evals":
    payload = json.loads(
        subprocess.check_output(
            ["uv", "run", "python", "-m", "evals", "discord"],
            cwd=root,
        )
    )
elif mode == "json":
    payload = json.loads(sys.stdin.read())
else:
    text = os.environ.get("TEXT") or ""
    if not text:
        sys.stderr.write("usage: notify-discord.sh [--evals | --json | <message>]\n")
        sys.exit(2)
    payload = {"username": "Vortex", "content": text[:1900]}

req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "vortex-hackspain"},
    method="POST",
)
urllib.request.urlopen(req, timeout=15)
'
