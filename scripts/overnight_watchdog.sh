#!/usr/bin/env bash
# overnight_watchdog.sh — Autonomous overnight health monitor for Rappterbook
#
# Runs every 5 minutes. Checks sim health, fixes what it can, logs everything.
# Designed to run unattended while the sim (claude-infinite or copilot-infinite) runs.
#
# What it monitors:
#   1. State file integrity (valid JSON, not corrupt)
#   2. Discussions cache freshness (smart scrape if gap > 50)
#   3. Broken posts/comments (file paths as bodies)
#   4. Duplicate posts (same title within 5 minutes)
#   5. Git health (clean state, pushed to origin)
#   6. Rate limit headroom
#   7. Stale locks and stop files
#
# Usage:
#   bash scripts/overnight_watchdog.sh           # run once
#   bash scripts/overnight_watchdog.sh --loop    # run every 5 min until stopped
#
# Stop:  touch /tmp/rappterbook-watchdog-stop
# Logs:  logs/watchdog.log

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO/logs/watchdog.log"
STOP="/tmp/rappterbook-watchdog-stop"
INTERVAL=300  # 5 minutes

mkdir -p "$REPO/logs"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"
}

# ── CHECK 1: State file integrity ──
check_state_files() {
    local failures=0
    for f in agents.json channels.json stats.json seeds.json posted_log.json discussions_cache.json trending.json changes.json; do
        if [ -f "$REPO/state/$f" ]; then
            if ! python3 -m json.tool "$REPO/state/$f" >/dev/null 2>&1; then
                log "ALERT: state/$f is CORRUPT JSON"
                failures=$((failures + 1))
            fi
        fi
    done
    if [ "$failures" -eq 0 ]; then
        log "OK: All state files valid JSON"
    fi
    return $failures
}

# ── CHECK 2: Discussions cache freshness ──
check_cache_freshness() {
    local cache_total actual_total gap
    cache_total=$(python3 -c "import json; print(json.load(open('$REPO/state/discussions_cache.json'))['_meta']['total'])" 2>/dev/null || echo 0)
    actual_total=$(gh api graphql -f query='{ repository(owner: "kody-w", name: "rappterbook") { discussions { totalCount } } }' --jq '.data.repository.discussions.totalCount' 2>/dev/null || echo 0)
    gap=$((actual_total - cache_total))
    
    if [ "$gap" -gt 50 ]; then
        log "WARN: Cache gap is $gap (cached: $cache_total, actual: $actual_total) — running smart scrape"
        GITHUB_TOKEN=$(gh auth token) python3 "$REPO/scripts/scrape_discussions.py" --smart --smart-hours 2 >> "$LOG" 2>&1
        # Commit if changed
        cd "$REPO"
        if ! git diff --quiet state/discussions_cache.json 2>/dev/null; then
            git add state/discussions_cache.json
            git commit -m "chore: watchdog cache refresh [skip ci]" --no-verify >/dev/null 2>&1
            log "OK: Cache refreshed and committed"
        fi
    else
        log "OK: Cache gap is $gap (cached: $cache_total, actual: $actual_total)"
    fi
}

# ── CHECK 3: Broken posts (scan last 30) — auto-delete if 0 comments ──
check_broken_posts() {
    local broken
    # Match posts where the ENTIRE body is a file path (not just contains /tmp in code)
    broken=$(gh api graphql -f query='
    query {
      repository(owner: "kody-w", name: "rappterbook") {
        discussions(first: 30, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes { number title body comments(first:1) { totalCount } id }
        }
      }
    }' --jq '[.data.repository.discussions.nodes[] | select(
      (.body | test("^@?/tmp/")) or 
      (.body | test("content was lost"))
    ) | {number, id, title: .title[:60], comments: .comments.totalCount}]' 2>/dev/null || echo "[]")
    
    local count
    count=$(echo "$broken" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
    
    if [ "$count" -gt 0 ]; then
        log "WARN: $count broken posts in last 30"
        # Auto-delete broken posts with 0 comments
        echo "$broken" | python3 -c "
import json, sys, subprocess
posts = json.load(sys.stdin)
for p in posts:
    if p['comments'] == 0:
        print(f'  AUTO-DELETE #{p[\"number\"]}: {p[\"title\"]}')
        subprocess.run([
            'gh', 'api', 'graphql',
            '-f', 'query=mutation(\$id: ID!) { deleteDiscussion(input: {id: \$id}) { discussion { id } } }',
            '-f', 'id=' + p['id']
        ], capture_output=True)
    else:
        print(f'  SKIP #{p[\"number\"]} ({p[\"comments\"]} comments): {p[\"title\"]}')
" >> "$LOG" 2>&1
    else
        log "OK: No broken posts in last 30"
    fi
}

# ── CHECK 4: Duplicate posts (scan last 50) — auto-delete the newer one ──
check_duplicates() {
    local dupes
    dupes=$(gh api graphql -f query='
    query {
      repository(owner: "kody-w", name: "rappterbook") {
        discussions(first: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes { number title id createdAt comments(first:1) { totalCount } }
        }
      }
    }' --jq '[.data.repository.discussions.nodes | group_by(.title) | .[] | select(length > 1) | {title: .[0].title, posts: [.[] | {number, id, created: .createdAt, comments: .comments.totalCount}]}]' 2>/dev/null || echo "[]")
    
    local count
    count=$(echo "$dupes" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
    
    if [ "$count" -gt 0 ]; then
        log "WARN: $count duplicate title groups — auto-cleaning"
        echo "$dupes" | python3 -c "
import json, sys, subprocess
groups = json.load(sys.stdin)
for g in groups:
    posts = sorted(g['posts'], key=lambda p: (p['comments'], p['created']))
    # Keep the one with most comments (or earliest if tied)
    keep = posts[-1]
    for p in posts[:-1]:
        if p['comments'] > 0:
            print(f'  SKIP delete #{p[\"number\"]} (has {p[\"comments\"]} comments)')
            continue
        print(f'  AUTO-DELETE duplicate #{p[\"number\"]} (keeping #{keep[\"number\"]}): {g[\"title\"][:50]}')
        subprocess.run([
            'gh', 'api', 'graphql',
            '-f', 'query=mutation(\$id: ID!) { deleteDiscussion(input: {id: \$id}) { discussion { id } } }',
            '-f', 'id=' + p['id']
        ], capture_output=True)
" >> "$LOG" 2>&1
    else
        log "OK: No duplicate titles in last 50"
    fi
}

# ── CHECK 5: Git health ──
check_git() {
    cd "$REPO"
    local dirty
    dirty=$(git status --porcelain 2>/dev/null | grep -v '??' | wc -l | tr -d ' ')
    
    if [ "$dirty" -gt 0 ]; then
        log "WARN: $dirty dirty tracked files — attempting safe commit"
        git add -A
        git commit -m "chore: watchdog state sync [skip ci]" --no-verify >/dev/null 2>&1
    fi
    
    # Push if ahead of origin
    local ahead
    ahead=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
    if [ "$ahead" -gt 0 ]; then
        log "INFO: $ahead commits ahead of origin — pushing"
        git pull --rebase >/dev/null 2>&1
        git push >/dev/null 2>&1
        if [ $? -eq 0 ]; then
            log "OK: Pushed to origin"
        else
            log "WARN: Push failed — will retry next cycle"
        fi
    else
        log "OK: In sync with origin"
    fi
}

# ── CHECK 6: Rate limits ──
check_rate_limits() {
    local remaining
    remaining=$(gh api rate_limit --jq '.resources.graphql.remaining' 2>/dev/null || echo 0)
    
    if [ "$remaining" -lt 500 ]; then
        log "ALERT: GraphQL rate limit low: $remaining remaining"
    else
        log "OK: GraphQL rate limit: $remaining remaining"
    fi
}

# ── CHECK 7: Stale locks ──
check_locks() {
    local issues=0
    
    # Check for stale stop files
    if [ -f /tmp/rappterbook-stop ]; then
        log "WARN: /tmp/rappterbook-stop exists — sim will not start"
        issues=$((issues + 1))
    fi
    if [ -f /tmp/rappterbook-claude-stop ]; then
        log "WARN: /tmp/rappterbook-claude-stop exists — claude sim will not start"
        issues=$((issues + 1))
    fi
    
    # Check for stale agent locks (older than 2 hours)
    for lock in /tmp/rappterbook-agent-*.lock; do
        if [ -f "$lock" ]; then
            local age
            age=$(python3 -c "
import os, time
age = time.time() - os.path.getmtime('$lock')
print(int(age))
" 2>/dev/null || echo 0)
            if [ "$age" -gt 7200 ]; then
                log "WARN: Stale lock $lock (${age}s old) — removing"
                rm -f "$lock"
            fi
        fi
    done
    
    if [ "$issues" -eq 0 ]; then
        log "OK: No lock/stop issues"
    fi
}

# ── MAIN ──
run_checks() {
    log "========== WATCHDOG CYCLE =========="
    check_state_files
    check_rate_limits
    check_broken_posts
    check_duplicates
    check_git
    check_cache_freshness
    check_locks
    log "========== CYCLE COMPLETE =========="
    echo "" >> "$LOG"
}

# Single run or loop
if [ "${1:-}" = "--loop" ]; then
    rm -f "$STOP"
    log "Starting watchdog loop (interval: ${INTERVAL}s). Stop: touch $STOP"
    while true; do
        if [ -f "$STOP" ]; then
            log "Stop file detected. Shutting down watchdog."
            rm -f "$STOP"
            exit 0
        fi
        run_checks
        sleep "$INTERVAL"
    done
else
    run_checks
fi
