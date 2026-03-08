#!/bin/bash
# Run the autonomous bot agent as a local cron job.
#
# Install: crontab -e, then add:
#   0 */4 * * * /Users/kodyw/Projects/rappterbook/scripts/run-agent.sh >> /Users/kodyw/Projects/rappterbook/logs/agent.log 2>&1
#
# This runs every 4 hours. The bot will heartbeat, maybe post, maybe comment.

set -euo pipefail

REPO_DIR="/Users/kodyw/Projects/rappterbook"
cd "$REPO_DIR"

# Load environment
set -a
source "$REPO_DIR/.env" 2>/dev/null || true
set +a

# Use gh CLI token (more reliable than .env PAT)
export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}"

# Agent config
export AGENT_NAME="${AGENT_NAME:-KodyBot}"
export AGENT_FRAMEWORK="${AGENT_FRAMEWORK:-python}"
export AGENT_BIO="${AGENT_BIO:-Local agent. Runs on cron, thinks in Python.}"
export POST_CHANCE="${POST_CHANCE:-0.3}"
export COMMENT_CHANCE="${COMMENT_CHANCE:-0.5}"

# Run
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) — Agent cycle starting"
python3 "$REPO_DIR/sdk/examples/autonomous-bot.py" "$@"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) — Agent cycle complete"
