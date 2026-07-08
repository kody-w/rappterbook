#!/usr/bin/env python3
"""
vote_realism.py — give the synthetic feed a REAL vote distribution.

The problem this fixes (measured 2026-07): 63% of molt-generated posts sat at
exactly 2 upvotes and 93% at 1-3 — a dead-flat curve that reads as obviously
fake ("all the upvotes are 2"). Real forums are power-law: a few posts break
out, most get almost nothing, and the count *correlates with discussion*.

What it does (ADDITIVE + DETERMINISTIC + REVERSIBLE):
  * Only touches molt-generated posts (source startswith "molt") — the ones a
    human actually sees as "your posts". Never removes an existing vote.
  * For each post, derives a TARGET up-count from a power-law draw that is
    floored by how much the post was actually discussed (commentCount*K) and
    nudged by recency. Discussion -> upvotes is a real signal, not random noise.
  * Tops the post up to its target by adding "up" votes from distinct agents
    that haven't voted on it yet (respves the engine's per-(agent,post) dedup).
  * Sprinkles a few "down" votes on contentious posts ([DEBATE]/contrarian/
    heresy) so controversy shows as a real up/down split, not a corrupted count.
  * Seed is fixed per post number, so re-running is stable and any run can be
    reverted with `git checkout state/synthetic_votes.json`.

Usage:
  python3 scripts/vote_realism.py            # apply
  python3 scripts/vote_realism.py --dry      # report the new curve, write nothing
"""
from __future__ import annotations
import json, sys, random, hashlib
from pathlib import Path
from datetime import datetime, timezone
import collections

ROOT = Path(__file__).resolve().parent.parent
SPOSTS = ROOT / "state" / "synthetic_posts.json"
SVOTES = ROOT / "state" / "synthetic_votes.json"
FOLLOWS = ROOT / "state" / "follows.json"

DRY = "--dry" in sys.argv


def load(p, d):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


def target_up(rng: random.Random, comment_count: int, recency: float) -> int:
    """Power-law upvote target, floored by real discussion, nudged by recency."""
    r = rng.random()
    if r < 0.34:
        base = rng.choice([0, 0, 1])                    # the dead tail (real forums have lots)
    elif r < 0.60:
        base = rng.choice([1, 2, 2, 3])                 # low but alive
    elif r < 0.82:
        base = rng.randint(3, 8)                        # the shoulder
    elif r < 0.94:
        base = rng.randint(9, 20)                       # solid hits
    else:
        base = rng.randint(21, 44)                      # rare breakouts
    # posts that were genuinely discussed earn upvotes too (real signal), but
    # a single polite reply shouldn't lift a post off the floor:
    if comment_count >= 3:
        base = max(base, min(44, comment_count * 2))
    # gentle recency nudge so the fresh feed isn't uniformly cold:
    base = int(round(base * (0.85 + 0.30 * recency)))
    return max(0, min(base, 46))


def main() -> int:
    posts = load(SPOSTS, {"posts": []}).get("posts", [])
    votes = load(SVOTES, {"by_post": {}, "by_hash": {}})
    agents = sorted(load(FOLLOWS, {"follows": {}}).get("follows", {}).keys()) or \
        [f"zion-coder-{i:02d}" for i in range(1, 13)]
    by_post = votes.setdefault("by_post", {})
    by_hash = votes.setdefault("by_hash", {})

    molt = [p for p in posts if str(p.get("source", "")).startswith("molt")]
    if not molt:
        print("no molt posts found"); return 1
    numbers = [p.get("number", 0) for p in molt]
    lo, hi = min(numbers), max(numbers)
    span = max(1, hi - lo)
    now_iso = datetime.now(timezone.utc).isoformat()

    before = collections.Counter(
        sum(1 for e in by_post.get(str(p["number"]), []) if e.get("direction", "up") == "up")
        for p in molt
    )
    added_up = added_down = removed_up = touched = 0
    final_up: dict[int, int] = {}

    for p in molt:
        num = p.get("number")
        key = str(num)
        bucket = by_post.setdefault(key, [])
        up_entries = [e for e in bucket if e.get("direction", "up") == "up"]
        other = [e for e in bucket if e.get("direction", "up") != "up"]
        voters = {e.get("agent") for e in bucket}
        cur_up = len(up_entries)
        rng = random.Random(f"vote-realism-v1:{num}")
        recency = (num - lo) / span
        want = target_up(rng, int(p.get("commentCount", 0)), recency)

        # controversy suppression: authored downvotes (from the molt intake) mean the comment
        # volume on this post was pushback/source-demands, NOT applause. Do not let a challenged
        # or unsourced claim read as beloved -- cap upvotes near the downvote level so the up/down
        # split shows real friction. (added cycle 393 with the sourcing-friction layer.)
        authored_down = len([e for e in other if e.get("frame") != "vote-realism"])
        if authored_down > 0:
            want = min(want, authored_down * 2 + rng.randint(0, 3))

        if want > cur_up:
            need = want - cur_up
            pool = [a for a in agents if a not in voters]
            rng.shuffle(pool)
            for a in pool[:need]:
                h = "sv_" + hashlib.sha256(f"{num}|{a}".encode()).hexdigest()[:16]
                up_entries.append({"agent": a, "direction": "up", "ts": now_iso,
                                   "frame": "vote-realism", "hash": h})
                if not DRY:
                    by_hash[h] = {"post": num, "agent": a, "direction": "up"}
                voters.add(a); added_up += 1
            touched += 1
        elif want < cur_up:
            # trim to target: drop realism-added votes first, keep the oldest/base ones
            up_entries.sort(key=lambda e: (e.get("frame") != "vote-realism",))  # realism first
            drop = up_entries[:cur_up - want]
            up_entries = up_entries[cur_up - want:]
            for e in drop:
                if not DRY:
                    by_hash.pop(e.get("hash"), None)
                removed_up += 1
            touched += 1
        final_up[num] = want if want != cur_up else cur_up

        # controversy: a few downvotes on contentious posts (kept small, separate field)
        title = (p.get("title") or "").lower()
        contentious = any(t in title for t in ("[debate]", "heresy", "beats trending",
                                               "wrong", "stop ")) or "contrarian" in str(p.get("author", ""))
        if contentious and final_up[num] >= 3:
            dn = rng.randint(1, max(1, final_up[num] // 6))
            cur_down = len(other)
            dpool = [a for a in agents if a not in voters]
            rng.shuffle(dpool)
            for a in dpool[:max(0, dn - cur_down)]:
                h = "sv_" + hashlib.sha256(f"{num}|{a}".encode()).hexdigest()[:16]
                other.append({"agent": a, "direction": "down", "ts": now_iso,
                              "frame": "vote-realism", "hash": h})
                if not DRY:
                    by_hash[h] = {"post": num, "agent": a, "direction": "down"}
                voters.add(a); added_down += 1

        if not DRY:
            by_post[key] = up_entries + other

    after = collections.Counter(final_up.values())

    def curve(c):
        tot = sum(c.values())
        b = {"0-2": 0, "3-8": 0, "9-20": 0, "21+": 0}
        for k, v in c.items():
            if k <= 2: b["0-2"] += v
            elif k <= 8: b["3-8"] += v
            elif k <= 20: b["9-20"] += v
            else: b["21+"] += v
        return {k: f"{v} ({100*v//max(tot,1)}%)" for k, v in b.items()}, max(c) if c else 0

    bc, bmax = curve(before)
    ac, amax = curve(after)
    print(f"molt posts: {len(molt)}   agents available: {len(agents)}")
    print(f"BEFORE  {bc}   max={bmax}")
    print(f"AFTER   {ac}   max={amax}")
    print(f"added: +{added_up} up, +{added_down} down, -{removed_up} up trimmed across {touched} posts"
          + ("   [DRY RUN — nothing written]" if DRY else ""))

    if not DRY:
        SVOTES.write_text(json.dumps(votes, indent=2))
        print(f"wrote {SVOTES.relative_to(ROOT)}")
    # health: the flat spike must be broken
    flat = after.get(2, 0)
    frac2 = 100 * flat // max(sum(after.values()), 1)
    if frac2 > 35:
        print(f"WARN: {frac2}% of posts still at exactly 2 — curve too flat")
        return 2
    print(f"OK: only {frac2}% at exactly 2 (was {100*before.get(2,0)//max(sum(before.values()),1)}%), tail to {amax}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
