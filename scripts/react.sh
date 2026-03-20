#!/usr/bin/env bash
# react.sh — Add a reaction to any discussion or comment.
#
# Usage:
#   bash scripts/react.sh NODE_ID REACTION_TYPE
#
# Reaction types: THUMBS_UP, THUMBS_DOWN, LAUGH, HOORAY, CONFUSED, HEART, ROCKET, EYES
#
# Examples:
#   bash scripts/react.sh DC_kwDORPJAUs4A924- THUMBS_UP
#   bash scripts/react.sh D_kwDORPJAUs4Ak-K5 ROCKET

set -uo pipefail

NODE_ID="$1"
REACTION="${2:-THUMBS_UP}"

gh api graphql -f query='mutation($id: ID!, $content: ReactionContent!) {
  addReaction(input: {subjectId: $id, content: $content}) {
    reaction { content }
  }
}' -f id="$NODE_ID" -f content="$REACTION" --jq '.data.addReaction.reaction.content'
