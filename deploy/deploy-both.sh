#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
STATE_FILE="${VORTEX_DEPLOY_STATE:-/home/factory/personal/vortex-deploy.state}"
LOCK_FILE="${VORTEX_DEPLOY_LOCK:-/tmp/vortex-deploy.lock}"
PUBLIC_LINE="${VORTEX_PUBLIC_LINE:-wss://line.167.233.80.47.sslip.io/ws}"
PUBLIC_WALL="${VORTEX_PUBLIC_WALL:-https://vortex.167.233.80.47.sslip.io/wall}"

FORCE=0
for arg in "$@"; do
  case "${arg}" in
    --force) FORCE=1 ;;
    -h|--help)
      printf '%s\n' "deploy/deploy-both.sh [--force]"
      exit 0
      ;;
    *)
      printf 'unknown option %s\n' "${arg}" >&2
      exit 2
      ;;
  esac
done

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "another deploy is already running"
  exit 0
fi

cd "${REPO_ROOT}"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "REFUSE: working tree has tracked changes" >&2
  git status --porcelain --untracked-files=no >&2
  exit 2
fi

git fetch origin --prune
git checkout --quiet main
WANT="$(git rev-parse origin/main)"
HAVE="$(git rev-parse HEAD)"
LAST=""
if [[ -f "${STATE_FILE}" ]]; then
  LAST="$(tr -d '[:space:]' < "${STATE_FILE}")"
fi

if [[ "${FORCE}" -eq 0 && "${HAVE}" == "${WANT}" && "${LAST}" == "${WANT}" ]]; then
  exit 0
fi

if [[ "${HAVE}" != "${WANT}" ]]; then
  git pull --ff-only origin main
fi

# Do not rebuild/restart while Prosper is mid-run (kills in-flight scored calls).
if [[ "${FORCE}" -eq 0 ]]; then
  if ! "${REPO_ROOT}/scripts/prosper-deploy-guard.sh"; then
    echo "REFUSE: Prosper active_run — leaving previous image up; retry next tick" >&2
    exit 0
  fi
fi

SUBJECT="$(git log -1 --pretty=%s)"
SHA="$(git rev-parse --short HEAD)"
PR=""
if [[ "${SUBJECT}" =~ Merge\ pull\ request\ #([0-9]+) ]]; then
  PR="${BASH_REMATCH[1]}"
fi

notify() {
  local text="$1"
  local url=""
  local env_file
  for env_file in "${SCRIPT_DIR}/.env" "${REPO_ROOT}/.env"; do
    if [[ -f "${env_file}" ]]; then
      url="$(python3 -c '
from pathlib import Path
import sys
preferred = None
fallback = None
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith("DISCORD_UPDATES_WEBHOOK_URL=") and "https://" in line:
        preferred = line.split("=", 1)[1].strip().strip("\"'\''")
    elif line.startswith("DISCORD_WEBHOOK_URL=") and "https://" in line:
        fallback = line.split("=", 1)[1].strip().strip("\"'\''")
print(preferred or fallback or "")
' "${env_file}")"
      if [[ -n "${url}" ]]; then
        break
      fi
    fi
  done
  if [[ -z "${url}" ]]; then
    echo "no Discord webhook; skip notify" >&2
    return 0
  fi
  DISCORD_WEBHOOK_URL="${url}" "${REPO_ROOT}/scripts/notify-discord.sh" "${text}" || echo "Discord notify failed" >&2
}

what=""
if [[ -n "${PR}" ]]; then
  what="el PR ${PR}"
else
  what="${SUBJECT}"
fi

if ! "${SCRIPT_DIR}/deploy.sh" --skip-pull; then
  notify "El servidor no pudo publicar ${what}. Sigue la versión de antes. Hay que mirarlo."
  exit 1
fi

if ! docker compose -f "${SCRIPT_DIR}/compose.yml" up -d --build; then
  notify "La línea ya está, pero la consola no pudo publicarse (${what}). Hay que mirarlo."
  exit 1
fi

HEALTH=""
for _ in $(seq 1 30); do
  HEALTH="$(docker inspect -f '{{.State.Health.Status}}' vortex-board 2>/dev/null || echo missing)"
  [[ "${HEALTH}" == healthy ]] && break
  sleep 2
done
if [[ "${HEALTH}" != healthy ]]; then
  notify "La línea ya está, pero la consola no arrancó (${what}). Hay que mirarlo."
  exit 1
fi

CODE="$(curl -sS -L -m 15 -o /dev/null -w '%{http_code}' "${PUBLIC_WALL}" || echo 000)"
if [[ "${CODE}" != 200 ]]; then
  notify "La línea ya está, pero el muro contestó ${CODE} (${what}). Hay que mirarlo."
  exit 1
fi

printf '%s\n' "${WANT}" > "${STATE_FILE}"

notify "Ya está en el servidor la última versión (${what}).
Línea y consola al día.
Línea: ${PUBLIC_LINE}
Muro: ${PUBLIC_WALL}"

echo "DEPLOYED ${SHA} ${SUBJECT}"
