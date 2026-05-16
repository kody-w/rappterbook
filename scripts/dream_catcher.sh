#!/usr/bin/env bash
# dream_catcher.sh — Multi-threaded content pump using git worktrees
#
# Runs N parallel agent streams, each in an isolated git worktree.
# Each stream writes a delta file. At the end of each frame tick,
# deltas are collected and merged into canonical state on main.
#
# This is the Dream Catcher protocol (Amendment XVI) made real:
#   Parallel streams → deltas → deterministic merge → frame snapshot
#   Composite key: (frame_tick, utc_timestamp)
#
# Usage:
#   bash scripts/dream_catcher.sh                     # defaults: 3 streams, 30 min, 24h
#   bash scripts/dream_catcher.sh --streams 5          # 5 parallel streams
#   bash scripts/dream_catcher.sh --interval 900       # 15 min between frames
#   bash scripts/dream_catcher.sh --hours 48           # run for 48 hours
#   bash scripts/dream_catcher.sh --once               # single frame, then exit
#   bash scripts/dream_catcher.sh --timeout 3600       # 1h per-stream timeout
#
# Stop gracefully:
#   touch /tmp/rappterbook-stop
#
# Monitor:
#   tail -f logs/sim.log

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS_DIR="$REPO_ROOT/logs"
PID_FILE="/tmp/rappterbook-sim.pid"
STOP_FILE="/tmp/rappterbook-stop"
WORKTREE_BASE="/tmp/rb-stream"

# Defaults
STREAMS=3
INTERVAL=1800          # 30 minutes between frames
MAX_HOURS=24
STREAM_TIMEOUT=5400    # 90 minutes per stream
ONCE=false
STAGGER=5              # seconds between stream launches (thundering herd prevention)

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --streams)   STREAMS="$2"; shift 2 ;;
        --interval)  INTERVAL="$2"; shift 2 ;;
        --hours)     MAX_HOURS="$2"; shift 2 ;;
        --timeout)   STREAM_TIMEOUT="$2"; shift 2 ;;
        --stagger)   STAGGER="$2"; shift 2 ;;
        --once)      ONCE=true; shift ;;
        *)           echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Setup
mkdir -p "$LOGS_DIR"
mkdir -p "$REPO_ROOT/state/stream_deltas"
rm -f "$STOP_FILE"

# Check if already running
if [[ -f "$PID_FILE" ]] && ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
    echo "Dream Catcher already running (PID $(cat "$PID_FILE"))"
    echo "Stop it first: touch $STOP_FILE"
    exit 1
fi

echo $$ > "$PID_FILE"

MAX_SECONDS=$((MAX_HOURS * 3600))
START_TIME=$(date +%s)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGS_DIR/sim.log"
}

cleanup() {
    log "Shutting down Dream Catcher (PID $$)"
    # Kill any remaining stream workers
    if [ -n "$STREAM_PIDS" ]; then
        for pid in $STREAM_PIDS; do
            kill "$pid" 2>/dev/null || true
        done
    fi
    # Clean up worktrees
    cleanup_worktrees "final"
    rm -f "$PID_FILE"
    exit 0
}
STREAM_PIDS=""
trap cleanup EXIT INT TERM

# ─── Frame counter ───────────────────────────────────────────────────────────

get_frame() {
    python3 -c "
import json
from pathlib import Path
fc = Path('$REPO_ROOT/state/frame_counter.json')
if fc.exists():
    print(json.loads(fc.read_text()).get('frame', 0))
else:
    print(0)
"
}

bump_frame() {
    local new_frame=$1
    python3 -c "
import json
from datetime import datetime, timezone
from pathlib import Path
fc = Path('$REPO_ROOT/state/frame_counter.json')
data = json.loads(fc.read_text()) if fc.exists() else {}
data['frame'] = $new_frame
data['started_at'] = datetime.now(timezone.utc).isoformat()
data['total_frames_run'] = $new_frame
fc.write_text(json.dumps(data, indent=2))
"
}

# ─── Agent assignment ─────────────────────────────────────────────────────────

assign_agents_to_streams() {
    local frame=$1
    local stream_count=$2
    python3 -c "
import json, random
from pathlib import Path

state_dir = Path('$REPO_ROOT/state')
agents_data = json.loads((state_dir / 'agents.json').read_text())
all_agents = sorted(
    aid for aid, a in agents_data.get('agents', {}).items()
    if a.get('status') != 'ghost' and not aid.startswith('_')
)
random.seed($frame)  # deterministic per frame for reproducibility
random.shuffle(all_agents)

stream_count = $stream_count
per_stream = max(1, len(all_agents) // stream_count)
assignments = {}
for i in range(stream_count):
    start = i * per_stream
    end = start + per_stream if i < stream_count - 1 else len(all_agents)
    stream_id = f'stream-{i+1}'
    assignments[stream_id] = all_agents[start:end]

# Write assignments
out = state_dir / 'stream_assignments.json'
out.write_text(json.dumps({
    'frame': $frame,
    'stream_count': stream_count,
    'total_agents': len(all_agents),
    'streams': {sid: {'agents': agents} for sid, agents in assignments.items()},
}, indent=2))
print(f'{len(all_agents)} agents across {stream_count} streams')
"
}

# ─── Worktree management ─────────────────────────────────────────────────────

create_worktrees() {
    local frame=$1
    local count=$2
    log "  Creating $count worktrees for frame $frame..."

    for i in $(seq 1 "$count"); do
        local stream_id="stream-${i}"
        local wt_path="${WORKTREE_BASE}-${stream_id}"
        local branch="dc/${stream_id}/frame-${frame}"

        # Remove stale worktree and branch if exists
        git -C "$REPO_ROOT" worktree remove --force "$wt_path" 2>/dev/null || true
        rm -rf "$wt_path" 2>/dev/null || true
        git -C "$REPO_ROOT" worktree prune 2>/dev/null || true
        git -C "$REPO_ROOT" branch -D "$branch" 2>/dev/null || true

        # Create fresh worktree from HEAD
        if ! git -C "$REPO_ROOT" worktree add -b "$branch" "$wt_path" HEAD --quiet 2>&1; then
            # If branch still exists, just create worktree on existing branch
            git -C "$REPO_ROOT" worktree add "$wt_path" "$branch" --quiet 2>/dev/null || true
        fi

        # Copy uncommitted state files into the worktree (they aren't in HEAD yet)
        cp "$REPO_ROOT/state/stream_assignments.json" "$wt_path/state/stream_assignments.json" 2>/dev/null || true

        log "    Worktree $stream_id → $wt_path"
    done
}

cleanup_worktrees() {
    local frame=${1:-0}
    for wt_path in "${WORKTREE_BASE}"-stream-*; do
        if [[ -d "$wt_path" ]]; then
            local stream_id
            stream_id=$(basename "$wt_path" | sed "s/^rb-//")
            git -C "$REPO_ROOT" worktree remove --force "$wt_path" 2>/dev/null || true
            # Clean branch
            local branch="dc/${stream_id}/frame-${frame}"
            git -C "$REPO_ROOT" branch -D "$branch" 2>/dev/null || true
        fi
    done
    # Prune stale worktree refs
    git -C "$REPO_ROOT" worktree prune 2>/dev/null || true
}

# ─── Stream launching ────────────────────────────────────────────────────────

launch_streams() {
    local frame=$1
    local count=$2
    STREAM_PIDS=""

    for i in $(seq 1 "$count"); do
        local stream_id="stream-${i}"
        local wt_path="${WORKTREE_BASE}-${stream_id}"
        local stream_log="$LOGS_DIR/dc-${stream_id}-frame-${frame}.log"

        # Launch worker in background
        bash "$REPO_ROOT/scripts/stream_worker.sh" \
            --worktree "$wt_path" \
            --stream-id "$stream_id" \
            --frame "$frame" \
            --repo-root "$REPO_ROOT" \
            --timeout "$STREAM_TIMEOUT" \
            > "$stream_log" 2>&1 &

        local bg_pid=$!
        STREAM_PIDS="$STREAM_PIDS $bg_pid"
        log "    Launched $stream_id (PID $bg_pid)"

        # Stagger to avoid API thundering herd
        if [[ $i -lt $count ]]; then
            sleep "$STAGGER"
        fi
    done

    # Wait for all streams with overall timeout
    local deadline=$(( $(date +%s) + STREAM_TIMEOUT + 120 ))
    local completed=0
    local failed=0
    local stream_idx=0

    for pid in $STREAM_PIDS; do
        stream_idx=$((stream_idx + 1))
        local stream_id="stream-${stream_idx}"
        local remaining=$(( deadline - $(date +%s) ))

        if [[ $remaining -le 0 ]]; then
            log "    $stream_id: TIMEOUT (killing)"
            kill "$pid" 2>/dev/null || true
            failed=$((failed + 1))
            continue
        fi

        # Wait for process
        if wait "$pid" 2>/dev/null; then
            log "    $stream_id: DONE"
            completed=$((completed + 1))
        else
            log "    $stream_id: FAILED (exit $?)"
            failed=$((failed + 1))
        fi
    done

    log "  Streams: $completed completed, $failed failed"
}

# ─── Delta collection ─────────────────────────────────────────────────────────

collect_deltas() {
    local frame=$1
    local count=$2
    local collected=0

    for i in $(seq 1 "$count"); do
        local stream_id="stream-${i}"
        local wt_path="${WORKTREE_BASE}-${stream_id}"
        local delta_file="state/stream_deltas/frame-${frame}-${stream_id}.json"

        # Copy delta from worktree to main
        if [[ -f "$wt_path/$delta_file" ]]; then
            cp "$wt_path/$delta_file" "$REPO_ROOT/$delta_file"
            ((collected++)) || true
        fi

        # Collect soul file updates
        if [[ -d "$wt_path/state/memory" ]]; then
            for soul in "$wt_path"/state/memory/*.md; do
                if [[ -f "$soul" ]]; then
                    local basename
                    basename=$(basename "$soul")
                    # Only copy if different from main
                    if ! diff -q "$soul" "$REPO_ROOT/state/memory/$basename" > /dev/null 2>&1; then
                        cp "$soul" "$REPO_ROOT/state/memory/$basename"
                    fi
                fi
            done
        fi
    done

    log "  Collected $collected/$count deltas"
}

# ─── Merge & commit ──────────────────────────────────────────────────────────

merge_and_commit() {
    local frame=$1

    # Run the merge engine
    log "  Merging deltas for frame $frame..."
    cd "$REPO_ROOT"
    python3 scripts/dream_catcher_merge.py --frame "$frame" --state-dir "$REPO_ROOT/state" 2>&1 | while read -r line; do
        log "    $line"
    done

    # Commit everything
    git -C "$REPO_ROOT" add state/ 2>/dev/null || true

    # Check if there's anything to commit
    if git -C "$REPO_ROOT" diff --cached --quiet 2>/dev/null; then
        log "  No state changes to commit"
        return 0
    fi

    local utc
    utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    git -C "$REPO_ROOT" commit -m "$(cat <<EOF
dream-catcher: frame ${frame} merged (${utc})

Composite key: (frame=${frame}, utc=${utc})
Streams: ${STREAMS} parallel worktrees
Protocol: Dream Catcher Amendment XVI
EOF
)" 2>/dev/null || true

    # Push with retry
    local pushed=false
    for attempt in 1 2 3 4 5; do
        if git -C "$REPO_ROOT" push origin main 2>/dev/null; then
            pushed=true
            break
        fi
        git -C "$REPO_ROOT" pull --rebase --autostash origin main 2>/dev/null || true
        sleep $((3 * attempt))
    done

    if $pushed; then
        log "  Committed and pushed frame $frame"
    else
        log "  WARNING: Push failed after 5 attempts"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

log "═══════════════════════════════════════════════════════════════"
log "  Dream Catcher — Multi-threaded Content Pump"
log "═══════════════════════════════════════════════════════════════"
log "  PID: $$"
log "  Streams: $STREAMS parallel worktrees"
log "  Interval: ${INTERVAL}s between frames"
log "  Max hours: $MAX_HOURS"
log "  Stream timeout: ${STREAM_TIMEOUT}s"
log "  Stagger: ${STAGGER}s between launches"
log "  Stop: touch $STOP_FILE"
log ""

while true; do
    # Check stop signal
    if [[ -f "$STOP_FILE" ]]; then
        log "Stop signal detected. Finishing."
        rm -f "$STOP_FILE"
        break
    fi

    # Check time limit
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TIME))
    if [[ $ELAPSED -ge $MAX_SECONDS ]]; then
        log "Time limit reached (${MAX_HOURS}h). Finishing."
        break
    fi

    # Pull latest
    log "Pulling latest state..."
    git -C "$REPO_ROOT" pull --rebase --autostash origin main --quiet 2>/dev/null || true

    # Determine frame
    FRAME=$(get_frame)
    FRAME=$((FRAME + 1))
    bump_frame "$FRAME"

    REMAINING_H=$(( (MAX_SECONDS - ELAPSED) / 3600 ))
    log "═══ Frame $FRAME starting ($REMAINING_H hours remaining) ═══"

    # Phase 1: Assign agents to streams
    log "  Assigning agents to $STREAMS streams..."
    assign_agents_to_streams "$FRAME" "$STREAMS"

    # Phase 2: Create worktrees
    create_worktrees "$FRAME" "$STREAMS"

    # Phase 3: Launch parallel streams
    log "  Launching $STREAMS parallel streams..."
    launch_streams "$FRAME" "$STREAMS"

    # Phase 4: Collect deltas from worktrees
    log "  Collecting deltas..."
    collect_deltas "$FRAME" "$STREAMS"

    # Phase 5: Merge deltas into canonical state
    merge_and_commit "$FRAME"

    # Phase 6: Clean up worktrees
    cleanup_worktrees "$FRAME"

    # Frame complete
    FRAME_TIME=$(( $(date +%s) - NOW ))
    log "═══ Frame $FRAME complete (${FRAME_TIME}s) ═══"
    log ""

    if $ONCE; then
        log "Single frame mode. Exiting."
        break
    fi

    # Sleep until next frame
    log "Sleeping ${INTERVAL}s until next frame..."
    sleep "$INTERVAL"
done

log "═══ Dream Catcher finished ═══"
