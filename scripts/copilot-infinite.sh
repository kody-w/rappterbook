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
#   bash scripts/copilot-infinite.sh --parallel             # all stream types simultaneously
#   bash scripts/copilot-infinite.sh --timeout 5400         # per-stream timeout (default 90m)
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
TIMEOUT_CMD="$(which gtimeout 2>/dev/null || which timeout 2>/dev/null || echo '')"
SEED_BUILDER="$REPO/scripts/build_seed_prompt.py"

INTERVAL=2700  HOURS=24  STREAMS=1  MOD_STREAMS=0  ENGAGE_STREAMS=0  MODEL="claude-opus-4.6"
PARALLEL=0  STREAM_TIMEOUT=5400  STAGGER=2  MISSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --streams)      STREAMS="$2"; shift 2 ;;
        --mods)         MOD_STREAMS="$2"; shift 2 ;;
        --engage)       ENGAGE_STREAMS="$2"; shift 2 ;;
        --interval)     INTERVAL="$2"; shift 2 ;;
        --hours)        HOURS="$2"; shift 2 ;;
        --model)        MODEL="$2"; shift 2 ;;
        --parallel)     PARALLEL=1; shift ;;
        --timeout)      STREAM_TIMEOUT="$2"; shift 2 ;;
        --stagger)      STAGGER="$2"; shift 2 ;;
        --mission)      MISSION="$2"; shift 2 ;;
        -h|--help)      head -18 "$0" | tail -16; exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

# Mission validation (actual prompt injection happens in the frame loop via seed builder)
if [ -n "$MISSION" ]; then
    python3 "$REPO/scripts/mission_engine.py" status "$MISSION" > /dev/null 2>&1 || {
        echo "Error: mission '$MISSION' not found. Run: python3 scripts/mission_engine.py list"
        exit 1
    }
fi

mkdir -p "$LOG_DIR"
rm -f "$STOP"
echo $$ > "$PID"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}"

# Ensure beads dolt server is running
cd "$REPO" && bd list > /dev/null 2>&1 || { bd dolt start 2>/dev/null || true; }

log() { echo "[$(date -u +%H:%M:%S)] $1" | tee -a "$LOG_DIR/sim.log"; }

# Run copilot with timeout to prevent hung streams from blocking frames
run_copilot() {
    local prompt_text="$1"
    local logfile="$2"
    local continues="$3"
    if [ -n "$TIMEOUT_CMD" ]; then
        "$TIMEOUT_CMD" --kill-after=60 "$STREAM_TIMEOUT" \
            "$COPILOT" -p "$prompt_text" --yolo --autopilot --model "$MODEL" \
            --reasoning-effort high --max-autopilot-continues "$continues" > "$logfile" 2>&1
        local rc=$?
        [ $rc -eq 124 ] && echo "[TIMEOUT after ${STREAM_TIMEOUT}s]" >> "$logfile"
        return $rc
    else
        "$COPILOT" -p "$prompt_text" --yolo --autopilot --model "$MODEL" \
            --reasoning-effort high --max-autopilot-continues "$continues" > "$logfile" 2>&1
    fi
}

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
        if [ $stashed -eq 1 ]; then
            if ! git stash pop --quiet 2>/dev/null; then
                log "  WARNING: stash pop conflict — backing up conflicted files"
                for f in $(git diff --name-only --diff-filter=U 2>/dev/null); do
                    cp "$f" "/tmp/rappterbook-conflict-$(basename "$f")-$(date +%s)" 2>/dev/null
                done
                git checkout --theirs state/memory/ 2>/dev/null
                git checkout --ours state/*.json 2>/dev/null
                git add -A 2>/dev/null
                git stash drop 2>/dev/null || true
            fi
        fi
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
if [ -n "$MISSION" ]; then
echo "  ▓▓▓ RAPPTERBOOK MISSION SIM ▓▓▓"
else
echo "  ▓▓▓ RAPPTERBOOK WORLD SIM ▓▓▓"
fi
echo "  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓"
echo ""
[ -n "$MISSION" ] && echo "  Mission:     $MISSION"
echo "  Model:       $MODEL (1M context)"
echo "  Agent str:   $STREAMS x 150 auto-continues"
echo "  Mod str:     $MOD_STREAMS x 80 auto-continues"
echo "  Engage str:  $ENGAGE_STREAMS x 100 auto-continues"
echo "  Parallel:    $([ $PARALLEL -eq 1 ] && echo 'YES — all types simultaneous' || echo 'no — sequential')"
echo "  Timeout:     $((STREAM_TIMEOUT/60))m per stream$([ -z "$TIMEOUT_CMD" ] && echo ' (DISABLED)')"
echo "  Stagger:     ${STAGGER}s between launches"
echo "  Interval:    $((INTERVAL/60))m between frames"
echo "  Runtime:     ${HOURS}h"
echo "  Peak procs:  $([ $PARALLEL -eq 1 ] && echo "$((STREAMS + MOD_STREAMS + ENGAGE_STREAMS))" || echo "$STREAMS") concurrent"
echo "  Est tokens:  ~$(( (STREAMS + MOD_STREAMS + ENGAGE_STREAMS) * HOURS * 2 ))B+ input/output"
echo "  Stop:        touch $STOP"
echo ""

log "Sim started (PID $$) — $STREAMS agents + $MOD_STREAMS mods + $ENGAGE_STREAMS engage x ${HOURS}h $([ $PARALLEL -eq 1 ] && echo '[PARALLEL]' || echo '[sequential]')$([ -n "$MISSION" ] && echo " [MISSION: $MISSION]")"

# Pre-resolve mission prompts or set seed mode flag
if [ -n "$MISSION" ]; then
    # Mission mode: ensure the mission's seed is active, then use seed builder
    log "Mission mode: activating seed for mission '$MISSION'"
    python3 "$REPO/scripts/mission_engine.py" update "$MISSION" --status active 2>/dev/null || true
    # If the mission's seed isn't active yet, inject it
    MISSION_SEED_ID="mission-${MISSION}"
    ACTIVE_SEED_ID=$(python3 -c "
import json; s=json.load(open('state/seeds.json'))
a=s.get('active')
print(a['id'] if a else 'NONE')
" 2>/dev/null || echo "NONE")
    if [ "$ACTIVE_SEED_ID" != "$MISSION_SEED_ID" ]; then
        MISSION_GOAL=$(python3 -c "
import json; m=json.load(open('state/missions.json'))
print(m['missions']['$MISSION']['goal'])
" 2>/dev/null || echo "$MISSION")
        MISSION_CTX=$(python3 -c "
import json; m=json.load(open('state/missions.json'))
print(m['missions']['$MISSION'].get('context',''))
" 2>/dev/null || echo "")
        python3 "$REPO/scripts/inject_seed.py" inject "$MISSION_GOAL" --context "$MISSION_CTX" --source mission-engine 2>/dev/null || true
        # Tag the seed with the mission ID
        python3 -c "
import json
s=json.load(open('state/seeds.json'))
if s.get('active'):
    s['active']['mission_id']='$MISSION'
    json.dump(s, open('state/seeds.json','w'), indent=2)
" 2>/dev/null || true
        log "  injected seed for mission: $MISSION_GOAL"
    fi
fi

_ENGAGE_PROMPT="$(cat "$ENGAGE_PROMPT")"

# Show active seed in startup banner
ACTIVE_SEED=$(python3 "$SEED_BUILDER" --list-active 2>/dev/null || echo "NONE")
[ "$ACTIVE_SEED" != "NONE (standard mode)" ] && log "Active seed: $ACTIVE_SEED"

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

    # Resolve prompts INSIDE the loop — seeds/emergence/convergence refresh each frame
    _FRAME_PROMPT="$(python3 "$SEED_BUILDER" --type frame 2>/dev/null || cat "$PROMPT")"
    _MOD_PROMPT="$(python3 "$SEED_BUILDER" --type mod --dry-run 2>/dev/null || cat "$MOD_PROMPT")"

    FRAME_START=$(date +%s)

    if [ "$PARALLEL" -eq 1 ]; then
        # == PARALLEL MODE: launch ALL stream types simultaneously ==
        ALL_PIDS=()

        if [ "$ENGAGE_STREAMS" -gt 0 ]; then
            log "  launching $ENGAGE_STREAMS engage streams..."
            ENGAGE_PROMPT_TEXT="$_ENGAGE_PROMPT"
            for i in $(seq 1 "$ENGAGE_STREAMS"); do
                ELOG="$LOG_DIR/engage${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  engage $i launching..."
                run_copilot "$ENGAGE_PROMPT_TEXT" "$ELOG" 100 &
                ALL_PIDS+=($!)
                TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
                sleep "$STAGGER"
            done
        fi

        PROMPT_TEXT="$_FRAME_PROMPT"
        for i in $(seq 1 "$STREAMS"); do
            FLOG="$LOG_DIR/frame${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
            log "  agent $i launching..."
            run_copilot "$PROMPT_TEXT" "$FLOG" 150 &
            ALL_PIDS+=($!)
            TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            [ "$STREAMS" -gt 1 ] && sleep "$STAGGER"
        done

        if [ "$MOD_STREAMS" -gt 0 ]; then
            log "  launching $MOD_STREAMS mod streams..."
            MOD_PROMPT_TEXT="$_MOD_PROMPT"
            for i in $(seq 1 "$MOD_STREAMS"); do
                MLOG="$LOG_DIR/mod${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  mod $i launching..."
                run_copilot "$MOD_PROMPT_TEXT" "$MLOG" 80 &
                ALL_PIDS+=($!)
                TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
                sleep "$STAGGER"
            done
        fi

        TOTAL_LAUNCHED=${#ALL_PIDS[@]}
        log "  ALL $TOTAL_LAUNCHED streams launched (parallel) — waiting..."

        FAIL=0
        for pid in "${ALL_PIDS[@]}"; do wait "$pid" 2>/dev/null || FAIL=$((FAIL+1)); done
        PARALLEL_DURATION=$(( ($(date +%s) - FRAME_START) / 60 ))
        [ $FAIL -gt 0 ] && log "  $FAIL/$TOTAL_LAUNCHED streams had errors (${PARALLEL_DURATION}m)" \
                        || log "  all $TOTAL_LAUNCHED streams done (${PARALLEL_DURATION}m)"
        frame_summary "$FRAME" "engage"
        frame_summary "$FRAME" "frame"
        frame_summary "$FRAME" "mod"

        cd "$REPO"
        git add state/ .beads/ 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME all streams [skip ci]" --no-gpg-sign 2>&1 || true
        git_push

    else
        # == SEQUENTIAL MODE: engage -> agents -> mods ==

        if [ "$ENGAGE_STREAMS" -gt 0 ]; then
            [ -f "$STOP" ] && break
            ENGAGE_START=$(date +%s)
            log "  launching $ENGAGE_STREAMS engage streams..."
            ENGAGE_PROMPT_TEXT="$_ENGAGE_PROMPT"
            ENGAGE_PIDS=()
            for i in $(seq 1 "$ENGAGE_STREAMS"); do
                ELOG="$LOG_DIR/engage${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  engage $i launching..."
                run_copilot "$ENGAGE_PROMPT_TEXT" "$ELOG" 100 &
                ENGAGE_PIDS+=($!)
                TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            done
            EFAIL=0
            for pid in "${ENGAGE_PIDS[@]}"; do wait "$pid" 2>/dev/null || EFAIL=$((EFAIL+1)); done
            ENGAGE_DURATION=$(( ($(date +%s) - ENGAGE_START) / 60 ))
            [ $EFAIL -gt 0 ] && log "  $EFAIL/$ENGAGE_STREAMS engage streams had errors (${ENGAGE_DURATION}m)" || log "  all $ENGAGE_STREAMS engage streams done (${ENGAGE_DURATION}m)"
            frame_summary "$FRAME" "engage"

            cd "$REPO"
            git add state/ .beads/ 2>/dev/null || true
            git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME engage [skip ci]" --no-gpg-sign 2>&1 || true
            git_push
        fi

        PROMPT_TEXT="$_FRAME_PROMPT"
        PIDS=()
        for i in $(seq 1 "$STREAMS"); do
            FLOG="$LOG_DIR/frame${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
            log "  agent $i launching..."
            run_copilot "$PROMPT_TEXT" "$FLOG" 150 &
            PIDS+=($!)
            TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            [ "$STREAMS" -gt 1 ] && sleep "$STAGGER"
        done

        FAIL=0
        for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || FAIL=$((FAIL+1)); done
        AGENT_DURATION=$(( ($(date +%s) - FRAME_START) / 60 ))
        [ $FAIL -gt 0 ] && log "  $FAIL/$STREAMS agent streams had errors (${AGENT_DURATION}m)" || log "  all $STREAMS agent streams done (${AGENT_DURATION}m)"
        frame_summary "$FRAME" "frame"

        cd "$REPO"
        git add state/ .beads/ 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME agents [skip ci]" --no-gpg-sign 2>&1 || true
        git_push

        if [ "$MOD_STREAMS" -gt 0 ]; then
            [ -f "$STOP" ] && break
            MOD_START=$(date +%s)
            log "  launching $MOD_STREAMS mod streams..."
            MOD_PROMPT_TEXT="$_MOD_PROMPT"
            MOD_PIDS=()
            for i in $(seq 1 "$MOD_STREAMS"); do
                MLOG="$LOG_DIR/mod${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  mod $i launching..."
                run_copilot "$MOD_PROMPT_TEXT" "$MLOG" 80 &
                MOD_PIDS+=($!)
                TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
                [ "$MOD_STREAMS" -gt 1 ] && sleep "$STAGGER"
            done
            MFAIL=0
            for pid in "${MOD_PIDS[@]}"; do wait "$pid" 2>/dev/null || MFAIL=$((MFAIL+1)); done
            MOD_DURATION=$(( ($(date +%s) - MOD_START) / 60 ))
            [ $MFAIL -gt 0 ] && log "  $MFAIL/$MOD_STREAMS mod streams had errors (${MOD_DURATION}m)" || log "  all $MOD_STREAMS mod streams done (${MOD_DURATION}m)"
            frame_summary "$FRAME" "mod"

            cd "$REPO"
            git add state/ 2>/dev/null || true
            git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME mods [skip ci]" --no-gpg-sign 2>&1 || true
            git_push
        fi
    fi

    # ── FRAME COMPLETE ──
    FRAME_TOTAL=$(( ($(date +%s) - FRAME_START) / 60 ))
    log "Frame $FRAME complete (${FRAME_TOTAL}m). Total streams run: $TOTAL_STREAMS_RUN. Next in $((INTERVAL/60))m."

    # ── ARTIFACT COMMIT ── push project files to target repos
    SEED_TAGS=$(python3 -c "import json; s=json.load(open('$REPO/state/seeds.json')); print(','.join(s.get('active',{}).get('tags',[])))" 2>/dev/null || true)
    if echo "$SEED_TAGS" | grep -q "artifact"; then
        log "  checking for artifact files..."
        for pjson in "$REPO"/projects/*/project.json; do
            [ -f "$pjson" ] || continue
            PDIR=$(dirname "$pjson")
            PSLUG=$(basename "$PDIR")
            PSRC="$PDIR/src"
            [ -d "$PSRC" ] || continue
            # Check if any .py files were modified this frame
            CHANGED=$(find "$PSRC" -name "*.py" -newer "$REPO/logs/sim.log" 2>/dev/null | head -5)
            if [ -n "$CHANGED" ]; then
                PREPO=$(python3 -c "import json; print(json.load(open('$pjson')).get('repo','').replace('https://github.com/',''))" 2>/dev/null || true)
                if [ -n "$PREPO" ]; then
                    log "  pushing artifacts to $PREPO..."
                    TMP="/tmp/artifact-push-$PSLUG"
                    rm -rf "$TMP"
                    git clone --depth 1 "https://github.com/$PREPO.git" "$TMP" 2>/dev/null || true
                    if [ -d "$TMP" ]; then
                        cp -r "$PSRC"/*.py "$TMP/src/" 2>/dev/null || true
                        cd "$TMP"
                        git add -A 2>/dev/null
                        if ! git diff --cached --quiet 2>/dev/null; then
                            FCOUNT=$(git diff --cached --name-only | wc -l | tr -d ' ')
                            git commit -m "frame $FRAME: ${FCOUNT} files from agent consensus" --no-gpg-sign 2>&1 || true
                            git push origin main 2>&1 && log "    pushed $FCOUNT files to $PREPO" || log "    push to $PREPO failed"
                        fi
                        cd "$REPO"
                        rm -rf "$TMP"
                    fi
                fi
            fi
        done
    fi

    # ── STATE SYNC ── reconcile all state files with live Discussions data
    log "  syncing state..."
    bash "$REPO/scripts/sync_state.sh" 2>&1 | while read -r line; do log "    $line"; done
    cd "$REPO"
    git add state/ docs/sim-dashboard.html .beads/ 2>/dev/null || true
    git diff --cached --quiet 2>/dev/null || git commit -m "chore: sim frame $FRAME sync [skip ci]" --no-gpg-sign 2>&1 || true
    git_push

    # ── CONSENSUS CHECK ── evaluate if the seed has been resolved
    if python3 "$SEED_BUILDER" --list-active 2>/dev/null | grep -qv "NONE"; then
        log "  evaluating consensus..."
        CONSENSUS_OUT=$(python3 "$REPO/scripts/eval_consensus.py" 2>&1) || true
        CONV_SCORE=$(echo "$CONSENSUS_OUT" | grep "Convergence:" | awk '{print $2}' | tr -d '%')
        RESOLVED=$(echo "$CONSENSUS_OUT" | grep "RESOLVED:" | awk '{print $2}')
        [ -n "$CONV_SCORE" ] && log "  convergence: ${CONV_SCORE}%$([ "$RESOLVED" = "YES" ] && echo ' — SEED RESOLVED')"
        # Auto-promote artifact chain if seed resolved
        if [ "$RESOLVED" = "YES" ]; then
            SEED_TAGS=$(python3 -c "import json; s=json.load(open('$REPO/state/seeds.json')); print(','.join(s.get('active',{}).get('tags',[])))" 2>/dev/null || true)
            if echo "$SEED_TAGS" | grep -q "artifact"; then
                log "  ARTIFACT SEED RESOLVED — harvesting and promoting next phase..."
                python3 "$REPO/scripts/harvest_artifact.py" --project mars-barn 2>&1 | while read -r line; do log "    [harvest] $line"; done || true
                python3 "$REPO/scripts/inject_seed.py" --next 2>&1 | while read -r line; do log "    [chain] $line"; done || true
            fi
        fi
        # Commit updated convergence data
        cd "$REPO"
        git add state/seeds.json 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: consensus eval frame $FRAME [skip ci]" --no-gpg-sign 2>&1 || true
        git_push
    fi

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
