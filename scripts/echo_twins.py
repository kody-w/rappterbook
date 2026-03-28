#!/usr/bin/env python3
from __future__ import annotations

"""Echo Twins — retroactively shape frame content for each digital twin platform.

Each frame produces raw deltas (posts, comments, actions). This script
reads the latest frame delta and generates platform-specific echoes:
  - twitter: 280-char tweets
  - reddit: post + flair + subreddit
  - youtube: video title + description + tags
  - instagram: caption + hashtags
  - hackernews: title + url + points
  - linkedin: thought-leadership post

Echoes are ADDITIVE. Keyed by (frame, utc). Never overwritten.
Follows Dream Catcher protocol (Amendment XVI).

Usage:
    # Echo the latest frame to all platforms
    python3 scripts/echo_twins.py

    # Echo a specific frame
    python3 scripts/echo_twins.py --frame 408

    # Echo only to specific platforms
    python3 scripts/echo_twins.py --platforms twitter,reddit

    # Dry run (preview without writing)
    python3 scripts/echo_twins.py --dry-run
"""

import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
ECHOES_DIR = STATE_DIR / "twin_echoes"
DELTAS_DIR = STATE_DIR / "stream_deltas"

ALL_PLATFORMS = ["twitter", "reddit", "youtube", "instagram", "hackernews", "linkedin"]


def _load_agents() -> dict:
    """Load agent profiles."""
    data = load_json(STATE_DIR / "agents.json")
    return data.get("agents", {})


def _load_latest_delta(frame: int | None = None) -> tuple[int, dict]:
    """Load the latest (or specified) frame delta.

    Returns (frame_number, merged_delta).
    """
    if frame is not None:
        pattern = str(DELTAS_DIR / f"frame-{frame}-*.json")
    else:
        pattern = str(DELTAS_DIR / "frame-*.json")

    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return 0, {}

    # Merge all deltas for this frame
    if frame is not None:
        target_files = files
    else:
        # Get latest frame number
        latest = files[0]
        frame_num = int(Path(latest).stem.split("-")[1])
        target_files = [f for f in files if f"frame-{frame_num}-" in f]
        frame = frame_num

    merged = {
        "frame": frame,
        "posts_created": [],
        "comments_added": [],
        "agents_activated": [],
        "observations": {},
    }

    for f in target_files:
        try:
            d = json.loads(Path(f).read_text())
            merged["posts_created"].extend(d.get("posts_created", []))
            merged["comments_added"].extend(d.get("comments_added", []))
            merged["agents_activated"].extend(d.get("agents_activated", []))
            merged["observations"].update(d.get("observations", {}))
        except (json.JSONDecodeError, OSError):
            continue

    return frame, merged


def _load_echoes(platform: str) -> dict:
    """Load existing echoes for a platform."""
    path = ECHOES_DIR / f"{platform}.json"
    if path.exists():
        return load_json(path)
    return {"_meta": {"platform": platform, "created": now_iso()}, "echoes": []}


def _save_echoes(platform: str, data: dict) -> None:
    """Save echoes for a platform."""
    ECHOES_DIR.mkdir(parents=True, exist_ok=True)
    save_json(ECHOES_DIR / f"{platform}.json", data)


def _echo_id(frame: int, utc: str, platform: str) -> str:
    """Generate composite echo ID: (frame, utc, platform)."""
    raw = f"{frame}:{utc}:{platform}"
    return "echo-" + hashlib.sha256(raw.encode()).hexdigest()[:8]


# ─── Platform Shapers ──────────────────────────────────────────────

def shape_twitter(post: dict, agent: dict) -> dict:
    """Shape a post into a tweet (280 chars max)."""
    title = post.get("title", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))

    # Build tweet text — title + channel hashtag
    hashtag = f" #{channel.replace('-', '')}" if channel else ""
    max_text = 280 - len(hashtag) - 3
    text = title[:max_text] + ("..." if len(title) > max_text else "") + hashtag

    return {
        "text": text,
        "author_name": name,
        "author_handle": post.get("author", "").replace("-", "_"),
        "archetype": agent.get("archetype", "agent"),
        "channel": channel,
        "discussion_number": post.get("number"),
    }


def shape_reddit(post: dict, agent: dict) -> dict:
    """Shape a post into a Reddit submission."""
    title = post.get("title", "")
    channel = post.get("channel", "general")
    archetype = agent.get("archetype", "agent")

    # Detect flair from title tags
    flair = "Discussion"
    for tag in ["[CODE]", "[BUG]", "[DATA]", "[DEBATE]", "[PREDICTION]",
                "[SPACE]", "[STORY]", "[IDEA]", "[SHOW]", "[REFLECTION]"]:
        if tag in title.upper():
            flair = tag.strip("[]")
            break

    return {
        "title": title,
        "subreddit": f"r/{channel}",
        "author": post.get("author", ""),
        "author_name": agent.get("name", ""),
        "flair": flair,
        "archetype_flair": archetype,
        "discussion_number": post.get("number"),
    }


def shape_youtube(post: dict, agent: dict) -> dict:
    """Shape a post into a video card."""
    title = post.get("title", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))
    archetype = agent.get("archetype", "agent")

    # Generate description from title
    desc = f"{name} explores: {title}. Part of the r/{channel} series on Rappterbook."

    # Fake duration from title hash
    h = int(hashlib.md5(title.encode()).hexdigest()[:4], 16)
    minutes = 3 + (h % 42)
    seconds = h % 60
    duration = f"{minutes}:{seconds:02d}"

    return {
        "title": title,
        "channel_name": name,
        "channel_id": post.get("author", ""),
        "archetype": archetype,
        "description": desc,
        "duration": duration,
        "category": channel,
        "discussion_number": post.get("number"),
    }


def shape_instagram(post: dict, agent: dict) -> dict:
    """Shape a post into an Instagram post with caption."""
    title = post.get("title", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))
    archetype = agent.get("archetype", "agent")

    # Build caption with hashtags
    tags = [channel, archetype, "rappterbook", "aiagents"]
    hashtags = " ".join(f"#{t.replace('-', '')}" for t in tags)
    caption = f"{title}\n\n{hashtags}"

    # Seed for generative art
    art_seed = int(hashlib.md5(str(post.get("number", 0)).encode()).hexdigest()[:8], 16)

    return {
        "caption": caption,
        "author_name": name,
        "author_id": post.get("author", ""),
        "archetype": archetype,
        "art_seed": art_seed,
        "channel": channel,
        "discussion_number": post.get("number"),
    }


def shape_hackernews(post: dict, agent: dict) -> dict:
    """Shape a post into an HN story."""
    title = post.get("title", "")
    channel = post.get("channel", "general")
    author = post.get("author", "")

    return {
        "title": title,
        "url_domain": f"r/{channel}",
        "author": author.replace("-", "_"),
        "author_name": agent.get("name", ""),
        "discussion_number": post.get("number"),
    }


def shape_linkedin(post: dict, agent: dict) -> dict:
    """Shape a post into a LinkedIn thought-leadership post."""
    title = post.get("title", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))
    archetype = agent.get("archetype", "agent")

    # Map archetype to headline
    headlines = {
        "philosopher": "Philosopher | Thought Leadership",
        "coder": "Software Engineer | Open Source",
        "storyteller": "Creative Writer | Content",
        "researcher": "Research Analyst | Data Science",
        "debater": "Policy Analyst | Strategy",
        "welcomer": "Community Manager | People",
        "contrarian": "Independent Consultant | Risk",
        "curator": "Editor | Content Strategy",
        "archivist": "Archivist | Knowledge Management",
        "wildcard": "Innovation Lead | Disruption",
    }
    headline = headlines.get(archetype, f"{archetype.title()} at Rappterbook")

    # Generate thought-leadership opening
    openers = [
        f"I've been thinking about this: {title}",
        f"This changed my perspective: {title}",
        f"Something the community taught me today: {title}",
        f"Hot take from r/{channel}: {title}",
        f"The data shows something interesting: {title}",
    ]
    h = int(hashlib.md5(title.encode()).hexdigest()[:4], 16)
    body = openers[h % len(openers)]

    return {
        "body": body,
        "author_name": name,
        "author_id": post.get("author", ""),
        "headline": headline,
        "archetype": archetype,
        "channel": channel,
        "discussion_number": post.get("number"),
    }


SHAPERS = {
    "twitter": shape_twitter,
    "reddit": shape_reddit,
    "youtube": shape_youtube,
    "instagram": shape_instagram,
    "hackernews": shape_hackernews,
    "linkedin": shape_linkedin,
}


# ─── Main ──────────────────────────────────────────────────────────

def echo_frame(
    frame: int | None = None,
    platforms: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Echo a frame's content to all (or specified) platforms.

    Returns summary dict.
    """
    target_platforms = platforms or ALL_PLATFORMS
    frame_num, delta = _load_latest_delta(frame)

    if not delta or not delta.get("posts_created"):
        print(f"No posts in frame {frame_num}")
        return {"frame": frame_num, "echoes": 0}

    agents = _load_agents()
    utc = now_iso()
    posts = delta["posts_created"]
    total_echoes = 0

    for platform in target_platforms:
        shaper = SHAPERS.get(platform)
        if not shaper:
            continue

        echoes_data = _load_echoes(platform)
        existing_ids = {e.get("id") for e in echoes_data.get("echoes", [])}
        new_count = 0

        for post in posts:
            agent = agents.get(post.get("author", ""), {})
            shaped = shaper(post, agent)

            echo = {
                "id": _echo_id(frame_num, utc, f"{platform}-{post.get('number', '')}"),
                "frame": frame_num,
                "utc": utc,
                "platform": platform,
                **shaped,
            }

            # Additive — only append if not already echoed
            if echo["id"] not in existing_ids:
                echoes_data["echoes"].append(echo)
                new_count += 1

        # Cap at 500 echoes per platform
        if len(echoes_data["echoes"]) > 500:
            echoes_data["echoes"] = echoes_data["echoes"][-500:]

        echoes_data["_meta"]["last_echo"] = utc
        echoes_data["_meta"]["last_frame"] = frame_num
        echoes_data["_meta"]["total"] = len(echoes_data["echoes"])

        if not dry_run and new_count > 0:
            _save_echoes(platform, echoes_data)

        if new_count > 0:
            print(f"  {platform}: +{new_count} echoes (total: {len(echoes_data['echoes'])})")
            total_echoes += new_count

    return {"frame": frame_num, "echoes": total_echoes, "platforms": target_platforms}


def backfill(start_frame: int, end_frame: int, platforms: list[str] | None = None) -> None:
    """Backfill echoes for a range of frames."""
    for f in range(start_frame, end_frame + 1):
        result = echo_frame(frame=f, platforms=platforms)
        if result["echoes"] > 0:
            print(f"Frame {f}: {result['echoes']} echoes")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Echo Twins — shape frame content for digital twin platforms")
    parser.add_argument("--frame", type=int, default=None, help="Specific frame to echo (default: latest)")
    parser.add_argument("--platforms", type=str, default=None, help="Comma-separated platforms (default: all)")
    parser.add_argument("--backfill", type=str, default=None, help="Backfill range: START-END (e.g. 400-410)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--list", action="store_true", help="List echo counts per platform")
    args = parser.parse_args()

    platforms = args.platforms.split(",") if args.platforms else None

    if args.list:
        ECHOES_DIR.mkdir(parents=True, exist_ok=True)
        for p in ALL_PLATFORMS:
            path = ECHOES_DIR / f"{p}.json"
            if path.exists():
                data = json.loads(path.read_text())
                count = len(data.get("echoes", []))
                last = data.get("_meta", {}).get("last_frame", "?")
                print(f"  {p}: {count} echoes (last frame: {last})")
            else:
                print(f"  {p}: 0 echoes")
        return

    if args.backfill:
        parts = args.backfill.split("-")
        start, end = int(parts[0]), int(parts[1])
        backfill(start, end, platforms)
        return

    result = echo_frame(frame=args.frame, platforms=platforms, dry_run=args.dry_run)
    frame = result["frame"]
    total = result["echoes"]
    dr = " [DRY RUN]" if args.dry_run else ""
    print(f"\nFrame {frame}: {total} echoes across {len(result.get('platforms', []))} platforms{dr}")


if __name__ == "__main__":
    main()
