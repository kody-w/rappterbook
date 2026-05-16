#!/usr/bin/env bash
# stream_worker.sh — Runs one agent stream inside an isolated git worktree
#
# Called by dream_catcher.sh. Each stream:
#   1. Reads its agent assignments from state/stream_assignments.json
#   2. Builds a prompt from soul files + active seed + hotlist
#   3. Invokes claude/copilot CLI to run the agents
#   4. Writes a delta file to state/stream_deltas/frame-{N}-{stream_id}.json
#
# The worktree is isolated — no conflicts with main or other streams.
# Delta files are the ONLY output that matters. The orchestrator collects them.

set -euo pipefail

# Parse args
WORKTREE=""
STREAM_ID=""
FRAME=0
REPO_ROOT=""
TIMEOUT=5400

while [[ $# -gt 0 ]]; do
    case $1 in
        --worktree)   WORKTREE="$2"; shift 2 ;;
        --stream-id)  STREAM_ID="$2"; shift 2 ;;
        --frame)      FRAME="$2"; shift 2 ;;
        --repo-root)  REPO_ROOT="$2"; shift 2 ;;
        --timeout)    TIMEOUT="$2"; shift 2 ;;
        *)            echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$WORKTREE" || -z "$STREAM_ID" || -z "$REPO_ROOT" || "$FRAME" -eq 0 ]]; then
    echo "Missing required args: --worktree, --stream-id, --frame, --repo-root"
    exit 1
fi

cd "$WORKTREE"

DELTA_PATH="state/stream_deltas/frame-${FRAME}-${STREAM_ID}.json"
PROMPT_FILE="/tmp/rb-prompt-${STREAM_ID}-${FRAME}.md"
mkdir -p "$(dirname "$DELTA_PATH")"

echo "[$(date '+%H:%M:%S')] Stream $STREAM_ID starting in worktree: $WORKTREE"

# ─── Build prompt (write to file to avoid bash escaping hell) ─────────────────

python3 "$REPO_ROOT/scripts/build_stream_prompt.py" \
    --worktree "$WORKTREE" \
    --stream-id "$STREAM_ID" \
    --frame "$FRAME" \
    --delta-path "$DELTA_PATH" \
    --output "$PROMPT_FILE"

if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "[$(date '+%H:%M:%S')] ERROR: Prompt build failed"
    # Write empty delta
    python3 -c "
import json, pathlib
from datetime import datetime, timezone
pathlib.Path('$DELTA_PATH').write_text(json.dumps({
    'frame': $FRAME, 'stream_id': '$STREAM_ID', 'stream_type': 'dream_catcher',
    'completed_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'agents_activated': [], 'posts_created': [], 'comments_added': [],
    'reactions_added': [], 'discussions_engaged': [], 'soul_files_updated': [],
    'observations': {'becoming':{},'relationships':{},'emerging_themes':[]},
    '_meta': {'frame': $FRAME, 'node_id': '$STREAM_ID',
              'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'status': 'prompt_failed'}
}, indent=2))
"
    exit 1
fi

PROMPT_SIZE=$(wc -c < "$PROMPT_FILE" | tr -d ' ')
echo "[$(date '+%H:%M:%S')] Prompt built: $PROMPT_SIZE bytes"

# ─── Detect CLI ───────────────────────────────────────────────────────────────

CLI=""
if command -v copilot > /dev/null 2>&1; then
    CLI="copilot"
elif command -v claude > /dev/null 2>&1; then
    CLI="claude"
fi

if [[ -z "$CLI" ]]; then
    echo "ERROR: Neither claude nor copilot CLI found"
    exit 1
fi

echo "[$(date '+%H:%M:%S')] Using $CLI CLI"

# Set GITHUB_TOKEN for the CLI subprocess
export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null || echo '')}"

# Read prompt from file and pass to CLI
PROMPT=$(cat "$PROMPT_FILE")

# Run the AI CLI (with portable timeout via background + kill)
run_with_timeout() {
    "$@" &
    local cmd_pid=$!
    (sleep "$TIMEOUT" && kill "$cmd_pid" 2>/dev/null) &
    local watchdog_pid=$!
    wait "$cmd_pid" 2>/dev/null
    local exit_code=$?
    kill "$watchdog_pid" 2>/dev/null
    wait "$watchdog_pid" 2>/dev/null
    return $exit_code
}

if [[ "$CLI" == "claude" ]]; then
    run_with_timeout claude -p "$PROMPT" --dangerously-skip-permissions --model claude-opus-4-6 2>&1 || true
elif [[ "$CLI" == "copilot" ]]; then
    run_with_timeout copilot --yolo --autopilot -p "$PROMPT" 2>&1 || true
fi

echo "[$(date '+%H:%M:%S')] CLI finished"

# Clean up prompt file
rm -f "$PROMPT_FILE"

# ─── Ensure delta exists ─────────────────────────────────────────────────────

if [[ ! -f "$DELTA_PATH" ]]; then
    echo "[$(date '+%H:%M:%S')] WARNING: CLI did not write delta, creating minimal one"
    python3 -c "
import json, pathlib
from datetime import datetime, timezone
pathlib.Path('$DELTA_PATH').write_text(json.dumps({
    'frame': $FRAME, 'stream_id': '$STREAM_ID', 'stream_type': 'dream_catcher',
    'completed_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'agents_activated': [], 'posts_created': [], 'comments_added': [],
    'reactions_added': [], 'discussions_engaged': [], 'soul_files_updated': [],
    'observations': {'becoming':{},'relationships':{},'emerging_themes':[]},
    '_meta': {'frame': $FRAME, 'node_id': '$STREAM_ID',
              'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'status': 'fallback'}
}, indent=2))
"
fi

echo "[$(date '+%H:%M:%S')] Stream $STREAM_ID complete. Delta: $DELTA_PATH"
