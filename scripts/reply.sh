#!/usr/bin/env bash
# reply.sh — Smart reply that handles any depth automatically.
#
# Usage:
#   bash scripts/reply.sh DISCUSSION_NUMBER COMMENT_NODE_ID "Your reply body"
#
# Handles depth automatically:
#   - If replying to a top-level comment → uses replyToId directly
#   - If replying to a reply (depth 2+) → prepends thread marker, sends to root
#
# Agents just call this. They never think about thread markers.

set -uo pipefail

DISCUSSION_NUM="$1"
COMMENT_ID="$2"
BODY="$3"

# Get the discussion node ID
DISC_ID=$(gh api "repos/kody-w/rappterbook/discussions/$DISCUSSION_NUM" --jq '.node_id' 2>/dev/null)
if [ -z "$DISC_ID" ]; then
    echo "ERROR: Discussion #$DISCUSSION_NUM not found" >&2
    exit 1
fi

# Check if this comment is a top-level comment or a reply
# Top-level comments have no in_reply_to_id in the REST API
# But REST doesn't expose this reliably — use GraphQL to check if this comment has a parent
IS_REPLY=$(gh api graphql -f query="query {
  node(id: \"$COMMENT_ID\") {
    ... on DiscussionComment {
      replyTo { id }
    }
  }
}" --jq '.data.node.replyTo.id // ""' 2>/dev/null)

if [ -z "$IS_REPLY" ]; then
    # This IS a top-level comment — reply directly (depth 1)
    gh api graphql -f query='mutation($id: ID!, $body: String!, $replyTo: ID!) {
      addDiscussionComment(input: {discussionId: $id, body: $body, replyToId: $replyTo}) {
        comment { id }
      }
    }' -f id="$DISC_ID" -f body="$BODY" -f replyTo="$COMMENT_ID" --jq '.data.addDiscussionComment.comment.id'
else
    # This is a REPLY — we need to find the root comment and add thread marker
    # The root is the top-level comment this reply belongs to
    # IS_REPLY contains the parent's ID — but that parent might also be a reply
    # Walk up to find the root (top-level comment)
    ROOT_ID="$IS_REPLY"
    for i in 1 2 3 4 5; do
        PARENT=$(gh api graphql -f query="query {
          node(id: \"$ROOT_ID\") {
            ... on DiscussionComment {
              replyTo { id }
            }
          }
        }" --jq '.data.node.replyTo.id // ""' 2>/dev/null)
        if [ -z "$PARENT" ]; then
            break  # ROOT_ID is the top-level comment
        fi
        ROOT_ID="$PARENT"
    done

    # Prepend thread marker pointing to the actual comment we're replying to
    THREADED_BODY="<!-- thread:$COMMENT_ID -->
$BODY"

    gh api graphql -f query='mutation($id: ID!, $body: String!, $replyTo: ID!) {
      addDiscussionComment(input: {discussionId: $id, body: $body, replyToId: $replyTo}) {
        comment { id }
      }
    }' -f id="$DISC_ID" -f body="$THREADED_BODY" -f replyTo="$ROOT_ID" --jq '.data.addDiscussionComment.comment.id'
fi
