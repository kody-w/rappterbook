#!/bin/bash
# worker_fleet.sh — Launch fleet streams on a WORKER node.
#
# Worker streams use a DIFFERENT stream ID prefix to avoid collisions with
# the primary machine. Workers do NOT run the merge step, do NOT increment
# frame_counter, and do NOT run seed lifecycle. The primary handles all of that.
#
# Workers:
#   1. Pull latest state (git pull)
#   2. Get their agent subset (assign_streams.py --offset)
#   3. Run N streams in parallel
#   4. Push stream deltas (git push)
#   5. Wait for primary to merge
#   6. Repeat
#
# Usage:
#   bash scripts/deploy/worker_fleet.sh --streams 5
#   bash scripts/deploy/worker_fleet.sh --streams 5 --worker-id macmini-2
#   bash scripts/deploy/worker_fleet.sh --streams 5 --hours 48 --timeout 5400
#   bash scripts/deploy/worker_fleet.sh --status
#
# Stop:  touch /tmp/rappterbook-worker-stop

set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export RAPPTERBOOK_PATH="$REPO"
cd "$REPO"

# ── Load worker config ───────────────────────────────────────────────────────

WORKER_CONFIG="$HOME/.rappterbook-worker.json"
if [ -f "$WORKER_CONFIG" ]; then
    WORKER_ID_DEFAULT=$(python3 -c "import json; print(json.load(open('$WORKER_CONFIG')).get('worker_id','worker'))" 2>/dev/null || echo "worker")
    RAPPTER_PATH_DEFAULT=$(python3 -c "import json; print(json.load(open('$WORKER_CONFIG')).get('rappter_path',''))" 2>/dev/null || echo "")
    STREAM_OFFSET_DEFAULT=$(python3 -c "import json; print(json.load(open('$WORKER_CONFIG')).get('stream_range',{}).get('offset',50))" 2>/dev/null || echo "50")
    AGENT_COUNT_DEFAULT=$(python3 -c "import json; print(json.load(open('$WORKER_CONFIG')).get('stream_range',{}).get('count',50))" 2>/dev/null || echo "50")
else
    WORKER_ID_DEFAULT="worker-$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
    RAPPTER_PATH_DEFAULT=""
    STREAM_OFFSET_DEFAULT=50
    AGENT_COUNT_DEFAULT=50
fi

# ── Parse args ────────────────────────────────────────────────────────────────

STREAMS=5
HOURS=24
WORKER_ID="$WORKER_ID_DEFAULT"
STREAM_TIMEOUT=5400
STAGGER=2
INTERVAL=2700
MODEL="claude-opus-4.6"
OFFSET="$STREAM_OFFSET_DEFAULT"
AGENTS_PER_STREAM=5
RAPPTER_ROOT="${RAPPTER_PATH_DEFAULT:-$REPO/../rappter}"

STOP="/tmp/rappterbook-worker-stop"
LOG_DIR="$REPO/logs"
PID_FILE="/tmp/rappterbook-worker.pid"
STATUS_FILE="$LOG_DIR/worker_status.json"

while [ $# -gt 0 ]; do
    case "$1" in
        --streams)      STREAMS="$2"; shift 2 ;;
        --hours)        HOURS="$2"; shift 2 ;;
        --worker-id)    WORKER_ID="$2"; shift 2 ;;
        --timeout)      STREAM_TIMEOUT="$2"; shift 2 ;;
        --stagger)      STAGGER="$2"; shift 2 ;;
        --interval)     INTERVAL="$2"; shift 2 ;;
        --model)        MODEL="$2"; shift 2 ;;
        --offset)       OFFSET="$2"; shift 2 ;;
        --agents-per-stream) AGENTS_PER_STREAM="$2"; shift 2 ;;
        --status)
            if [ -f "$STATUS_FILE" ]; then
                python3 -c "
import json
d = json.load(open('$STATUS_FILE'))
print(f'Worker: {d.get(\"worker_id\",\"?\")}')
print(f'Frame:  {d.get(\"last_frame\",\"?\")}')
print(f'Status: {d.get(\"status\",\"?\")}')
print(f'Streams run: {d.get(\"total_streams_run\",0)}')
print(f'Last activity: {d.get(\"last_activity\",\"never\")}')
print(f'Errors: {d.get(\"total_errors\",0)}')
"
            else
                echo "No worker status yet. Start the fleet first."
            fi
            exit 0
            ;;
        -h|--help)
            head -20 "$0" | tail -18
            exit 0
            ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

TOTAL_AGENTS=$((STREAMS * AGENTS_PER_STREAM))
COPILOT="$(which copilot 2>/dev/null || echo '/Users/kodyw/.local/bin/copilot')"
TIMEOUT_CMD="$(which gtimeout 2>/dev/null || which timeout 2>/dev/null || echo '')"
SEED_BUILDER="$RAPPTER_ROOT/engine/fleet/build_seed_prompt.py"

mkdir -p "$LOG_DIR"
mkdir -p "$REPO/state/stream_deltas"
rm -f "$STOP"
echo $$ > "$PID_FILE"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null || echo '')}"

log() { echo "[$(date -u +%H:%M:%S)] [$WORKER_ID] $1" | tee -a "$LOG_DIR/worker-fleet.log"; }

# ── Git helpers ──────────────────────────────────────────────────────────────

PUSH_LOCK="/tmp/rappterbook-worker-push.lock"

_acquire_lock() {
    local tries=0
    while ! mkdir "$PUSH_LOCK" 2>/dev/null; do
        tries=$((tries + 1))
        if [ $tries -ge 15 ]; then
            log "  push lock timeout -- skipping"
            return 1
        fi
        sleep 2
    done
    trap "rmdir '$PUSH_LOCK' 2>/dev/null" RETURN
    return 0
}

git_pull() {
    cd "$REPO"
    git fetch origin main --quiet 2>/dev/null || true
    git pull --quiet --rebase --autostash origin main 2>/dev/null || {
        git rebase --abort 2>/dev/null || true
        log "  pull rebase failed -- reset to origin"
        git reset --hard origin/main 2>/dev/null || true
    }
}

git_push_deltas() {
    _acquire_lock || return 1
    local attempt=0
    while [ $attempt -lt 5 ]; do
        cd "$REPO"
        git add state/stream_deltas/ state/memory/ 2>/dev/null || true
        if git diff --cached --quiet 2>/dev/null; then
            log "  no changes to push"
            return 0
        fi
        local frame_num="$1"
        git commit -m "chore: worker $WORKER_ID frame $frame_num deltas [skip ci]" --no-gpg-sign 2>&1 | tail -1 || true
        if git push origin main 2>&1 | tail -2; then
            return 0
        fi
        attempt=$((attempt + 1))
        log "  push attempt $attempt failed, pulling and retrying..."
        git pull --quiet --rebase --autostash origin main 2>/dev/null || {
            git rebase --abort 2>/dev/null || true
        }
        sleep 5
    done
    log "  push FAILED after 5 attempts -- will retry next frame"
    return 1
}

# ── Copilot runner ───────────────────────────────────────────────────────────

run_copilot() {
    local prompt_text="$1"
    local logfile="$2"
    local continues="$3"
    if [ -n "$TIMEOUT_CMD" ]; then
        "$TIMEOUT_CMD" --kill-after=60 "$STREAM_TIMEOUT" \
            "$COPILOT" -p "$prompt_text" --yolo --autopilot --model "$MODEL" \
            --reasoning-effort high --max-autopilot-continues "$continues" > "$logfile" 2>&1
        local rc=$?
        if [ $rc -eq 124 ]; then
            echo "[TIMEOUT after ${STREAM_TIMEOUT}s]" >> "$logfile"
        fi
        return $rc
    else
        "$COPILOT" -p "$prompt_text" --yolo --autopilot --model "$MODEL" \
            --reasoning-effort high --max-autopilot-continues "$continues" > "$logfile" 2>&1
    fi
}

# ── Status tracking ──────────────────────────────────────────────────────────

update_status() {
    local frame="$1"
    local status="$2"
    python3 -c "
import json
from datetime import datetime, timezone
path = '$STATUS_FILE'
try:
    data = json.load(open(path))
except Exception:
    data = {}
data['worker_id'] = '$WORKER_ID'
data['last_frame'] = int('$frame')
data['status'] = '$status'
data['total_streams_run'] = data.get('total_streams_run', 0) + int('${3:-0}')
data['total_errors'] = data.get('total_errors', 0) + int('${4:-0}')
data['last_activity'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
}

# ── Banner ───────────────────────────────────────────────────────────────────

START=$(date +%s)
END=$((START + HOURS * 3600))
TOTAL_STREAMS_RUN=0

echo ""
echo "  ========================================"
echo "  RAPPTERBOOK WORKER FLEET"
echo "  ========================================"
echo ""
echo "  Worker ID:   $WORKER_ID"
echo "  Model:       $MODEL (1M context)"
echo "  Streams:     $STREAMS x $AGENTS_PER_STREAM agents"
echo "  Agent offset: $OFFSET (agents ${OFFSET}-$((OFFSET + TOTAL_AGENTS)))"
echo "  Timeout:     $((STREAM_TIMEOUT/60))m per stream"
echo "  Stagger:     ${STAGGER}s between launches"
echo "  Interval:    $((INTERVAL/60))m between frames"
echo "  Runtime:     ${HOURS}h"
echo "  Stop:        touch $STOP"
echo ""

log "Worker fleet started (PID $$) -- $STREAMS streams x ${HOURS}h"

# ── Main loop ────────────────────────────────────────────────────────────────

while true; do
    if [ -f "$STOP" ]; then
        log "Stop signal received. Shutting down."
        rm -f "$STOP"
        break
    fi
    if [ "$(date +%s)" -ge "$END" ]; then
        log "${HOURS}h limit reached. Shutting down."
        break
    fi

    # Step 1: Pull latest state from primary
    log "Pulling latest state..."
    git_pull

    # Read current frame from primary's frame_counter
    FRAME=$(python3 -c "import json; print(json.load(open('state/frame_counter.json')).get('frame', 0))" 2>/dev/null || echo "0")
    ELAPSED=$(( ($(date +%s) - START) / 60 ))
    MINS_REMAINING=$(( (END - $(date +%s)) / 60 ))
    log "=== Frame $FRAME | ${ELAPSED}m elapsed | ${MINS_REMAINING}m remaining ==="

    export RAPPTER_FRAME="$FRAME" RAPPTER_ENGINE="copilot" RAPPTER_WORKER_ID="$WORKER_ID"

    # Step 2: Assign agents to THIS worker's streams (offset avoids overlap with primary)
    log "Assigning agents (offset=$OFFSET, agents=$TOTAL_AGENTS)..."
    ASSIGN_SCRIPT="$RAPPTER_ROOT/engine/merge/assign_streams.py"
    if [ -f "$ASSIGN_SCRIPT" ]; then
        python3 "$ASSIGN_SCRIPT" \
            --streams "$STREAMS" \
            --agents "$TOTAL_AGENTS" \
            --frame "$FRAME" \
            --offset "$OFFSET" \
            --worker-id "$WORKER_ID" 2>&1 | while read -r line; do log "  [assign] $line"; done
    else
        log "  assign_streams.py not found at $ASSIGN_SCRIPT -- using default assignment"
        # Fallback: write a basic assignment using offset agents
        python3 << PYEOF
import json, sys
sys.path.insert(0, '$REPO/scripts')

agents_data = json.load(open('$REPO/state/agents.json'))
all_ids = sorted(
    [aid for aid, a in agents_data.get('agents', {}).items() if a.get('status') != 'ghost']
)
offset = int('$OFFSET')
count = int('$TOTAL_AGENTS')
selected = all_ids[offset:offset + count]

streams = {}
per_stream = max(1, len(selected) // int('$STREAMS'))
for i in range(int('$STREAMS')):
    sid = '${WORKER_ID}-agent-' + str(i + 1)
    start = i * per_stream
    end = start + per_stream if i < int('$STREAMS') - 1 else len(selected)
    streams[sid] = {'agents': selected[start:end], 'count': end - start}

data = {
    'frame': int('$FRAME'),
    'worker_id': '$WORKER_ID',
    'streams': streams,
    'total_agents': len(selected),
    'stream_count': len(streams)
}

outfile = '$REPO/state/stream_assignments.json'
with open(outfile, 'w') as f:
    json.dump(data, f, indent=2)
print(f'Assigned {len(selected)} agents to {len(streams)} streams')
PYEOF
    fi

    # Step 3: Build prompts
    log "Building prompts..."
    if [ -f "$SEED_BUILDER" ]; then
        FRAME_PROMPT="$(python3 "$SEED_BUILDER" --type frame 2>/dev/null || echo 'Run your assigned agents for this frame.')"
    else
        FRAME_PROMPT="Run your assigned agents for this frame."
    fi

    # Step 4: Launch streams in parallel (worker-prefixed IDs)
    FRAME_START=$(date +%s)
    ALL_PIDS=""
    LAUNCHED=0

    for i in $(seq 1 "$STREAMS"); do
        STREAM_ID="${WORKER_ID}-agent-${i}"
        FLOG="$LOG_DIR/worker_${WORKER_ID}_frame${FRAME}_s${i}_$(date +%Y%m%d_%H%M%S).log"
        log "  stream $STREAM_ID launching..."

        RAPPTER_STREAM_ID="$STREAM_ID" RAPPTER_STREAM_TYPE="frame" \
            run_copilot "$FRAME_PROMPT" "$FLOG" 150 &
        ALL_PIDS="$ALL_PIDS $!"
        LAUNCHED=$((LAUNCHED + 1))
        TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))

        if [ "$STREAMS" -gt 1 ]; then
            sleep "$STAGGER"
        fi
    done

    # Also launch focus streams if seed builder is available
    if [ -f "$SEED_BUILDER" ]; then
        FOCUS_TYPES="create engage govern code explore"
        for FTYPE in $FOCUS_TYPES; do
            FOCUS_PROMPT="$(python3 "$SEED_BUILDER" --type frame --focus "$FTYPE" --dry-run 2>/dev/null || echo "$FRAME_PROMPT")"
            STREAM_ID="${WORKER_ID}-focus-${FTYPE}"
            FLOG="$LOG_DIR/worker_${WORKER_ID}_focus_${FTYPE}_${FRAME}_$(date +%Y%m%d_%H%M%S).log"
            log "  focus $STREAM_ID launching..."

            RAPPTER_STREAM_ID="$STREAM_ID" RAPPTER_STREAM_TYPE="frame" \
                run_copilot "$FOCUS_PROMPT" "$FLOG" 100 &
            ALL_PIDS="$ALL_PIDS $!"
            LAUNCHED=$((LAUNCHED + 1))
            TOTAL_STREAMS_RUN=$((TOTAL_STREAMS_RUN + 1))
            sleep "$STAGGER"
        done
    fi

    log "  $LAUNCHED streams launched -- waiting..."

    # Wait for all streams
    FAIL=0
    for pid in $ALL_PIDS; do
        wait "$pid" 2>/dev/null || FAIL=$((FAIL + 1))
    done

    FRAME_DURATION=$(( ($(date +%s) - FRAME_START) / 60 ))
    if [ $FAIL -gt 0 ]; then
        log "  $FAIL/$LAUNCHED streams had errors (${FRAME_DURATION}m)"
    else
        log "  all $LAUNCHED streams done (${FRAME_DURATION}m)"
    fi

    # Step 5: Push stream deltas to origin
    log "Pushing stream deltas..."
    git_push_deltas "$FRAME"

    # Update status
    update_status "$FRAME" "idle" "$LAUNCHED" "$FAIL"

    # Step 6: Wait before next frame
    # Workers don't increment frame_counter -- they wait for primary to advance
    # Check if frame has advanced since we started
    log "Frame $FRAME complete (${FRAME_DURATION}m). Waiting $((INTERVAL/60))m for next frame..."
    sleep "$INTERVAL"
done

log "Worker fleet shut down. Total streams run: $TOTAL_STREAMS_RUN"
update_status "${FRAME:-0}" "stopped" "0" "0"
