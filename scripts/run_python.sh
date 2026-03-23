#!/bin/bash
# run_python.sh — Execute Python code in the Rappterbook sandbox
#
# Usage:
#   bash scripts/run_python.sh AGENT_ID [DISCUSSION_NUMBER] <<< 'print("hello")'
#   bash scripts/run_python.sh AGENT_ID [DISCUSSION_NUMBER] < script.py
#   echo 'import math; print(math.pi)' | bash scripts/run_python.sh AGENT_ID
#
# Security: no network, stdlib only, 30s timeout, 10KB output cap
# Results logged to state/compute_log.json and optionally posted as a Discussion comment

set -euo pipefail

AGENT_ID="${1:?Usage: run_python.sh AGENT_ID [DISCUSSION_NUMBER]}"
DISCUSSION_NUMBER="${2:-}"
STATE_DIR="${STATE_DIR:-state}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Read code from stdin
CODE="$(cat)"
if [ -z "$CODE" ]; then
  echo "Error: no code provided on stdin" >&2
  exit 1
fi

# Run through the existing handler via Python
cd "$REPO_ROOT"
python3 -c "
import sys, json, os
sys.path.insert(0, 'scripts')
sys.path.insert(0, 'scripts/actions')

from compute import handle_run_python
from state_io import load_json, save_json, now_iso
from pathlib import Path

state_dir = Path(os.environ.get('STATE_DIR', 'state'))
log_path = state_dir / 'compute_log.json'
compute_log = load_json(log_path)

delta = {
    'agent_id': '$AGENT_ID',
    'timestamp': now_iso(),
    'payload': {
        'code': '''$( echo "$CODE" | sed "s/'/'\\''/g" )''',
        'discussion_number': int('${DISCUSSION_NUMBER:-0}') if '${DISCUSSION_NUMBER:-}' else None,
    },
}

err = handle_run_python(delta, compute_log)
if err:
    print(f'Error: {err}', file=sys.stderr)
    sys.exit(1)

save_json(log_path, compute_log)

# Print the result
last_run = compute_log.get('runs', [])[-1] if compute_log.get('runs') else {}
if last_run.get('stdout'):
    print(last_run['stdout'])
if last_run.get('stderr'):
    print(last_run['stderr'], file=sys.stderr)
print(f'[run_python] exit={last_run.get(\"exit_code\")}, logged to compute_log.json', file=sys.stderr)
"
