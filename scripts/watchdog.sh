#!/usr/bin/env bash
# watchdog.sh — Autonomous babysitter for the sim fleet.
# Runs alongside copilot-infinite.sh to:
#   1. Resolve merge conflicts automatically
#   2. Restart the fleet if it dies
#   3. Push state to remote periodically
#   4. Protect critical files from yolo overwrites
#
# Usage: nohup bash scripts/watchdog.sh > logs/watchdog.log 2>&1 &
# Stop:  touch /tmp/rappterbook-watchdog-stop

set -uo pipefail

REPO="/Users/kodyw/Projects/rappterbook"
LOG="$REPO/logs/watchdog.log"
STOP="/tmp/rappterbook-watchdog-stop"
SIM_PID_FILE="/tmp/rappterbook-sim.pid"
CHECK_INTERVAL=120  # check every 2 minutes

# Critical files that yolo streams must NEVER overwrite
PROTECTED_FILES=(
    "scripts/copilot-infinite.sh"
    "scripts/prompts/frame.md"
    "scripts/prompts/moderator.md"
    "scripts/sync_state.sh"
    "scripts/watchdog.sh"
    "scripts/build_sim_dashboard.py"
    "scripts/update_sim_status.py"
    "CLAUDE.md"
    "AGENTS.md"
    "CONSTITUTION.md"
)

cd "$REPO"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}"

log() { echo "[$(date -u +%H:%M:%S)] [watchdog] $1" | tee -a "$LOG"; }

rm -f "$STOP"

# Snapshot protected files so we can restore them if yolo overwrites
SNAPSHOT_DIR="/tmp/rappterbook-protected"
mkdir -p "$SNAPSHOT_DIR"
for f in "${PROTECTED_FILES[@]}"; do
    if [ -f "$REPO/$f" ]; then
        mkdir -p "$SNAPSHOT_DIR/$(dirname "$f")"
        cp "$REPO/$f" "$SNAPSHOT_DIR/$f"
    fi
done
log "Snapshotted ${#PROTECTED_FILES[@]} protected files"

# Resolve any merge conflicts by keeping both sides for .md, theirs for .json
resolve_conflicts() {
    local conflicts
    conflicts=$(git diff --name-only --diff-filter=U 2>/dev/null)
    [ -z "$conflicts" ] && return 0

    log "Found conflicts, resolving..."
    while IFS= read -r f; do
        if [[ "$f" == *.json ]]; then
            # JSON: take theirs (latest computed)
            git checkout --theirs "$f" 2>/dev/null && git add "$f"
            log "  resolved (theirs): $f"
        elif [[ "$f" == *.md ]]; then
            # Markdown: strip conflict markers, keep both
            sed -i '' '/^<<<<<<< /d; /^=======/d; /^>>>>>>> /d' "$f" 2>/dev/null
            git add "$f"
            log "  resolved (both): $f"
        else
            git checkout --theirs "$f" 2>/dev/null && git add "$f"
            log "  resolved (theirs): $f"
        fi
    done <<< "$conflicts"

    git rebase --continue 2>/dev/null || git commit -m "chore: watchdog resolved merge conflicts [skip ci]" --no-gpg-sign 2>/dev/null || true
    log "Conflicts resolved"
}

# Check if protected files were overwritten and restore them
protect_files() {
    local restored=0
    for f in "${PROTECTED_FILES[@]}"; do
        if [ -f "$SNAPSHOT_DIR/$f" ] && [ -f "$REPO/$f" ]; then
            if ! diff -q "$SNAPSHOT_DIR/$f" "$REPO/$f" > /dev/null 2>&1; then
                cp "$SNAPSHOT_DIR/$f" "$REPO/$f"
                git add "$REPO/$f" 2>/dev/null
                log "  RESTORED protected file: $f (yolo stream overwrote it)"
                restored=$((restored + 1))
            fi
        fi
    done
    if [ $restored -gt 0 ]; then
        git commit -m "chore: watchdog restored $restored protected files [skip ci]" --no-gpg-sign 2>/dev/null || true
    fi
}

# Check if sim is alive and restart if dead
check_sim() {
    if [ -f "$SIM_PID_FILE" ]; then
        local pid
        pid=$(cat "$SIM_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0  # running
        fi
    fi
    return 1  # dead
}

restart_sim() {
    log "SIM IS DEAD — restarting fleet..."
    rm -f /tmp/rappterbook-stop 2>/dev/null
    rm -f /tmp/rappterbook-agent-*.lock 2>/dev/null || true
    nohup bash "$REPO/scripts/copilot-infinite.sh" --streams 5 --mods 2 --interval 60 --hours 10 > "$REPO/logs/sim.log" 2>&1 &
    sleep 3
    local new_pid
    new_pid=$(cat "$SIM_PID_FILE" 2>/dev/null)
    log "Fleet restarted (PID $new_pid)"
}

log "Watchdog started"
log "Checking every ${CHECK_INTERVAL}s"

while true; do
    [ -f "$STOP" ] && { log "Stop signal. Exiting."; rm -f "$STOP"; break; }

    cd "$REPO"

    # 1. Resolve any pending merge conflicts
    resolve_conflicts

    # 2. Protect critical files from yolo overwrites
    protect_files

    # 3. Check sim health, restart if dead
    if ! check_sim; then
        restart_sim
    fi

    # 4. Try to push any uncommitted state (locked to avoid race with sim)
    PUSH_LOCK="/tmp/rappterbook-push.lock"
    git add state/ .beads/ docs/sim-dashboard.html 2>/dev/null || true
    git diff --cached --quiet 2>/dev/null || {
        git commit -m "chore: watchdog state sync [skip ci]" --no-gpg-sign 2>/dev/null || true
        lock_tries=0
        while ! mkdir "$PUSH_LOCK" 2>/dev/null; do
            lock_tries=$((lock_tries + 1))
            [ $lock_tries -ge 15 ] && { log "push lock timeout — skipping"; break; }
            sleep 2
        done
        if [ -d "$PUSH_LOCK" ]; then
            stashed=0
            if ! git diff --quiet 2>/dev/null; then
                git stash --quiet 2>/dev/null && stashed=1
            fi
            git pull --quiet --rebase origin main 2>/dev/null || {
                git rebase --abort 2>/dev/null || true
            }
            if [ $stashed -eq 1 ]; then
                if ! git stash pop --quiet 2>/dev/null; then
                    log "WARNING: stash pop conflict — backing up conflicted files"
                    for f in $(git diff --name-only --diff-filter=U 2>/dev/null); do
                        cp "$f" "/tmp/rappterbook-conflict-$(basename "$f")-$(date +%s)" 2>/dev/null
                    done
                    git checkout --theirs state/memory/ 2>/dev/null
                    git checkout --ours state/*.json 2>/dev/null
                    git add -A 2>/dev/null
                    git stash drop 2>/dev/null || true
                fi
            fi
            resolve_conflicts
            push_ok=0
            for pa in 1 2 3; do
                git push origin main 2>/dev/null && { push_ok=1; break; }
                log "  push attempt $pa failed, retrying in 5s..."
                sleep 5
                git pull --quiet --rebase origin main 2>/dev/null || true
            done
            [ $push_ok -eq 0 ] && log "  watchdog push FAILED — will retry next cycle"
            rmdir "$PUSH_LOCK" 2>/dev/null || true
        fi
    }

    sleep "$CHECK_INTERVAL"
done

log "Watchdog exited"
