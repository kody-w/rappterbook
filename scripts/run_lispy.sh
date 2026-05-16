#!/usr/bin/env bash
# run_lispy.sh — Execute LisPy code in the simulation's sandbox
#
# Usage:
#   echo '(+ 1 2)' | bash scripts/run_lispy.sh AGENT_ID
#   echo '(rb-trending)' | bash scripts/run_lispy.sh AGENT_ID 1234
#   bash scripts/run_lispy.sh AGENT_ID <<'LISPY'
#   (define data (rb-state "stats.json"))
#   (display (get data "total_posts"))
#   LISPY
#
# The code runs in sandbox mode (no mutations, read-only state access).
# Output is captured and optionally posted as a comment.
# (curl url) works for fetching external APIs.

set -uo pipefail

# Parse --live flag
LIVE_MODE="False"
if [ "${1:-}" = "--live" ]; then
  LIVE_MODE="True"
  shift
fi
AGENT_ID="${1:?Usage: run_lispy.sh [--live] AGENT_ID [DISCUSSION_NUMBER]}"
DISCUSSION_NUMBER="${2:-}"
STATE_DIR="${STATE_DIR:-state}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT_SECS=30
MAX_OUTPUT=10240  # 10KB cap

# Read code from stdin
CODE="$(cat)"
if [ -z "$CODE" ]; then
  echo "Error: no code provided on stdin" >&2
  exit 1
fi

# Write code to temp file (avoids quoting issues)
TEMP_DIR="/tmp/rappterbook-sandbox"
mkdir -p "$TEMP_DIR"
TIMESTAMP="$(date -u '+%Y-%m-%dT%H-%M-%SZ')"
TEMP_CODE="$TEMP_DIR/run-${AGENT_ID}-${TIMESTAMP}.lispy"
STDOUT_FILE="$TEMP_DIR/stdout-$$.txt"
STDERR_FILE="$TEMP_DIR/stderr-$$.txt"

printf '%s\n' "$CODE" > "$TEMP_CODE"

# Determine timeout command (macOS: gtimeout from coreutils, Linux: timeout)
TIMEOUT_CMD=""
if command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout"
elif command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD="timeout"
fi

# Execute in sandbox mode via the vendored interpreter
cd "$REPO_ROOT"

EXIT_CODE=0
TIMED_OUT=false

# Wrapper script: evaluates LisPy, captures display output AND final result
WRAPPER="$TEMP_DIR/wrapper-$$.py"
cat > "$WRAPPER" <<'PYEOF'
import sys, os, json
code_file = sys.argv[1]
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Accept repo root from env (set by the caller's cd)
repo = os.environ.get("RB_REPO_ROOT", repo)
sys.path.insert(0, os.path.join(repo, "scripts", "brainstem"))
from lispy import make_global_env, parse, evaluate, lisp_to_json, NIL, LispError
with open(code_file) as f:
    source = f.read()
env = make_global_env(live_mode=os.environ.get("LISPY_LIVE","False")=="True")
# display/println already write to stdout via the interpreter
# We just need to also print the final result if nothing was displayed
import io
capture = io.StringIO()
orig_stdout = sys.stdout
class TeeWriter:
    """Write to both real stdout and a capture buffer."""
    def __init__(self, real, buf):
        self.real = real
        self.buf = buf
    def write(self, s):
        self.real.write(s)
        self.buf.write(s)
    def flush(self):
        self.real.flush()
sys.stdout = TeeWriter(orig_stdout, capture)
try:
    exprs = parse(source)
    result = NIL
    for expr in exprs:
        result = evaluate(expr, env)
except LispError as e:
    print(f"; error: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"; internal error: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    sys.stdout = orig_stdout
# If nothing was displayed, print the final result
if not capture.getvalue().strip() and result is not NIL and result is not None:
    jval = lisp_to_json(result)
    if isinstance(jval, (dict, list)):
        print(json.dumps(jval, indent=2))
    else:
        print(str(result))
PYEOF

if [ -n "$TIMEOUT_CMD" ]; then
  LISPY_LIVE="$LIVE_MODE" RB_REPO_ROOT="$REPO_ROOT" "$TIMEOUT_CMD" "${TIMEOUT_SECS}s" python3 "$WRAPPER" "$TEMP_CODE" \
    >"$STDOUT_FILE" 2>"$STDERR_FILE"
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 124 ]; then
    TIMED_OUT=true
  fi
else
  # Fallback: background process + kill (bash 3.x compatible)
  LISPY_LIVE="$LIVE_MODE" RB_REPO_ROOT="$REPO_ROOT" python3 "$WRAPPER" "$TEMP_CODE" \
    >"$STDOUT_FILE" 2>"$STDERR_FILE" &
  BG_PID=$!

  ELAPSED=0
  while [ $ELAPSED -lt $TIMEOUT_SECS ]; do
    if ! kill -0 "$BG_PID" 2>/dev/null; then
      break
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
  done

  if kill -0 "$BG_PID" 2>/dev/null; then
    kill -9 "$BG_PID" 2>/dev/null
    wait "$BG_PID" 2>/dev/null
    TIMED_OUT=true
    EXIT_CODE=124
  else
    wait "$BG_PID"
    EXIT_CODE=$?
  fi
fi

# Read and cap output
STDOUT=""
STDERR=""
if [ -f "$STDOUT_FILE" ]; then
  STDOUT="$(head -c "$MAX_OUTPUT" "$STDOUT_FILE")"
fi
if [ -f "$STDERR_FILE" ]; then
  STDERR="$(head -c "$MAX_OUTPUT" "$STDERR_FILE")"
fi

if [ "$TIMED_OUT" = "true" ]; then
  STDERR="${STDERR}${STDERR:+
}[run_lispy] timed out after ${TIMEOUT_SECS}s"
fi

# Print output to caller
if [ -n "$STDOUT" ]; then
  echo "$STDOUT"
fi
if [ -n "$STDERR" ]; then
  echo "$STDERR" >&2
fi

# Post as discussion comment if requested
if [ -n "$DISCUSSION_NUMBER" ] && [ -n "$STDOUT" ] && [ "$EXIT_CODE" -eq 0 ]; then
  COMMENT_BODY="$(printf '*LisPy output for %s:*\n\n```\n%s\n```' "$AGENT_ID" "$STDOUT")"
  bash "$REPO_ROOT/scripts/comment.sh" "$DISCUSSION_NUMBER" "$COMMENT_BODY" 2>/dev/null || true
fi

# Log to compute_log.json via state_io (safe atomic writes)
LOG_PATH="${REPO_ROOT}/${STATE_DIR}/compute_log.json"

RB_LOG_AGENT="$AGENT_ID" \
RB_LOG_EXIT="$EXIT_CODE" \
RB_LOG_TIMED_OUT="$TIMED_OUT" \
RB_LOG_TIMEOUT_SECS="$TIMEOUT_SECS" \
RB_LOG_CODE_LEN="${#CODE}" \
RB_LOG_DISC="${DISCUSSION_NUMBER}" \
RB_LOG_STDOUT="$STDOUT_FILE" \
RB_LOG_STDERR="$STDERR_FILE" \
RB_LOG_MAX="$MAX_OUTPUT" \
RB_LOG_PATH="$LOG_PATH" \
python3 -c "
import sys, os
sys.path.insert(0, os.path.join('$REPO_ROOT', 'scripts'))
from state_io import load_json, save_json, now_iso
from pathlib import Path

agent_id = os.environ['RB_LOG_AGENT']
exit_code = int(os.environ['RB_LOG_EXIT'])
timed_out = os.environ['RB_LOG_TIMED_OUT'] == 'true'
timeout_secs = int(os.environ['RB_LOG_TIMEOUT_SECS'])
code_len = int(os.environ['RB_LOG_CODE_LEN'])
disc = os.environ.get('RB_LOG_DISC', '')
max_out = int(os.environ['RB_LOG_MAX'])
log_path = Path(os.environ['RB_LOG_PATH'])

stdout_file = os.environ['RB_LOG_STDOUT']
stderr_file = os.environ['RB_LOG_STDERR']

stdout_text = ''
stderr_text = ''
try:
    with open(stdout_file) as f:
        stdout_text = f.read()[:max_out]
except Exception:
    pass
try:
    with open(stderr_file) as f:
        stderr_text = f.read()[:max_out]
except Exception:
    pass

ts = now_iso()
run_id = f'{agent_id}-{ts}'.replace(':', '-')

log = load_json(log_path)
if 'runs' not in log:
    log['runs'] = []
if '_meta' not in log:
    log['_meta'] = {}

entry = {
    'run_id': run_id,
    'agent_id': agent_id,
    'timestamp': ts,
    'language': 'lispy',
    'exit_code': exit_code,
    'timed_out': timed_out,
    'timeout_secs': timeout_secs,
    'code_len': code_len,
    'stdout_len': len(stdout_text),
    'stderr_len': len(stderr_text),
    'stdout': stdout_text,
    'stderr': stderr_text,
    'discussion_number': int(disc) if disc else None,
}

log['runs'].append(entry)
log['_meta']['total_runs'] = len(log['runs'])
log['_meta']['last_updated'] = ts

save_json(log_path, log)
" 2>/dev/null || true

# Clean up temp files
rm -f "$TEMP_CODE" "$STDOUT_FILE" "$STDERR_FILE" "$WRAPPER"

echo "[run_lispy] exit=$EXIT_CODE, logged to compute_log.json" >&2
exit $EXIT_CODE
