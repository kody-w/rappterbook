#!/usr/bin/env python3
"""harvest_target_repo.py — static sidecars for overseer.html, control.html, factory.html.

All three dashboards polled api.github.com from the visitor's browser (no
Authorization header on the calls this script replaces) for the "target"
factory repo's pull requests and full file tree — kody-w/rappterbook-rappterbook-2,
which is PRIVATE, so those calls were already silently returning nothing for
every anonymous visitor (identical to the AINexus precedent: the API path was
dead on arrival for the audience it ran in front of). CI holds real access via
`gh`, harvests both endpoints, and commits them in the exact API response
shape so all three pages change by one URL each.

Run on a schedule — this data changes as the autonomous build agents work,
independent of pushes to rappterbook itself.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
TARGET = "kody-w/rappterbook-rappterbook-2"


def gh_api(endpoint):
    r = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"!! gh api {endpoint} failed: {r.stderr.strip()}", file=sys.stderr)
        return None
    return json.loads(r.stdout)


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    ok = True

    prs = gh_api(f"repos/{TARGET}/pulls?state=all&per_page=100")
    if isinstance(prs, list):
        (STATE / "target_repo_prs.json").write_text(json.dumps(prs, indent=0) + "\n")
        print(f"wrote state/target_repo_prs.json — {len(prs)} PRs")
    else:
        ok = False

    tree = gh_api(f"repos/{TARGET}/git/trees/main?recursive=1")
    if isinstance(tree, dict) and "tree" in tree:
        (STATE / "target_repo_tree.json").write_text(json.dumps(tree, indent=0) + "\n")
        print(f"wrote state/target_repo_tree.json — {len(tree['tree'])} entries")
    else:
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
