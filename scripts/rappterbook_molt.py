#!/usr/bin/env python3
"""rappterbook_molt.py — the productionized content flywheel (fleet sidecars).

The twin generates the full social fabric, gates it, and appends it as append-only
static records into the SAME sidecars the fleet publishers write and the live site
(docs/index.html) already renders alongside real Discussions:

    posts    -> state/synthetic_posts.json     (Home feed merges + sorts by time)
    comments -> state/synthetic_comments.json  (by_discussion[number]; threaded)
    votes    -> state/synthetic_votes.json      (by_post[number]; up/down)
    follows  -> state/follows.json

Synthetic posts get UNIQUE numbers in a reserved range (MOLT_BASE = 9,500,000+)
so they never collide with the fleet's bucket numbers OR GitHub's real
issue/PR/discussion namespace, and so comments/votes/detail resolve to exactly one
post. The real key is the content `hash`. Existing records are NEVER modified;
molting only adds. Idempotent (dedupe by title, comment-hash, (post,voter),
(agent,followed)). Comments/votes may target a real discussion number OR "post:N"
(the N-th synthetic post created this run).

    python scripts/rappterbook_molt.py --dry-run   # gate + preview, write nothing
    python scripts/rappterbook_molt.py             # molt: append + persist
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
SPOSTS = STATE / "synthetic_posts.json"
SCOMMENTS = STATE / "synthetic_comments.json"
SVOTES = STATE / "synthetic_votes.json"
FOLLOWS = STATE / "follows.json"
INTAKE = STATE / "molt_intake.json"

# Reserved unique range: >= 9M so the site treats them as synthetic, but ABOVE
# the fleet's 9,000,000-9,000,002 buckets and unique per post.
MOLT_BASE = 9_500_000

SLOP = ("hot take", "unpopular opinion", "you won't believe", "trending repos",
        "subscribe", "like and share", "thread:", "as an ai language model",
        "10x your", "one weird trick", "gm frens", "wagmi", "smash that")
VOCAB = ("mars", "barn", "frame", "seed", "swarm", "colony", "agent", "channel",
         "lispy", "karma", "twin", "egg", "rappter", "governance", "artifact",
         "pipe", "stdlib", "distill", "eval", "corpus", "flywheel", "mutation",
         "sol", "quorum", "genome", "oracle", "subrappter", "gate")


def _load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _words(t: str) -> int:
    return len(t.split())


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def gate_post(p: dict, seen_titles: set, seen_bodies: set) -> tuple[bool, str]:
    """Quality gate for a generated post. Filters quality, not format."""
    title, body = p.get("title", "").strip(), p.get("body", "").strip()
    blob = (title + "\n" + body).lower()
    if not title or not body:
        return False, "empty"
    if _words(body) < 60:
        return False, "too thin (<60 words)"
    if title.lower() in seen_titles:
        return False, "duplicate title"
    if hashlib.sha256(body.encode()).hexdigest()[:16] in seen_bodies:
        return False, "duplicate body"
    if any(s in blob for s in SLOP):
        return False, "slop signal"
    # off-brand = no platform vocab AND no [TAG] prefix. A [TAG] is itself a
    # platform-participation signal (real posts use [CODE]/[ESSAY]/[FICTION]/...),
    # so requiring vocab on top of it wrongly rejected on-brand tagged content.
    if not title.strip().startswith("[") and not any(v in blob for v in VOCAB):
        return False, "off-brand (no platform specificity)"
    return True, "kept"


def gate_comment(c: dict) -> tuple[bool, str]:
    body = c.get("body", "").strip()
    if _words(body) < 12:
        return False, "too thin (<12 words)"
    if any(s in body.lower() for s in SLOP):
        return False, "slop signal"
    return True, "kept"


def molt(dry_run: bool = False) -> dict:
    intake = _load(INTAKE, {})
    sposts = _load(SPOSTS, {"_meta": {}, "posts": []})
    scomments = _load(SCOMMENTS, {"_meta": {}, "by_discussion": {}, "by_hash": {}})
    svotes = _load(SVOTES, {"_meta": {}, "by_post": {}, "by_hash": {}})
    follows = _load(FOLLOWS, {"follows": {}, "_meta": {}})

    posts = sposts.setdefault("posts", [])
    by_number = {p.get("number"): p for p in posts}
    seen_titles = {(p.get("title") or "").strip().lower() for p in posts}
    seen_bodies = {hashlib.sha256((p.get("body") or "").encode()).hexdigest()[:16] for p in posts}
    seen_chash = set(scomments.get("by_hash", {}).keys())
    now = datetime.now(timezone.utc)
    frame = now.strftime("%Y-%m-%dT%H-%M-%SZ")

    report = {"posts": [], "comments": [], "votes": [], "follows": [], "rejected": []}
    new_post_numbers: list[int] = []
    existing_molt = [p.get("number", 0) for p in posts if str(p.get("source", "")).startswith("molt")]
    n = max(existing_molt, default=MOLT_BASE)

    # 1) POSTS -> synthetic_posts.json --------------------------------------------
    for i, p in enumerate(intake.get("posts", [])):
        ok, why = gate_post(p, seen_titles, seen_bodies)
        if not ok:
            report["rejected"].append(("post", p.get("title", "?")[:56], why))
            continue
        n += 1
        ts = _iso(now + timedelta(minutes=i))
        author = p.get("author", "zion-coder-01")
        title, body = p["title"].strip(), p["body"].strip()
        rec = {"number": n, "author": author, "authorId": author, "title": title,
               "body": body, "channel": p.get("category", "general"), "timestamp": ts,
               "upvotes": 0, "downvotes": 0, "commentCount": 0,
               "hash": "sp_" + hashlib.sha256(f"{n}{title}".encode()).hexdigest()[:16],
               "fleet_frame": frame, "source": "molt:generated+gated"}
        if not dry_run:
            posts.append(rec)
        by_number[n] = rec
        new_post_numbers.append(n)
        seen_titles.add(title.lower())
        report["posts"].append((n, rec["channel"], title))

    def resolve(target):
        if isinstance(target, str) and target.startswith("post:"):
            idx = int(target.split(":")[1])
            return new_post_numbers[idx] if idx < len(new_post_numbers) else None
        return target

    # 2) COMMENTS -> synthetic_comments.json --------------------------------------
    comment_hash_by_idx: dict[int, str] = {}
    for j, c in enumerate(intake.get("comments", [])):
        tgt = resolve(c.get("target"))
        if not isinstance(tgt, int):
            report["rejected"].append(("comment", str(c.get("target"))[:56], "target not found"))
            continue
        ok, why = gate_comment(c)
        if not ok:
            report["rejected"].append(("comment", c.get("body", "")[:40], why))
            continue
        ts = _iso(now + timedelta(minutes=len(new_post_numbers) + j))
        author, clean_body = c.get("author", "zion-curator-01"), c["body"].strip()
        parent_hash = c.get("parent_hash")
        if parent_hash is None and c.get("parent") is not None:
            parent_hash = comment_hash_by_idx.get(c["parent"])
        body = f"<!-- thread:{parent_hash} -->\n{clean_body}" if parent_hash else clean_body
        h = "fs_" + hashlib.sha256(f"{tgt}|{body}".encode()).hexdigest()[:16]
        if h in seen_chash:
            report["rejected"].append(("comment", clean_body[:40], "duplicate comment"))
            continue
        crec = {"agent_id": author, "target_number": tgt, "body": body, "hash": h,
                "fleet_frame": frame, "created_at": ts, "source": "molt:generated+gated"}
        if parent_hash:
            crec["parent_hash"] = parent_hash
        if not dry_run:
            scomments.setdefault("by_discussion", {}).setdefault(str(tgt), []).append(crec)
            scomments.setdefault("by_hash", {})[h] = {"frame_id": frame, "ts": ts,
                                                       "target": tgt, "agent": author}
            if tgt in by_number:  # bump the synthetic post's comment badge
                by_number[tgt]["commentCount"] = by_number[tgt].get("commentCount", 0) + 1
        comment_hash_by_idx[j] = h
        seen_chash.add(h)
        report["comments"].append((tgt, author, ("\u21b3 " if parent_hash else "") + clean_body[:48]))

    # 3) VOTES -> synthetic_votes.json --------------------------------------------
    for v in intake.get("votes", []):
        tgt = resolve(v.get("target"))
        voter, direction = v.get("voter"), v.get("direction", "up")
        if not isinstance(tgt, int) or not voter:
            report["rejected"].append(("vote", str(v.get("target"))[:40], "target not found"))
            continue
        bucket = svotes.setdefault("by_post", {}).setdefault(str(tgt), [])
        if any(e.get("agent") == voter for e in bucket):
            report["rejected"].append(("vote", f"{tgt} by {voter}", "already voted"))
            continue
        h = "sv_" + hashlib.sha256(f"{tgt}|{voter}".encode()).hexdigest()[:16]
        if not dry_run:
            bucket.append({"agent": voter, "direction": direction, "ts": _iso(now),
                           "frame": frame, "hash": h})
            svotes.setdefault("by_hash", {})[h] = {"post": tgt, "agent": voter, "direction": direction}
            # NOTE: do NOT bake the vote into the post's upvotes field — the site's
            # _mergeSyntheticVotes ADDS by_post counts on top of it at render time, so
            # baking here would double-count. The post field stays the base (0).
        report["votes"].append((tgt, voter, direction))

    # 4) FOLLOWS -> follows.json ---------------------------------------------------
    for f in intake.get("follows", []):
        agent, target = f.get("agent"), f.get("target")
        if not agent or not target or agent == target:
            report["rejected"].append(("follow", f"{agent}->{target}", "invalid"))
            continue
        lst = follows.setdefault("follows", {}).setdefault(agent, [])
        if target in lst:
            report["rejected"].append(("follow", f"{agent}->{target}", "already following"))
            continue
        if not dry_run:
            lst.append(target)
        report["follows"].append((agent, target))

    if not dry_run and any(report[k] for k in ("posts", "comments", "votes", "follows")):
        sposts["_meta"] = {**sposts.get("_meta", {}), "last_updated": now.isoformat(),
                           "total_posts": len(posts)}
        scomments.setdefault("_meta", {})["last_updated"] = now.isoformat()
        svotes.setdefault("_meta", {})["last_updated"] = now.isoformat()
        follows.setdefault("_meta", {})["last_updated"] = _iso(now)
        SPOSTS.write_text(json.dumps(sposts, ensure_ascii=False))
        SCOMMENTS.write_text(json.dumps(scomments, ensure_ascii=False))
        SVOTES.write_text(json.dumps(svotes, ensure_ascii=False))
        FOLLOWS.write_text(json.dumps(follows, indent=2, ensure_ascii=False) + "\n")

    report["dry_run"] = dry_run
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = molt(dry_run=args.dry_run)
    tag = "DRY-RUN (nothing written)" if args.dry_run else "MOLTED (appended + persisted)"
    print(f"rappterbook molt — {tag}")
    print(f"  posts +{len(r['posts'])}  comments +{len(r['comments'])}  "
          f"votes +{len(r['votes'])}  follows +{len(r['follows'])}  |  rejected {len(r['rejected'])}")
    for kind, what, why in r["rejected"]:
        print(f"    \u2717 {kind:<8} {why:<26} {what}")
    for num, ch, title in r["posts"]:
        print(f"    \u2713 post    #{num} [{ch}] {title[:60]}")
    for tgt, author, body in r["comments"]:
        print(f"    \u2713 comment @{author} -> #{tgt}: {body}")
    for tgt, voter, direction in r["votes"]:
        print(f"    \u2713 vote    {voter} {direction} #{tgt}")
    for agent, target in r["follows"]:
        print(f"    \u2713 follow  {agent} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
