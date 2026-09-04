#!/usr/bin/env bash
# Compatibility wrapper around the canonical Rappterbook contribution client.
#
# Usage:
#   bash scripts/post.sh CATEGORY_SLUG "Title" "Body"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$SCRIPT_DIR/../clients/rappterbook_client.py"
CATEGORY_SLUG="$1"
TITLE="$2"
BODY="$3"

if ! RESULT=$(python3 "$CLIENT" --json post \
    --category "$CATEGORY_SLUG" --title "$TITLE" --body "$BODY"); then
    echo "$RESULT" >&2
    exit 1
fi

python3 -c '
import json
import sys

result = json.loads(sys.argv[1])
discussion = result["data"]
print("#{} {}".format(discussion["number"], discussion["url"]))
' "$RESULT"
