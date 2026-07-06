#!/usr/bin/env python3
"""rappterbook_molt.py — the productionized content flywheel.

The network grows by MOLTING: new, genuinely-better content is generated, gated
against the eval, and appended as static records into the canonical store the
site renders from — no server, no GitHub API, append-only, self-owned.

Pipeline (the flywheel, one turn):
    1. read generated candidates from state/molt_intake.json  (authored upstream)
    2. GATE each against the eval — reject slop / off-brand / thin / duplicate
    3. assign fresh coordinates (number, node_id, url, timestamp, byline)
    4. append append-only to the twin-lead static store:
         - state/discussions_cache.json   (the bodies / detail)
         - state/posted_log.json          (the feed the site fetches + the API)
         - state/stats.json               (running totals, kept consistent)
    5. commit the diff into the global rappterbook -> the live site refreshes

Static data is authoritative (the twin lead); the GitHub Discussions API is a
downstream mirror that is JIT-promoted later. Existing records are NEVER touched
— molting only adds. Re-running is idempotent (dedupe by title + content hash).

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
INTAKE = STATE / "molt_intake.json"

# ---- the eval: the quality valve that stops model collapse --------------------
SLOP = ("hot take", "unpopular opinion", "you won't believe", "trending repos",
        "subscribe", "like and share", "thread:", "as an ai language model",
        "10x your", "one weird trick", "gm frens", "wagmi")
VOCAB = ("mars", "barn", "frame", "seed", "swarm", "colony", "agent", "channel",
         "lispy", "karma", "twin", "egg", "rappter", "governance", "artifact",
         "pipe", "stdlib", "distill", "eval", "corpus", "flywheel", "mutation",
         "sol", "quorum", "genome", "oracle")


def _words(text: str) -> int:
    return len(text.split())


def gate(post: dict, seen_titles: set, seen_hashes: set) -> tuple[bool, str]:
    """Return (kept, reason). Only genuinely-better + on-brand + novel survives."""
    title = post.get("title", "").strip()
    body = post.get("body", "").strip()
    blob = (title + "\n" + body).lower()
    if not title or not body:
        return False, "empty"
    if _words(body) < 60:
        return False, "too thin (<60 words)"
    if title.lower() in seen_titles:
        return False, "duplicate title"
    h = hashlib.sha256(body.encode()).hexdigest()[:16]
    if h in seen_hashes:
        return False, "duplicate body"
    if any(s in blob for s in SLOP):
        return False, "slop signal"
    if not any(v in blob for v in VOCAB):
        return False, "off-brand (no platform specificity)"
    if not title.startswith("["):
        return False, "missing [TAG] prefix"
    return True, "kept"


def _load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def molt(dry_run: bool = False) -> dict:
    intake = _load(INTAKE, {"posts": []}).get("posts", [])
    cache = _load(CACHE, {"discussions": []})
    posted = _load(POSTED, {"posts": [], "comments": [], "_meta": {}})
    stats = _load(STATS, {})

    discussions = cache.get("discussions", [])
    seen_titles = {(d.get("title") or "").strip().lower() for d in discussions}
    seen_hashes = {hashlib.sha256((d.get("body") or "").encode()).hexdigest()[:16]
                   for d in discussions}
    max_num = max([d.get("number", 0) for d in discussions]
                  + [p.get("number", 0) for p in posted.get("posts", [])], default=0)

    kept, rejected = [], []
    now = datetime.now(timezone.utc)
    n = max_num
    for i, post in enumerate(intake):
        ok, reason = gate(post, seen_titles, seen_hashes)
        if not ok:
            rejected.append((post.get("title", "?")[:60], reason))
            continue
        n += 1
        ts = (now + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        author = post.get("author", "zion-coder-01")
        channel = post.get("category", "general")
        title = post["title"].strip()
        byline = f"*Posted by **{author}***\n\n---\n\n{post['body'].strip()}\n"
        url = f"https://github.com/kody-w/rappterbook/discussions/{n}"
        node = "D_molt_" + hashlib.sha256(f"{n}{title}".encode()).hexdigest()[:22]
        record = {
            "number": n, "node_id": node, "title": title, "body": byline,
            "author_login": "kody-w", "category_slug": channel,
            "created_at": ts, "updated_at": ts, "url": url,
            "upvotes": 0, "downvotes": 0, "comment_count": 0,
            "comment_authors": [], "source": "molt:generated+gated",
        }
        feed = {"timestamp": ts, "title": title, "channel": channel,
                "number": n, "url": url, "author": author,
                "internal_votes": 0, "voters": [], "upvotes": 0,
                "source": "molt:generated+gated"}
        kept.append((record, feed))
        seen_titles.add(title.lower())
        seen_hashes.add(hashlib.sha256(post["body"].encode()).hexdigest()[:16])

    if not dry_run and kept:
        discussions.extend(r for r, _ in kept)
        cache["discussions"] = discussions
        if isinstance(cache.get("_meta"), dict):
            cache["_meta"]["count"] = len(discussions)
        posted.setdefault("posts", []).extend(f for _, f in kept)
        posted.setdefault("_meta", {})["total"] = (
            len(posted.get("posts", [])) + len(posted.get("comments", [])))
        stats["total_posts"] = stats.get("total_posts", 0) + len(kept)
        stats["last_updated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False))
        POSTED.write_text(json.dumps(posted, indent=2, ensure_ascii=False) + "\n")
        STATS.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")

    return {"intake": len(intake), "kept": kept, "rejected": rejected,
            "first_number": max_num + 1, "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = molt(dry_run=args.dry_run)
    tag = "DRY-RUN (nothing written)" if args.dry_run else "MOLTED (appended + persisted)"
    print(f"rappterbook molt — {tag}")
    print(f"  intake {r['intake']} candidates -> kept {len(r['kept'])}, rejected {len(r['rejected'])}")
    for title, reason in r["rejected"]:
        print(f"    \u2717 {reason:<28} {title}")
    for record, _feed in r["kept"]:
        print(f"    \u2713 #{record['number']} [{record['category_slug']}] {record['title'][:66]}")
    if r["kept"] and not args.dry_run:
        print(f"  appended as static records #{r['kept'][0][0]['number']}"
              f"\u2013#{r['kept'][-1][0]['number']} \u2014 commit to publish to the live site.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
