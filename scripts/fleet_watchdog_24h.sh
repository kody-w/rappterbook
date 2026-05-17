#!/usr/bin/env bash
# fleet_watchdog_24h.sh — Keeps ≥1 copilot-infinite orchestrator alive,
# with telemetry feedback loop from state/prompts.jsonl.
set -uo pipefail

REPO="${RAPPTERBOOK_PATH:-/Users/kodyw/Projects/rappterbook}"
HARNESS=/Users/kodyw/Projects/rappter/engine/fleet/copilot-infinite.sh
LOG="$REPO/logs/watchdog.log"
mkdir -p "$REPO/logs"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

[ -f /tmp/rappterbook-autorun-stop ] && exit 0
[ -f /tmp/rappterbook-stop ] && exit 0
if [ -f /tmp/rappterbook-autorun-deadline ]; then
    D=$(cat /tmp/rappterbook-autorun-deadline 2>/dev/null || echo 0)
    [ "$(date +%s)" -gt "$D" ] && exit 0
fi

[ -x "$HARNESS" ] || { log "missing harness"; exit 1; }

LIVE=$(ps -eo pid,ppid,command | awk '/copilot-infinite.sh/ && !/awk/ && $2==1 {c++} END {print c+0}')
COP=$(ps -eo command | grep -c '/Users/kodyw/.local/bin/copilot -p' || echo 0)

RATE_LIMITED=$(tail -100 "$REPO/state/prompts.jsonl" 2>/dev/null | python3 -c "
import json,sys
rl=0
for line in sys.stdin:
    try:
        d=json.loads(line); s=str(d.get('status','')).upper()
        if 'RATE' in s or '429' in s or 'CIRCUIT' in s: rl+=1
    except: pass
print(rl)
" 2>/dev/null || echo 0)

log "live=$LIVE copilot=$COP rate_limited=$RATE_LIMITED/100"

if [ "$RATE_LIMITED" -ge 30 ]; then
    log "back off — rate-limit storm ($RATE_LIMITED/100)"
    exit 0
fi
if [ "$COP" -ge 80 ]; then log "back off — too many copilots"; exit 0; fi
if [ "$LIVE" -ge 1 ]; then log "ok"; exit 0; fi
if [ "$LIVE" -ge 2 ]; then log "at max"; exit 0; fi

log "spawn claude-opus-4.7 orchestrator (smaller — 3 streams)"
cd "$(dirname "$HARNESS")" || exit 1
nohup bash "$HARNESS" --streams 3 --mods 1 --parallel --hours 8 --model claude-opus-4.7 \
    >> "$REPO/logs/sim.log" 2>&1 &
log "spawned pid=$!"
