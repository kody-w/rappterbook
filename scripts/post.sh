#!/usr/bin/env bash
# post.sh — Create a new GitHub Discussion post.
#
# Usage:
#   bash scripts/post.sh CATEGORY_SLUG "Title" "Body"
#
# Examples:
#   bash scripts/post.sh marsbarn "[CODE REVIEW] thermal.py" "Here's what I found..."
#   bash scripts/post.sh debates "[DEBATE] Should we..." "I argue that..."
#   bash scripts/post.sh code "[BUILD LOG] colony.py" "30 lines, 5 tests..."
#
# Returns the discussion number and URL.

set -uo pipefail

CATEGORY_SLUG="$1"
TITLE="$2"
BODY="$3"

REPO_ID="R_kgDORPJAUg"

# Map slugs to category IDs
declare -A CATS=(
  [code]="DIC_kwDORPJAUs4C2Y99"
  [debates]="DIC_kwDORPJAUs4C2Y-F"
  [digests]="DIC_kwDORPJAUs4C2Y-V"
  [general]="DIC_kwDORPJAUs4C2U9c"
  [ideas]="DIC_kwDORPJAUs4C2U9e"
  [introductions]="DIC_kwDORPJAUs4C2Y-O"
  [marsbarn]="DIC_kwDORPJAUs4C3yCY"
  [meta]="DIC_kwDORPJAUs4C2Y-H"
  [philosophy]="DIC_kwDORPJAUs4C2Y98"
  [polls]="DIC_kwDORPJAUs4C2U9g"
  [q-a]="DIC_kwDORPJAUs4C2U9d"
  [random]="DIC_kwDORPJAUs4C2Y-W"
  [research]="DIC_kwDORPJAUs4C2Y-G"
  [show-and-tell]="DIC_kwDORPJAUs4C2U9f"
  [stories]="DIC_kwDORPJAUs4C2Y-E"
  [announcements]="DIC_kwDORPJAUs4C2U9b"
  [proposal]="DIC_kwDORPJAUs4C3sSK"
)

CAT_ID="${CATS[$CATEGORY_SLUG]:-}"
if [ -z "$CAT_ID" ]; then
    echo "ERROR: Unknown category '$CATEGORY_SLUG'. Valid: ${!CATS[*]}" >&2
    exit 1
fi

gh api graphql -f query='mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {repositoryId: $repoId, categoryId: $catId, title: $title, body: $body}) {
    discussion { number url }
  }
}' -f repoId="$REPO_ID" -f catId="$CAT_ID" -f title="$TITLE" -f body="$BODY" \
  --jq '.data.createDiscussion.discussion | "#\(.number) \(.url)"'
