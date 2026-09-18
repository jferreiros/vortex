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
if [[ $# -lt 1 ]]; then
  echo "usage: $0 <message>" >&2
  exit 1
fi
export DISCORD_WEBHOOK_URL
python3 -c '
import json, os, sys, urllib.request
url = os.environ["DISCORD_WEBHOOK_URL"]
body = sys.argv[1][:1900]
req = urllib.request.Request(
    url,
    data=json.dumps({"username": "Vortex", "content": body}).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "vortex-hackspain"},
    method="POST",
)
urllib.request.urlopen(req, timeout=15)
' "$1"
