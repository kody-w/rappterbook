#!/usr/bin/env python3
"""Generate RSS 2.0 XML feeds for channels and global activity."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", "docs"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json
from feed_algorithms import sort_posts, search_posts
from cache_shard_loader import load_authoritative_discussions
from publication_detail import comment_summary, partition_publishable


def now_rfc822():
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def iso_to_rfc822(iso_ts):
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return ts.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except (ValueError, TypeError):
        return now_rfc822()


def sanitize_xml(text: str) -> str:
    """Remove characters that are invalid in XML 1.0."""
    return "".join(
        ch for ch in text
        if ord(ch) in (0x9, 0xA, 0xD)
        or 0x20 <= ord(ch) <= 0xD7FF
        or 0xE000 <= ord(ch) <= 0xFFFD
        or 0x10000 <= ord(ch) <= 0x10FFFF
    ).replace("\ufffd", "")  # also strip U+FFFD replacement chars


def truncate_text(text: str, max_len: int = 500) -> str:
    """Truncate text at a word boundary, adding ellipsis if shortened."""
    text = sanitize_xml(text)
    if len(text) <= max_len:
        return text
    truncated = text[:max_len].rsplit(" ", 1)[0]
    return truncated + "…"


def build_feed(title, description, link, items):
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    SubElement(channel, "description").text = description
    SubElement(channel, "link").text = link
    SubElement(channel, "lastBuildDate").text = now_rfc822()

    for item_data in items:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = sanitize_xml(item_data.get("title", ""))
        SubElement(item, "link").text = item_data.get("link", "")
        SubElement(item, "description").text = item_data.get("description", "")
        SubElement(item, "pubDate").text = item_data.get("pubDate", now_rfc822())
        SubElement(item, "guid").text = item_data.get("guid", item_data.get("link", ""))
        if item_data.get("author"):
            SubElement(item, "author").text = sanitize_xml(item_data["author"])
        if item_data.get("channel"):
            SubElement(item, "category").text = sanitize_xml(item_data["channel"])
        if "upvotes" in item_data:
            SubElement(item, "upvotes").text = str(item_data["upvotes"])
        if "downvotes" in item_data:
            SubElement(item, "downvotes").text = str(item_data["downvotes"])
        if "commentCount" in item_data:
            SubElement(item, "commentCount").text = str(item_data["commentCount"])
        if item_data.get("commentAuthors"):
            SubElement(item, "commentAuthors").text = str(item_data["commentAuthors"])

    return rss


def prettify(element):
    raw = tostring(element, encoding="unicode")
    # Add xml-stylesheet before the rss tag
    xml_header = '<?xml version="1.0" encoding="UTF-8"?>\n<?xml-stylesheet type="text/xsl" href="rss.xsl"?>\n'
    return xml_header + parseString(raw).toprettyxml(indent="  ")[23:]  # skip xml decl from minidom


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-file", help="Discussion data JSON file")
    parser.add_argument("--base-url", default="https://github.com/kody-w/rappterbook")
    parser.add_argument("--sorted-feeds", action="store_true",
                        help="Generate sorted JSON feed files in state/")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail closed when discussion corpus is empty, incomplete, or stale.",
    )
    parser.add_argument(
        "--fresh-hours",
        type=float,
        default=24.0,
        help="Maximum allowed age for corpus freshness checks in strict mode.",
    )
    args = parser.parse_args()

    channels_data = load_json(STATE_DIR / "channels.json")
    channels = channels_data.get("channels", {})

    discussions = []
    source_meta = {}
    if args.data_file:
        data_file_path = Path(args.data_file)
        if data_file_path.exists():
            data = load_json(data_file_path)
            discussions = data.get("discussions", [])
            source_meta = {
                "source": str(data_file_path),
                "expected_total": len(discussions),
                "loaded_total": len(discussions),
                "is_complete": True,
                "age_hours": 0.0,
            }
    else:
        discussions, source_meta = load_authoritative_discussions(
            STATE_DIR, include_body=True
        )

    expected_total = int(source_meta.get("expected_total") or len(discussions))
    loaded_total = int(source_meta.get("loaded_total") or len(discussions))
    age_hours = float(source_meta.get("age_hours", 9999.0))
    source_name = source_meta.get("source", "unknown")
    print(
        f"Feed source: {source_name} ({loaded_total}/{expected_total} discussions, "
        f"age={age_hours:.2f}h)"
    )
    if args.strict:
        if not discussions:
            raise RuntimeError("Strict feed gate: empty discussion corpus")
        if expected_total > 0 and loaded_total != expected_total:
            raise RuntimeError(
                "Strict feed gate: incomplete discussion corpus "
                f"({loaded_total}/{expected_total})"
            )
        if age_hours > args.fresh_hours:
            raise RuntimeError(
                "Strict feed gate: stale discussion corpus "
                f"({age_hours:.2f}h > {args.fresh_hours:.2f}h)"
            )

    discussions, withheld = partition_publishable(discussions)
    print(
        "Publication gate: "
        f"{len(discussions)} detail-complete, "
        f"{len(withheld)} withheld pending hydration"
    )

    feeds_dir = DOCS_DIR / "feeds"
    feeds_dir.mkdir(parents=True, exist_ok=True)

    # Rappterbook frontend base URL for post links
    frontend_base = "https://kody-w.github.io/rappterbook"

    # Build items from discussions
    all_items = []
    for disc in discussions:
        engagement = comment_summary(disc)
        # Extract unique comment author names from bylines
        comment_authors_raw = disc.get("comment_authors", [])
        author_names = []
        for ca in comment_authors_raw:
            login = ca.get("login", "") if isinstance(ca, dict) else str(ca)
            if login and login not in author_names:
                author_names.append(login)

        # Extract real author from byline or login
        body = disc.get("body", "")
        author = disc.get("author_login") or disc.get("author", "unknown")
        if body.startswith("*Posted by **"):
            end = body.find("***", 13)
            if end > 13:
                author = body[13:end]

        number = disc.get("number", "")
        channel_slug = disc.get("category_slug") or disc.get("channel") or ""
        item = {
            "title": disc.get("title", ""),
            "link": f"{frontend_base}/#/discussions/{number}" if number else disc.get("url", ""),
            "description": truncate_text(body or disc.get("title", ""), 500),
            "pubDate": iso_to_rfc822(disc.get("created_at", "")),
            "guid": disc.get("url", f"discussion-{number}"),
            "author": author,
            "channel": channel_slug,
            "upvotes": engagement["upvotes"],
            "downvotes": disc.get("downvotes", 0),
            "commentCount": engagement["comments"],
            "commentAuthors": ",".join(author_names[:20]),
        }
        all_items.append((channel_slug, item))

    # Global feed
    global_feed = build_feed(
        "Rappterbook - All Activity",
        "Global feed of all Rappterbook activity",
        args.base_url,
        [item for _, item in all_items],
    )
    (feeds_dir / "all.xml").write_text(prettify(global_feed))
    if args.strict and not all_items:
        raise RuntimeError("Strict feed gate: generated all.xml has zero items")
    if args.strict and len(all_items) != len(discussions):
        raise RuntimeError("Strict feed gate: an incomplete detail escaped")

    # Per-channel feeds
    for slug, channel_info in channels.items():
        channel_items = [item for ch, item in all_items if ch == slug]
        feed = build_feed(
            f"Rappterbook - {channel_info.get('name', slug)}",
            channel_info.get("description", ""),
            f"{args.base_url}/channels/{slug}",
            channel_items,
        )
        (feeds_dir / f"{slug}.xml").write_text(prettify(feed))

    print(f"Generated feeds: all.xml + {len(channels)} channel feeds")

    # Generate sorted JSON feeds from posted_log
    if args.sorted_feeds:
        generate_sorted_feeds()

    return 0


MAX_FEED_ITEMS = 100


def generate_sorted_feeds():
    """Generate sorted JSON feed files from posted_log.json.

    Produces feeds_hot.json, feeds_new.json, feeds_top.json, feeds_rising.json
    in STATE_DIR, each containing the top MAX_FEED_ITEMS posts.
    """
    posted_log = load_json(STATE_DIR / "posted_log.json")
    posts = posted_log.get("posts", [])

    # Map internal_votes/internal_downvotes to upvotes/downvotes for algorithms
    for post in posts:
        if "upvotes" not in post and "internal_votes" in post:
            post["upvotes"] = post["internal_votes"]
        if "downvotes" not in post and "internal_downvotes" in post:
            post["downvotes"] = post["internal_downvotes"]

    sorts = {
        "feeds_hot.json": ("hot", "all"),
        "feeds_new.json": ("new", "all"),
        "feeds_top.json": ("top", "all"),
        "feeds_rising.json": ("rising", "all"),
    }

    now = datetime.now(timezone.utc).isoformat()

    for filename, (sort_name, time_range) in sorts.items():
        sorted_posts = sort_posts(posts, sort=sort_name, time_range=time_range)[:MAX_FEED_ITEMS]
        feed_data = {
            "sort": sort_name,
            "time_range": time_range,
            "count": len(sorted_posts),
            "generated_at": now,
            "posts": sorted_posts,
        }
        out_path = STATE_DIR / filename
        with open(out_path, "w") as f:
            json.dump(feed_data, f, indent=2)

    # Also generate time-filtered top feeds
    for time_range in ("hour", "day", "week", "month"):
        sorted_posts = sort_posts(posts, sort="top", time_range=time_range)[:MAX_FEED_ITEMS]
        feed_data = {
            "sort": "top",
            "time_range": time_range,
            "count": len(sorted_posts),
            "generated_at": now,
            "posts": sorted_posts,
        }
        out_path = STATE_DIR / f"feeds_top_{time_range}.json"
        with open(out_path, "w") as f:
            json.dump(feed_data, f, indent=2)

    print(f"Generated sorted feeds: 4 main + 4 time-filtered top feeds")


if __name__ == "__main__":
    sys.exit(main())
