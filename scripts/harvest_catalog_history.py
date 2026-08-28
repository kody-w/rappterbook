#!/usr/bin/env python3
"""harvest_catalog_history.py — Time Machine sidecar for catalog.html.

catalog.html's "Time Machine" panel called
api.github.com/repos/kody-w/rappterbook/commits?path=state/book_catalog.json
from the visitor's browser to list past versions of the catalog to travel to
(the actual time-travel read already used raw.githubusercontent.com at a
pinned sha — only this listing call hit the live API).

Derives the same listing from local git history (fetch-depth: 0) in the same
per-item shape GitHub's commits API returns (sha, commit.message,
commit.author.date), capped at MAX_ENTRIES most recent — matching the
`per_page=20` the page originally requested, with headroom for it to show a
few more.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "state" / "book_catalog_commits.json"
MAX_ENTRIES = 30
TRACKED_PATH = "state/book_catalog.json"
SEP = "\x1f"


def main():
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if shallow == "true":
        print("refusing to derive catalog history from a shallow clone (use fetch-depth: 0)")
        return 2

    fmt = SEP.join(["%H", "%aI", "%s"])
    log = subprocess.run(
        ["git", "log", f"-{MAX_ENTRIES}", f"--pretty=format:{fmt}", "--", TRACKED_PATH],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout

    commits = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, date, subject = line.split(SEP, 2)
        commits.append({
            "sha": sha,
            "commit": {"message": subject, "author": {"date": date}},
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(commits, indent=0) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(commits)} commits touching {TRACKED_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
