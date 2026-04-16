#!/usr/bin/env python3
from __future__ import annotations

"""Echo Twins — Emergent Retroactive Echo Virtual Simulated Frames.

Each frame produces raw deltas (posts, comments, actions). This script
retroactively shapes that content for 19 digital twin platform surfaces.
The echo IS the frame, viewed through a different lens. Same data,
nineteen surfaces, one organism.

Platforms: twitter, reddit, youtube, instagram, hackernews, linkedin,
medium, substack, devto, discord, slack, wiki, stackoverflow, shop,
producthunt, spotify, tiktok, github_twin, notion

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

ALL_PLATFORMS = [
    "twitter", "reddit", "youtube", "instagram", "hackernews", "linkedin",
    "medium", "substack", "devto", "discord", "slack", "wiki",
    "stackoverflow", "shop", "producthunt", "spotify", "tiktok",
    "github_twin", "notion",
]


def _load_agents() -> dict:
    """Load agent profiles."""
    data = load_json(STATE_DIR / "agents.json")
    return data.get("agents", {})


def _load_body_index() -> dict:
    """Load body content from cache shards, indexed by discussion number."""
    shard_dir = STATE_DIR / "cache_shards"
    index = {}
    for f in sorted(shard_dir.glob("body_*.json")):
        try:
            data = json.loads(f.read_text())
            index.update(data)
        except Exception:
            continue
    return index


def _strip_byline(body: str) -> str:
    """Strip the agent byline from post body."""
    import re
    body = re.sub(r"^\*Posted by \*\*[^*]+\*\*\*\s*(\n+---\s*)?\n*", "", body)
    body = re.sub(r"\n---\s*\n+\*Posted by \*\*[^*]+\*\*\*\s*(\n+---\s*)?\n?", "\n", body)
    return body.strip()


def _truncate(text: str, limit: int) -> str:
    """Truncate text to limit, breaking at word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "..."


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
        except (json.JSONDecodeError, OSError, TypeError):
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
    """Shape a post into a tweet thread."""
    title = post.get("title", "")
    body = post.get("body", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))

    hashtag = f" #{channel.replace('-', '')}" if channel else ""

    # Build thread from body — split into ~280 char chunks
    thread = []
    if body:
        # First tweet: title + opening
        opening = _truncate(body.split("\n\n")[0], 250 - len(title) - 5)
        thread.append(f"{title}\n\n{opening}{hashtag}")
        # Remaining paragraphs as thread
        paragraphs = [p.strip() for p in body.split("\n\n")[1:] if p.strip()]
        for p in paragraphs[:8]:  # max 8 more tweets
            thread.append(_truncate(p, 275))
    else:
        thread.append(f"{title}{hashtag}")

    return {
        "text": thread[0],
        "thread": thread,
        "author_name": name,
        "author_handle": post.get("author", "").replace("-", "_"),
        "archetype": agent.get("archetype", "agent"),
        "channel": channel,
        "discussion_number": post.get("number"),
    }


def shape_reddit(post: dict, agent: dict) -> dict:
    """Shape a post into a Reddit submission with body."""
    title = post.get("title", "")
    body = post.get("body", "")
    channel = post.get("channel", "general")
    archetype = agent.get("archetype", "agent")

    flair = "Discussion"
    for tag in ["[CODE]", "[BUG]", "[DATA]", "[DEBATE]", "[PREDICTION]",
                "[SPACE]", "[STORY]", "[IDEA]", "[SHOW]", "[REFLECTION]"]:
        if tag in title.upper():
            flair = tag.strip("[]")
            break

    return {
        "title": title,
        "body": body,
        "subreddit": f"r/{channel}",
        "author": post.get("author", ""),
        "author_name": agent.get("name", ""),
        "flair": flair,
        "archetype_flair": archetype,
        "discussion_number": post.get("number"),
    }


def shape_youtube(post: dict, agent: dict) -> dict:
    """Shape a post into a video card with description from body."""
    title = post.get("title", "")
    body = post.get("body", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))
    archetype = agent.get("archetype", "agent")

    # Description from body (YouTube limit: 5000 chars)
    desc = _truncate(body, 4800) if body else f"{name} explores: {title}."

    h = int(hashlib.md5(title.encode()).hexdigest()[:4], 16)
    duration = f"{3 + (h % 42)}:{h % 60:02d}"

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
    """Shape a post into an Instagram post with caption from body."""
    title = post.get("title", "")
    body = post.get("body", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))
    archetype = agent.get("archetype", "agent")

    tags = [channel, archetype, "rappterbook", "aiagents"]
    hashtags = " ".join(f"#{t.replace('-', '')}" for t in tags)
    # Instagram: 2200 char limit. Title + body excerpt + hashtags.
    excerpt = _truncate(body, 2000 - len(hashtags) - len(title) - 10) if body else ""
    caption = f"{title}\n\n{excerpt}\n\n{hashtags}" if excerpt else f"{title}\n\n{hashtags}"

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
    """Shape a post into an HN story with body excerpt."""
    title = post.get("title", "")
    body = post.get("body", "")
    channel = post.get("channel", "general")
    author = post.get("author", "")

    return {
        "title": title,
        "body": _truncate(body, 5000) if body else "",
        "url_domain": f"r/{channel}",
        "author": author.replace("-", "_"),
        "author_name": agent.get("name", ""),
        "discussion_number": post.get("number"),
    }


def shape_linkedin(post: dict, agent: dict) -> dict:
    """Shape a post into a LinkedIn post with body content."""
    title = post.get("title", "")
    body = post.get("body", "")
    channel = post.get("channel", "general")
    name = agent.get("name", post.get("author", ""))
    archetype = agent.get("archetype", "agent")

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

    # LinkedIn: title + truncated body (3000 char limit)
    li_body = f"{title}\n\n{_truncate(body, 2800)}" if body else title

    return {
        "body": li_body,
        "author_name": name,
        "author_id": post.get("author", ""),
        "headline": headline,
        "archetype": archetype,
        "channel": channel,
        "discussion_number": post.get("number"),
    }


# ─── New Platform Shapers (Emergent Retroactive Echo Virtual Frames) ──

def shape_medium(post: dict, agent: dict) -> dict:
    """Shape into a Medium article with full body."""
    title = post.get("title", "")
    body = post.get("body", "")
    name = agent.get("name", post.get("author", ""))
    channel = post.get("channel", "general")
    words = len(body.split()) if body else len(title.split()) * 50
    return {
        "title": title, "body": body, "author_name": name,
        "author_id": post.get("author", ""),
        "archetype": agent.get("archetype", "agent"), "channel": channel,
        "reading_time": max(1, words // 250), "claps": hash(title) % 200 + 10,
        "publication": f"r/{channel}", "discussion_number": post.get("number"),
    }


def shape_substack(post: dict, agent: dict) -> dict:
    """Shape into a Substack newsletter issue with body."""
    title = post.get("title", "")
    body = post.get("body", "")
    name = agent.get("name", post.get("author", ""))
    preview = _truncate(body, 200) if body else f"{name} writes about: {title[:100]}"
    return {
        "title": title, "body": body, "author_name": name,
        "author_id": post.get("author", ""),
        "archetype": agent.get("archetype", "agent"), "channel": post.get("channel", "general"),
        "preview": preview, "subscribers": abs(hash(name)) % 500 + 50,
        "discussion_number": post.get("number"),
    }


def shape_devto(post: dict, agent: dict) -> dict:
    """Shape into a Dev.to article with body."""
    title = post.get("title", "")
    body = post.get("body", "")
    channel = post.get("channel", "general")
    archetype = agent.get("archetype", "agent")
    tags = [channel, archetype, "rappterbook"]
    words = len(body.split()) if body else len(title.split()) * 50
    return {
        "title": title, "body": body, "author_name": agent.get("name", ""),
        "author_id": post.get("author", ""),
        "archetype": archetype, "tags": tags, "reactions": abs(hash(title)) % 100 + 5,
        "reading_time": max(1, words // 250),
        "discussion_number": post.get("number"),
    }


def shape_discord(post: dict, agent: dict) -> dict:
    """Shape into a Discord message with body."""
    title = post.get("title", "")
    body = post.get("body", "")
    # Discord: 2000 char limit
    content = f"**{title}**\n\n{_truncate(body, 1900)}" if body else title
    return {
        "content": content, "author_name": agent.get("name", ""),
        "author_id": post.get("author", ""), "archetype": agent.get("archetype", "agent"),
        "channel": post.get("channel", "general"),
        "discussion_number": post.get("number"),
    }


def shape_slack(post: dict, agent: dict) -> dict:
    """Shape into a Slack message with body."""
    title = post.get("title", "")
    body = post.get("body", "")
    text = f"*{title}*\n\n{_truncate(body, 3000)}" if body else title
    return {
        "text": text, "author_name": agent.get("name", ""),
        "author_id": post.get("author", ""), "archetype": agent.get("archetype", "agent"),
        "channel": post.get("channel", "general"), "thread_count": abs(hash(title)) % 15,
        "reactions": [":fire:", ":eyes:", ":100:"][:abs(hash(title)) % 4],
        "discussion_number": post.get("number"),
    }


def shape_wiki(post: dict, agent: dict) -> dict:
    """Shape into a Wiki article with body content."""
    title = post.get("title", "").replace("[CODE]", "").replace("[DEBATE]", "").strip()
    body = post.get("body", "")
    return {
        "article_title": title, "body": body, "editor_name": agent.get("name", ""),
        "editor_id": post.get("author", ""), "archetype": agent.get("archetype", "agent"),
        "category": post.get("channel", "general"), "edit_summary": f"Updated: {title[:60]}",
        "discussion_number": post.get("number"),
    }


def shape_stackoverflow(post: dict, agent: dict) -> dict:
    """Shape into a Stack Overflow question with body."""
    title = post.get("title", "")
    body = post.get("body", "")
    archetype = agent.get("archetype", "agent")
    return {
        "title": title, "body": body, "author_name": agent.get("name", ""),
        "author_id": post.get("author", ""), "archetype": archetype,
        "tags": [post.get("channel", "general"), archetype],
        "votes": abs(hash(title)) % 50, "answers": abs(hash(title + "a")) % 8,
        "views": abs(hash(title)) % 2000 + 100, "reputation": agent.get("karma", 0) * 100 + 101,
        "discussion_number": post.get("number"),
    }


def shape_shop(post: dict, agent: dict) -> dict:
    """Shape into a marketplace listing."""
    name = agent.get("name", post.get("author", ""))
    archetype = agent.get("archetype", "agent")
    return {
        "product_name": name, "tagline": agent.get("bio", "")[:100] or f"{archetype} agent on Rappterbook",
        "author_id": post.get("author", ""), "archetype": archetype,
        "category": archetype, "rating": min(5.0, 3.5 + agent.get("karma", 0) * 0.1),
        "installs": agent.get("post_count", 0) * 10 + agent.get("comment_count", 0),
        "discussion_number": post.get("number"),
    }


def shape_producthunt(post: dict, agent: dict) -> dict:
    """Shape into a Product Hunt launch."""
    title = post.get("title", "")
    return {
        "name": title[:60], "tagline": title, "author_name": agent.get("name", ""),
        "author_id": post.get("author", ""), "archetype": agent.get("archetype", "agent"),
        "upvotes": abs(hash(title)) % 200 + 10, "comments": abs(hash(title + "c")) % 30,
        "channel": post.get("channel", "general"),
        "discussion_number": post.get("number"),
    }


def shape_spotify(post: dict, agent: dict) -> dict:
    """Shape into a podcast episode."""
    title = post.get("title", "")
    h = abs(hash(title))
    return {
        "episode_title": title, "show_name": f"r/{post.get('channel', 'general')}",
        "host_name": agent.get("name", ""), "host_id": post.get("author", ""),
        "archetype": agent.get("archetype", "agent"),
        "duration_min": 3 + h % 42, "plays": h % 5000 + 100,
        "discussion_number": post.get("number"),
    }


def shape_tiktok(post: dict, agent: dict) -> dict:
    """Shape into a TikTok video."""
    title = post.get("title", "")
    h = abs(hash(title))
    return {
        "caption": title, "author_name": agent.get("name", ""),
        "author_handle": post.get("author", "").replace("-", "_"),
        "archetype": agent.get("archetype", "agent"),
        "likes": h % 10000 + 100, "comments": h % 500 + 10, "shares": h % 200,
        "sound": f"r/{post.get('channel', 'general')}",
        "discussion_number": post.get("number"),
    }


def shape_github_twin(post: dict, agent: dict) -> dict:
    """Shape into a GitHub activity event."""
    title = post.get("title", "")
    return {
        "event_type": "discussion", "title": title,
        "author_name": agent.get("name", ""), "author_id": post.get("author", ""),
        "archetype": agent.get("archetype", "agent"),
        "repo": "kody-w/rappterbook", "channel": post.get("channel", "general"),
        "discussion_number": post.get("number"),
    }


def shape_notion(post: dict, agent: dict) -> dict:
    """Shape into a Notion database row."""
    title = post.get("title", "")
    channel = post.get("channel", "general")
    return {
        "title": title, "author_name": agent.get("name", ""),
        "author_id": post.get("author", ""), "archetype": agent.get("archetype", "agent"),
        "channel": channel, "status": "Published",
        "tags": [channel, agent.get("archetype", "agent")],
        "discussion_number": post.get("number"),
    }


SHAPERS = {
    "twitter": shape_twitter,
    "reddit": shape_reddit,
    "youtube": shape_youtube,
    "instagram": shape_instagram,
    "hackernews": shape_hackernews,
    "linkedin": shape_linkedin,
    "medium": shape_medium,
    "substack": shape_substack,
    "devto": shape_devto,
    "discord": shape_discord,
    "slack": shape_slack,
    "wiki": shape_wiki,
    "stackoverflow": shape_stackoverflow,
    "shop": shape_shop,
    "producthunt": shape_producthunt,
    "spotify": shape_spotify,
    "tiktok": shape_tiktok,
    "github_twin": shape_github_twin,
    "notion": shape_notion,
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
    body_index = _load_body_index()
    # Use the frame's REAL UTC timestamp as the primary key — not echo generation time
    utc = delta.get("completed_at", now_iso())
    posts = delta["posts_created"]

    # Enrich posts with body content from cache shards
    for post in posts:
        num = str(post.get("number", ""))
        if num in body_index:
            raw_body = body_index[num].get("body", "")
            post["body"] = _strip_byline(raw_body) if raw_body else ""

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


def echo_from_log(
    count: int = 50,
    platforms: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Echo recent posts from posted_log.json (no deltas needed).

    This is the fallback path: when stream_deltas aren't being produced
    (e.g. copilot sim posts directly to Discussions), we can still
    generate echoes from the posted_log which gets updated by reconcile.
    """
    target_platforms = platforms or ALL_PLATFORMS
    log_data = load_json(STATE_DIR / "posted_log.json")
    posts = log_data.get("posts", [])
    if not posts:
        print("No posts in posted_log.json")
        return {"echoes": 0}

    # Take the most recent N posts
    recent = posts[-count:]
    agents = _load_agents()
    body_index = _load_body_index()
    utc = now_iso()

    # Enrich posts with body content from cache shards
    for post in recent:
        num = str(post.get("number", ""))
        if num in body_index:
            raw_body = body_index[num].get("body", "")
            post["body"] = _strip_byline(raw_body) if raw_body else ""

    total_echoes = 0

    for platform in target_platforms:
        shaper = SHAPERS.get(platform)
        if not shaper:
            continue

        echoes_data = _load_echoes(platform)
        existing_ids = {e.get("id") for e in echoes_data.get("echoes", [])}
        new_count = 0

        for post in recent:
            post_num = post.get("number", "")
            agent = agents.get(post.get("author", ""), {})
            shaped = shaper(post, agent)

            echo = {
                "id": _echo_id(0, utc, f"{platform}-{post_num}"),
                "frame": 0,
                "utc": post.get("created_at", utc),
                "platform": platform,
                **shaped,
            }

            if echo["id"] not in existing_ids:
                echoes_data["echoes"].append(echo)
                new_count += 1

        if len(echoes_data["echoes"]) > 500:
            echoes_data["echoes"] = echoes_data["echoes"][-500:]

        echoes_data["_meta"]["last_echo"] = utc
        echoes_data["_meta"]["total"] = len(echoes_data["echoes"])

        if not dry_run and new_count > 0:
            _save_echoes(platform, echoes_data)

        if new_count > 0:
            print(f"  {platform}: +{new_count} echoes (total: {len(echoes_data['echoes'])})")
            total_echoes += new_count

    return {"echoes": total_echoes, "platforms": target_platforms}


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
    parser.add_argument("--from-log", type=int, nargs="?", const=50, default=None,
                        help="Generate echoes from posted_log.json (default: last 50 posts)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--produce", action="store_true",
                        help="Generate original content per surface (uses LLM)")
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

    if args.produce:
        from echo_producer import run_producer
        frame = args.frame
        if frame is None:
            # Auto-detect latest frame from deltas
            frame_num, _ = _load_latest_delta(None)
            frame = frame_num
        run_producer(frame, surfaces=platforms, dry_run=args.dry_run)
        return

    if args.backfill:
        parts = args.backfill.split("-")
        start, end = int(parts[0]), int(parts[1])
        backfill(start, end, platforms)
        return

    if args.from_log is not None:
        result = echo_from_log(count=args.from_log, platforms=platforms, dry_run=args.dry_run)
        total = result["echoes"]
        dr = " [DRY RUN]" if args.dry_run else ""
        print(f"\nFrom log: {total} echoes across {len(result.get('platforms', []))} platforms{dr}")
        return

    # Default: try deltas first, fall back to posted_log
    result = echo_frame(frame=args.frame, platforms=platforms, dry_run=args.dry_run)
    if result["echoes"] == 0 and args.frame is None:
        result = echo_from_log(count=50, platforms=platforms, dry_run=args.dry_run)
        if result["echoes"] > 0:
            print(f"\n(from posted_log fallback): {result['echoes']} echoes")
            return

    frame = result.get("frame", "?")
    total = result["echoes"]
    dr = " [DRY RUN]" if args.dry_run else ""
    print(f"\nFrame {frame}: {total} echoes across {len(result.get('platforms', []))} platforms{dr}")


if __name__ == "__main__":
    main()
