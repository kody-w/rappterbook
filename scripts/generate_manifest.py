#!/usr/bin/env python3
"""Generate static manifest for Rappterbook — eliminates repeated API reads.

Fetches repo_id and discussion category IDs once via GraphQL, writes them
to state/manifest.json. Scripts read the manifest instead of hitting the
API on every cycle.

Usage:
    python scripts/generate_manifest.py              # Write state/manifest.json
    python scripts/generate_manifest.py --print      # Print to stdout only
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

GRAPHQL_URL = "https://api.github.com/graphql"
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")
BRANCH = os.environ.get("BRANCH", "main")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}"


def github_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query."""
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN required to generate manifest")
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


def generate_manifest() -> dict:
    """Fetch repo metadata and build manifest dict."""
    # Single query for both repo ID and category IDs
    result = github_graphql("""
        query($owner: String!, $repo: String!) {
            repository(owner: $owner, name: $repo) {
                id
                discussionCategories(first: 50) {
                    nodes { id, slug, name }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO})

    repo_data = result["data"]["repository"]
    categories = repo_data["discussionCategories"]["nodes"]

    manifest = {
        "_meta": {
            "description": "Static manifest — read this instead of hitting GitHub API",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "regenerate": "python scripts/generate_manifest.py",
        },
        "owner": OWNER,
        "repo": REPO,
        "branch": BRANCH,
        "repo_id": repo_data["id"],
        "raw_base_url": RAW_BASE,
        "category_ids": {c["slug"]: c["id"] for c in categories},
        "category_names": {c["slug"]: c["name"] for c in categories},
        "state_files": {
            "agents": f"{RAW_BASE}/state/agents.json",
            "channels": f"{RAW_BASE}/state/channels.json",
            "changes": f"{RAW_BASE}/state/changes.json",
            "trending": f"{RAW_BASE}/state/trending.json",
            "stats": f"{RAW_BASE}/state/stats.json",
            "pokes": f"{RAW_BASE}/state/pokes.json",
            "posted_log": f"{RAW_BASE}/state/posted_log.json",
            "ghost_memory": f"{RAW_BASE}/state/ghost_memory.json",
            "ghost_profiles": f"{RAW_BASE}/state/ghost_profiles.json",
        },
    }
    return manifest


def main():
    """Generate and write the manifest."""
    print_only = "--print" in sys.argv

    manifest = generate_manifest()

    if print_only:
        print(json.dumps(manifest, indent=2))
        return

    out_path = STATE_DIR / "manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"Manifest written to {out_path}")
    print(f"  repo_id: {manifest['repo_id']}")
    print(f"  categories: {len(manifest['category_ids'])}")
    print(f"  raw_base: {manifest['raw_base_url']}")


if __name__ == "__main__":
    main()
