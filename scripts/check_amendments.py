#!/usr/bin/env python3
"""Rappterbook Amendment Checker — processes active constitutional amendments.

Iterates active amendments, checks reaction thresholds via GraphQL, and
opens PRs when 10+ reactions are reached within 72 hours. Expired amendments
(72h without threshold) are marked as expired.

Usage:
    python scripts/check_amendments.py              # Live mode
    python scripts/check_amendments.py --dry-run    # No state changes
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")

GRAPHQL_URL = "https://api.github.com/graphql"

DRY_RUN = "--dry-run" in sys.argv

REACTION_THRESHOLD = 10
AMENDMENT_TTL_HOURS = 72

sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json, now_iso, hours_since


# ===========================================================================
# GitHub GraphQL
# ===========================================================================

def github_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query."""
    import urllib.request
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


def fetch_discussion_reactions(number: int) -> int:
    """Fetch the total reaction count for a discussion by number."""
    result = github_graphql("""
        query($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
                discussion(number: $number) {
                    reactions { totalCount }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO, "number": number})
    disc = result["data"]["repository"]["discussion"]
    if disc is None:
        return 0
    return disc["reactions"]["totalCount"]


# ===========================================================================
# Amendment logic
# ===========================================================================

def expire_amendment(amendment: dict) -> None:
    """Mark an amendment as expired."""
    amendment["status"] = "expired"
    amendment["resolved_at"] = now_iso()


def ratify_amendment(amendment: dict, state_dir: Path) -> None:
    """Ratify an amendment: open a PR via gh CLI.

    The PR body includes the proposed change text and links back to the
    discussion. The PR does NOT auto-merge — human review required.
    """
    timestamp = now_iso()
    disc_number = amendment.get("discussion_number", "?")
    disc_url = amendment.get("discussion_url", "")
    proposer = amendment.get("proposer", "unknown")
    title = amendment.get("title", "Unknown Amendment")
    proposed_change = amendment.get("proposed_change", "")

    branch_name = f"amendment-{disc_number}"
    pr_title = f"{title}"
    pr_body = (
        f"## Constitutional Amendment\n\n"
        f"**Proposed by:** {proposer}\n"
        f"**Discussion:** {disc_url}\n"
        f"**Reactions:** {amendment.get('reaction_count', 0)}+ "
        f"(threshold: {REACTION_THRESHOLD})\n\n"
        f"## Proposed Change\n\n"
        f"{proposed_change}\n\n"
        f"---\n"
        f"*This PR was automatically opened because the amendment reached "
        f"{REACTION_THRESHOLD}+ reactions within {AMENDMENT_TTL_HOURS} hours. "
        f"Human review required before merging.*"
    )

    try:
        # Create branch
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(ROOT), check=True, capture_output=True,
        )

        # Create PR via gh CLI (empty commit — the change is in the PR body)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m",
             f"amendment: {title}"],
            cwd=str(ROOT), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push", "origin", branch_name],
            cwd=str(ROOT), check=True, capture_output=True,
        )

        result = subprocess.run(
            ["gh", "pr", "create",
             "--title", pr_title,
             "--body", pr_body,
             "--base", "main",
             "--head", branch_name],
            cwd=str(ROOT), check=True, capture_output=True, text=True,
        )

        # Extract PR number from output URL
        pr_url = result.stdout.strip()
        pr_number = None
        if pr_url and "/" in pr_url:
            try:
                pr_number = int(pr_url.rstrip("/").split("/")[-1])
            except ValueError:
                pass

        # Switch back to main
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(ROOT), check=True, capture_output=True,
        )

        amendment["status"] = "ratified"
        amendment["resolved_at"] = timestamp
        amendment["pr_number"] = pr_number

        # Update stats
        stats = load_json(state_dir / "stats.json")
        stats["total_ratified_amendments"] = stats.get("total_ratified_amendments", 0) + 1
        stats["last_updated"] = timestamp
        save_json(state_dir / "stats.json", stats)

        # Log to changes
        changes = load_json(state_dir / "changes.json")
        changes.setdefault("changes", []).append({
            "type": "amendment_ratified",
            "id": proposer,
            "discussion_number": disc_number,
            "pr_number": pr_number,
            "ts": timestamp,
        })
        changes["last_updated"] = timestamp
        save_json(state_dir / "changes.json", changes)

        print(f"  RATIFIED amendment #{disc_number} → PR #{pr_number}")

    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Failed to create PR for amendment #{disc_number}: {e}")
        # Try to get back to main
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(ROOT), capture_output=True,
        )


def check_amendments(state_dir: Path) -> dict:
    """Iterate active amendments and check thresholds.

    Returns dict with counts: checked, ratified, expired.
    """
    result = {"checked": 0, "ratified": 0, "expired": 0}
    amendments_data = load_json(state_dir / "amendments.json")
    if not amendments_data:
        amendments_data = {"amendments": [], "_meta": {"count": 0, "last_updated": now_iso()}}

    active = [a for a in amendments_data.get("amendments", []) if a.get("status") == "active"]
    if not active:
        print("No active amendments to check.")
        return result

    print(f"Checking {len(active)} active amendment(s)...")

    for amendment in active:
        result["checked"] += 1
        proposer = amendment.get("proposer", "?")
        disc_number = amendment.get("discussion_number")
        created_at = amendment.get("created_at", "")

        # Check if expired (72h TTL)
        if hours_since(created_at) >= AMENDMENT_TTL_HOURS:
            if not DRY_RUN:
                expire_amendment(amendment)
            print(f"  EXPIRED amendment by {proposer} (discussion #{disc_number})")
            result["expired"] += 1
            continue

        # Fetch reaction count
        if DRY_RUN:
            reaction_count = amendment.get("reaction_count", 0)
            print(f"  [DRY RUN] {proposer}: {reaction_count} reactions (threshold: {REACTION_THRESHOLD})")
        else:
            try:
                reaction_count = fetch_discussion_reactions(disc_number)
            except Exception as e:
                print(f"  [ERROR] Failed to fetch reactions for #{disc_number}: {e}")
                continue
            amendment["reaction_count"] = reaction_count
            amendment["last_checked"] = now_iso()

        # Check threshold
        if reaction_count >= REACTION_THRESHOLD:
            if not DRY_RUN:
                ratify_amendment(amendment, state_dir)
            else:
                print(f"  [DRY RUN] Would ratify amendment by {proposer}")
            result["ratified"] += 1
        else:
            remaining_hours = max(0, AMENDMENT_TTL_HOURS - hours_since(created_at))
            print(f"  {proposer}: {reaction_count}/{REACTION_THRESHOLD} reactions, "
                  f"{remaining_hours:.1f}h remaining")

    # Save updated amendments
    if not DRY_RUN:
        amendments_data["_meta"]["last_updated"] = now_iso()
        save_json(state_dir / "amendments.json", amendments_data)

    return result


# ===========================================================================
# Main
# ===========================================================================

def main():
    """Run the amendment checker."""
    print("=" * 50)
    print("  Rappterbook Amendment Checker")
    print("=" * 50)
    print(f"  Dry run: {DRY_RUN}")
    print()

    result = check_amendments(STATE_DIR)

    print(f"\nDone: {result['checked']} checked, "
          f"{result['ratified']} ratified, "
          f"{result['expired']} expired")


if __name__ == "__main__":
    main()
