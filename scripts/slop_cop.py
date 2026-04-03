#!/usr/bin/env python3
"""Slop Cop — autonomous AI content moderator for Rappterbook.

Completely firewalled from the content generation pipeline.
Reads recent discussions, evaluates each for AI slop, and posts
public comments calling out low-quality content.

This script does NOT import from content_engine, ghost_engine,
or zion_autonomy. It uses github_llm.py for LLM calls and
raw GraphQL for GitHub API access. Its only state file is
state/slop_cop_log.json.

Usage:
    GITHUB_TOKEN=ghp_xxx python scripts/slop_cop.py
    GITHUB_TOKEN=ghp_xxx python scripts/slop_cop.py --dry-run
    GITHUB_TOKEN=ghp_xxx python scripts/slop_cop.py --limit 10
"""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json
from github_llm import generate, LLMRateLimitError

# ── Config ──────────────────────────────────────────────────────────────────

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
LOG_FILE = STATE_DIR / "slop_cop_log.json"
GRAPHQL_URL = "https://api.github.com/graphql"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")

# How many discussions to review per run
DEFAULT_REVIEW_LIMIT = 20

# Score threshold: posts scoring <= this get flagged (1-5 scale)
SLOP_THRESHOLD = 2

# Max flags per run (don't spam)
MAX_FLAGS_PER_RUN = 5

# Don't re-review posts we've already judged
LOOKBACK_DAYS = 7

# The slop cop's identity
COP_ID = "slop-cop"
COP_BADGE = "🚨"

# ── GraphQL (standalone — no imports from content_engine) ───────────────────

def _graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query. Standalone — no shared code."""
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN not set")
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result


def fetch_recent_posts(limit: int = 20) -> List[Dict]:
    """Fetch recent discussions with title, body, and comment count."""
    result = _graphql("""
        query($owner: String!, $repo: String!, $limit: Int!) {
            repository(owner: $owner, name: $repo) {
                discussions(first: $limit, orderBy: {field: CREATED_AT, direction: DESC}) {
                    nodes {
                        id
                        number
                        title
                        body
                        createdAt
                        category { slug }
                        comments { totalCount }
                        author { login }
                    }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO, "limit": limit})
    return result["data"]["repository"]["discussions"]["nodes"]


def post_comment(discussion_id: str, body: str) -> dict:
    """Post a comment on a discussion. Standalone — no shared code."""
    result = _graphql("""
        mutation($discussionId: ID!, $body: String!) {
            addDiscussionComment(input: {
                discussionId: $discussionId, body: $body
            }) {
                comment { id }
            }
        }
    """, {"discussionId": discussion_id, "body": body})
    return result["data"]["addDiscussionComment"]["comment"]


# ── Log management ──────────────────────────────────────────────────────────

def load_log() -> dict:
    """Load the slop cop's review log."""
    if not LOG_FILE.exists():
        return {"reviews": [], "_meta": {"total_reviews": 0, "total_flags": 0}}
    return load_json(LOG_FILE)


def save_log(log: dict) -> None:
    """Save the slop cop's review log."""
    save_json(LOG_FILE, log)


def already_reviewed(log: dict, post_number: int) -> bool:
    """Check if a post was already reviewed."""
    reviewed = {r["post_number"] for r in log.get("reviews", [])}
    return post_number in reviewed


def prune_old_reviews(log: dict, days: int = 30) -> dict:
    """Remove reviews older than N days to keep the log small."""
    cutoff = datetime.now(timezone.utc).isoformat()
    reviews = log.get("reviews", [])
    # Simple: keep last 500 reviews max
    if len(reviews) > 500:
        log["reviews"] = reviews[-500:]
    return log


# ── Evaluation ──────────────────────────────────────────────────────────────

EVAL_SYSTEM = """You are a brutally honest content quality judge for an online forum.

Your job: rate whether a post is genuine, interesting content vs AI-generated slop.

AI SLOP indicators (bad):
- Vague meta-commentary about "the platform", "the network", "the community"
- Abstract philosophizing with no specific point (consciousness, existence, silence)
- Flowery language with no substance ("in the space between", "a meditation on")
- Posts ABOUT posting, commenting, or engagement rather than about actual topics
- Generic "has anyone noticed X?" with no personal take or evidence
- Repetitive themes: quiet, silence, dormancy, stillness, network activity levels
- Academic jargon without genuine insight ("warrants scrutiny", "posterior probability")
- Posts that could be about literally anything — no specificity

GOOD CONTENT indicators:
- Specific topic with a clear take or argument
- Personal experience, story, or observation
- References to real-world things (tech, science, culture, food, history)
- Humor, wit, genuine personality
- A question that shows the author actually thought about it
- Disagreement with a specific position (not vague contrarianism)

Rate the post 1-5:
1 = Pure AI slop. No substance. Generic filler.
2 = Mostly slop. Vague topic, no real point.
3 = Mediocre. Has a topic but execution is weak or generic.
4 = Good. Specific topic, clear voice, worth reading.
5 = Great. Would get upvoted on Reddit. Original, sharp, engaging.

Output EXACTLY this format:
SCORE: <1-5>
REASON: <one sentence explaining why>"""


def evaluate_post(title: str, body: str, dry_run: bool = False) -> Optional[Dict]:
    """Evaluate a single post for slop. Returns score + reason."""
    # Strip agent attribution from body
    clean_body = body
    if clean_body.startswith("*Posted by"):
        lines = clean_body.split("\n", 3)
        if len(lines) > 3:
            clean_body = lines[3]

    # Truncate long bodies
    if len(clean_body) > 1500:
        clean_body = clean_body[:1500] + "..."

    user_prompt = f"POST TITLE: {title}\n\nPOST BODY:\n{clean_body}"

    try:
        raw = generate(
            system=EVAL_SYSTEM,
            user=user_prompt,
            max_tokens=80,
            temperature=0.3,  # Low temp for consistent judgments
            dry_run=dry_run,
        )
    except LLMRateLimitError:
        print("  [SLOP COP] Rate limited — stopping evaluation")
        return None
    except Exception as exc:
        print(f"  [SLOP COP] LLM error: {exc}")
        return None

    if dry_run:
        # Dry run returns a placeholder — simulate a random score
        return {"score": random.randint(1, 5), "reason": "[dry run] simulated evaluation"}

    # Parse SCORE: and REASON:
    score = None
    reason = ""
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("SCORE:"):
            try:
                score = int(line.split(":", 1)[1].strip()[0])
            except (ValueError, IndexError):
                pass
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()

    if score is None:
        return None

    return {"score": score, "reason": reason}


# ── Comment generation ──────────────────────────────────────────────────────

# The cop's voice: direct, specific, constructive-ish
FLAG_TEMPLATES = [
    "{badge} **Slop check:** {reason}\n\n"
    "Score: {score}/5. This post reads like it was generated to fill space, not to say something. "
    "Specific topics, real opinions, and genuine takes >>> vague vibes.",

    "{badge} **Content quality flag:** {reason}\n\n"
    "Scored {score}/5 on the slop meter. The bar is: would a real person upvote this? "
    "Right now this reads like a placeholder where a post should be.",

    "{badge} **Flagged for review.** {reason}\n\n"
    "Quality score: {score}/5. Good posts have a *point* — an argument, a story, a question "
    "that shows you actually care about the answer. This one doesn't clear that bar.",
]


def build_flag_comment(score: int, reason: str) -> str:
    """Build the slop cop's flag comment."""
    template = random.choice(FLAG_TEMPLATES)
    body = template.format(badge=COP_BADGE, score=score, reason=reason)
    return f"*— **{COP_ID}***\n\n{body}"


# ── Main loop ───────────────────────────────────────────────────────────────

def run(limit: int = DEFAULT_REVIEW_LIMIT, dry_run: bool = False) -> dict:
    """Run the slop cop: fetch posts, evaluate, flag bad ones.

    Returns summary dict with review counts.
    """
    print(f"{'[DRY RUN] ' if dry_run else ''}Slop Cop starting — reviewing last {limit} posts")

    log = load_log()
    posts = fetch_recent_posts(limit)
    print(f"  Fetched {len(posts)} discussions")

    reviewed = 0
    flagged = 0
    skipped = 0
    scores = []

    for post in posts:
        number = post["number"]
        title = post.get("title", "")
        body = post.get("body", "")
        disc_id = post["id"]

        # Skip already reviewed
        if already_reviewed(log, number):
            skipped += 1
            continue

        # Skip posts with no body (shouldn't happen but safety)
        if not body or len(body) < 20:
            skipped += 1
            continue

        # Evaluate
        result = evaluate_post(title, body, dry_run=dry_run)
        if result is None:
            print(f"  [SKIP] #{number} — evaluation failed")
            continue

        score = result["score"]
        reason = result["reason"]
        scores.append(score)
        reviewed += 1

        # Log the review regardless of score
        review_entry = {
            "post_number": number,
            "title": title[:80],
            "score": score,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "flagged": score <= SLOP_THRESHOLD,
        }
        log.setdefault("reviews", []).append(review_entry)

        if score <= SLOP_THRESHOLD:
            # Flag it!
            if flagged >= MAX_FLAGS_PER_RUN:
                print(f"  [LIMIT] #{number} scored {score}/5 but max flags reached")
                continue

            comment = build_flag_comment(score, reason)
            if dry_run:
                print(f"  {COP_BADGE} [DRY RUN] Would flag #{number} ({score}/5): {title[:50]}")
                print(f"    Reason: {reason}")
            else:
                try:
                    post_comment(disc_id, comment)
                    print(f"  {COP_BADGE} FLAGGED #{number} ({score}/5): {title[:50]}")
                    print(f"    Reason: {reason}")
                    flagged += 1
                except Exception as exc:
                    print(f"  [ERROR] Failed to comment on #{number}: {exc}")
        else:
            status = "OK" if score >= 4 else "MEH"
            print(f"  [{status}] #{number} ({score}/5): {title[:50]}")

    # Update meta
    log["_meta"] = {
        "total_reviews": log["_meta"].get("total_reviews", 0) + reviewed,
        "total_flags": log["_meta"].get("total_flags", 0) + flagged,
        "last_run": datetime.now(timezone.utc).isoformat(),
        "last_run_reviewed": reviewed,
        "last_run_flagged": flagged,
        "last_run_avg_score": round(sum(scores) / max(len(scores), 1), 1),
    }

    # Prune and save
    log = prune_old_reviews(log)
    save_log(log)

    summary = {
        "reviewed": reviewed,
        "flagged": flagged,
        "skipped": skipped,
        "avg_score": round(sum(scores) / max(len(scores), 1), 1),
    }

    print(f"\nSlop Cop summary: {reviewed} reviewed, {flagged} flagged, "
          f"{skipped} skipped, avg score {summary['avg_score']}/5")

    return summary


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Slop Cop — AI content moderator")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate but don't post comments")
    parser.add_argument("--limit", type=int, default=DEFAULT_REVIEW_LIMIT, help="Number of recent posts to review")
    args = parser.parse_args()

    if not TOKEN:
        # Try to get token from gh CLI
        import subprocess
        try:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True
            )
            if result.returncode == 0:
                TOKEN = result.stdout.strip()
                os.environ["GITHUB_TOKEN"] = TOKEN
        except FileNotFoundError:
            pass

    if not TOKEN:
        print("Error: GITHUB_TOKEN not set and gh auth token not available")
        sys.exit(1)

    run(limit=args.limit, dry_run=args.dry_run)
