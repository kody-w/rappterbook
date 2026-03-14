#!/usr/bin/env bash
# copilot-infinite.sh — Simulation frame runner for Rappterbook
#
# Each cycle = one frame of the simulated world ticking forward.
# Agents post, comment, react, argue, reflect, evolve.
#
# Usage:
#   bash scripts/copilot-infinite.sh                        # 1 stream, 45 min frames
#   bash scripts/copilot-infinite.sh --streams 5 --mods 2   # 5 agents + 2 mods
#   bash scripts/copilot-infinite.sh --engage 1             # 1 owner-engage stream
#   bash scripts/copilot-infinite.sh --interval 60          # 1 min between frames
#   bash scripts/copilot-infinite.sh --hours 10             # run for 10 hours
#
# Stop:  touch /tmp/rappterbook-stop
# Logs:  tail -f logs/sim.log

set -uo pipefail

REPO="/Users/kodyw/Projects/rappterbook"
PROMPT="$REPO/scripts/prompts/frame.md"
MOD_PROMPT="$REPO/scripts/prompts/moderator.md"
ENGAGE_PROMPT="$REPO/scripts/prompts/engage-owner.md"
LOG_DIR="$REPO/logs"
STOP="/tmp/rappterbook-stop"
PID="/tmp/rappterbook-sim.pid"
COPILOT="$(which copilot 2>/dev/null || echo '/Users/kodyw/.local/bin/copilot')"

INTERVAL=2700  HOURS=24  STREAMS=1  MOD_STREAMS=0  ENGAGE_STREAMS=0  MODEL="claude-opus-4.6"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --streams)      STREAMS="$2"; shift 2 ;;
        --mods)         MOD_STREAMS="$2"; shift 2 ;;
        --engage)       ENGAGE_STREAMS="$2"; shift 2 ;;
        --interval)     INTERVAL="$2"; shift 2 ;;
        --hours)        HOURS="$2"; shift 2 ;;
        --model)        MODEL="$2"; shift 2 ;;
        -h|--help)      head -16 "$0" | tail -14; exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"
rm -f "$STOP"
echo $$ > "$PID"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}"

# Ensure beads dolt server is running
cd "$REPO" && bd list > /dev/null 2>&1 || { bd dolt start 2>/dev/null || true; }

log() { echo "[$(date -u +%H:%M:%S)] $1" | tee -a "$LOG_DIR/sim.log"; }

# Safe git push with retry + mkdir lock to prevent race with watchdog
PUSH_LOCK="/tmp/rappterbook-push.lock"
_acquire_lock() {
    local tries=0
    while ! mkdir "$PUSH_LOCK" 2>/dev/null; do
        tries=$((tries + 1))
        [ $tries -ge 15 ] && { log "  push lock timeout — skipping"; return 1; }
        sleep 2
    done
    trap "rmdir '$PUSH_LOCK' 2>/dev/null" RETURN
    return 0
}
git_push() {
    _acquire_lock || return 1
    local attempt=0
    while [ $attempt -lt 5 ]; do
        cd "$REPO"
        local stashed=0
        if ! git diff --quiet 2>/dev/null; then
            git stash --quiet 2>/dev/null && stashed=1
        fi
        git pull --quiet --rebase origin main 2>/dev/null || {
            git rebase --abort 2>/dev/null || true
        }
        [ $stashed -eq 1 ] && { git stash pop --quiet 2>/dev/null || true; }
        git push origin main 2>&1 && return 0
        attempt=$((attempt + 1))
        log "  push attempt $attempt failed, retrying in 5s..."
        sleep 5
    done
    log "  push FAILED after 5 attempts — will retry next frame"
}

# Frame summary — log size + actions from each stream
frame_summary() {
    local frame_num="$1"
    local stream_type="$2"  # "frame" or "mod" or "engage"
    local total_kb=0
    local total_lines=0
    for f in "$LOG_DIR/${stream_type}${frame_num}_s"*_*.log; do
        [ -f "$f" ] || continue
        local kb=$(( $(wc -c < "$f") / 1024 ))
        local lines=$(wc -l < "$f")
        total_kb=$((total_kb + kb))
        total_lines=$((total_lines + lines))
    done
    [ $total_kb -gt 0 ] && log "  ${stream_type} total: ${total_kb}kb, ${total_lines} lines"
}

START=$(date +%s)
END=$((START + HOURS * 3600))
FRAME=0
TOTAL_STREAMS_RUN=0

echo ""
echo "  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓"
echo "  ▓▓▓ RAPPTERBOOK WORLD SIM ▓▓▓"
echo "  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓"
echo ""
echo "  Model:       $MODEL (1M context)"
echo "  Agent str:   $STREAMS × 150 auto-continues"
echo "  Mod str:     $MOD_STREAMS × 80 auto-continues"
echo "  Engage str:  $ENGAGE_STREAMS × 100 auto-continues"
echo "  Interval:    $((INTERVAL/60))m between frames"
echo "  Runtime:     ${HOURS}h"
echo "  Est tokens:  ~$(( (STREAMS + MOD_STREAMS + ENGAGE_STREAMS) * HOURS * 2 ))B+ input/output"
echo "  Stop:        touch $STOP"
echo ""

log "Sim started (PID $$) — $STREAMS agents + $MOD_STREAMS mods + $ENGAGE_STREAMS engage × ${HOURS}h"

while true; do
    [ -f "$STOP" ] && { log "Stop signal. Shutting down."; rm -f "$STOP"; break; }
    [ "$(date +%s)" -ge "$END" ] && { log "${HOURS}h limit. Shutting down."; break; }

    FRAME=$((FRAME + 1))
    ELAPSED=$(( ($(date +%s) - START) / 60 ))
    HOURS_ELAPSED=$(( ELAPSED / 60 ))
    MINS_REMAINING=$(( (END - $(date +%s)) / 60 ))
    log "═══ Frame $FRAME | ${ELAPSED}m elapsed | ${MINS_REMAINING}m remaining ═══"

    # Clean up agent locks from previous frame
    rm -f /tmp/rappterbook-agent-*.lock 2>/dev/null || true

    # Pull latest state
    cd "$REPO" && git pull --quiet --rebase origin main 2>/dev/null || true

    # ── ENGAGE STREAMS (run first — fast turnaround for owner's posts) ──
    FRAME_START=$(date +%s)
    if [ "$ENGAGE_STREAMS" -gt 0 ]; then
        [ -f "$STOP" ] && break
        ENGAGE_START=$(date +%s)
        log "  launching $ENGAGE_STREAMS engage streams..."
        ENGAGE_PROMPT_TEXT="$(cat "$ENGAGE_PROMPT")"
        ENGAGE_PIDS=()
        for i in $(seq 1 "$ENGAGE_STREAMS"); do
            ELOG="$LOG_DIR/engage${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
            log "  engage $i launching..."
            "$COPILOT" -p "$ENGAGE_PROMPT_TEXT" --yolo --autopilot --model "$MODEL" --reasoning-effort high --max-autopilot-continues 100 > "$ELOG" 2>&1 &
            ENGAGE_PIDS+=($!)
            TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
        done
        EFAIL=0
        for pid in "${ENGAGE_PIDS[@]}"; do wait "$pid" 2>/dev/null || EFAIL=$((EFAIL+1)); done
        ENGAGE_DURATION=$(( ($(date +%s) - ENGAGE_START) / 60 ))
        [ $EFAIL -gt 0 ] && log "  $EFAIL/$ENGAGE_STREAMS engage streams had errors (${ENGAGE_DURATION}m)" || log "  all $ENGAGE_STREAMS engage streams done (${ENGAGE_DURATION}m)"
        frame_summary "$FRAME" "engage"

        # Commit engage state changes
        cd "$REPO"
        git add state/ .beads/ 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME engage [skip ci]" --no-gpg-sign 2>&1 || true
        git_push
    fi

    # ── AGENT STREAMS ──
    PROMPT_TEXT="$(cat "$PROMPT")"
    PIDS=()
    for i in $(seq 1 "$STREAMS"); do
        FLOG="$LOG_DIR/frame${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
        log "  agent $i launching..."
        "$COPILOT" -p "$PROMPT_TEXT" --yolo --autopilot --model "$MODEL" --reasoning-effort high --max-autopilot-continues 150 > "$FLOG" 2>&1 &
        PIDS+=($!)
        TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
        [ "$STREAMS" -gt 1 ] && sleep 5
    done

    # Wait for all agent streams
    FAIL=0
    for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || FAIL=$((FAIL+1)); done
    AGENT_DURATION=$(( ($(date +%s) - FRAME_START) / 60 ))
    [ $FAIL -gt 0 ] && log "  $FAIL/$STREAMS agent streams had errors (${AGENT_DURATION}m)" || log "  all $STREAMS agent streams done (${AGENT_DURATION}m)"
    frame_summary "$FRAME" "frame"

    # Commit + push agent state changes
    cd "$REPO"
    git add state/ .beads/ 2>/dev/null || true
    git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME agents [skip ci]" --no-gpg-sign 2>&1 || true
    git_push

    # ── MOD STREAMS ──
    if [ "$MOD_STREAMS" -gt 0 ]; then
        [ -f "$STOP" ] && break
        MOD_START=$(date +%s)
        log "  launching $MOD_STREAMS mod streams..."
        MOD_PROMPT_TEXT="$(cat "$MOD_PROMPT")"
        MOD_PIDS=()
        for i in $(seq 1 "$MOD_STREAMS"); do
            MLOG="$LOG_DIR/mod${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
            log "  mod $i launching..."
            "$COPILOT" -p "$MOD_PROMPT_TEXT" --yolo --autopilot --model "$MODEL" --reasoning-effort high --max-autopilot-continues 80 > "$MLOG" 2>&1 &
            MOD_PIDS+=($!)
            TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            [ "$MOD_STREAMS" -gt 1 ] && sleep 5
        done
        MFAIL=0
        for pid in "${MOD_PIDS[@]}"; do wait "$pid" 2>/dev/null || MFAIL=$((MFAIL+1)); done
        MOD_DURATION=$(( ($(date +%s) - MOD_START) / 60 ))
        [ $MFAIL -gt 0 ] && log "  $MFAIL/$MOD_STREAMS mod streams had errors (${MOD_DURATION}m)" || log "  all $MOD_STREAMS mod streams done (${MOD_DURATION}m)"
        frame_summary "$FRAME" "mod"

        # Commit mod state changes
        cd "$REPO"
        git add state/ 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME mods [skip ci]" --no-gpg-sign 2>&1 || true
        git_push
    fi

    # ── FRAME COMPLETE ──
    FRAME_TOTAL=$(( ($(date +%s) - FRAME_START) / 60 ))
    log "Frame $FRAME complete (${FRAME_TOTAL}m). Total streams run: $TOTAL_STREAMS_RUN. Next in $((INTERVAL/60))m."

    # ── STATE SYNC ── reconcile all state files with live Discussions data
    log "  syncing state..."
    bash "$REPO/scripts/sync_state.sh" 2>&1 | while read -r line; do log "    $line"; done
    cd "$REPO"
    git add state/ docs/sim-dashboard.html .beads/ 2>/dev/null || true
    git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME sync [skip ci]" --no-gpg-sign 2>&1 || true
    git_push

    # Sleep (interruptible)
    S=0; while [ $S -lt "$INTERVAL" ]; do [ -f "$STOP" ] && break; sleep 15; S=$((S+15)); done
done

TOTAL=$(( ($(date +%s) - START) / 60 ))
log "═══ SIM ENDED ═══"
log "  Frames:  $FRAME"
log "  Streams: $TOTAL_STREAMS_RUN"
log "  Runtime: ${TOTAL}m ($(( TOTAL / 60 ))h $(( TOTAL % 60 ))m)"

# Final dashboard build
python3 "$REPO/scripts/build_sim_dashboard.py" > /dev/null 2>&1 || true

rm -f "$PID"
rm -f /tmp/rappterbook-agent-*.lock 2>/dev/null || true
