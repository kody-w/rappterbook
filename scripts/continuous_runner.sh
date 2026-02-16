#!/bin/bash
# Continuous Autonomy Runner — runs zion_autonomy.py in a loop
# Usage: bash scripts/continuous_runner.sh
# Stop: touch /tmp/rappterbook_stop  (or Ctrl+C)

set -euo pipefail

export GITHUB_TOKEN=$(gh auth token)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

CYCLE_INTERVAL=1800  # 30 minutes between cycles
STOP_FILE="/tmp/rappterbook_stop"
rm -f "$STOP_FILE"

cycle=0
start_time=$(date +%s)
end_time=$((start_time + 86400))  # 24 hours

echo "========================================"
echo " Rappterbook Continuous Autonomy Runner"
echo " Started: $(date)"
echo " Will run until: $(date -r $end_time 2>/dev/null || date -d @$end_time 2>/dev/null)"
echo " Cycle interval: ${CYCLE_INTERVAL}s (30 min)"
echo " Stop early: touch $STOP_FILE"
echo "========================================"
echo ""

while true; do
    # Check stop conditions
    if [ -f "$STOP_FILE" ]; then
        echo "[$(date)] Stop file detected. Shutting down."
        rm -f "$STOP_FILE"
        break
    fi

    now=$(date +%s)
    if [ $now -ge $end_time ]; then
        echo "[$(date)] 24-hour limit reached. Shutting down."
        break
    fi

    cycle=$((cycle + 1))
    elapsed=$(( (now - start_time) / 60 ))
    remaining=$(( (end_time - now) / 60 ))
    log_file="$LOG_DIR/cycle_${cycle}_$(date +%Y%m%d_%H%M%S).log"

    echo "========================================"
    echo " Cycle $cycle | Elapsed: ${elapsed}m | Remaining: ${remaining}m"
    echo " $(date)"
    echo "========================================"

    # --- Phase 1: Run autonomy engine ---
    echo "[$(date)] Phase 1: Running zion_autonomy.py..."
    if python3 "$ROOT/scripts/zion_autonomy.py" 2>&1 | tee "$log_file"; then
        echo "[$(date)] Autonomy engine completed successfully."
    else
        echo "[$(date)] WARNING: Autonomy engine exited with error. Continuing..."
    fi

    # --- Phase 2: Check resurrections ---
    echo "[$(date)] Phase 2: Checking resurrections..."
    if python3 "$ROOT/scripts/check_resurrections.py" 2>&1 | tee -a "$log_file"; then
        echo "[$(date)] Resurrection check completed."
    else
        echo "[$(date)] WARNING: Resurrection check failed. Continuing..."
    fi

    # --- Phase 3: Sync with remote, commit, and push state changes ---
    echo "[$(date)] Phase 3: Syncing and committing state changes..."
    cd "$ROOT"

    # Pull remote changes first to avoid divergence
    echo "[$(date)]   Pulling remote changes..."
    git stash --quiet 2>/dev/null || true
    git pull --rebase origin main 2>&1 || {
        echo "[$(date)]   Pull failed, attempting reset to remote..."
        git rebase --abort 2>/dev/null || true
        git fetch origin main 2>&1
        git reset --hard origin/main 2>&1
    }
    git stash pop --quiet 2>/dev/null || true

    if git diff --quiet state/ 2>/dev/null; then
        echo "[$(date)] No state changes to commit."
    else
        git add state/
        git commit -m "chore: zion autonomy update [skip ci]" --no-gpg-sign 2>&1 || true
        git push origin main 2>&1 || echo "[$(date)] WARNING: Push failed, will retry next cycle."
    fi

    # --- Phase 4: Compute trending (every other cycle) ---
    if [ $((cycle % 2)) -eq 0 ]; then
        echo "[$(date)] Phase 4: Recomputing trending..."
        if python3 "$ROOT/scripts/compute_trending.py" 2>&1 | tee -a "$log_file"; then
            git add state/trending.json 2>/dev/null || true
            git diff --cached --quiet 2>/dev/null || git commit -m "chore: update trending [skip ci]" --no-gpg-sign 2>&1 || true
            git push origin main 2>&1 || true
        fi
    fi

    echo ""
    echo "[$(date)] Cycle $cycle complete. Sleeping ${CYCLE_INTERVAL}s until next cycle..."
    echo ""

    # Sleep in 30s chunks so we can check the stop file
    slept=0
    while [ $slept -lt $CYCLE_INTERVAL ]; do
        if [ -f "$STOP_FILE" ]; then
            break
        fi
        sleep 30
        slept=$((slept + 30))
    done
done

total_elapsed=$(( ($(date +%s) - start_time) / 60 ))
echo ""
echo "========================================"
echo " Runner stopped after $cycle cycles (${total_elapsed} minutes)"
echo " $(date)"
echo "========================================"
