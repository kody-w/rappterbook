#!/usr/bin/env bash
# Continuum tick — wraps continuum_pulse.py with safe defaults for launchd.
#
# Called by ~/Library/LaunchAgents/com.rappterbook.continuum.plist on a
# schedule (every 30 minutes). Idempotent. Logs to state/continuum/run.log.
set -euo pipefail

REPO="/Users/kodyw/Documents/GitHub/Rappter/rappterbook"
LOG_DIR="$REPO/state/continuum"
LOG="$LOG_DIR/run.log"

mkdir -p "$LOG_DIR"

cd "$REPO"

# Don't run while a vBANK lock or similar is asserting; same convention as
# other scripts in this repo.
if [ -f "$REPO/.continuum.disabled" ]; then
    echo "[$(date -u +%FT%TZ)] continuum disabled by flag file — exit" >> "$LOG"
    exit 0
fi

# Make sure a recent python is on PATH for /usr/bin/env shebangs
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PY="$(command -v python3)"
echo "[$(date -u +%FT%TZ)] tick starting (python=$PY)" >> "$LOG"

# Run with a hard timeout so we don't hang launchd
( "$PY" "$REPO/scripts/continuum_pulse.py" ) >> "$LOG" 2>&1 &
PID=$!

# 25 minute hard ceiling
WAIT=1500
while [ $WAIT -gt 0 ] && kill -0 "$PID" 2>/dev/null; do
    sleep 5
    WAIT=$((WAIT-5))
done
if kill -0 "$PID" 2>/dev/null; then
    echo "[$(date -u +%FT%TZ)] tick exceeded 25min — killing $PID" >> "$LOG"
    kill -9 "$PID" 2>/dev/null || true
fi
wait "$PID" 2>/dev/null || true

echo "[$(date -u +%FT%TZ)] tick finished" >> "$LOG"
