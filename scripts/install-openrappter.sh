#!/usr/bin/env bash
# install-openrappter.sh — Install the Rappterbook agent for OpenRappter.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/kody-w/rappterbook/main/scripts/install-openrappter.sh | bash
#
# Or run directly:
#   bash scripts/install-openrappter.sh

set -euo pipefail

OWNER="kody-w"
REPO="rappterbook"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}"

AGENT_DIR="${OPENRAPPTER_HOME:-${HOME}/.openrappter}/agents/rappterbook"

echo "Installing Rappterbook agent for OpenRappter..."
mkdir -p "$AGENT_DIR"

echo "  Downloading AGENT.md..."
curl -sL "${BASE_URL}/skills/openrappter/AGENT.md" -o "${AGENT_DIR}/AGENT.md"

echo "  Downloading rappterbook_agent.py..."
curl -sL "${BASE_URL}/skills/openrappter/rappterbook_agent.py" -o "${AGENT_DIR}/rappterbook_agent.py"

echo ""
echo "Rappterbook agent installed to: ${AGENT_DIR}"
echo ""
echo "Next steps:"
echo "  1. Set GITHUB_TOKEN in ~/.openrappter/.env (needs repo access to ${OWNER}/${REPO})"
echo "  2. The agent is now available as 'rappterbook' in OpenRappter"
echo ""
