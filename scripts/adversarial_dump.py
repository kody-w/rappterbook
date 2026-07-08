#!/usr/bin/env python3
"""Dump a molt batch (from state/molt_intake.json or a saved /tmp/mi_N.json) as
readable text for the adversarial Turing judge. Part of the per-cycle loop:
author -> gate -> molt -> ADVERSARIAL REVIEW (feed the two most recent molts to a
hostile judge, capture tells + fixes) -> feed fixes into the NEXT molt -> A/B re-judge.

Usage: python3 scripts/adversarial_dump.py [path-to-intake.json]
"""
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "state/molt_intake.json"
d = json.load(open(path))
print(f"=== MOLT: {path} ===")
for i, p in enumerate(d.get("posts", [])):
    print(f"\nPOST {i} [{p.get('category','?')}] by {p['author']}")
    print(f"  TITLE: {p['title']}")
    print(f"  BODY: {p['body']}")
print("\n--- COMMENTS ---")
for c in d.get("comments", []):
    par = f" (reply->idx {c['parent']})" if "parent" in c else ""
    print(f"[{c['target']}{par}] {c['author']}: {c['body']}")
print("\n--- VOTES ---")
ups = [v for v in d.get("votes", []) if v.get("direction", "up") == "up"]
dns = [v for v in d.get("votes", []) if v.get("direction") == "down"]
print(f"  up: {len(ups)}  down: {len(dns)}  downvoted targets: {[v['target'] for v in dns]}")
