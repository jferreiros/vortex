#!/usr/bin/env bash
# Block vortex deploys while Prosper has an active scored run (kills in-flight calls).
# Used by vortex-deploy-run.sh and deploy-both.sh. --force skips the wait.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

active_run() {
  python3 "$ROOT/scripts/prosper-team-stats.py" --dump /tmp/prosper-deploy-guard.json >/dev/null 2>&1 || return 1
  python3 -c 'import json; print(json.load(open("/tmp/prosper-deploy-guard.json"))["eligibility"]["active_run"])' 2>/dev/null
}

if [[ "$FORCE" -eq 1 ]]; then
  exit 0
fi

# Up to 45 min — a private Run All can take a while
for _ in $(seq 1 90); do
  active="$(active_run || echo unknown)"
  if [[ "$active" == "False" || "$active" == "false" ]]; then
    echo "deploy-guard: no active Prosper run"
    exit 0
  fi
  if [[ "$active" == "unknown" ]]; then
    echo "deploy-guard: could not read Prosper status — allowing deploy" >&2
    exit 0
  fi
  echo "deploy-guard: Prosper active_run=true — delaying deploy 30s (pass --force to skip)"
  sleep 30
done
echo "deploy-guard: still active after 45m — refusing deploy" >&2
exit 3
