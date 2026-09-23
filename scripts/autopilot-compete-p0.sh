#!/usr/bin/env bash
# Wait for F1–F4 compete PRs, merge squash when ready, wait deploy, Run All,
# then overnight WIN cycles until board #1 (beat live leader, not tie at 30).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export GH_TOKEN="${GH_TOKEN:-$(cat /home/factory/.gh-token-personal 2>/dev/null || true)}"
STATE_FILE="${VORTEX_DEPLOY_STATE:-/home/factory/personal/vortex-deploy.state}"

notify() { "$ROOT/scripts/notify-discord.sh" "$1" || true; }

notify "Autopilot **WIN mode**: F1–F4 → deploy → Run All → ciclos hasta **#1** (superar líder live, ahora hash 30+)."

MERGED=0
DEADLINE=$((SECONDS + 10800))  # 3h for P0 merges
while (( SECONDS < DEADLINE )); do
  mapfile -t PRS < <(gh pr list --base main --state open --limit 30 --json number,title,url,mergeable,headRefName \
    --jq '.[] | select(.title|test("fix\\(compete\\): F[1-4]")) | [.number,.title,.url,.mergeable,.headRefName] | @tsv' 2>/dev/null || true)
  if ((${#PRS[@]})); then
    for row in "${PRS[@]}"; do
      num=$(echo "$row" | cut -f1)
      title=$(echo "$row" | cut -f2)
      url=$(echo "$row" | cut -f3)
      mergeable=$(echo "$row" | cut -f4)
      if [[ "$mergeable" == "MERGEABLE" ]]; then
        if gh pr merge "$num" --squash 2>/dev/null; then
          git push origin --delete "$(echo "$row" | cut -f5)" 2>/dev/null || true
          notify "Merged **$title** → main · $url · deploy ~1 min"
          MERGED=$((MERGED+1))
          echo "merged #$num $title"
        fi
      elif [[ "$mergeable" == "CONFLICTING" ]]; then
        echo "waiting conflict resolve on #$num"
      fi
    done
  fi
  DONE=$(gh pr list --base main --state merged --limit 40 --json title \
    --jq '[.[] | select(.title|test("fix\\(compete\\): F[1-4]"))] | length' 2>/dev/null || echo 0)
  echo "merged_compete_F_count=$DONE"
  if (( DONE >= 4 )); then
    notify "Autopilot: **4/4 P0 merged**. Deploy + Run All + overnight…"
    break
  fi
  sleep 45
done

DONE=$(gh pr list --base main --state merged --limit 40 --json title \
  --jq '[.[] | select(.title|test("fix\\(compete\\): F[1-4]"))] | length' 2>/dev/null || echo 0)
if (( DONE < 4 )); then
  notify "Autopilot P0 incomplete ($DONE/4) tras 3h — paso igual a deploy/Run All de lo mergeado + overnight."
fi

echo "Waiting for deploy of origin/main…"
DEPLOY_DEADLINE=$((SECONDS + 1800))
while (( SECONDS < DEPLOY_DEADLINE )); do
  git -C "$ROOT" fetch origin main -q 2>/dev/null || true
  WANT="$(git -C "$ROOT" rev-parse origin/main)"
  HAVE=""
  [[ -f "$STATE_FILE" ]] && HAVE="$(tr -d '[:space:]' < "$STATE_FILE")"
  LINE_UP="$(docker inspect -f '{{.State.Health.Status}}' vortex-line 2>/dev/null || echo missing)"
  if [[ -n "$HAVE" && "$HAVE" == "$WANT" && "$LINE_UP" == "healthy" ]]; then
    notify "Deploy OK · \`${WANT:0:7}\` · Run All…"
    break
  fi
  echo "deploy have=${HAVE:0:7} want=${WANT:0:7} line=$LINE_UP"
  sleep 20
done

# First scored Run All (records /tmp/prosper-best-points.txt)
python3 "$ROOT/scripts/prosper-run-all.py" || true

# Overnight WIN cycles until #1 (dynamic leader+1)
exec stdbuf -oL -eL bash "$ROOT/scripts/overnight-compete-loop.sh"
