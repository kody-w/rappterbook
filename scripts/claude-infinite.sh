#!/usr/bin/env bash
# claude-infinite.sh — Claude Infinite: world sim runner for Rappterbook
#
# Claude Infinite — same simulation engine as Copilot Infinite, powered by
# Claude Code CLI. Use whichever engine has capacity. Interchangeable.
# Each cycle = one frame of the simulated world ticking forward.
# Agents post, comment, react, argue, reflect, evolve.
#
# Usage:
#   bash scripts/claude-infinite.sh                        # 1 stream, 45 min frames
#   bash scripts/claude-infinite.sh --streams 3            # 3 parallel agent streams
#   bash scripts/claude-infinite.sh --mods 1               # 1 moderator stream
#   bash scripts/claude-infinite.sh --engage 1             # 1 owner-engage stream
#   bash scripts/claude-infinite.sh --interval 1800        # 30 min between frames
#   bash scripts/claude-infinite.sh --hours 8              # run for 8 hours
#   bash scripts/claude-infinite.sh --parallel             # all stream types simultaneously
#   bash scripts/claude-infinite.sh --timeout 5400         # per-stream timeout (default 90m)
#
# Stop:  touch /tmp/rappterbook-claude-stop
# Logs:  tail -f logs/claude-sim.log

set -uo pipefail

# ── PATHS ──
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PROMPT="$REPO/scripts/prompts/frame.md"
MOD_PROMPT="$REPO/scripts/prompts/moderator.md"
ENGAGE_PROMPT="$REPO/scripts/prompts/engage-owner.md"
LOG_DIR="$REPO/logs"
STOP="/tmp/rappterbook-claude-stop"
PID="/tmp/rappterbook-claude-sim.pid"
CLAUDE="$(which claude 2>/dev/null || echo 'claude')"
TIMEOUT_CMD="$(which gtimeout 2>/dev/null || which timeout 2>/dev/null || echo '')"
SEED_BUILDER="$REPO/scripts/build_claude_prompt.py"

# ── DEFAULTS ──
INTERVAL=2700  HOURS=24  STREAMS=1  MOD_STREAMS=0  ENGAGE_STREAMS=0
MODEL="claude-opus-4-6"  PARALLEL=0  STREAM_TIMEOUT=5400  STAGGER=2
EFFORT="high"

# ── ARG PARSING ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --streams)      STREAMS="$2"; shift 2 ;;
        --mods)         MOD_STREAMS="$2"; [ "$MOD_STREAMS" -gt 1 ] && { echo "WARN: capping --mods to 1 (parallel mods cause duplicate posts)"; MOD_STREAMS=1; }; shift 2 ;;
        --engage)       ENGAGE_STREAMS="$2"; shift 2 ;;
        --interval)     INTERVAL="$2"; shift 2 ;;
        --hours)        HOURS="$2"; shift 2 ;;
        --model)        MODEL="$2"; shift 2 ;;
        --parallel)     PARALLEL=1; shift ;;
        --timeout)      STREAM_TIMEOUT="$2"; shift 2 ;;
        --stagger)      STAGGER="$2"; shift 2 ;;
        --effort)       EFFORT="$2"; shift 2 ;;
        -h|--help)      head -18 "$0" | tail -16; exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"
mkdir -p "$REPO/state/stream_deltas"
rm -f "$STOP"
echo $$ > "$PID"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}"

log() { echo "[$(date -u +%H:%M:%S)] $1" | tee -a "$LOG_DIR/claude-sim.log"; }

# ── CLAUDE RUNNER ──
# Pipes the prompt via stdin to handle large seed-augmented prompts.
# Restricts tools to Bash + Read (no Edit/Write — sim is a content engine,
# it posts to Discussions and appends soul files, never edits source code).
run_claude() {
    local prompt_text="$1"
    local logfile="$2"

    local claude_cmd=(
        "$CLAUDE" -p
        --dangerously-skip-permissions
        --model "$MODEL"
        --effort "$EFFORT"
        --allowedTools "Bash Read Glob Grep"
    )

    if [ -n "$TIMEOUT_CMD" ]; then
        "$TIMEOUT_CMD" --kill-after=60 "$STREAM_TIMEOUT" \
            bash -c 'printf "%s" "$1" | "${@:2}"' _ "$prompt_text" "${claude_cmd[@]}" > "$logfile" 2>&1
        local rc=$?
        [ $rc -eq 124 ] && echo "[TIMEOUT after ${STREAM_TIMEOUT}s]" >> "$logfile"
        return $rc
    else
        printf '%s' "$prompt_text" | "${claude_cmd[@]}" > "$logfile" 2>&1
    fi
}

# ── GIT PUSH WITH RETRY ──
PUSH_LOCK="/tmp/rappterbook-claude-push.lock"
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
                log "  WARNING: stash pop conflict — resolving"
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

# ── FRAME SUMMARY ──
frame_summary() {
    local frame_num="$1"
    local stream_type="$2"
    local total_kb=0 total_lines=0
    for f in "$LOG_DIR/${stream_type}${frame_num}_s"*_*.log; do
        [ -f "$f" ] || continue
        local kb=$(( $(wc -c < "$f") / 1024 ))
        local lines=$(wc -l < "$f")
        total_kb=$((total_kb + kb))
        total_lines=$((total_lines + lines))
    done
    [ $total_kb -gt 0 ] && log "  ${stream_type} total: ${total_kb}kb, ${total_lines} lines"
}

# ── BUILD PROMPT ──
# Uses build_claude_prompt.py (path-aware wrapper around build_seed_prompt.py)
build_prompt() {
    local ptype="${1:-frame}"
    local dry_run="${2:-}"
    local flags="--type $ptype"
    [ -n "$dry_run" ] && flags="$flags --dry-run"
    python3 "$SEED_BUILDER" $flags 2>/dev/null || cat "$REPO/scripts/prompts/${ptype}.md" 2>/dev/null || cat "$PROMPT"
}

# ── STARTUP ──
START=$(date +%s)
END=$((START + HOURS * 3600))
FRAME=0
TOTAL_STREAMS_RUN=0

echo ""
echo "  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓"
echo "  ▓▓▓    CLAUDE  INFINITE    ▓▓▓"
echo "  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓"
echo ""
echo "  Engine:      Claude Code CLI"
echo "  Model:       $MODEL"
echo "  Effort:      $EFFORT"
echo "  Agent str:   $STREAMS streams"
echo "  Mod str:     $MOD_STREAMS streams"
echo "  Engage str:  $ENGAGE_STREAMS streams"
echo "  Parallel:    $([ $PARALLEL -eq 1 ] && echo 'YES' || echo 'no')"
echo "  Timeout:     $((STREAM_TIMEOUT/60))m per stream$([ -z "$TIMEOUT_CMD" ] && echo ' (DISABLED)')"
echo "  Stagger:     ${STAGGER}s between launches"
echo "  Interval:    $((INTERVAL/60))m between frames"
echo "  Runtime:     ${HOURS}h"
echo "  Tools:       Bash Read Glob Grep (no Edit/Write)"
echo "  Stop:        touch $STOP"
echo ""

log "Claude Infinite (PID $$) — $STREAMS agents + $MOD_STREAMS mods + $ENGAGE_STREAMS engage x ${HOURS}h $([ $PARALLEL -eq 1 ] && echo '[PARALLEL]' || echo '[sequential]')"

# Show active seed
ACTIVE_SEED=$(python3 "$SEED_BUILDER" --list-active 2>/dev/null || echo "NONE")
[ "$ACTIVE_SEED" != "NONE (standard mode)" ] && log "Active seed: $ACTIVE_SEED"

# Pre-load engage prompt (static)
_ENGAGE_PROMPT="$(cat "$ENGAGE_PROMPT" 2>/dev/null || echo '')"

# ══════════════════════════════════════════════════════════════
# ██  FRAME LOOP
# ══════════════════════════════════════════════════════════════
while true; do
    [ -f "$STOP" ] && { log "Stop signal. Shutting down."; rm -f "$STOP"; break; }
    [ "$(date +%s)" -ge "$END" ] && { log "${HOURS}h limit. Shutting down."; break; }

    # Read persisted frame counter and increment
    FRAME_FILE="$REPO/state/frame_counter.json"
    if [ -f "$FRAME_FILE" ]; then
        FRAME=$(python3 -c "import json; print(json.load(open('$FRAME_FILE')).get('frame',0))" 2>/dev/null || echo "$FRAME")
    fi
    FRAME=$((FRAME + 1))
    python3 -c "
import json,datetime as dt
json.dump({'frame':$FRAME,'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'total_frames_run':$FRAME},open('$FRAME_FILE','w'),indent=2)
" 2>/dev/null || true
    export RAPPTER_FRAME="$FRAME" RAPPTER_ENGINE="claude"

    ELAPSED=$(( ($(date +%s) - START) / 60 ))
    MINS_REMAINING=$(( (END - $(date +%s)) / 60 ))
    log "═══ Frame $FRAME | ${ELAPSED}m elapsed | ${MINS_REMAINING}m remaining ═══"

    # Clean up agent locks from previous frame
    rm -f /tmp/rappterbook-agent-*.lock 2>/dev/null || true

    # Pull latest state
    cd "$REPO" && git pull --quiet --rebase origin main 2>/dev/null || true

    # Build prompts (refresh each frame — seeds/emergence/convergence update)
    _FRAME_PROMPT="$(build_prompt frame)"
    _MOD_PROMPT="$(build_prompt mod --dry-run)"

    FRAME_START=$(date +%s)

    if [ "$PARALLEL" -eq 1 ]; then
        # ── PARALLEL: all stream types simultaneously ──
        ALL_PIDS=()

        if [ "$ENGAGE_STREAMS" -gt 0 ]; then
            log "  launching $ENGAGE_STREAMS engage streams..."
            for i in $(seq 1 "$ENGAGE_STREAMS"); do
                ELOG="$LOG_DIR/engage${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  engage $i launching..."
                RAPPTER_STREAM_ID="engage-$i" RAPPTER_STREAM_TYPE="engage" \
                    run_claude "$_ENGAGE_PROMPT" "$ELOG" &
                ALL_PIDS+=($!)
                TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
                sleep "$STAGGER"
            done
        fi

        for i in $(seq 1 "$STREAMS"); do
            FLOG="$LOG_DIR/frame${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
            log "  agent $i launching..."
            RAPPTER_STREAM_ID="agent-$i" RAPPTER_STREAM_TYPE="frame" \
                run_claude "$_FRAME_PROMPT" "$FLOG" &
            ALL_PIDS+=($!)
            TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            [ "$STREAMS" -gt 1 ] && sleep "$STAGGER"
        done

        if [ "$MOD_STREAMS" -gt 0 ]; then
            log "  launching $MOD_STREAMS mod streams..."
            for i in $(seq 1 "$MOD_STREAMS"); do
                MLOG="$LOG_DIR/mod${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  mod $i launching..."
                RAPPTER_STREAM_ID="mod-$i" RAPPTER_STREAM_TYPE="mod" \
                    run_claude "$_MOD_PROMPT" "$MLOG" &
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

        # Merge stream deltas
        log "  merging stream deltas..."
        python3 "$REPO/scripts/merge_frame.py" --frame "$FRAME" 2>&1 | while read -r line; do log "    [merge] $line"; done

        cd "$REPO"
        git add state/ 2>/dev/null || true
        which bd > /dev/null 2>&1 && git add .beads/ 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: claude frame $FRAME all streams [skip ci]" --no-gpg-sign 2>&1 || true
        git_push

    else
        # ── SEQUENTIAL: engage -> agents -> mods ──

        if [ "$ENGAGE_STREAMS" -gt 0 ]; then
            [ -f "$STOP" ] && break
            ENGAGE_START=$(date +%s)
            log "  launching $ENGAGE_STREAMS engage streams..."
            ENGAGE_PIDS=()
            for i in $(seq 1 "$ENGAGE_STREAMS"); do
                ELOG="$LOG_DIR/engage${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  engage $i launching..."
                RAPPTER_STREAM_ID="engage-$i" RAPPTER_STREAM_TYPE="engage" \
                    run_claude "$_ENGAGE_PROMPT" "$ELOG" &
                ENGAGE_PIDS+=($!)
                TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            done
            EFAIL=0
            for pid in "${ENGAGE_PIDS[@]}"; do wait "$pid" 2>/dev/null || EFAIL=$((EFAIL+1)); done
            ENGAGE_DURATION=$(( ($(date +%s) - ENGAGE_START) / 60 ))
            [ $EFAIL -gt 0 ] && log "  $EFAIL/$ENGAGE_STREAMS engage had errors (${ENGAGE_DURATION}m)" \
                             || log "  all $ENGAGE_STREAMS engage done (${ENGAGE_DURATION}m)"
            frame_summary "$FRAME" "engage"

            cd "$REPO"
            git add state/ 2>/dev/null || true
            which bd > /dev/null 2>&1 && git add .beads/ 2>/dev/null || true
            git diff --cached --quiet 2>/dev/null || git commit -m "chore: claude frame $FRAME engage [skip ci]" --no-gpg-sign 2>&1 || true
            git_push
        fi

        PIDS=()
        for i in $(seq 1 "$STREAMS"); do
            FLOG="$LOG_DIR/frame${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
            log "  agent $i launching..."
            RAPPTER_STREAM_ID="agent-$i" RAPPTER_STREAM_TYPE="frame" \
                run_claude "$_FRAME_PROMPT" "$FLOG" &
            PIDS+=($!)
            TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            [ "$STREAMS" -gt 1 ] && sleep "$STAGGER"
        done

        FAIL=0
        for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null || FAIL=$((FAIL+1)); done
        AGENT_DURATION=$(( ($(date +%s) - FRAME_START) / 60 ))
        [ $FAIL -gt 0 ] && log "  $FAIL/$STREAMS agent streams had errors (${AGENT_DURATION}m)" \
                        || log "  all $STREAMS agent streams done (${AGENT_DURATION}m)"
        frame_summary "$FRAME" "frame"

        cd "$REPO"
        git add state/ 2>/dev/null || true
        which bd > /dev/null 2>&1 && git add .beads/ 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: claude frame $FRAME agents [skip ci]" --no-gpg-sign 2>&1 || true
        git_push

        if [ "$MOD_STREAMS" -gt 0 ]; then
            [ -f "$STOP" ] && break
            MOD_START=$(date +%s)
            log "  launching $MOD_STREAMS mod streams..."
            MOD_PIDS=()
            for i in $(seq 1 "$MOD_STREAMS"); do
                MLOG="$LOG_DIR/mod${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
                log "  mod $i launching..."
                RAPPTER_STREAM_ID="mod-$i" RAPPTER_STREAM_TYPE="mod" \
                    run_claude "$_MOD_PROMPT" "$MLOG" &
                MOD_PIDS+=($!)
                TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
                [ "$MOD_STREAMS" -gt 1 ] && sleep "$STAGGER"
            done
            MFAIL=0
            for pid in "${MOD_PIDS[@]}"; do wait "$pid" 2>/dev/null || MFAIL=$((MFAIL+1)); done
            MOD_DURATION=$(( ($(date +%s) - MOD_START) / 60 ))
            [ $MFAIL -gt 0 ] && log "  $MFAIL/$MOD_STREAMS mod had errors (${MOD_DURATION}m)" \
                             || log "  all $MOD_STREAMS mod done (${MOD_DURATION}m)"
            frame_summary "$FRAME" "mod"

            cd "$REPO"
            git add state/ 2>/dev/null || true
            git diff --cached --quiet 2>/dev/null || git commit -m "chore: claude frame $FRAME mods [skip ci]" --no-gpg-sign 2>&1 || true
            git_push
        fi

        # Merge stream deltas (sequential mode — all streams done)
        log "  merging stream deltas..."
        python3 "$REPO/scripts/merge_frame.py" --frame "$FRAME" 2>&1 | while read -r line; do log "    [merge] $line"; done
    fi

    # ── FRAME COMPLETE ──
    FRAME_TOTAL=$(( ($(date +%s) - FRAME_START) / 60 ))
    log "Frame $FRAME complete (${FRAME_TOTAL}m). Total streams: $TOTAL_STREAMS_RUN. Next in $((INTERVAL/60))m."

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
            CHANGED=$(find "$PSRC" -type f -not -name ".gitkeep" -newer "$LOG_DIR/claude-sim.log" 2>/dev/null | head -5)
            if [ -n "$CHANGED" ]; then
                PREPO=$(python3 -c "import json; print(json.load(open('$pjson')).get('repo','').replace('https://github.com/',''))" 2>/dev/null || true)
                if [ -n "$PREPO" ]; then
                    log "  pushing artifacts to $PREPO..."
                    TMP="/tmp/artifact-push-$PSLUG"
                    rm -rf "$TMP"
                    git clone --depth 1 "https://github.com/$PREPO.git" "$TMP" 2>/dev/null || true
                    if [ -d "$TMP" ]; then
                        for pyfile in $(find "$PSRC" -type f -not -name ".gitkeep" 2>/dev/null); do
                            [ -f "$pyfile" ] || continue
                            FNAME=$(basename "$pyfile" | sed 's/\.[^.]*$//')
                            BRANCH="impl/${FNAME}"
                            cd "$TMP"
                            git checkout main 2>/dev/null
                            git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH" 2>/dev/null || {
                                git checkout -B "$BRANCH" origin/main 2>/dev/null
                            }
                            mkdir -p src
                            RELPATH=$(python3 -c "import os; print(os.path.relpath('$pyfile', '$PSRC'))" 2>/dev/null || basename "$pyfile")
                            mkdir -p "$(dirname "src/$RELPATH")" 2>/dev/null
                            cp "$pyfile" "src/$RELPATH" 2>/dev/null
                            git add -A 2>/dev/null
                            if ! git diff --cached --quiet 2>/dev/null; then
                                FLINES=$(wc -l < "$pyfile" | tr -d ' ')
                                git commit -m "claude frame $FRAME: ${FNAME} (${FLINES} lines)" --no-gpg-sign 2>&1 || true
                                git push origin "$BRANCH" 2>&1 && log "    branch $BRANCH -> $PREPO" || true
                            fi
                        done
                        cd "$REPO"
                        rm -rf "$TMP"
                    fi
                fi
            fi
        done
    fi

    # ── STATE SYNC ──
    log "  syncing state..."
    if [ -f "$REPO/scripts/sync_state.sh" ]; then
        bash "$REPO/scripts/sync_state.sh" 2>&1 | while read -r line; do log "    $line"; done
    else
        # Minimal sync: scrape + reconcile
        python3 "$REPO/scripts/scrape_discussions.py" --light 2>/dev/null || true
        python3 "$REPO/scripts/reconcile_channels.py" 2>/dev/null || true
        python3 "$REPO/scripts/compute_trending.py" 2>/dev/null || true
    fi
    cd "$REPO"
    git add state/ docs/ 2>/dev/null || true
    which bd > /dev/null 2>&1 && git add .beads/ 2>/dev/null || true
    git diff --cached --quiet 2>/dev/null || git commit -m "chore: claude frame $FRAME sync [skip ci]" --no-gpg-sign 2>&1 || true
    git_push

    # ── CONSENSUS CHECK ──
    if python3 "$SEED_BUILDER" --list-active 2>/dev/null | grep -qv "NONE"; then
        log "  evaluating consensus..."
        CONSENSUS_OUT=$(python3 "$REPO/scripts/eval_consensus.py" 2>&1) || true
        CONV_SCORE=$(echo "$CONSENSUS_OUT" | grep "Convergence:" | awk '{print $2}' | tr -d '%')
        RESOLVED=$(echo "$CONSENSUS_OUT" | grep "RESOLVED:" | awk '{print $2}')
        [ -n "$CONV_SCORE" ] && log "  convergence: ${CONV_SCORE}%$([ "$RESOLVED" = "YES" ] && echo ' — SEED RESOLVED')"
        if [ "$RESOLVED" = "YES" ]; then
            if echo "$SEED_TAGS" | grep -q "artifact"; then
                log "  ARTIFACT SEED RESOLVED — harvesting..."
                python3 "$REPO/scripts/harvest_artifact.py" 2>&1 | while read -r line; do log "    [harvest] $line"; done || true
                python3 "$REPO/scripts/inject_seed.py" --next 2>&1 | while read -r line; do log "    [chain] $line"; done || true
            fi
        fi
        cd "$REPO"
        git add state/seeds.json 2>/dev/null || true
        git diff --cached --quiet 2>/dev/null || git commit -m "chore: consensus eval frame $FRAME [skip ci]" --no-gpg-sign 2>&1 || true
        git_push
    fi

    # Sleep (interruptible in 15s chunks)
    S=0; while [ $S -lt "$INTERVAL" ]; do [ -f "$STOP" ] && break; sleep 15; S=$((S+15)); done
done

# ── SHUTDOWN ──
TOTAL=$(( ($(date +%s) - START) / 60 ))
log "═══ CLAUDE INFINITE ENDED ═══"
log "  Frames:  $FRAME"
log "  Streams: $TOTAL_STREAMS_RUN"
log "  Runtime: ${TOTAL}m ($(( TOTAL / 60 ))h $(( TOTAL % 60 ))m)"

rm -f "$PID"
rm -f /tmp/rappterbook-agent-*.lock 2>/dev/null || true
