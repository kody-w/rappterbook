#!/bin/bash
# infinite_doublejump_tick.sh — launchd wrapper for the infinite-doublejump tick.
# Sets PATH for launchd-spawned shells (which inherit a minimal env)
# and writes a one-line summary per tick to /tmp/infinite-doublejump/tail.log.

export PATH="/Users/kodyw/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/kodyw/.pyenv/shims"
export HOME="/Users/kodyw"
set -u

LOG_DIR=/tmp/infinite-doublejump
LOG_TAIL=$LOG_DIR/tail.log
mkdir -p "$LOG_DIR"

TICK_STAMP=$(date -u +%FT%TZ)
TICK_START=$(date +%s)

REPO=/Users/kodyw/Documents/GitHub/Rappter/rappterbook
cd "$REPO"

SUMMARY=$(python3 "$REPO/scripts/infinite_doublejump_tick.py" 2>&1 | tail -1)
TICK_END=$(date +%s)
WALL=$(( TICK_END - TICK_START ))

echo "[$TICK_STAMP wall=${WALL}s] $SUMMARY" >> "$LOG_TAIL"
