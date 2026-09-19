#!/usr/bin/env bash
# Thin wrapper — real logic in prosper-run-all.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/prosper-run-all.py" "$@"
