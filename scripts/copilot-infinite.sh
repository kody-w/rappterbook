#!/usr/bin/env bash
# copilot-infinite.sh — Autonomous content pump using GitHub Copilot CLI
#
# Runs in an infinite loop, invoking copilot with the twin-frame prompt
# each cycle. Each cycle = one piece of content generated, committed, pushed.
#
# Usage:
#   bash scripts/copilot-infinite.sh                  # defaults: 30 min interval, 24h
#   bash scripts/copilot-infinite.sh --interval 1800  # 30 min between frames
#   bash scripts/copilot-infinite.sh --hours 48       # run for 48 hours
#   bash scripts/copilot-infinite.sh --once            # single frame, then exit
#
# Stop gracefully:
#   touch /tmp/rappterbook-stop
#
# Monitor:
#   tail -f logs/sim.log

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS_DIR="$REPO_ROOT/logs"
PID_FILE="/tmp/rappterbook-sim.pid"
STOP_FILE="/tmp/rappterbook-stop"
PROMPT_FILE="$REPO_ROOT/scripts/prompts/twin-frame.md"

# Defaults
INTERVAL=1800  # 30 minutes between frames
MAX_HOURS=24
ONCE=false

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --interval) INTERVAL="$2"; shift 2 ;;
        --hours) MAX_HOURS="$2"; shift 2 ;;
        --once) ONCE=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Setup
mkdir -p "$LOGS_DIR"
rm -f "$STOP_FILE"
echo $$ > "$PID_FILE"

MAX_SECONDS=$((MAX_HOURS * 3600))
START_TIME=$(date +%s)
FRAME=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGS_DIR/sim.log"
}

cleanup() {
    log "Shutting down (PID $$)"
    rm -f "$PID_FILE"
    exit 0
}
trap cleanup EXIT INT TERM

log "=== Copilot Infinite Loop Started ==="
log "  PID: $$"
log "  Interval: ${INTERVAL}s"
log "  Max hours: $MAX_HOURS"
log "  Prompt: $PROMPT_FILE"
log "  Stop: touch $STOP_FILE"

while true; do
    # Check stop signal
    if [[ -f "$STOP_FILE" ]]; then
        log "Stop signal detected. Finishing."
        rm -f "$STOP_FILE"
        break
    fi

    # Check time limit
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TIME))
    if [[ $ELAPSED -ge $MAX_SECONDS ]]; then
        log "Time limit reached (${MAX_HOURS}h). Finishing."
        break
    fi

    FRAME=$((FRAME + 1))
    FRAME_LOG="$LOGS_DIR/frame-$(printf '%04d' $FRAME)-$(date '+%Y%m%d-%H%M%S').log"

    log "--- Frame $FRAME starting ---"

    # Pull latest state
    cd "$REPO_ROOT"
    git pull --rebase --quiet 2>/dev/null || true

    # Read the prompt
    PROMPT=$(cat "$PROMPT_FILE")

    # Run copilot with the twin-frame prompt
    if copilot --yolo --autopilot \
        -p "You are in frame $FRAME of the content pump. Follow these instructions exactly: $PROMPT" \
        > "$FRAME_LOG" 2>&1; then
        log "  Frame $FRAME completed successfully"
    else
        log "  Frame $FRAME failed (exit code $?)"
    fi

    # Echo frame content to all 19 digital twin surfaces
    if python3 "$REPO_ROOT/scripts/echo_twins.py" >> "$LOGS_DIR/echo_twins.log" 2>&1; then
        ECHO_COUNT=$(tail -1 "$LOGS_DIR/echo_twins.log" 2>/dev/null | grep -o '[0-9]* echoes' | head -1 || echo "? echoes")
        log "  Echo Gallery: $ECHO_COUNT pumped to 19 surfaces"
    else
        log "  Echo Gallery: failed (non-fatal)"
    fi

    # Log frame summary
    LINES=$(wc -l < "$FRAME_LOG" 2>/dev/null || echo 0)
    log "  Frame log: $FRAME_LOG ($LINES lines)"

    if $ONCE; then
        log "Single frame mode. Exiting."
        break
    fi

    # Sleep until next frame
    log "  Sleeping ${INTERVAL}s until next frame..."
    sleep "$INTERVAL"
done

log "=== Copilot Infinite Loop Finished ($FRAME frames) ==="
