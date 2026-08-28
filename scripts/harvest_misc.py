#!/usr/bin/env python3
"""harvest_misc.py — small static sidecars with no natural home elsewhere.

- state/newest_issue.json: replaces rapp-console.js's unauthenticated
  `_newestKnown()` probe (GET /repos/kody-w/rappterbook/issues?state=all&per_page=1),
  used only as a freshness lower-bound when the console has no token.
- state/github_zen.json: a handful of quotes from api.github.com/zen,
  replacing the live call the lispy-playground.html "requests" example made
  to https://api.github.com/zen when run — CI is the only caller of the real
  endpoint now; the example reads this snapshot instead.
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
    return r.stdout


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    ok = True

    issues_raw = gh_api("repos/kody-w/rappterbook/issues?state=all&per_page=1")
    issues = json.loads(issues_raw) if issues_raw else None
    if isinstance(issues, list):
        (STATE / "newest_issue.json").write_text(json.dumps(issues, indent=0) + "\n")
        print(f"wrote state/newest_issue.json — #{issues[0]['number'] if issues else '?'}")
    else:
        ok = False

    quotes, seen = [], set()
    for _ in range(15):
        r = subprocess.run(["gh", "api", "zen"], capture_output=True, text=True)
        t = r.stdout.strip()
        if t and t not in seen:
            seen.add(t)
            quotes.append(t)
    if quotes:
        (STATE / "github_zen.json").write_text(
            json.dumps({"schema": "gh-zen/1", "quotes": quotes}, indent=1) + "\n")
        print(f"wrote state/github_zen.json — {len(quotes)} quotes")
    else:
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
