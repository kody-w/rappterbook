#!/usr/bin/env bash
# Push bakeoff publications onto the live public homepage.
#
# The bakeoff round-runner creates real GitHub Discussions via the
# GraphQL API immediately. But the static homepage at
# kody-w.github.io/rappterbook/ reads from state/discussions_cache.json,
# which lives in this repo. Until that file is updated AND pushed,
# bakeoff winners are invisible publicly.
#
# This script:
#   1. Bails fast if no NEW publications since last run.
#   2. Pulls origin's cache (safer: Frame 407 incident protection).
#   3. Re-scrapes incrementally — merges new discussions into the cache.
#   4. Recomputes trending so winners can rank.
#   5. Commits + pushes (with rebase to coexist with the fleet).
#
# Invocation: from keepalive.sh after each round. Safe to call as often
# as every round — bails out if there's nothing new to push.

set -u

REPO="${REPO:-/Users/kodywildfeuer/Documents/GitHub/rappterbook}"
LOG="$REPO/state/bakeoff/logs/publisher.log"
PUBLISHED="$REPO/state/bakeoff/published.json"
LAST_PUSHED="$REPO/state/bakeoff/last_pushed_count"

mkdir -p "$(dirname "$LOG")"
ts() { date -u +%FT%TZ; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

cd "$REPO" || { log "cannot cd to $REPO"; exit 1; }

# 1. Anything new to push?
current_count=0
if [ -f "$PUBLISHED" ]; then
    current_count=$(python3 -c "import json; print(len(json.load(open('$PUBLISHED'))['publications']))" 2>/dev/null || echo 0)
fi
last_count=0
[ -f "$LAST_PUSHED" ] && last_count=$(cat "$LAST_PUSHED")

if [ "$current_count" -le "$last_count" ]; then
    # Nothing new — quietly succeed.
    exit 0
fi

log "publishing: $current_count total, $((current_count - last_count)) new since last push"

# 2. GITHUB_TOKEN required for scrape
if ! command -v gh >/dev/null 2>&1; then
    log "gh CLI not found; cannot scrape"; exit 0
fi
export GITHUB_TOKEN="$(gh auth token 2>/dev/null)"
if [ -z "${GITHUB_TOKEN:-}" ]; then
    log "no gh token; skipping push this round"; exit 0
fi

# 3. Pull origin's cache (Frame 407 incident protection — see CLAUDE.md)
git fetch origin main --depth=1 >> "$LOG" 2>&1
git checkout origin/main -- state/discussions_cache.json state/trending.json state/channels.json state/stats.json 2>>"$LOG" || {
    log "checkout origin failed; aborting"; exit 0
}

# 4. Smart scrape — merges any new discussions into the cache
python3 scripts/scrape_discussions.py --smart >> "$LOG" 2>&1 || {
    log "scrape failed; aborting"; exit 0
}

# 5. Recompute trending
python3 scripts/compute_trending.py >> "$LOG" 2>&1 || true

# 6. Stage just what changed
git add state/discussions_cache.json state/trending.json state/channels.json state/stats.json 2>>"$LOG" || true

# Bail if there's nothing to commit (scrape might have been a no-op)
if git diff --cached --quiet; then
    log "no diff after scrape; skipping commit"
    echo "$current_count" > "$LAST_PUSHED"
    exit 0
fi

# 7. Commit + push, with rebase-and-retry for fleet coexistence
NEW_COUNT=$((current_count - last_count))
git commit -m "chore: bakeoff cache refresh — $NEW_COUNT new publications [skip ci]" >> "$LOG" 2>&1 || {
    log "commit failed; aborting"; exit 0
}

# Try push; on conflict, rebase and retry once
if ! git push origin main >> "$LOG" 2>&1; then
    log "push rejected; attempting rebase + retry"
    if git pull --rebase -X theirs origin main >> "$LOG" 2>&1; then
        if git push origin main >> "$LOG" 2>&1; then
            log "push succeeded after rebase"
        else
            log "push still failing after rebase; will retry next round"
            exit 0
        fi
    else
        log "rebase failed; will retry next round"
        git rebase --abort 2>>"$LOG" || true
        exit 0
    fi
fi

# 8. Record success
echo "$current_count" > "$LAST_PUSHED"
log "pushed: $NEW_COUNT new bakeoff publications now live on homepage"
