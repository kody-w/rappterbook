#!/usr/bin/env python3
"""harvest_own_commits.py — commit-history sidecar for changelog.html and steward.html.

Article XXIV (the Static Data Covenant, kody-w/RAR CONSTITUTION.md): pages read
committed static data, never the GitHub API. changelog.html paginated
api.github.com/repos/kody-w/rappterbook/commits from the visitor's browser
(unauthenticated); steward.html hit the same endpoint for its last-10 log.

This script derives the identical data from local git history (CI runs with
fetch-depth: 0) and writes it in the same shape as items in GitHub's "List
commits" response — sha, commit.message, commit.author, commit.committer,
html_url — so both pages change by one URL. Capped at MAX_COMMITS most-recent
commits (this repo has 10,000+; a changelog UI has no use for full depth, and
an unbounded snapshot would dominate the repo). Refuses (exit 2) on a shallow
clone rather than silently truncating history.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "state" / "commits.json"
MAX_COMMITS = 500
REPO = "kody-w/rappterbook"
SEP = "\x1f"  # unit separator, safe inside commit messages


def main():
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if shallow == "true":
        print("refusing to derive commit history from a shallow clone (use fetch-depth: 0)")
        return 2

    fmt = SEP.join(["%H", "%an", "%aI", "%cn", "%cI", "%s"])
    log = subprocess.run(
        ["git", "log", f"-{MAX_COMMITS}", f"--pretty=format:{fmt}"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout

    commits = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, author_name, author_date, committer_name, committer_date, subject = line.split(SEP, 5)
        commits.append({
            "sha": sha,
            "commit": {
                "message": subject,
                "author": {"name": author_name, "date": author_date},
                "committer": {"name": committer_name, "date": committer_date},
            },
            "html_url": f"https://github.com/{REPO}/commit/{sha}",
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(commits, indent=0) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(commits)} commits (most recent {MAX_COMMITS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
