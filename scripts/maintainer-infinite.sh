#!/usr/bin/env bash
#
# maintainer-infinite.sh — grunt-work harness.
#
# Runs maintainer_tick.py on a schedule. Each tick processes ONE pending
# ticket from state/maintainer_queue.json by spawning `copilot -p` in a
# throwaway git worktree and opening a PR with the result.
#
# This is the maintainer lane. Unlike the generator fleet, it does
# not hit GitHub's comment-throttle — it creates commits and PRs, which
# have much higher rate limits.
#
# Safe on multiple machines: claim_ticket() in maintainer_tick.py is an
# atomic state write. Two workers can race safely — the second will see
# the first's in_progress flag and skip to the next pending ticket.
#
# Usage:
#   ./scripts/maintainer-infinite.sh [options]
#
# Options:
#   --interval SECONDS   Sleep between ticks (default: 600)
#   --hours HOURS        Stop after HOURS (default: 168)
#   --model NAME         Copilot model (default: claude-opus-4.7)
#   --timeout SECONDS    Per-ticket timeout (default: 1800)
#   --dry-run            Plan only, no copilot invocation
#   --once               Process a single ticket and exit
#   --machine-id NAME    Override machine identifier

set -eo pipefail

INTERVAL=600
HOURS=168
MODEL="claude-opus-4.7"
TIMEOUT=1800
DRY_RUN=0
ONCE=0
MACHINE_ID="$(uname -n)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval)   INTERVAL="$2"; shift 2 ;;
    --hours)      HOURS="$2"; shift 2 ;;
    --model)      MODEL="$2"; shift 2 ;;
    --timeout)    TIMEOUT="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --once)       ONCE=1; shift ;;
    --machine-id) MACHINE_ID="$2"; shift 2 ;;
    -h|--help)    sed -n '2,30p' "$0"; exit 0 ;;
    *)            echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export MACHINE_ID
export MAINTAINER_MODEL="$MODEL"
export MAINTAINER_TIMEOUT="$TIMEOUT"
export MAINTAINER_DRY_RUN="$DRY_RUN"

mkdir -p "$REPO_ROOT/logs"
LOG_FILE="$REPO_ROOT/logs/maintainer-${MACHINE_ID}.log"

log() { echo "[maintainer-infinite machine=$MACHINE_ID] $*"; }

log "starting (model=$MODEL interval=${INTERVAL}s hours=$HOURS timeout=${TIMEOUT}s)"

START_TS=$(date +%s)
END_TS=$(( START_TS + HOURS * 3600 ))
TICK=0
IDLE_STREAK=0

while :; do
  TICK=$(( TICK + 1 ))
  log "tick #$TICK $(date -u +%FT%TZ)"

  # Pull latest queue state
  git fetch --quiet origin main 2>>"$LOG_FILE" || true
  git checkout --quiet origin/main -- state/maintainer_queue.json 2>>"$LOG_FILE" || true

  set +e
  python3 scripts/maintainer_tick.py 2>&1 | tee -a "$LOG_FILE"
  rc=${PIPESTATUS[0]}
  set -e

  case "$rc" in
    0) IDLE_STREAK=0; log "tick #$TICK processed a ticket" ;;
    1) IDLE_STREAK=$(( IDLE_STREAK + 1 )); log "tick #$TICK idle (streak=$IDLE_STREAK)" ;;
    *) log "tick #$TICK fatal rc=$rc — continuing" ;;
  esac

  # Commit queue state if changed (don't touch other state)
  if [[ "$DRY_RUN" != "1" ]]; then
    git add state/maintainer_queue.json 2>/dev/null || true
    if ! git diff --cached --quiet state/maintainer_queue.json 2>/dev/null; then
      git -c user.name="kody-w" -c user.email="kodyw@users.noreply.github.com" \
          commit -m "chore(maintainer): tick #$TICK queue update from $MACHINE_ID [skip ci]" \
          >>"$LOG_FILE" 2>&1 || true
      for attempt in 1 2 3; do
        if git pull --rebase --quiet origin main >>"$LOG_FILE" 2>&1 && \
           git push --quiet >>"$LOG_FILE" 2>&1; then
          break
        fi
        sleep $(( attempt * 5 ))
      done
    fi
  fi

  [[ "$ONCE" == "1" ]] && { log "--once set, exiting"; exit 0; }

  NOW_TS=$(date +%s)
  [[ "$NOW_TS" -ge "$END_TS" ]] && { log "hit $HOURS hours, exiting"; exit 0; }

  # Back off when queue is idle (avoid busy-looping on empty queue)
  SLEEP=$INTERVAL
  if [[ "$IDLE_STREAK" -ge 3 ]]; then
    SLEEP=$(( INTERVAL * 2 ))
    log "backing off to ${SLEEP}s (idle streak=$IDLE_STREAK)"
  fi
  sleep "$SLEEP"
done
