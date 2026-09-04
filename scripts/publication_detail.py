#!/usr/bin/env python3
"""Publication readiness for discussions whose detail pages must be complete."""
from __future__ import annotations

import re


VOTE_BODIES = {"⬆️", "👍", "👎", "❤️", "🚀", "👀"}
THREAD_RE = re.compile(r"^<!--\s*thread:\S+\s*-->\n?")
BYLINE_RE = re.compile(r"^\*— \*\*[^*]+\*\*\*\s*\n?", re.MULTILINE)


def strip_comment_byline(body: str) -> str:
    """Remove transport metadata before classifying a comment."""
    text = THREAD_RE.sub("", body or "")
    return BYLINE_RE.sub("", text).strip()


def is_vote_comment(body: str) -> bool:
    """Return whether a comment body carries only a vote signal."""
    return strip_comment_byline(body) in VOTE_BODIES


def detail_status(discussion: dict) -> tuple[bool, str]:
    """Return whether the public detail page can represent the discussion."""
    if "body" not in discussion:
        return False, "body missing"
    total_comments = int(discussion.get("comment_count", 0) or 0)
    if total_comments == 0:
        return True, "body complete; no comments"
    if discussion.get("comments_complete") is not True:
        return False, "comment bodies incomplete"
    top_level = int(discussion.get("top_level_comment_count", -1) or 0)
    if top_level != total_comments:
        return False, (
            f"top-level comment coverage {top_level}/{total_comments}"
        )
    if not isinstance(discussion.get("comments"), list):
        return False, "comments array missing"
    return True, "detail complete"


def partition_publishable(
    discussions: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split the authoritative corpus into publishable and withheld rows."""
    published = []
    withheld = []
    for discussion in discussions:
        ready, reason = detail_status(discussion)
        if ready:
            published.append(discussion)
        else:
            withheld.append({
                "number": discussion.get("number"),
                "reason": reason,
            })
    return published, withheld


def comment_summary(discussion: dict, posted: dict | None = None) -> dict:
    """Count comments while trusting only GitHub's native reaction total."""
    comments = discussion.get("comments") or []
    vote_comments = sum(
        1 for comment in comments
        if is_vote_comment(str(comment.get("body") or ""))
    )
    substantive = len(comments) - vote_comments
    return {
        "comments": substantive,
        "comments_total": len(comments),
        "vote_comment_count": vote_comments,
        "upvotes": int(discussion.get("upvotes", 0) or 0),
    }
