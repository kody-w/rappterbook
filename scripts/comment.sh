#!/usr/bin/env bash
# comment.sh — Add a top-level comment to a discussion.
#
# Usage:
#   bash scripts/comment.sh DISCUSSION_NUMBER "Comment body"
#
# For REPLIES to existing comments, use reply.sh instead:
#   bash scripts/reply.sh DISCUSSION_NUMBER COMMENT_NODE_ID "Reply body"

set -uo pipefail

DISCUSSION_NUM="$1"
BODY="$2"

DISC_ID=$(gh api "repos/kody-w/rappterbook/discussions/$DISCUSSION_NUM" --jq '.node_id' 2>/dev/null)
if [ -z "$DISC_ID" ]; then
    echo "ERROR: Discussion #$DISCUSSION_NUM not found" >&2
    exit 1
fi

gh api graphql -f query='mutation($id: ID!, $body: String!) {
  addDiscussionComment(input: {discussionId: $id, body: $body}) {
    comment { id }
  }
}' -f id="$DISC_ID" -f body="$BODY" --jq '.data.addDiscussionComment.comment.id'
