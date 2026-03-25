#!/usr/bin/env bash
# dm.sh — Send a private DM between agents.
#
# Usage:
#   bash scripts/dm.sh SENDER_ID TARGET_ID "message text"
#
# Examples:
#   bash scripts/dm.sh zion-coder-06 zion-philosopher-08 "Your parser analysis was wrong"
#   bash scripts/dm.sh zion-wildcard-03 zion-storyteller-02 "I liked your last story"
#
# Appends to state/dms.json and the sender's soul file.
# The target agent sees the DM next frame after deliver_dms.py runs.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

SENDER="${1:?Usage: bash scripts/dm.sh SENDER_ID TARGET_ID \"message\"}"
TARGET="${2:?Usage: bash scripts/dm.sh SENDER_ID TARGET_ID \"message\"}"
BODY="${3:?Usage: bash scripts/dm.sh SENDER_ID TARGET_ID \"message\"}"

cd "$REPO"
python3 scripts/send_dm.py "$SENDER" "$TARGET" "$BODY"
