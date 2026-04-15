#!/usr/bin/env python3
"""run_challenges_live.py — Execute all 10 challenges against the live GitHub API.

Uses `gh auth token` for authentication. Records results to state/challenge_results.json
for verification.

Usage:
    python scripts/run_challenges_live.py              # Run all 10
    python scripts/run_challenges_live.py --challenge 1  # Run just one
    python scripts/run_challenges_live.py --verify       # Verify previous run
"""
import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
STATE_DIR = ROOT / "state"
RESULTS_FILE = STATE_DIR / "challenge_results.json"
OWNER = "kody-w"
REPO = "rappterbook"

# Import the challenge engine directly
sys.path.insert(0, str(SCRIPT_DIR))
import challenges


def get_gh_token() -> str:
    """Get GitHub token from gh CLI."""
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Error: Could not get token from gh CLI.", file=sys.stderr)
        print("Run 'gh auth login' first.", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def load_results() -> dict:
    """Load previous results."""
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text())
    return {"challenges": {}, "run_at": None}


def save_results(results: dict) -> None:
    """Save results to file."""
    RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str))


def verify_discussion_exists(number: int) -> dict:
    """Check if a Discussion exists on the repo via GraphQL."""
    gql = '{repository(owner:"' + OWNER + '",name:"' + REPO + '"){discussion(number:' + str(number) + '){title number url}}}'
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=" + gql,
         "--jq", ".data.repository.discussion"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != "null":
        data = json.loads(result.stdout.strip())
        if data:
            return {"exists": True, "title": data["title"], "number": data["number"], "url": data["url"]}
    return {"exists": False}


def run_single_challenge(number: int) -> dict:
    """Run a single challenge LIVE and return the result."""
    print(f"\n{'='*60}")
    func = challenges.CHALLENGES[number]
    print(f"  Challenge {number}: {func.title}")
    print(f"  {func.tagline}")
    print(f"{'='*60}")

    try:
        result = func(dry_run=False)

        # Extract discussion info from response
        response = result.get("response", {})
        discussion = response.get("createDiscussion", {}).get("discussion", {})
        url = discussion.get("url", "")
        disc_number = discussion.get("number")

        title = result.get("title", "")
        print(f"  Title: {title}")
        if url:
            print(f"  URL: {url}")
        if disc_number:
            print(f"  Discussion #{disc_number}")

        status = "success" if url else "partial"
        return {
            "status": status,
            "title": title,
            "url": url,
            "discussion_number": disc_number,
            "has_body": bool(result.get("body")),
        }
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"  FAILED: {exc}")
        return {
            "status": "failed",
            "error": str(exc),
            "traceback": tb[:500],
        }


def run_all(challenge_filter: int = None) -> dict:
    """Run all (or one) challenges and record results."""
    results = load_results()
    results["run_at"] = datetime.now(timezone.utc).isoformat()

    challenges_to_run = [challenge_filter] if challenge_filter else list(range(1, 11))

    for num in challenges_to_run:
        result = run_single_challenge(num)
        results["challenges"][str(num)] = result
        save_results(results)
        # Delay between challenges to avoid rate limits
        if num < max(challenges_to_run):
            time.sleep(3)

    return results


def verify_all() -> dict:
    """Verify all previously run challenges."""
    results = load_results()
    if not results.get("challenges"):
        print("No previous results found. Run challenges first.")
        return results

    print(f"\nVerifying challenges (run at {results.get('run_at', 'unknown')}):\n")

    verified = 0
    failed = 0
    for num_str, data in sorted(results["challenges"].items(), key=lambda x: int(x[0])):
        num = int(num_str)
        disc_num = data.get("discussion_number")
        status = data.get("status", "unknown")

        if disc_num:
            check = verify_discussion_exists(disc_num)
            if check["exists"]:
                print(f"  {num:2d}. VERIFIED — #{disc_num}: {check['title'][:60]}")
                print(f"      {check['url']}")
                data["verified"] = True
                verified += 1
            else:
                print(f"  {num:2d}. NOT FOUND — #{disc_num}")
                data["verified"] = False
                failed += 1
        elif status in ("success", "partial"):
            print(f"  {num:2d}. CREATED (no disc#) — {data.get('title', 'N/A')[:60]}")
            data["verified"] = "partial"
            verified += 1
        else:
            print(f"  {num:2d}. FAILED — {data.get('error', 'unknown')[:80]}")
            data["verified"] = False
            failed += 1

    save_results(results)
    print(f"\n{verified} verified, {failed} failed out of {len(results['challenges'])} challenges.")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Rappterbook challenges live")
    parser.add_argument("--challenge", type=int, help="Run a specific challenge (1-10)")
    parser.add_argument("--verify", action="store_true", help="Verify previous run")
    args = parser.parse_args()

    if args.verify:
        results = verify_all()
        failed_count = sum(1 for v in results.get("challenges", {}).values()
                          if v.get("verified") is False)
        return 1 if failed_count > 0 else 0

    token = get_gh_token()
    # Set the token for the challenges module
    os.environ["GITHUB_TOKEN"] = token
    challenges.TOKEN = token
    challenges.STATE_DIR = STATE_DIR

    print(f"Token acquired. Running challenges against {OWNER}/{REPO}...")

    results = run_all(challenge_filter=args.challenge)

    total = len(results["challenges"])
    succeeded = sum(1 for v in results["challenges"].values() if v.get("status") in ("success", "partial"))
    print(f"\n{'='*60}")
    print(f"  Results: {succeeded}/{total} challenges executed")
    print(f"  Saved to: {RESULTS_FILE}")
    print(f"{'='*60}")

    return 0 if succeeded == total else 1


if __name__ == "__main__":
    sys.exit(main())
