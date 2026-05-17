#!/usr/bin/env bash
# daemons_watchdog.sh — Restart tock_daemon and program_runtime if dead.
set -uo pipefail
REPO="${RAPPTERBOOK_PATH:-/Users/kodyw/Projects/rappterbook}"
LOG="$REPO/logs/daemons_watchdog.log"
mkdir -p "$REPO/logs"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

[ -f /tmp/rappterbook-autorun-stop ] && exit 0
[ -f /tmp/rappterbook-stop ] && exit 0
if [ -f /tmp/rappterbook-autorun-deadline ]; then
    D=$(cat /tmp/rappterbook-autorun-deadline 2>/dev/null || echo 0)
    [ "$(date +%s)" -gt "$D" ] && exit 0
fi

cd "$REPO" || exit 1

if [ -f scripts/tock_daemon.py ] && ! pgrep -f "scripts/tock_daemon.py" > /dev/null; then
    log "tock_daemon dead — restart"
    nohup python3 scripts/tock_daemon.py > logs/tock_daemon.log 2>&1 &
    log "respawned $!"
fi

if [ -f scripts/program_runtime.py ] && ! pgrep -f "scripts/program_runtime.py --watch" > /dev/null; then
    log "program_runtime dead — restart"
    nohup python3 scripts/program_runtime.py --watch 1.0 > logs/program_runtime.log 2>&1 &
    log "respawned $!"
fi
