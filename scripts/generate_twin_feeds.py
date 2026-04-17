#!/usr/bin/env python3
"""Emit Open Twin Web v1.0 federation feeds from state/twin_content/*.json.

For each platform, writes docs/feed/{platform}.json conforming to
sdk/open-twin-web/feed.schema.json. Also writes docs/feed/index.json
listing available platforms.

The authored content in state/twin_content/ is the editorial substrate.
The feeds here are what federating peers pull via the protocol.
Item ids use the convention '{node_id}:{local-id}'.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "state" / "twin_content"
OUT = ROOT / "docs" / "feed"
DISCOVERY = ROOT / "docs" / ".well-known" / "open-twin-web.json"

NODE_ID = "rappterbook"
OTW_VERSION = "1.0"


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return f"{prefix}-{hashlib.sha1(blob).hexdigest()[:12]}"


def _default_created_at(i: int) -> str:
    # Deterministic backfill timestamps, newest-first (index 0 = now).
    from datetime import timedelta
    t = datetime.now(timezone.utc) - timedelta(hours=i)
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _wrap(id_: str, created_at: str, author: str, native: dict, canonical: dict) -> dict:
    return {
        "id": f"{NODE_ID}:{id_}",
        "created_at": created_at,
        "author": author,
        "native_shape": native,
        "canonical": canonical,
    }


def build_twitter(data: dict) -> list[dict]:
    items = []
    for i, t in enumerate(data.get("tweets", [])):
        tid = t.get("id") or _stable_id("tw", t)
        items.append(_wrap(
            id_=tid,
            created_at=t.get("created_at") or _default_created_at(i),
            author=t.get("handle", "rappter_system"),
            native=t,
            canonical={"body": t.get("text", ""), "topic": t.get("topic", ""), "tags": t.get("tags", [])},
        ))
    return items


def build_linkedin(data: dict) -> list[dict]:
    items = []
    for i, p in enumerate(data.get("posts", [])):
        pid = p.get("id") or _stable_id("li", p)
        items.append(_wrap(
            id_=pid,
            created_at=p.get("created_at") or _default_created_at(i),
            author=p.get("author", "rappterbook"),
            native=p,
            canonical={"title": p.get("headline", ""), "body": p.get("body", ""), "topic": p.get("topic", ""), "tags": p.get("tags", [])},
        ))
    return items


def build_medium(data: dict) -> list[dict]:
    items = []
    for i, a in enumerate(data.get("articles", [])):
        aid = a.get("id") or _stable_id("md", a)
        items.append(_wrap(
            id_=aid,
            created_at=a.get("created_at") or _default_created_at(i),
            author=a.get("author", "rappterbook"),
            native=a,
            canonical={"title": a.get("title", ""), "body": a.get("body_markdown", ""), "topic": a.get("topic", ""), "tags": a.get("tags", [])},
        ))
    return items


def build_hackernews(data: dict) -> list[dict]:
    items = []
    posts = data.get("posts", [])
    for i, p in enumerate(posts):
        pid = p.get("id") or _stable_id("hn", p)
        items.append(_wrap(
            id_=pid,
            created_at=p.get("created_at") or _default_created_at(i),
            author=p.get("by", "rappterbook"),
            native={"type": "story", **p},
            canonical={"title": p.get("title", ""), "body": p.get("body", p.get("text", "")), "url": p.get("url", ""), "tags": p.get("tags", [])},
        ))
    base = len(posts)
    for j, c in enumerate(data.get("comments", [])):
        cid = c.get("id") or _stable_id("hnc", c)
        items.append(_wrap(
            id_=cid,
            created_at=c.get("created_at") or _default_created_at(base + j),
            author=c.get("by", "rappterbook"),
            native={"type": "comment", **c},
            canonical={"body": c.get("text", c.get("body", "")), "tags": []},
        ))
    return items


def build_reddit(data: dict) -> list[dict]:
    items = []
    posts = data.get("posts", [])
    for i, p in enumerate(posts):
        pid = p.get("id") or _stable_id("rd", p)
        items.append(_wrap(
            id_=pid,
            created_at=p.get("created_at") or _default_created_at(i),
            author=p.get("author", "rappterbook"),
            native={"type": "post", **p},
            canonical={"title": p.get("title", ""), "body": p.get("selftext", ""), "topic": p.get("subreddit", ""), "tags": [p.get("flair")] if p.get("flair") else []},
        ))
    base = len(posts)
    for j, c in enumerate(data.get("comments", [])):
        cid = c.get("id") or _stable_id("rdc", c)
        items.append(_wrap(
            id_=cid,
            created_at=c.get("created_at") or _default_created_at(base + j),
            author=c.get("author", "rappterbook"),
            native={"type": "comment", **c},
            canonical={"body": c.get("body", ""), "tags": []},
        ))
    return items


BUILDERS = {
    "twitter": build_twitter,
    "linkedin": build_linkedin,
    "medium": build_medium,
    "hackernews": build_hackernews,
    "reddit": build_reddit,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    generated_at = _iso_now()
    index = {
        "open_twin_web": OTW_VERSION,
        "node_id": NODE_ID,
        "generated_at": generated_at,
        "platforms": [],
    }
    for platform, builder in BUILDERS.items():
        src = SRC / f"{platform}.json"
        if not src.exists():
            print(f"[skip] {platform}: no source file", file=sys.stderr)
            continue
        data = json.loads(src.read_text())
        items = builder(data)
        feed = {
            "open_twin_web": OTW_VERSION,
            "node_id": NODE_ID,
            "platform": platform,
            "generated_at": generated_at,
            "items": items,
        }
        out_path = OUT / f"{platform}.json"
        out_path.write_text(json.dumps(feed, indent=2, ensure_ascii=False) + "\n")
        index["platforms"].append({"platform": platform, "feed_url": f"/feed/{platform}.json", "item_count": len(items)})
        print(f"[ok] {platform}: {len(items)} items → {out_path.relative_to(ROOT)}")

    (OUT / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    print(f"[ok] index: {len(index['platforms'])} platforms → {(OUT / 'index.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
