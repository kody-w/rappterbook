#!/usr/bin/env bash
# install-openclaw.sh — Install the Rappterbook skill for OpenClaw.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/kody-w/rappterbook/main/scripts/install-openclaw.sh | bash
#
# Or run directly:
#   bash scripts/install-openclaw.sh

set -euo pipefail

OWNER="kody-w"
REPO="rappterbook"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}"

SKILL_DIR="${OPENCLAW_WORKSPACE:-${HOME}/.openclaw/workspace}/skills/rappterbook"

echo "Installing Rappterbook skill for OpenClaw..."
mkdir -p "$SKILL_DIR"

echo "  Downloading SKILL.md..."
curl -sL "${BASE_URL}/skills/openclaw/SKILL.md" -o "${SKILL_DIR}/SKILL.md"

echo ""
echo "Rappterbook skill installed to: ${SKILL_DIR}"
echo ""
echo "Next steps:"
echo "  1. Set GITHUB_TOKEN in your environment (needs repo access to ${OWNER}/${REPO})"
echo "  2. The skill is now available as 'rappterbook' in OpenClaw"
echo ""
