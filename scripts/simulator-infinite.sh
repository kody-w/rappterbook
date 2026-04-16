#!/usr/bin/env bash
#
# simulator-infinite.sh — local simulator loop.
#
# Wraps scripts/mars_colony.py (existing) in a scheduled loop, committing
# one Martian sol per tick. Runs locally, does not touch Discussions.
# Safe to leave running for weeks on any machine.
#
# The Mars colony sim is self-contained: real weather from twin_echoes,
# real resource mechanics, real colonist deaths (archived to graveyard).
# This harness just advances time on a cadence.
#
# Usage:
#   ./scripts/simulator-infinite.sh [options]
#
# Options:
#   --sol-interval SEC   Real seconds between sols (default: 3600 = 1 sol/hour)
#   --hours HOURS        Stop after HOURS (default: 168)
#   --once               Advance one sol and exit
#   --machine-id NAME    Override machine identifier
#   --sim NAME           Simulator to run (default: mars_colony)

set -eo pipefail

INTERVAL=3600
HOURS=168
ONCE=0
MACHINE_ID="$(uname -n)"
SIM="mars_colony"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sol-interval|--interval) INTERVAL="$2"; shift 2 ;;
    --hours)      HOURS="$2"; shift 2 ;;
    --once)       ONCE=1; shift ;;
    --machine-id) MACHINE_ID="$2"; shift 2 ;;
    --sim)        SIM="$2"; shift 2 ;;
    -h|--help)    sed -n '2,25p' "$0"; exit 0 ;;
    *)            echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SIM_SCRIPT="$REPO_ROOT/scripts/${SIM}.py"
if [[ ! -f "$SIM_SCRIPT" ]]; then
  echo "simulator not found: $SIM_SCRIPT" >&2
  exit 2
fi

mkdir -p "$REPO_ROOT/logs"
LOG_FILE="$REPO_ROOT/logs/simulator-${SIM}-${MACHINE_ID}.log"

log() { echo "[simulator sim=$SIM machine=$MACHINE_ID] $*"; }

log "starting (interval=${INTERVAL}s hours=$HOURS)"

START_TS=$(date +%s)
END_TS=$(( START_TS + HOURS * 3600 ))
TICK=0

while :; do
  TICK=$(( TICK + 1 ))
  log "sol tick #$TICK $(date -u +%FT%TZ)"

  # Refresh state before advancing (the sim modifies state files)
  git fetch --quiet origin main 2>>"$LOG_FILE" || true
  git checkout --quiet origin/main -- "state/${SIM}/" 2>>"$LOG_FILE" || true

  set +e
  python3 "$SIM_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
  rc=${PIPESTATUS[0]}
  set -e
  if [[ "$rc" != "0" ]]; then
    log "sim rc=$rc — continuing"
  fi

  # Commit only the sim's own state subtree to avoid fleet conflicts
  SIM_DIR="state/${SIM}"
  git add "$SIM_DIR" 2>/dev/null || true
  if ! git diff --cached --quiet "$SIM_DIR" 2>/dev/null; then
    git -c user.name="kody-w" -c user.email="kodyw@users.noreply.github.com" \
        commit -m "sim(${SIM}): sol tick #$TICK from $MACHINE_ID [skip ci]" \
        >>"$LOG_FILE" 2>&1 || true
    for attempt in 1 2 3; do
      if git pull --rebase --quiet origin main >>"$LOG_FILE" 2>&1 && \
         git push --quiet >>"$LOG_FILE" 2>&1; then
        break
      fi
      sleep $(( attempt * 5 ))
    done
  fi

  [[ "$ONCE" == "1" ]] && { log "--once set, exiting"; exit 0; }

  NOW_TS=$(date +%s)
  [[ "$NOW_TS" -ge "$END_TS" ]] && { log "hit $HOURS hours, exiting"; exit 0; }

  sleep "$INTERVAL"
done
