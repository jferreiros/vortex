#!/usr/bin/env bash
# Overnight compete loop: keep fix→merge→deploy→Run All until we LEAD
# the board (strictly more points than whoever is #1), or morning deadline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export GH_TOKEN="${GH_TOKEN:-$(cat /home/factory/.gh-token-personal 2>/dev/null || true)}"
export CURSOR_API_KEY="${CURSOR_API_KEY:-}"

MAX_CYCLES="${MAX_CYCLES:-10}"
# Keep grinding until 10:00 UTC (12:00 CEST)
STOP_EPOCH="${STOP_EPOCH:-$(python3 -c 'from datetime import datetime,timezone; print(int(datetime(2026,9,19,10,0,tzinfo=timezone.utc).timestamp()))')}"
STATE_FILE="${VORTEX_DEPLOY_STATE:-/home/factory/personal/vortex-deploy.state}"
AGENT_BIN="${AGENT_BIN:-/home/factory/.local/bin/agent}"
MODEL="${OVERNIGHT_MODEL:-claude-opus-5-thinking-high}"
LOG=/tmp/overnight-compete-loop.log
POINTS_FILE=/tmp/prosper-best-points.txt
CYCLE_DIR=/tmp/overnight-cycles
BOARD_URL="${BOARD_URL:-https://hackspain.getprosperapp.com/leaderboard/api/board}"
TEAM_NAME="${PROSPER_TEAM_NAME:-vortex}"
mkdir -p "$CYCLE_DIR"

notify() { "$ROOT/scripts/notify-discord.sh" "$1" || true; }
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

best_points() {
  if [[ -f "$POINTS_FILE" ]]; then
    tr -d '[:space:]' < "$POINTS_FILE"
    return
  fi
  python3 "$ROOT/scripts/prosper-team-stats.py" --best 2>/dev/null || echo 0
}

# Prints: leader_name leader_pts our_pts our_rank need_pts (need = leader+epsilon if we aren't sole #1)
board_snapshot() {
  python3 - <<'PY'
import json, urllib.request, os
board=json.loads(urllib.request.urlopen(os.environ.get("BOARD_URL","https://hackspain.getprosperapp.com/leaderboard/api/board"), timeout=20).read())
entries=board.get("entries") or []
ours_name=os.environ.get("TEAM_NAME","vortex")
ours=next((e for e in entries if e.get("name")==ours_name), None)
leader=entries[0] if entries else {"name":"?","points":0,"rank":1}
our_pts=float((ours or {}).get("points") or 0)
our_rank=int((ours or {}).get("rank") or 99)
leader_pts=float(leader.get("points") or 0)
leader_name=leader.get("name") or "?"
second=float(entries[1].get("points") or 0) if len(entries) > 1 else 0.0
winning = our_rank == 1 and our_pts > second
if our_rank != 1:
    # Must strictly beat whoever is ahead (and stay ahead of movers)
    target = leader_pts + 1.0
else:
    # Already #1 — keep at least +1 over #2 in case they climb
    target = second + 1.0
print(f"{leader_name}\t{leader_pts}\t{our_pts}\t{our_rank}\t{target}\t{int(winning)}")
PY
}

we_are_winning() {
  local snap winning
  snap="$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot)"
  winning=$(echo "$snap" | cut -f6)
  [[ "$winning" == "1" ]]
}

dynamic_target() {
  BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot | cut -f5
}

wait_deploy() {
  local deadline=$((SECONDS + 1800))
  while (( SECONDS < deadline )); do
    git fetch origin main -q 2>/dev/null || true
    local want have line
    want="$(git rev-parse origin/main)"
    have=""
    [[ -f "$STATE_FILE" ]] && have="$(tr -d '[:space:]' < "$STATE_FILE")"
    line="$(docker inspect -f '{{.State.Health.Status}}' vortex-line 2>/dev/null || echo missing)"
    if [[ -n "$have" && "$have" == "$want" && "$line" == "healthy" ]]; then
      log "deploy OK ${want:0:7}"
      return 0
    fi
    log "deploy have=${have:0:7} want=${want:0:7} line=$line"
    sleep 20
  done
  return 1
}

merge_open_compete_prs() {
  mapfile -t PRS < <(gh pr list --base main --state open --limit 40 --json number,title,url,mergeable,headRefName \
    --jq '.[] | select(.title|test("fix\\(compete\\):")) | [.number,.title,.url,.mergeable,.headRefName] | @tsv' 2>/dev/null || true)
  local n=0
  for row in "${PRS[@]:-}"; do
    [[ -z "${row:-}" ]] && continue
    local num title url mergeable
    num=$(echo "$row" | cut -f1)
    title=$(echo "$row" | cut -f2)
    url=$(echo "$row" | cut -f3)
    mergeable=$(echo "$row" | cut -f4)
    if [[ "$mergeable" == "MERGEABLE" ]]; then
      if gh pr merge "$num" --squash 2>/dev/null; then
        git push origin --delete "$(echo "$row" | cut -f5)" 2>/dev/null || true
        notify "Overnight merged **$title** · $url"
        log "merged #$num $title"
        n=$((n+1))
      fi
    elif [[ "$mergeable" == "CONFLICTING" ]]; then
      log "PR #$num CONFLICTING — spawning rebase agent"
      notify "PR #$num conflicting — agent rebase"
      "$AGENT_BIN" -p --force --trust --workspace "$ROOT" --model "$MODEL" \
        "Resolve merge conflicts on GitHub PR #$num in repo $ROOT so it becomes MERGEABLE against main. Rebase the PR branch onto origin/main, keep both intents, push --force-with-lease, do not merge. Discord notify via scripts/notify-discord.sh when MERGEABLE." \
        >>"$CYCLE_DIR/rebase-$num.log" 2>&1 || true
    fi
  done
  echo "$n"
}

run_all_and_record() {
  log "Run All starting…"
  set +e
  python3 "$ROOT/scripts/prosper-run-all.py" | tee -a "$LOG"
  local rc=${PIPESTATUS[0]}
  set -e
  python3 "$ROOT/scripts/prosper-team-stats.py" --write "$POINTS_FILE" || true
  local pts snap leader_name leader_pts our_rank target
  pts="$(best_points)"
  snap="$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot)"
  leader_name=$(echo "$snap" | cut -f1)
  leader_pts=$(echo "$snap" | cut -f2)
  our_rank=$(echo "$snap" | cut -f4)
  target=$(echo "$snap" | cut -f5)
  log "Run All done rc=$rc best=$pts rank=$our_rank leader=$leader_name:$leader_pts target>$target"
  notify "Run All → **${pts}** pts · rank **#${our_rank}** · líder ${leader_name} ${leader_pts} · target ganar (>${leader_pts})"
  echo "$pts"
}

spawn_improve_cycle() {
  local cycle="$1"
  local pts="$2"
  local snap target leader_name leader_pts our_rank
  snap="$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot)"
  leader_name=$(echo "$snap" | cut -f1)
  leader_pts=$(echo "$snap" | cut -f2)
  our_rank=$(echo "$snap" | cut -f4)
  target=$(echo "$snap" | cut -f5)
  local brief="$CYCLE_DIR/cycle-${cycle}-brief.md"
  python3 "$ROOT/scripts/prosper-team-stats.py" --dump "$CYCLE_DIR/cycle-${cycle}-team.json" || true
  {
    echo "# Overnight WIN cycle $cycle"
    echo "Goal: BEAT the leader. Not tie. Rank #1 with more points than everyone else."
    echo "Board: leader=$leader_name at $leader_pts · vortex=$pts rank=$our_rank · aim_target>$target"
    echo "Pass-rate report (READ FIRST): $ROOT/docs/competition/pass-rate-re-2026-09-19.md"
    echo "Priority order from that report:"
    echo "  1) Stop defaulting fallback to NO_ACTION/out_of_scope (0 accepted cases use it)."
    echo "     Prefer BOOK/REGISTER when a prepared action or chart exists; only emit the 3"
    echo "     real refusal reasons: provider_not_found, referral_required, specialty_not_covered."
    echo "  2) Wall-clock ~180s — submit as soon as decided; hard fallback by T+150s."
    echo "  3) Do NOT touch deploy timer unless adding active_run guard (may already be on main)."
    echo "Team dump: $CYCLE_DIR/cycle-${cycle}-team.json"
    echo "Logs: /tmp/vortex-calls.jsonl /tmp/vortex-recent-calls.json /tmp/prosper-team-latest.json"
    echo
    echo "Implement the highest-ROI scoring fix for HackSpain Prosper team vortex."
    echo "Open a PR against main titled: fix(compete): C${cycle} <short description>"
    echo "Branch: fix/compete-C${cycle}-<slug> from latest origin/main."
    echo "Add tests. Scoped pytest. Push + gh pr create. Do NOT merge."
    echo "Discord via $ROOT/scripts/notify-discord.sh with PR URL."
    echo "Do not regress F1–F4. Prefer one tight high-points fix (action/reason/specialty/confirm/hangup/booking)."
    echo "Someone else may pass 30 tonight — optimize for max private-case points, not a 30 ceiling."
  } >"$brief"

  notify "🏆 Ciclo **C${cycle}**: #${our_rank} con ${pts} · líder **${leader_name} ${leader_pts}** → Opus para **ganar**"
  log "spawning WIN agent cycle $cycle target>$target"
  "$AGENT_BIN" -p --force --trust --workspace "$ROOT" --model "$MODEL" \
    "$(cat "$brief")" \
    >>"$CYCLE_DIR/cycle-${cycle}-agent.log" 2>&1 || true
  log "improve agent cycle $cycle finished"
}

wait_for_cycle_pr() {
  local cycle="$1"
  local deadline=$((SECONDS + 5400))
  while (( SECONDS < deadline )); do
    merge_open_compete_prs >/dev/null || true
    local found
    found=$(gh pr list --base main --state all --limit 40 --json number,state,mergeable,title,url \
      --jq '[.[] | select(.title|test("fix\\(compete\\): C'"${cycle}"'(\\s|$)"))] | .[0] // empty' 2>/dev/null || true)
    if [[ -n "$found" ]]; then
      local state mergeable num
      state=$(echo "$found" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("state",""))')
      mergeable=$(echo "$found" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("mergeable",""))')
      num=$(echo "$found" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("number",""))')
      log "C${cycle} PR #$num state=$state mergeable=$mergeable"
      if [[ "$state" == "MERGED" ]]; then
        return 0
      fi
      if [[ "$mergeable" == "MERGEABLE" && "$state" == "OPEN" ]]; then
        gh pr merge "$num" --squash 2>/dev/null && return 0
      fi
    fi
    sleep 60
  done
  return 1
}

notify "Overnight **WIN mode** · superar al líder (ahora hash 30) · máx ${MAX_CYCLES} ciclos · hasta 10:00 UTC · si alguien nos pisa, el target sube"
log "overnight WIN loop start max=$MAX_CYCLES"

if [[ ! -f "$POINTS_FILE" ]]; then
  wait_deploy || log "deploy wait failed — still attempting Run All"
  run_all_and_record >/dev/null || true
fi

for cycle in $(seq 1 "$MAX_CYCLES"); do
  now=$(date +%s)
  if (( now >= STOP_EPOCH )); then
    snap="$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot)"
    notify "Overnight cortado 10:00 UTC · $(echo "$snap" | awk -F'\t' '{printf "#%s %s pts (líder %s %s)", $4, $3, $1, $2}')"
    log "stop epoch"
    break
  fi

  snap="$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot)"
  leader_name=$(echo "$snap" | cut -f1)
  leader_pts=$(echo "$snap" | cut -f2)
  pts=$(echo "$snap" | cut -f3)
  our_rank=$(echo "$snap" | cut -f4)
  target=$(echo "$snap" | cut -f5)
  winning=$(echo "$snap" | cut -f6)
  echo "$pts" > "$POINTS_FILE"

  if [[ "$winning" == "1" ]]; then
    # Still do one extra cycle if margin < 2 pts (someone close)
    margin=$(python3 -c "print(float('$pts')-float('$leader_pts') if '$leader_name'!='$TEAM_NAME' else float('$pts')-float('$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot | cut -f2)'))" 2>/dev/null || echo 99)
    # If we are #1, leader_name is us — compare to #2 via target
    if python3 -c "import sys; sys.exit(0 if float('$pts') >= float('$target') else 1)"; then
      notify "🏆 **#1 con ${pts} pts** · margen OK vs campo. Seguimos monitoreando; no más ciclos salvo que nos pasen."
      log "winning with $pts target $target"
      # Monitor loop: if board shows we dropped, continue cycles
      while (( $(date +%s) < STOP_EPOCH )); do
        sleep 300
        snap="$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot)"
        winning=$(echo "$snap" | cut -f6)
        if [[ "$winning" != "1" ]]; then
          notify "⚠️ Nos pasaron · $(echo "$snap" | awk -F'\t' '{print $1,$2}') > nosotros $(echo "$snap" | cut -f3) — reanudando ciclos"
          break
        fi
        log "still #1 $(echo "$snap" | cut -f3)"
      done
      winning=$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot | cut -f6)
      [[ "$winning" == "1" ]] && continue
      # else fall through to spawn cycle with same cycle number... use cycle as-is
    fi
  fi

  notify "Overnight: #${our_rank} **${pts}** · líder **${leader_name} ${leader_pts}** → C${cycle}/${MAX_CYCLES} para **ganar** (target>${target})"
  spawn_improve_cycle "$cycle" "$pts"
  if wait_for_cycle_pr "$cycle"; then
    wait_deploy || true
    run_all_and_record >/dev/null || true
  else
    notify "Overnight C${cycle}: sin PR a tiempo — siguiente ciclo"
    log "cycle $cycle no PR"
  fi
done

snap="$(BOARD_URL="$BOARD_URL" TEAM_NAME="$TEAM_NAME" board_snapshot)"
notify "Overnight FIN · #$(echo "$snap" | cut -f4) **$(echo "$snap" | cut -f3)** pts · líder $(echo "$snap" | cut -f1) $(echo "$snap" | cut -f2)"
log "done $snap"
we_are_winning
