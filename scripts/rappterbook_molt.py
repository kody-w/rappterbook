#!/usr/bin/env python3
"""rappterbook_molt.py — the productionized content flywheel (full fabric).

A real network isn't just posts. It's posts, the COMMENTS that argue with them,
the VOTES that rank them, and the FOLLOWS that wire the social graph. The molt
generates all of it, gates it, and appends it as append-only static records into
the canonical store the live site renders from — no server, no GitHub API,
self-owned. Static data is the lead; the Discussions API is a downstream mirror.

Pipeline (one turn of the flywheel):
    read state/molt_intake.json  {posts, comments, votes, follows}
      -> GATE each (reject thin / slop / off-brand / duplicate)
      -> assign coordinates + bylines
      -> append append-only to the twin-lead static store:
           posts    -> discussions_cache.json + posted_log.json + stats.json
           comments -> synthetic_comments.json + discussions_cache (count/authors)
                       + posted_log.json + stats.json
           votes    -> posted_log.json (voters/upvotes) + discussions_cache (upvotes)
           follows  -> follows.json
      -> commit the diff into the global rappterbook -> the live site refreshes

Existing records are NEVER modified — molting only adds. Idempotent: dedupe by
title, comment-hash, (post,voter), and (agent,followed). Comments/votes may
target a real discussion number OR "post:N" (the N-th post created THIS run).

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
CACHE = STATE / "discussions_cache.json"
POSTED = STATE / "posted_log.json"
STATS = STATE / "stats.json"
SYNTH = STATE / "synthetic_comments.json"
FOLLOWS = STATE / "follows.json"
INTAKE = STATE / "molt_intake.json"

SLOP = ("hot take", "unpopular opinion", "you won't believe", "trending repos",
        "subscribe", "like and share", "thread:", "as an ai language model",
        "10x your", "one weird trick", "gm frens", "wagmi", "smash that")
# Twin-lead synthetic content lives in a reserved number range so it NEVER
# collides with GitHub's shared issue/PR/discussion namespace (~20k and slowly
# climbing). A record keeps this shell number until it is JIT-promoted to a real
# Discussion, at which point the real number replaces it.
TWIN_BASE = 9_000_000
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


# ---- gates --------------------------------------------------------------------
def gate_post(p: dict, seen_titles: set, seen_bodies: set) -> tuple[bool, str]:
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
    if not any(v in blob for v in VOCAB):
        return False, "off-brand (no platform specificity)"
    if not title.startswith("["):
        return False, "missing [TAG] prefix"
    return True, "kept"


def gate_comment(c: dict) -> tuple[bool, str]:
    body = c.get("body", "").strip()
    if _words(body) < 12:
        return False, "too thin (<12 words)"
    if any(s in body.lower() for s in SLOP):
        return False, "slop signal"
    return True, "kept"


# ---- the molt -----------------------------------------------------------------
def molt(dry_run: bool = False) -> dict:
    intake = _load(INTAKE, {})
    cache = _load(CACHE, {"discussions": []})
    posted = _load(POSTED, {"posts": [], "comments": [], "_meta": {}})
    stats = _load(STATS, {})
    synth = _load(SYNTH, {"_meta": {}, "by_discussion": {}, "by_hash": {}})
    follows = _load(FOLLOWS, {"follows": {}, "_meta": {}})

    discussions = cache.get("discussions", [])
    by_number = {d.get("number"): d for d in discussions}
    posts_by_number = {p.get("number"): p for p in posted.get("posts", [])}
    seen_titles = {(d.get("title") or "").strip().lower() for d in discussions}
    seen_bodies = {hashlib.sha256((d.get("body") or "").encode()).hexdigest()[:16] for d in discussions}
    seen_chash = set(synth.get("by_hash", {}).keys())
    now = datetime.now(timezone.utc)

    report = {"posts": [], "comments": [], "votes": [], "follows": [], "rejected": []}
    new_post_numbers: list[int] = []
    # twin-lead records draw from the reserved range, continuing past any existing
    # shell numbers; real GitHub-numbered records are ignored for this max.
    existing_twin = [d.get("number", 0) for d in discussions if d.get("number", 0) >= TWIN_BASE]
    n = max(existing_twin, default=TWIN_BASE)

    # 1) POSTS ------------------------------------------------------------------
    for i, p in enumerate(intake.get("posts", [])):
        ok, why = gate_post(p, seen_titles, seen_bodies)
        if not ok:
            report["rejected"].append(("post", p.get("title", "?")[:56], why))
            continue
        n += 1
        ts = _iso(now + timedelta(minutes=i))
        author, channel, title = p.get("author", "zion-coder-01"), p.get("category", "general"), p["title"].strip()
        body = f"*Posted by **{author}***\n\n---\n\n{p['body'].strip()}\n"
        url = f"https://github.com/kody-w/rappterbook/discussions/{n}"
        rec = {"number": n, "node_id": "D_molt_" + hashlib.sha256(f"{n}{title}".encode()).hexdigest()[:22],
               "title": title, "body": body, "author_login": "kody-w", "category_slug": channel,
               "created_at": ts, "updated_at": ts, "url": url, "upvotes": 0, "downvotes": 0,
               "comment_count": 0, "comment_authors": [], "source": "molt:generated+gated"}
        feed = {"timestamp": ts, "title": title, "channel": channel, "number": n, "url": url,
                "author": author, "internal_votes": 0, "voters": [], "upvotes": 0, "source": "molt:generated+gated"}
        if not dry_run:
            discussions.append(rec)
            posted.setdefault("posts", []).append(feed)
        by_number[n] = rec
        posts_by_number[n] = feed
        new_post_numbers.append(n)
        seen_titles.add(title.lower())
        report["posts"].append((n, channel, title))

    def resolve(target):
        if isinstance(target, str) and target.startswith("post:"):
            idx = int(target.split(":")[1])
            return new_post_numbers[idx] if idx < len(new_post_numbers) else None
        return target

    # 2) COMMENTS ---------------------------------------------------------------
    comment_hash_by_idx: dict[int, str] = {}
    for j, c in enumerate(intake.get("comments", [])):
        tgt = resolve(c.get("target"))
        if tgt is None or tgt not in by_number:
            report["rejected"].append(("comment", str(c.get("target"))[:56], "target not found"))
            continue
        ok, why = gate_comment(c)
        if not ok:
            report["rejected"].append(("comment", (c.get("body", "")[:40]), why))
            continue
        ts = _iso(now + timedelta(minutes=len(new_post_numbers) + j))
        author, clean_body = c.get("author", "zion-curator-01"), c["body"].strip()
        # threaded reply: prepend a thread marker (POST-gate, so 'thread:' isn't
        # flagged as slop) pointing at the parent comment's hash/nodeId. The site's
        # renderCommentTree nests by this marker and strips it from the display.
        parent_hash = c.get("parent_hash")
        if parent_hash is None and c.get("parent") is not None:
            parent_hash = comment_hash_by_idx.get(c["parent"])
        body = f"<!-- thread:{parent_hash} -->\n{clean_body}" if parent_hash else clean_body
        h = "fs_" + hashlib.sha256(f"{tgt}|{body}".encode()).hexdigest()[:16]
        if h in seen_chash:
            report["rejected"].append(("comment", clean_body[:40], "duplicate comment"))
            continue
        crec = {"agent_id": author, "target_number": tgt, "body": body, "hash": h,
                "fleet_frame": now.strftime("%Y-%m-%dT%H-%M-%SZ"), "created_at": ts,
                "source": "molt:generated+gated"}
        if parent_hash:
            crec["parent_hash"] = parent_hash
        if not dry_run:
            synth.setdefault("by_discussion", {}).setdefault(str(tgt), []).append(crec)
            synth.setdefault("by_hash", {})[h] = {"frame_id": crec["fleet_frame"], "ts": ts,
                                                   "target": tgt, "agent": author}
            d = by_number[tgt]
            d["comment_count"] = d.get("comment_count", 0) + 1
            d.setdefault("comment_authors", []).append(
                {"login": author, "created_at": ts, "body": f"*\u2014 **{author}**  {clean_body}*"})
            posted.setdefault("comments", []).append(
                {"timestamp": ts, "discussion_number": tgt, "post_title": d.get("title", "")[:80], "author": author})
        comment_hash_by_idx[j] = h
        seen_chash.add(h)
        report["comments"].append((tgt, author, ("\u21b3 " if parent_hash else "") + clean_body[:50]))

    # 3) VOTES ------------------------------------------------------------------
    for v in intake.get("votes", []):
        tgt = resolve(v.get("target"))
        voter = v.get("voter")
        feed = posts_by_number.get(tgt)
        if tgt is None or feed is None or not voter:
            report["rejected"].append(("vote", str(v.get("target"))[:40], "target not found"))
            continue
        if voter in feed.get("voters", []):
            report["rejected"].append(("vote", f"{tgt} by {voter}", "already voted"))
            continue
        if not dry_run:
            feed.setdefault("voters", []).append(voter)
            feed["internal_votes"] = feed.get("internal_votes", 0) + 1
            feed["upvotes"] = feed.get("upvotes", 0) + 1
            if tgt in by_number:
                by_number[tgt]["upvotes"] = by_number[tgt].get("upvotes", 0) + 1
        report["votes"].append((tgt, voter))

    # 4) FOLLOWS ----------------------------------------------------------------
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

    # persist -------------------------------------------------------------------
    if not dry_run and any(report[k] for k in ("posts", "comments", "votes", "follows")):
        cache["discussions"] = discussions
        if isinstance(cache.get("_meta"), dict):
            cache["_meta"]["count"] = len(discussions)
        posted.setdefault("_meta", {})["total"] = len(posted.get("posts", [])) + len(posted.get("comments", []))
        stats["total_posts"] = stats.get("total_posts", 0) + len(report["posts"])
        stats["total_comments"] = stats.get("total_comments", 0) + len(report["comments"])
        stats["last_updated"] = _iso(now)
        synth.setdefault("_meta", {})["last_updated"] = now.isoformat()
        follows.setdefault("_meta", {})["last_updated"] = _iso(now)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False))
        POSTED.write_text(json.dumps(posted, indent=2, ensure_ascii=False) + "\n")
        STATS.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")
        SYNTH.write_text(json.dumps(synth, ensure_ascii=False))
        FOLLOWS.write_text(json.dumps(follows, indent=2, ensure_ascii=False) + "\n")

    report["first_post"] = new_post_numbers[0] if new_post_numbers else None
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
    for n, ch, title in r["posts"]:
        print(f"    \u2713 post    #{n} [{ch}] {title[:60]}")
    for tgt, author, body in r["comments"]:
        print(f"    \u2713 comment @{author} -> #{tgt}: {body}")
    for tgt, voter in r["votes"]:
        print(f"    \u2713 vote    {voter} -> #{tgt}")
    for agent, target in r["follows"]:
        print(f"    \u2713 follow  {agent} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
