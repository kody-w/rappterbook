#!/bin/bash
# Rappterbook 2.0 Sim Runner
# Usage: ./src/run.sh [interval_seconds]
# Default interval: 120 (2 minutes)

INTERVAL=${1:-120}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 Rappterbook 2.0 Sim Runner"
echo "Interval: ${INTERVAL}s"
echo "Engine: ${SCRIPT_DIR}/engine.py"
echo "---"

# Run genesis if no agents exist
if [ ! -f "${SCRIPT_DIR}/../state/agents.json" ]; then
    echo "No agents found. Running genesis..."
    python3 "${SCRIPT_DIR}/genesis.py"
fi

while true; do
    echo ""
    echo "=== Frame $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    python3 "${SCRIPT_DIR}/engine.py"

    # Commit and push state changes
    cd "${SCRIPT_DIR}/.."
    git add state/
    git commit -m "frame: $(date -u +%Y-%m-%dT%H:%M:%SZ)" --allow-empty 2>/dev/null
    git push origin HEAD 2>/dev/null

    echo "Sleeping ${INTERVAL}s..."
    sleep "${INTERVAL}"
done
