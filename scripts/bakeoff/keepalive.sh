#!/usr/bin/env bash
# Bakeoff keepalive — runs one bakeoff round, sleeps, repeats. Forever.
#
# This is the server-side heartbeat. Even if the Claude session driving
# meta-review goes idle, this loop keeps producing generations + mutations
# at a steady cadence. Crashes are logged and the loop restarts.
#
# Cadence: BAKEOFF_INTERVAL_SECS (default 240 = 4 min between rounds).
# Stops cleanly on SIGTERM / SIGINT.

set -u

REPO="${REPO:-/Users/kodywildfeuer/Documents/GitHub/rappterbook}"
INTERVAL="${BAKEOFF_INTERVAL_SECS:-240}"
LOG="$REPO/state/bakeoff/logs/keepalive.log"
PIDFILE="$REPO/state/bakeoff/keepalive.pid"
# Neighborhood-discoverable rapp pid (per <slug>_<pid>_rap.pid convention —
# noun is "rapp" everywhere; `_rap.pid` filename suffix uses one p for
# readability only). The pid in the filename IS the session rappid —
# alive while the process is.
RAP_SLUG="${RAP_SLUG:-bakeoff_daemon}"
RAP_PIDS_DIR="${RAPP_PIDS_DIR:-$HOME/.rapp/pids}"
RAP_PIDFILE="$RAP_PIDS_DIR/${RAP_SLUG}_${$}_rap.pid"

mkdir -p "$REPO/state/bakeoff/logs"
mkdir -p "$RAP_PIDS_DIR"
echo $$ > "$PIDFILE"
echo $$ > "$RAP_PIDFILE"

cleanup() {
    echo "[$(date -u +%FT%TZ)] keepalive: shutting down (pid $$)" >> "$LOG"
    rm -f "$PIDFILE"
    rm -f "$RAP_PIDFILE"
    exit 0
}
trap cleanup TERM INT

cd "$REPO" || exit 1

echo "[$(date -u +%FT%TZ)] keepalive: starting (interval=${INTERVAL}s, pid $$)" >> "$LOG"

round=0
while true; do
    round=$((round + 1))
    start=$(date -u +%FT%TZ)
    echo "" >> "$LOG"
    echo "── ROUND $round @ $start ───────────────────────" >> "$LOG"

    # Run one round; capture exit + output
    if python3 -m scripts.bakeoff.runner >> "$LOG" 2>&1; then
        status="ok"
    else
        rc=$?
        status="FAIL rc=$rc"
        echo "[$(date -u +%FT%TZ)] keepalive: round $round FAILED (rc=$rc); backing off 60s" >> "$LOG"
        sleep 60
    fi

    # Refresh the estate + leviathan dashboard snapshots
    python3 scripts/export_estate.py >> "$LOG" 2>&1 || true
    python3 scripts/export_leviathan.py >> "$LOG" 2>&1 || true

    # Push bakeoff publications to the live public homepage. Bails fast
    # if no new publications since last push; safe to call every round.
    bash "$REPO/scripts/bakeoff/publish_to_public.sh" >> "$LOG" 2>&1 || true

    echo "[$(date -u +%FT%TZ)] keepalive: round $round done ($status); sleeping ${INTERVAL}s" >> "$LOG"
    sleep "$INTERVAL"
done
