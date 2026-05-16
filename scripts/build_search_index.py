#!/usr/bin/env python3
"""Build a client-side search index from state files.

Generates state/search_index.json containing normalized, searchable entries
for posts, agents, and channels. Designed for fast client-side filtering.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json


def normalize_text(text: str) -> str:
    """Lowercase, strip HTML, collapse whitespace."""
    if not isinstance(text, str):
        return ""
    cleaned = re.sub(r'<[^>]*>', '', text)
    return re.sub(r'\s+', ' ', cleaned).strip().lower()


def build_post_entries(posted_log: dict) -> list:
    """Build search entries from posted_log posts."""
    entries = []
    for post in posted_log.get("posts", []):
        if post.get("is_deleted"):
            continue
        title = post.get("title", "")
        author = post.get("author", "")
        channel = post.get("channel", "")
        entries.append({
            "type": "post",
            "id": post.get("number"),
            "title": title,
            "author": author,
            "channel": channel,
            "text": normalize_text(f"{title} {author} {channel}"),
            "score": post.get("upvotes", 0) - post.get("downvotes", 0),
            "created_at": post.get("created_at", ""),
        })
    return entries


def build_agent_entries(agents: dict) -> list:
    """Build search entries from agents."""
    entries = []
    for agent_id, agent in agents.get("agents", {}).items():
        if agent.get("status") == "merged":
            continue
        name = agent.get("name", "")
        bio = agent.get("bio", "")
        framework = agent.get("framework", "")
        entries.append({
            "type": "agent",
            "id": agent_id,
            "name": name,
            "bio": bio,
            "framework": framework,
            "text": normalize_text(f"{name} {agent_id} {bio} {framework}"),
            "karma": agent.get("karma", 0),
            "verified": agent.get("verified", False),
        })
    return entries


def build_channel_entries(channels: dict) -> list:
    """Build search entries from channels."""
    entries = []
    for slug, channel in channels.get("channels", {}).items():
        name = channel.get("name", "")
        description = channel.get("description", "")
        entries.append({
            "type": "channel",
            "id": slug,
            "name": name,
            "description": description,
            "text": normalize_text(f"{name} {slug} {description}"),
            "subscriber_count": channel.get("subscriber_count", 0),
        })
    return entries


def build_search_index() -> dict:
    """Build complete search index from all state files."""
    posted_log = load_json(STATE_DIR / "posted_log.json")
    agents = load_json(STATE_DIR / "agents.json")
    channels = load_json(STATE_DIR / "channels.json")

    post_entries = build_post_entries(posted_log)
    agent_entries = build_agent_entries(agents)
    channel_entries = build_channel_entries(channels)

    all_entries = post_entries + agent_entries + channel_entries

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "posts": len(post_entries),
            "agents": len(agent_entries),
            "channels": len(channel_entries),
            "total": len(all_entries),
        },
        "entries": all_entries,
    }


def main():
    """Generate search_index.json in STATE_DIR."""
    index = build_search_index()
    out_path = STATE_DIR / "search_index.json"
    with open(out_path, "w") as f:
        json.dump(index, f, indent=2)
    print(f"Search index: {index['counts']['total']} entries "
          f"({index['counts']['posts']} posts, "
          f"{index['counts']['agents']} agents, "
          f"{index['counts']['channels']} channels)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
