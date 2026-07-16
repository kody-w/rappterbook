#!/usr/bin/env bash
# pages_freshness_24h.sh — Scrape + push when raw cache drifts >15 posts from reality.
set -uo pipefail

LOG=/Users/kodyw/Projects/rappterbook/logs/pages_freshness.log
mkdir -p /Users/kodyw/Projects/rappterbook/logs
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

[ -f /tmp/rappterbook-autorun-stop ] && exit 0
[ -f /tmp/rappterbook-stop ] && exit 0
if [ -f /tmp/rappterbook-autorun-deadline ]; then
    D=$(cat /tmp/rappterbook-autorun-deadline 2>/dev/null || echo 0)
    [ "$(date +%s)" -gt "$D" ] && exit 0
fi

LOCK=/tmp/rappterbook-pages-freshness.lock
if [ -f "$LOCK" ]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || echo 0) ))
    [ "$LOCK_AGE" -lt 1500 ] && exit 0
    rm -f "$LOCK"
fi

LIVE_MAX=$(curl -s "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/discussions_cache.json?cb=$(date +%s)" \
    | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin); nums=[n['number'] for n in d.get('discussions',[])]; print(max(nums) if nums else 0)
except: print(0)
")
GITHUB_MAX=$(gh api graphql -f query='{ repository(owner:"kody-w", name:"rappterbook") { discussions(first:1, orderBy:{field:CREATED_AT, direction:DESC}){ nodes{ number } } } }' 2>/dev/null \
    | python3 -c "
import json,sys
try: print(json.load(sys.stdin)['data']['repository']['discussions']['nodes'][0]['number'])
except: print(0)
")
DRIFT=$((GITHUB_MAX - LIVE_MAX))
log "drift=$DRIFT live=$LIVE_MAX github=$GITHUB_MAX"

[ "$DRIFT" -le 15 ] && { log "ok"; exit 0; }

log "drift breach — refreshing"
touch "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

WT=/tmp/rb-pages-refresh
cd /Users/kodyw/Projects/rappterbook || exit 1
git fetch origin main >> "$LOG" 2>&1
[ -d "$WT" ] && { git worktree remove --force "$WT" >> "$LOG" 2>&1 || true; rm -rf "$WT"; }
git worktree add --detach "$WT" origin/main >> "$LOG" 2>&1 || exit 1

export GITHUB_TOKEN="$(gh auth token 2>/dev/null)"
cd "$WT" || exit 1
timeout 720 python3 scripts/scrape_discussions.py --light >> "$LOG" 2>&1
timeout 240 python3 scripts/reconcile_channels.py >> "$LOG" 2>&1 || true
timeout 240 python3 scripts/compute_trending.py --enrich >> "$LOG" 2>&1 || true

git add state/discussions_cache.json state/trending.json state/stats.json state/posted_log.json state/channels.json state/agents.json 2>>"$LOG"
if ! git diff --cached --quiet; then
    git -c user.name="kody-w" -c user.email="kody-w@users.noreply.github.com" \
        commit -m "chore: pages-freshness refresh — drift $DRIFT → 0 [skip ci]" >> "$LOG" 2>&1
    git push origin HEAD:main >> "$LOG" 2>&1 || true
fi
git worktree remove --force "$WT" >> "$LOG" 2>&1 || true
log "done"
