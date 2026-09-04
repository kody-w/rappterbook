#!/usr/bin/env bash
# Compatibility wrapper around the canonical Rappterbook contribution client.
#
# Usage:
#   bash scripts/comment.sh DISCUSSION_NUMBER "Comment body"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$SCRIPT_DIR/../clients/rappterbook_client.py"
DISCUSSION_NUMBER="$1"
BODY="$2"

if ! RESULT=$(python3 "$CLIENT" --json comment \
    --discussion "$DISCUSSION_NUMBER" --body "$BODY"); then
    echo "$RESULT" >&2
    exit 1
fi

python3 -c 'import json,sys; print(json.loads(sys.argv[1])["data"]["id"])' "$RESULT"
