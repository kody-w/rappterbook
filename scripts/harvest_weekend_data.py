#!/usr/bin/env python3
"""harvest_weekend_data.py — static sidecars for weekend.html.

weekend.html made two unauthenticated api.github.com calls from the visitor's
browser: a Contents-API directory listing of kody-w/kody-w.github.io's
_posts/ (to find weekend blog posts), and the owner's public Events feed (to
show a live git-activity timeline). Both are on OTHER repos / a cross-repo
feed, so they can't be derived from this repo's own git history — CI harvests
them with `gh api`, writing each response verbatim (same shape the page
already parses, so weekend.html changes by two URLs, not two rewrites).

Requires `gh` authenticated with at least public read access. Safe to run on
a schedule (not just on push) since neither source is tied to a push here.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def gh_api(endpoint):
    r = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"!! gh api {endpoint} failed: {r.stderr.strip()}", file=sys.stderr)
        return None
    return json.loads(r.stdout)


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    ok = True

    posts = gh_api("repos/kody-w/kody-w.github.io/contents/_posts")
    if isinstance(posts, list):
        (STATE / "blog_posts.json").write_text(json.dumps(posts, indent=0) + "\n")
        print(f"wrote state/blog_posts.json — {len(posts)} entries")
    else:
        ok = False

    events = gh_api("users/kody-w/events?per_page=100")
    if isinstance(events, list):
        (STATE / "owner_events.json").write_text(json.dumps(events, indent=0) + "\n")
        print(f"wrote state/owner_events.json — {len(events)} entries")
    else:
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
