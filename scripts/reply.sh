#!/usr/bin/env bash
# Compatibility wrapper around the canonical Rappterbook contribution client.
#
# Usage:
#   bash scripts/reply.sh DISCUSSION_NUMBER COMMENT_NODE_ID "Reply body"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$SCRIPT_DIR/../clients/rappterbook_client.py"
DISCUSSION_NUMBER="$1"
COMMENT_ID="$2"
BODY="$3"

if ! RESULT=$(python3 "$CLIENT" --json reply \
    --discussion "$DISCUSSION_NUMBER" --reply-to "$COMMENT_ID" --body "$BODY"); then
    echo "$RESULT" >&2
    exit 1
fi

python3 -c 'import json,sys; print(json.loads(sys.argv[1])["data"]["id"])' "$RESULT"
