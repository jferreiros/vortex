#!/usr/bin/env bash
#
# Vortex — deploy the call socket in one command.
#
#     deploy/deploy.sh                  fetch main, rebuild, restart, verify
#     deploy/deploy.sh --skip-pull      redeploy the working tree as it stands
#     deploy/deploy.sh --check-only     verify what is already running
#
# Exit code 0 means the public endpoint answered. Anything else means do not
# start a run yet.

set -Eeuo pipefail

# ---------------------------------------------------------------- where we are
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE=(docker compose -f "${SCRIPT_DIR}/compose.yaml")
CONTAINER=vortex-line

# The host Traefik routes to us on. Override for a different name:
#     VORTEX_PUBLIC_HOST=line.vortex.jferreiros.com deploy/deploy.sh
PUBLIC_HOST="${VORTEX_PUBLIC_HOST:-line.167.233.80.47.sslip.io}"
WS_PATH="${VORTEX_WS_PATH:-/ws}"

# ------------------------------------------------------------------- reporting
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
else
  BOLD=''; RED=''; GREEN=''; YELLOW=''; DIM=''; OFF=''
fi

STEP=0
step() { STEP=$((STEP + 1)); printf '%s[%d/%d]%s %s\n' "${BOLD}" "${STEP}" "${TOTAL}" "${OFF}" "$1"; }
ok()   { printf '      %s✓%s %s\n' "${GREEN}" "${OFF}" "$1"; }
warn() { printf '      %s!%s %s\n' "${YELLOW}" "${OFF}" "$1"; }
die()  { printf '\n%s✗ FAILED:%s %s\n' "${RED}" "${OFF}" "$1" >&2; exit 1; }
trap 'die "line $LINENO. Nothing was left half-started: check '\''deploy/deploy.sh --check-only'\''."' ERR

SKIP_PULL=0
CHECK_ONLY=0
for arg in "$@"; do
  case "${arg}" in
    --skip-pull)  SKIP_PULL=1 ;;
    --check-only) CHECK_ONLY=1 ;;
    -h|--help)    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            die "unknown option ${arg}" ;;
  esac
done

TOTAL=5
[[ ${CHECK_ONLY} -eq 1 ]] && TOTAL=2
[[ ${SKIP_PULL} -eq 1 ]] && TOTAL=$((TOTAL - 1))

START=$(date +%s)
printf '%sVortex deploy%s  %s%s%s\n' "${BOLD}" "${OFF}" "${DIM}" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "${OFF}"

# Fail on the real reason now, rather than on a symptom two minutes from now.
docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon as $(id -un).
      If it is a permission problem, this user needs to be in the docker group:
        sudo usermod -aG docker $(id -un)     # then open a new login shell"

# ------------------------------------------------------------------ 1. sources
if [[ ${CHECK_ONLY} -eq 0 && ${SKIP_PULL} -eq 0 ]]; then
  step "Fetching the latest main"
  cd "${REPO_ROOT}"
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "${BRANCH}" != "main" ]]; then
    warn "on branch ${BRANCH}, not main — deploying that instead"
  fi
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    warn "working tree has local changes — skipping the pull, deploying what is on disk"
  else
    git pull --ff-only --quiet
    ok "$(git log -1 --pretty='%h %s')"
  fi
fi

# -------------------------------------------------------- 2. build and restart
if [[ ${CHECK_ONLY} -eq 0 ]]; then
  [[ -f "${SCRIPT_DIR}/.env" ]] || die "deploy/.env is missing. cp deploy/.env.example deploy/.env"
  docker network inspect coolify >/dev/null 2>&1 \
    || die "the 'coolify' Docker network is not there. Traefik is what publishes us; do not create the network by hand, ask whoever runs Coolify."

  step "Building the image"
  "${COMPOSE[@]}" build
  ok "vortex-line:local"

  step "Restarting the container"
  "${COMPOSE[@]}" up -d --remove-orphans
  ok "$(docker inspect -f '{{.Name}} {{.State.Status}}' "${CONTAINER}" | sed 's|^/||')"
fi

# ------------------------------------------------------------------- 3. health
step "Waiting for the container to report healthy"
docker inspect "${CONTAINER}" >/dev/null 2>&1 \
  || die "there is no ${CONTAINER} container. Run deploy/deploy.sh without --check-only."
for _ in $(seq 1 60); do
  STATE="$(docker inspect -f '{{.State.Health.Status}}' "${CONTAINER}" 2>/dev/null || echo missing)"
  [[ "${STATE}" == healthy ]] && break
  [[ "${STATE}" == unhealthy ]] && die "the container is unhealthy. docker logs ${CONTAINER} --tail 50"
  sleep 2
done
[[ "${STATE:-}" == healthy ]] || die "still ${STATE:-missing} after 120 s. docker logs ${CONTAINER} --tail 50"
MODES="$(docker exec "${CONTAINER}" python -c \
  'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:7860/health")); print("clinic="+d["clinic"], "voice="+d["voice"], "ws="+d["ws_path"])')"
ok "healthy — ${MODES}"

# ------------------------------------------------------ 4. the public endpoint
step "Checking the public endpoint"
CODE="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "https://${PUBLIC_HOST}/health" || echo 000)"
case "${CODE}" in
  200) ok "https://${PUBLIC_HOST}/health -> 200" ;;
  000) die "https://${PUBLIC_HOST} did not answer. DNS for ${PUBLIC_HOST}, or Traefik, or the certificate. See deploy/README.md." ;;
  404) die "Traefik answered ${CODE}: no router matched ${PUBLIC_HOST}. Check the Host() labels in deploy/compose.yaml." ;;
  503) die "Traefik answered ${CODE}: the router matched but found no healthy backend. Is the container on the 'coolify' network?" ;;
  *)   die "https://${PUBLIC_HOST}/health answered ${CODE}" ;;
esac

# --------------------------------------------------- 5. the handshake, for real
# /health proves HTTPS. Only a real upgrade proves the thing we are actually
# paid to serve: a Twilio Media Streams call, end to end, through Traefik.
if [[ ${CHECK_ONLY} -eq 0 ]]; then
  step "Dialling the public endpoint with a fake call"
  # From inside the container: scripts/fake_caller.py is already in the image,
  # so this needs nothing installed on the host. It leaves through the public
  # address and comes back via Traefik, the same path a real call takes.
  if docker exec "${CONTAINER}" python scripts/fake_caller.py \
       --url "wss://${PUBLIC_HOST}${WS_PATH}" --calls 1 --seconds 2; then
    ok "the WebSocket handshake completed through Traefik"
  else
    die "the handshake did not complete. HTTPS works but the upgrade does not.
      If the container simply cannot reach this host's own public address, run the
      same dial from the host instead:
        uv run python scripts/fake_caller.py --url wss://${PUBLIC_HOST}${WS_PATH} --calls 1
      Otherwise see deploy/README.md."
  fi
fi

printf '\n%s✓ Vortex is up%s  %s(%ss)%s\n' "${GREEN}${BOLD}" "${OFF}" "${DIM}" "$(($(date +%s) - START))" "${OFF}"
printf '  Endpoint for the dashboard: %swss://%s%s%s\n' "${BOLD}" "${PUBLIC_HOST}" "${WS_PATH}" "${OFF}"
printf '  %sLogs: docker logs -f %s   Calls: docker exec %s tail -f /app/logs/calls.jsonl%s\n' \
  "${DIM}" "${CONTAINER}" "${CONTAINER}" "${OFF}"
