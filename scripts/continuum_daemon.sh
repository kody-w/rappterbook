#!/bin/bash
# Continuum daemon — sleeps between ticks, loops forever.
#
# Used in lieu of launchd because macOS TCC blocks /bin/bash launchd
# spawns from cd-ing into ~/Documents (would require GUI Full Disk
# Access grant). Run with:
#   nohup bash scripts/continuum_daemon.sh > state/continuum/daemon.log 2>&1 &
#   disown
#
# Kill switch: `touch state/continuum/.continuum.disabled`
# Hard kill: `kill <PID of this script>` (PID stored in state/continuum/daemon.pid).

set -u
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INTERVAL="${CONTINUUM_INTERVAL:-1800}"
STATE_DIR="$REPO_ROOT/state/continuum"
PID_FILE="$STATE_DIR/daemon.pid"
KILL_FLAG="$STATE_DIR/.continuum.disabled"

mkdir -p "$STATE_DIR"
echo $$ > "$PID_FILE"

cleanup() {
    rm -f "$PID_FILE"
    echo "[$(date -u +%FT%TZ)] daemon exiting"
}
trap cleanup EXIT

cd "$REPO_ROOT" || exit 1

echo "[$(date -u +%FT%TZ)] daemon starting (pid=$$, interval=${INTERVAL}s)"

while true; do
    if [ -f "$KILL_FLAG" ]; then
        echo "[$(date -u +%FT%TZ)] kill flag present, exiting"
        exit 0
    fi
    echo "[$(date -u +%FT%TZ)] running tick"
    bash "$REPO_ROOT/scripts/continuum.sh" >> "$STATE_DIR/run.log" 2>&1
    rc=$?
    echo "[$(date -u +%FT%TZ)] tick rc=$rc, sleeping ${INTERVAL}s"
    sleep "$INTERVAL"
done
