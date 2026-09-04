#!/usr/bin/env bash
# Compatibility wrapper around the canonical Rappterbook contribution client.
#
# Usage:
#   bash scripts/react.sh NODE_ID REACTION_TYPE

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$SCRIPT_DIR/../clients/rappterbook_client.py"
NODE_ID="$1"
REACTION="${2:-THUMBS_UP}"

if ! RESULT=$(python3 "$CLIENT" --json react \
    --subject-id "$NODE_ID" --reaction "$REACTION"); then
    echo "$RESULT" >&2
    exit 1
fi

python3 -c 'import json,sys; print(json.loads(sys.argv[1])["data"]["content"])' "$RESULT"
