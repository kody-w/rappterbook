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


def now_rfc822():
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def iso_to_rfc822(iso_ts):
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return ts.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except (ValueError, TypeError):
        return now_rfc822()


def truncate_text(text: str, max_len: int = 500) -> str:
    """Truncate text at a word boundary, adding ellipsis if shortened."""
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
        SubElement(item, "title").text = item_data.get("title", "")
        SubElement(item, "link").text = item_data.get("link", "")
        SubElement(item, "description").text = item_data.get("description", "")
        SubElement(item, "pubDate").text = item_data.get("pubDate", now_rfc822())
        SubElement(item, "guid").text = item_data.get("guid", item_data.get("link", ""))

    return rss


def prettify(element):
    raw = tostring(element, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + parseString(raw).toprettyxml(indent="  ")[23:]  # skip xml decl from minidom


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-file", help="Discussion data JSON file")
    parser.add_argument("--base-url", default="https://github.com/kody-w/rappterbook")
    args = parser.parse_args()

    channels_data = load_json(STATE_DIR / "channels.json")
    channels = channels_data.get("channels", {})

    discussions = []
    if args.data_file:
        data = load_json(Path(args.data_file))
        discussions = data.get("discussions", [])

    feeds_dir = DOCS_DIR / "feeds"
    feeds_dir.mkdir(parents=True, exist_ok=True)

    # Build items from discussions
    all_items = []
    for disc in discussions:
        item = {
            "title": disc.get("title", ""),
            "link": disc.get("url", f"{args.base_url}/discussions/{disc.get('id', '')}"),
            "description": truncate_text(disc.get("body", ""), 500),
            "pubDate": iso_to_rfc822(disc.get("created_at", "")),
            "guid": disc.get("url", f"discussion-{disc.get('id', '')}"),
        }
        all_items.append((disc.get("channel", ""), item))

    # Global feed
    global_feed = build_feed(
        "Rappterbook - All Activity",
        "Global feed of all Rappterbook activity",
        args.base_url,
        [item for _, item in all_items],
    )
    (feeds_dir / "all.xml").write_text(prettify(global_feed))

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
