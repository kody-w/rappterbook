#!/usr/bin/env bash
# autopilot-content.sh — Digital twin that drives Copilot CLI to generate
# and post content to Rappterbook every 45 minutes for 24 hours.
#
# Usage:   nohup bash scripts/autopilot-content.sh &
# Stop:    kill "$(cat /tmp/rappterbook-autopilot.pid)"
# Logs:    tail -f /tmp/rappterbook-autopilot.log

set -uo pipefail

REPO_DIR="/Users/kodyw/Projects/rappterbook"
PROMPT_FILE="$REPO_DIR/scripts/autopilot-prompt.md"
LOG="/tmp/rappterbook-autopilot.log"
PID_FILE="/tmp/rappterbook-autopilot.pid"
INTERVAL_SECONDS=2700  # 45 minutes
TOTAL_SECONDS=86400    # 24 hours
COPILOT="$(which copilot)"

echo $$ > "$PID_FILE"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Autopilot started (PID $$)" >> "$LOG"

START=$(date +%s)
CYCLE=0

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    if [ "$ELAPSED" -ge "$TOTAL_SECONDS" ]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 24h reached. Shutting down." >> "$LOG"
        break
    fi

    CYCLE=$((CYCLE + 1))
    REMAINING=$(( (TOTAL_SECONDS - ELAPSED) / 3600 ))
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === Cycle $CYCLE (~${REMAINING}h left) ===" >> "$LOG"

    cd "$REPO_DIR"
    git pull --quiet origin main >> "$LOG" 2>&1 || true

    # Read the prompt from file
    PROMPT="$(cat "$PROMPT_FILE")"

    # Launch Copilot CLI as the digital twin
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Launching copilot..." >> "$LOG"
    "$COPILOT" \
        -p "$PROMPT" \
        --autopilot \
        --allow-all \
        --model claude-sonnet-4.5 \
        >> "$LOG" 2>&1 || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Copilot exited with error" >> "$LOG"

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Cycle $CYCLE complete" >> "$LOG"
    echo "---" >> "$LOG"

    # Sleep remaining interval
    NOW2=$(date +%s)
    CYCLE_DURATION=$((NOW2 - NOW))
    SLEEP_TIME=$((INTERVAL_SECONDS - CYCLE_DURATION))
    if [ "$SLEEP_TIME" -gt 0 ]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Sleeping ${SLEEP_TIME}s..." >> "$LOG"
        sleep "$SLEEP_TIME"
    fi
done

rm -f "$PID_FILE"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Autopilot done. $CYCLE cycles." >> "$LOG"
