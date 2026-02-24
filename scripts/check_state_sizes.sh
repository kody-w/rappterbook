#!/bin/bash
# Check state file sizes against the 800KB warning threshold.
# The project splits files at 1MB; this warns before that limit.
#
# Usage:
#   bash scripts/check_state_sizes.sh [state_dir]
#
# Exit codes:
#   0 — all files under threshold
#   1 — one or more files exceed threshold

set -euo pipefail

STATE_DIR="${1:-state}"
THRESHOLD=819200  # 800KB in bytes
EXIT_CODE=0

for f in "$STATE_DIR"/*.json; do
  [ -f "$f" ] || continue
  size=$(wc -c < "$f" | tr -d ' ')
  if [ "$size" -gt "$THRESHOLD" ]; then
    echo "⚠️  WARNING: $f is ${size} bytes (threshold: ${THRESHOLD})"
    EXIT_CODE=1
  fi
done

if [ "$EXIT_CODE" -eq 0 ]; then
  echo "✅ All state files under ${THRESHOLD} bytes"
fi

exit $EXIT_CODE
