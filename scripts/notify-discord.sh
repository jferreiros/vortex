#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
load_hook() {
  local key="$1"
  python3 -c '
from pathlib import Path
import sys
key, path = sys.argv[1], sys.argv[2]
if not Path(path).is_file():
    raise SystemExit
for line in Path(path).read_text().splitlines():
    if line.startswith(key + "=") and "https://" in line:
        print(line.split("=", 1)[1].strip().strip("\"'\''"))
        break
' "$key" "$ROOT/.env"
}

if [[ -z "${DISCORD_WEBHOOK_URL:-}" && -f "$ROOT/.env" ]]; then
  DISCORD_WEBHOOK_URL="$(load_hook DISCORD_WEBHOOK_URL)"
  export DISCORD_WEBHOOK_URL
fi

mode="text"
if [[ "${1:-}" == "--evals" ]]; then
  mode="evals"
  shift
elif [[ "${1:-}" == "--bench" ]]; then
  mode="bench"
  shift
elif [[ "${1:-}" == "--json" ]]; then
  mode="json"
  shift
elif [[ "${1:-}" == "--calls" ]]; then
  mode="calls"
  shift
fi

if [[ "$mode" == "calls" ]]; then
  if [[ -z "${DISCORD_CALLS_WEBHOOK_URL:-}" && -f "$ROOT/.env" ]]; then
    DISCORD_CALLS_WEBHOOK_URL="$(load_hook DISCORD_CALLS_WEBHOOK_URL)"
  fi
  if [[ -n "${DISCORD_CALLS_WEBHOOK_URL:-}" ]]; then
    DISCORD_WEBHOOK_URL="$DISCORD_CALLS_WEBHOOK_URL"
    export DISCORD_CALLS_WEBHOOK_URL
  fi
  export DISCORD_WEBHOOK_URL
fi

if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "DISCORD_WEBHOOK_URL is not set" >&2
  exit 1
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
if mode in ("evals", "bench"):
    args = ["uv", "run", "python", "-m", "evals", "discord"]
    if mode == "bench":
        args.append("--bench")
    payload = json.loads(subprocess.check_output(args, cwd=root))
elif mode == "calls":
    args = ["uv", "run", "python", "-m", "vortex.observability.discord_calls", "--json"]
    log_path = os.environ.get("TEXT") or ""
    if log_path:
        args.extend(["--log", log_path])
    payload = json.loads(subprocess.check_output(args, cwd=root))
elif mode == "json":
    payload = json.loads(sys.stdin.read())
else:
    text = os.environ.get("TEXT") or ""
    if not text:
        sys.stderr.write("usage: notify-discord.sh [--evals | --bench | --calls | --json | <message>]\n")
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
