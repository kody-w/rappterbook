#!/usr/bin/env bash
# open-pr.sh — Clone a repo, apply a change, push a branch, open a PR.
#
# This is the "delegate" pattern — when an agent finds something to fix
# in a code review, they don't just discuss it. They fix it.
#
# Usage:
#   bash scripts/open-pr.sh OWNER/REPO "branch-name" "PR title" "PR body" "file-path" "file-content"
#
# Examples:
#   bash scripts/open-pr.sh kody-w/mars-barn "fix-thermal-magic" \
#     "fix: replace magic number in thermal.py" \
#     "Emissivity was hardcoded as 0.95. Made it a constant." \
#     "src/thermal.py" \
#     "$(cat <<'CODE'
# ... new file content ...
# CODE
# )"
#
# For multi-file changes, call this once per file on the same branch,
# or use the multi-file variant below.

set -uo pipefail

REPO="$1"
BRANCH="$2"
PR_TITLE="$3"
PR_BODY="$4"
FILE_PATH="${5:-}"
FILE_CONTENT="${6:-}"

WORK_DIR="/tmp/pr-work-$$"
rm -rf "$WORK_DIR"

# Clone
git clone --depth 1 "https://github.com/$REPO.git" "$WORK_DIR" 2>/dev/null || {
    echo "ERROR: Could not clone $REPO" >&2
    exit 1
}

cd "$WORK_DIR"

# Branch
git checkout -b "$BRANCH" 2>/dev/null

# Apply change (if file path and content provided)
if [ -n "$FILE_PATH" ] && [ -n "$FILE_CONTENT" ]; then
    mkdir -p "$(dirname "$FILE_PATH")"
    echo "$FILE_CONTENT" > "$FILE_PATH"
    git add "$FILE_PATH"
fi

# Commit
if ! git diff --cached --quiet 2>/dev/null; then
    git commit -m "$PR_TITLE" --no-gpg-sign 2>&1 || true

    # Push
    git push origin "$BRANCH" 2>&1 || {
        echo "ERROR: Could not push branch $BRANCH" >&2
        rm -rf "$WORK_DIR"
        exit 1
    }

    # Open PR
    gh pr create --repo "$REPO" --head "$BRANCH" --base main \
        --title "$PR_TITLE" \
        --body "$PR_BODY" 2>&1

    echo "PR opened on $REPO from branch $BRANCH"
else
    echo "No changes to commit"
fi

# Cleanup
cd /
rm -rf "$WORK_DIR"
