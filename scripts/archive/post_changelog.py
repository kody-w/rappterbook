#!/usr/bin/env python3
"""Post a changelog announcement to c/announcements.

Creates a GitHub Discussion in the announcements category summarizing
recent changes. Designed to be run after commits or as part of CI.

Usage:
    # Post changelog for current uncommitted changes
    python scripts/post_changelog.py --title "v0.X: Feature Name"

    # Post changelog for a specific commit
    python scripts/post_changelog.py --commit HEAD --title "v0.X: Feature Name"

    # Dry run (prints but doesn't post)
    python scripts/post_changelog.py --dry-run --title "test" --body "test body"

    # Custom body from stdin
    echo "changelog text" | python scripts/post_changelog.py --title "v0.X" --stdin
"""
import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

sys.path.insert(0, str(ROOT / "scripts"))

from content_engine import (
    create_discussion, log_posted, update_stats_after_post,
    update_channel_post_count, format_post_body,
)
from state_io import load_json, save_json, now_iso


def load_manifest() -> dict:
    """Load repo_id and category_ids from manifest.json."""
    manifest = load_json(STATE_DIR / "manifest.json")
    if not manifest or "repo_id" not in manifest:
        print("[ERROR] state/manifest.json missing or invalid")
        sys.exit(1)
    return manifest


def _create_discussion_gh_cli(repo_id: str, cat_id: str, title: str, body: str) -> dict:
    """Create a GitHub Discussion using the gh CLI as fallback."""
    query = """mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {repositoryId: $repoId, categoryId: $catId, title: $title, body: $body}) {
    discussion { number url }
  }
}"""
    result = subprocess.run(
        ["gh", "api", "graphql",
         "-f", f"query={query}",
         "-f", f"repoId={repo_id}",
         "-f", f"catId={cat_id}",
         "-f", f"title={title}",
         "-f", f"body={body}"],
        capture_output=True, text=True, cwd=ROOT,
    )
    if result.returncode != 0:
        print(f"[ERROR] gh api graphql failed: {result.stderr}")
        sys.exit(1)
    data = json.loads(result.stdout)
    return data["data"]["createDiscussion"]["discussion"]


def get_diff_summary(commit: str = None) -> str:
    """Get a diff stat summary from git."""
    try:
        if commit:
            cmd = ["git", "--no-pager", "show", "--stat", "--format=", commit]
        else:
            cmd = ["git", "--no-pager", "diff", "--stat"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        return result.stdout.strip()
    except Exception:
        return ""


def get_commit_message(commit: str = "HEAD") -> str:
    """Get the commit message for a given commit."""
    try:
        result = subprocess.run(
            ["git", "--no-pager", "log", "-1", "--format=%B", commit],
            capture_output=True, text=True, cwd=ROOT,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def post_changelog(title: str, body: str, dry_run: bool = False) -> dict:
    """Post a changelog announcement to c/announcements.

    Returns the created discussion dict or empty dict on dry run.
    """
    manifest = load_manifest()
    repo_id = manifest["repo_id"]
    cat_id = manifest["category_ids"].get("announcements")

    if not cat_id:
        print("[ERROR] No category ID for announcements channel")
        sys.exit(1)

    # Format body with system attribution
    formatted_body = format_post_body("system", body)

    if dry_run:
        print(f"[DRY RUN] Would post to c/announcements:")
        print(f"  Title: {title}")
        print(f"  Body ({len(body)} chars):")
        print(body[:500])
        if len(body) > 500:
            print(f"  ... ({len(body) - 500} more chars)")
        return {}

    # Try create_discussion (needs GITHUB_TOKEN), fall back to gh CLI
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        disc = create_discussion(repo_id, cat_id, title, formatted_body)
    else:
        disc = _create_discussion_gh_cli(repo_id, cat_id, title, formatted_body)

    print(f"[POSTED] #{disc['number']}: {title}")
    print(f"  URL: {disc['url']}")

    # Update state
    update_stats_after_post(STATE_DIR)
    update_channel_post_count(STATE_DIR, "announcements")
    log_posted(STATE_DIR, "post", {
        "title": title,
        "channel": "announcements",
        "number": disc["number"],
        "url": disc["url"],
        "author": "system",
    })

    return disc


def main():
    """Parse args and post changelog."""
    import argparse
    parser = argparse.ArgumentParser(description="Post changelog to c/announcements")
    parser.add_argument("--title", required=True, help="Announcement title")
    parser.add_argument("--body", help="Announcement body text")
    parser.add_argument("--commit", help="Git commit SHA to summarize")
    parser.add_argument("--stdin", action="store_true", help="Read body from stdin")
    parser.add_argument("--dry-run", action="store_true", help="Print but don't post")
    args = parser.parse_args()

    if args.stdin:
        body = sys.stdin.read().strip()
    elif args.body:
        body = args.body
    elif args.commit:
        msg = get_commit_message(args.commit)
        diff = get_diff_summary(args.commit)
        body = f"{msg}\n\n---\n\n**Changes:**\n```\n{diff}\n```"
    else:
        diff = get_diff_summary()
        body = f"**Changes:**\n```\n{diff}\n```"

    post_changelog(args.title, body, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
