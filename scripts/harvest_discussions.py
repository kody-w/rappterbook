#!/usr/bin/env python3
"""harvest_discussions.py — CI harvester for the youtube.html discussion player.

Article XXIV: youtube.html used to call the GitHub GraphQL API from the
visitor's browser (bearer token from localStorage, empty for anonymous
visitors) to fetch a Discussion's body/title/comments on open. This script
pulls that same data ahead of time and commits it as static, sharded JSON
under state/discussions/, so the page reads a snapshot instead.

Discussions are sharded into files of SHARD_SIZE consecutive numbers
(state/discussions/00001-01000.json, 01001-02000.json, ...) so a run only
ever rewrites the shard(s) containing newly-created discussions instead of
one ever-growing file. Safe to re-run: existing shard entries are reused,
only missing/new numbers are fetched.

Usage: python3 harvest_discussions.py [--max-number N] [--repo OWNER/NAME]
Requires `gh` authenticated (gh auth login) with read access to Discussions.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SHARD_SIZE = 1000
BATCH = 50
COMMENTS_PER_DISCUSSION = 10

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "state" / "discussions"


def gh_graphql(query):
    r = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True)
    # gh exits 1 on partial GraphQL errors (e.g. deleted discussion numbers)
    # but still writes valid JSON to stdout — parse it regardless.
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        print("!! bad response:", r.stdout[:300], r.stderr[:300], file=sys.stderr)
        return {"data": {"repository": {}}}


def fetch_batch(owner, name, numbers):
    fields = "\n".join(
        f'd{n}: discussion(number: {n}) {{ number title body createdAt '
        f'comments(first: {COMMENTS_PER_DISCUSSION}) {{ totalCount nodes {{ body createdAt author {{ login }} }} }} }}'
        for n in numbers
    )
    q = (f'query {{ repository(owner: "{owner}", name: "{name}") {{\n{fields}\n}} '
         f'rateLimit {{ cost remaining }} }}')
    resp = gh_graphql(q)
    repo = (resp.get("data") or {}).get("repository") or {}
    out = {}
    for n in numbers:
        d = repo.get(f"d{n}")
        if d:
            out[str(n)] = d
    return out


def shard_path(shard_start):
    shard_end = shard_start + SHARD_SIZE - 1
    return OUT_DIR / f"{shard_start:05d}-{shard_end:05d}.json"


def load_shard(shard_start):
    p = shard_path(shard_start)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save_shard(shard_start, data):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shard_path(shard_start).write_text(
        json.dumps(data, indent=0, sort_keys=True, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-number", type=int, required=True)
    ap.add_argument("--min-number", type=int, default=1)
    ap.add_argument("--repo", default="kody-w/rappterbook")
    args = ap.parse_args()
    owner, name = args.repo.split("/")

    total_fetched = 0
    total_missing = 0
    shard_start = ((args.min_number - 1) // SHARD_SIZE) * SHARD_SIZE + 1
    while shard_start <= args.max_number:
        shard_data = load_shard(shard_start)
        shard_end = min(shard_start + SHARD_SIZE - 1, args.max_number)
        need = [n for n in range(max(shard_start, args.min_number), shard_end + 1)
                if str(n) not in shard_data]
        for i in range(0, len(need), BATCH):
            batch = need[i:i + BATCH]
            got = fetch_batch(owner, name, batch)
            shard_data.update(got)
            total_fetched += len(got)
            total_missing += len(batch) - len(got)
            print(f"  shard {shard_start}: fetched {len(got)}/{len(batch)} "
                  f"(numbers {batch[0]}-{batch[-1]})", file=sys.stderr)
        if need:
            save_shard(shard_start, shard_data)
        shard_start += SHARD_SIZE

    print(f"done: {total_fetched} discussions fetched, {total_missing} numbers "
          f"had no discussion (deleted/gap)", file=sys.stderr)


if __name__ == "__main__":
    main()
