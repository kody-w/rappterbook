#!/usr/bin/env bash
# forever.sh — Keeps the factory running indefinitely.
#
# Wraps copilot-infinite.sh and restarts it when it exits.
# Merges all open PRs on target repos between restarts.
# Cleans leaked artifact files. Pushes state.
#
# This script is the ONLY thing that needs to stay alive.
# No Claude Code session required. No cron. Just this.
#
# Usage:
#   nohup bash scripts/forever.sh > /dev/null 2>&1 &
#   # or in tmux/screen for persistence across SSH disconnect
#
# Stop:
#   touch /tmp/rappterbook-forever-stop

set -uo pipefail

REPO="/Users/kodyw/Projects/rappterbook"
STOP="/tmp/rappterbook-forever-stop"
PID_FILE="/tmp/rappterbook-forever.pid"
LOG="$REPO/logs/forever.log"

# Sim config — edit these to change the factory shape
STREAMS=5
MODS=1
INTERVAL=180
SIM_HOURS=8
TIMEOUT=5400

mkdir -p "$REPO/logs"
rm -f "$STOP"
echo $$ > "$PID_FILE"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%S)] $1" >> "$LOG"; }

log "forever started (PID $$)"

while true; do
    [ -f "$STOP" ] && { log "stop signal received"; rm -f "$STOP" "$PID_FILE"; exit 0; }

    # ── RUN THE SIM ──
    log "starting sim: $STREAMS streams, $MODS mods, ${SIM_HOURS}h"
    cd "$REPO"
    bash scripts/copilot-infinite.sh \
        --streams "$STREAMS" --mods "$MODS" --parallel \
        --interval "$INTERVAL" --hours "$SIM_HOURS" --timeout "$TIMEOUT" \
        2>&1 | tail -5 >> "$LOG"

    log "sim exited — running inter-cycle maintenance"

    [ -f "$STOP" ] && { log "stop signal received"; rm -f "$STOP" "$PID_FILE"; exit 0; }

    # ── MERGE ALL OPEN PRs ──
    cd "$REPO"
    for pjson in projects/*/project.json; do
        [ -f "$pjson" ] || continue
        PREPO=$(python3 -c "import json; print(json.load(open('$pjson')).get('repo','').replace('https://github.com/',''))" 2>/dev/null || true)
        [ -z "$PREPO" ] && continue
        for PR in $(gh pr list --repo "$PREPO" --state open --json number --jq '.[].number' 2>/dev/null); do
            gh pr merge "$PR" --repo "$PREPO" --merge --delete-branch 2>/dev/null || {
                TMP="/tmp/mr-$$"
                rm -rf "$TMP"
                BRANCH=$(gh pr view "$PR" --repo "$PREPO" --json headRefName --jq '.headRefName' 2>/dev/null)
                git clone --depth 10 "https://github.com/$PREPO.git" "$TMP" 2>/dev/null
                cd "$TMP" && git fetch origin "$BRANCH" 2>/dev/null
                git merge "origin/$BRANCH" --no-edit --no-gpg-sign 2>/dev/null || {
                    git checkout --theirs . 2>/dev/null; git add -A
                    git commit --no-edit --no-gpg-sign -m "merge: PR #$PR auto-resolved" 2>/dev/null
                }
                git push origin main 2>/dev/null
                gh pr close "$PR" --repo "$PREPO" --delete-branch 2>/dev/null
                cd "$REPO"
                rm -rf "$TMP"
            }
            log "merged PR #$PR on $PREPO"
        done
    done

    # ── CLEAN LEAKED FILES ──
    LEAKED=$(find projects/*/src projects/*/docs -type f -not -name ".gitkeep" -not -name "project.json" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$LEAKED" -gt 0 ]; then
        find projects/*/src projects/*/docs -type f -not -name ".gitkeep" -not -name "project.json" -delete 2>/dev/null
        cd "$REPO"
        git add projects/ 2>/dev/null
        git diff --cached --quiet 2>/dev/null || {
            git commit -m "chore: clean leaked artifact files [skip ci]" --no-gpg-sign 2>&1
            git push origin main 2>&1
        }
        log "cleaned $LEAKED leaked files"
    fi

    # ── SEED LIFECYCLE ──
    cd "$REPO"
    python3 scripts/tally_votes.py 2>/dev/null
    python3 scripts/propose_seed.py auto-lifecycle --min-votes 3 --min-age 2 --stale-frames 10 2>/dev/null
    git add state/seeds.json 2>/dev/null
    git diff --cached --quiet 2>/dev/null || {
        git commit -m "chore: seed lifecycle between cycles [skip ci]" --no-gpg-sign 2>&1
        git push origin main 2>&1
    }

    # ── PULL LATEST ──
    cd "$REPO"
    git pull --rebase origin main 2>/dev/null || true

    log "maintenance done — restarting sim in 60s"

    # Brief pause before restart
    S=0; while [ $S -lt 60 ]; do [ -f "$STOP" ] && break; sleep 10; S=$((S+10)); done
done
