#!/usr/bin/env bash
#
# overseer-infinite.sh — role-aware observer harness.
#
# Runs overseer_tick.py on a schedule until stopped. Designed to run on
# ANY machine you own, including machines that are NOT running the
# generator fleet. Multiple overseers across machines are safe (the
# tick is read-only + JSON delta writes).
#
# Key design choice: no LLM calls in the base loop. overseer_tick.py
# is pure stdlib observation. If you want LLM reflection layered on,
# set OVERSEER_REFLECT=1 — it will call `gh copilot` (or your local
# Copilot CLI) between ticks, writing prose to state/overseer/reports/.
#
# Multi-machine pattern:
#   Machine A:  overseer-infinite.sh --role primary --interval 600
#   Machine B:  overseer-infinite.sh --role backup  --interval 900 --offset 300
#   Machine C:  overseer-infinite.sh --role forensic --interval 1800 --file-issues
#
# All three write deltas to state/overseer/ with their MACHINE_ID. The
# append-only history.jsonl is one-line-per-tick and merges cleanly.
#
# Usage:
#   ./scripts/overseer-infinite.sh [options]
#
# Options:
#   --role NAME          Role label written into snapshots (default: primary)
#   --interval SECONDS   Sleep between ticks (default: 900 = 15 min)
#   --offset SECONDS     Delay before first tick (default: 0) — stagger machines
#   --hours HOURS        Stop after HOURS (default: 168 = 1 week)
#   --file-issues        File GitHub issues for critical/high findings (dedup'd)
#   --dry-run            Run observations, log, but do not file issues
#   --once               Run a single tick and exit
#   --machine-id NAME    Override machine identifier (default: $(uname -n))
#
# Stop with Ctrl-C or `kill <PID>`. Idempotent on restart.

set -eo pipefail

ROLE="primary"
INTERVAL=900
OFFSET=0
HOURS=168
FILE_ISSUES=0
DRY_RUN=0
ONCE=0
MACHINE_ID="$(uname -n)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role)        ROLE="$2"; shift 2 ;;
    --interval)    INTERVAL="$2"; shift 2 ;;
    --offset)      OFFSET="$2"; shift 2 ;;
    --hours)       HOURS="$2"; shift 2 ;;
    --file-issues) FILE_ISSUES=1; shift ;;
    --dry-run)     DRY_RUN=1; shift ;;
    --once)        ONCE=1; shift ;;
    --machine-id)  MACHINE_ID="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,40p' "$0"; exit 0 ;;
    *)
      echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export MACHINE_ID
export OVERSEER_FILE_ISSUES="$FILE_ISSUES"
export OVERSEER_DRY_RUN="$DRY_RUN"

log() { echo "[overseer-infinite role=$ROLE machine=$MACHINE_ID] $*"; }

log "starting (interval=${INTERVAL}s, hours=${HOURS}, file-issues=${FILE_ISSUES})"

if [[ "$OFFSET" -gt 0 ]]; then
  log "offset sleep ${OFFSET}s"
  sleep "$OFFSET"
fi

START_TS=$(date +%s)
END_TS=$(( START_TS + HOURS * 3600 ))
TICK=0

# Ensure logs directory exists
mkdir -p "$REPO_ROOT/logs"
LOG_FILE="$REPO_ROOT/logs/overseer-${MACHINE_ID}-${ROLE}.log"

while :; do
  TICK=$(( TICK + 1 ))
  NOW=$(date -u +%FT%TZ)
  log "tick #$TICK at $NOW"

  # Pull latest state (best-effort; observer is tolerant)
  git fetch --quiet origin main 2>>"$LOG_FILE" || true
  git checkout --quiet origin/main -- state/ 2>>"$LOG_FILE" || true

  if python3 scripts/overseer_tick.py 2>&1 | tee -a "$LOG_FILE"; then
    log "tick #$TICK completed"
  else
    log "tick #$TICK FAILED — continuing"
  fi

  # Commit history + latest.json (multi-machine safe via append + atomic save)
  if [[ "$DRY_RUN" != "1" ]]; then
    git add state/overseer/ 2>/dev/null || true
    if ! git diff --cached --quiet 2>/dev/null; then
      git -c user.name="kody-w" \
          -c user.email="kodyw@users.noreply.github.com" \
          commit -m "chore(overseer): tick #$TICK from $MACHINE_ID/$ROLE [skip ci]" \
          >>"$LOG_FILE" 2>&1 || true
      # Use safe_commit fallback if available, else plain push
      if [[ -x scripts/safe_commit.sh ]]; then
        # safe_commit was already called via add+commit+push path elsewhere;
        # here we just try a push with rebase retry.
        for attempt in 1 2 3; do
          if git pull --rebase --quiet origin main >>"$LOG_FILE" 2>&1 && \
             git push --quiet >>"$LOG_FILE" 2>&1; then
            log "pushed tick #$TICK (attempt $attempt)"
            break
          fi
          log "push attempt $attempt failed; retrying"
          sleep $(( attempt * 5 ))
        done
      fi
    fi
  fi

  [[ "$ONCE" == "1" ]] && { log "--once set, exiting"; exit 0; }

  NOW_TS=$(date +%s)
  if [[ "$NOW_TS" -ge "$END_TS" ]]; then
    log "reached $HOURS hours, exiting"
    exit 0
  fi

  log "sleeping ${INTERVAL}s before tick #$((TICK+1))"
  sleep "$INTERVAL"
done
