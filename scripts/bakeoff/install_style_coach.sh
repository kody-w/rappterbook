#!/usr/bin/env bash
# Install StyleCoach into a local brainstem.
# Usage: bash scripts/bakeoff/install_style_coach.sh [BRAINSTEM_HOME]
# Default BRAINSTEM_HOME is ~/.brainstem
set -euo pipefail

BRAINSTEM_HOME="${1:-$HOME/.brainstem}"
SRC="$(cd "$(dirname "$0")" && pwd)/brainstem_agents/style_coach_agent.py"
DST_DIR="$BRAINSTEM_HOME/src/rapp_brainstem/agents"
STATE_DIR="$BRAINSTEM_HOME/state"
STYLE_FILE="$STATE_DIR/style_guide.json"

if [ ! -d "$DST_DIR" ]; then
    echo "ERROR: brainstem agent dir not found: $DST_DIR" >&2
    echo "Install brainstem first:  curl -fsSL https://kody-w.github.io/RAPP/installer/install.sh | bash" >&2
    exit 1
fi

cp "$SRC" "$DST_DIR/style_coach_agent.py"
echo "✓ StyleCoach copied to $DST_DIR/style_coach_agent.py"

mkdir -p "$STATE_DIR"
if [ ! -f "$STYLE_FILE" ]; then
    cat > "$STYLE_FILE" <<'JSON'
{
  "version": "0.0.0",
  "round": 0,
  "rules": [],
  "last_score": {},
  "_meta": {
    "created_by": "scripts/bakeoff/install_style_coach.sh",
    "purpose": "Auto-tuned style rules. Mutated by scripts/bakeoff/bakeoff.py."
  }
}
JSON
    echo "✓ Bootstrapped empty $STYLE_FILE"
else
    echo "✓ Style guide already exists at $STYLE_FILE (untouched)"
fi

# Best-effort hot-reload check
if curl -s "http://127.0.0.1:7071/health" 2>/dev/null | grep -q "StyleCoach"; then
    echo "✓ Brainstem already lists StyleCoach — hot-loaded"
else
    echo "ℹ︎ Brainstem isn't currently listing StyleCoach. Either it's not running, or restart it."
fi
