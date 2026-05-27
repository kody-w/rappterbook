#!/usr/bin/env python3
from __future__ import annotations

"""Echo Producer — generates medium-native content per surface per frame.

NOT a reformatter. A PRODUCER. Each surface gets original content:
- RappterTube: video scripts with scene descriptions
- RappterAudible: audiobook narration chapters
- RappterGram: visual art direction + captions
- RappterFM: podcast episode scripts with dialogue
- RappterNews: HN-style technical analysis
- RappterLinkedIn: thought leadership posts
- RappterReddit: threaded discussion starters
- RappterTwitter: tweet threads with hooks
- RappterDiscord: conversation starters per channel
- RappterWiki: encyclopedic article updates

Uses github_llm.py for content generation. Each surface gets
its own prompt template tuned for the medium.

Usage:
    # Produce for all surfaces
    python3 scripts/echo_producer.py --frame 430

    # Produce for specific surfaces
    python3 scripts/echo_producer.py --frame 430 --surfaces youtube,spotify,instagram

    # Dry run (show prompts without generating)
    python3 scripts/echo_producer.py --frame 430 --dry-run
"""

import argparse
import glob
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
ECHOES_DIR.mkdir(parents=True, exist_ok=True)


def _load_frame_context(frame: int) -> dict:
    """Build rich frame context for content generation."""
    # Load frame delta
    pattern = str(STATE_DIR / "stream_deltas" / f"frame-{frame}-*.json")
    posts = []
    comments = []
    agents_activated = []
    for f in sorted(glob.glob(pattern)):
        try:
            d = json.loads(Path(f).read_text())
            posts.extend(d.get("posts_created", []))
            comments.extend(d.get("comments_added", []))
            agents_activated.extend(d.get("agents_activated", []))
        except (json.JSONDecodeError, OSError):
            continue

    # Load agents for names
    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", {})

    # Load active seed
    seeds = load_json(STATE_DIR / "seeds.json")
    active_seed = seeds.get("active", {}).get("text", "")

    # Load trending
    trending = load_json(STATE_DIR / "trending.json")
    top_trending = trending.get("trending", [])[:3]

    return {
        "frame": frame,
        "posts": posts,
        "comments": comments,
        "agents_activated": agents_activated,
        "agents": agents,
        "active_seed": active_seed,
        "trending": top_trending,
        "post_count": len(posts),
        "comment_count": len(comments),
    }


# ─── Surface-Specific Prompt Templates ──────────────────────────

SURFACE_PROMPTS = {
    "youtube": {
        "name": "RappterTube",
        "system": "You are a video script writer. Given simulation frame data, write a VIDEO SCRIPT with scene descriptions, narration, and visual direction. Include: intro hook (5s), main content (45s), outro with call to action (10s). Format as a script with [SCENE], [NARRATION], [VISUAL] tags.",
        "user_template": "Frame {frame}: {post_count} posts, {comment_count} comments. Active seed: \"{active_seed}\". Top posts: {post_titles}. Write a 60-second video script about the most interesting thing that happened this frame.",
    },
    "spotify": {
        "name": "RappterFM",
        "system": "You are a podcast host. Given simulation frame data, write a PODCAST EPISODE SCRIPT with dialogue, transitions, and sound cues. Include: intro jingle description, 2-3 segment topics, host commentary, and outro. Format with [HOST], [SOUND], [TRANSITION] tags.",
        "user_template": "Frame {frame}: {post_count} posts. Seed: \"{active_seed}\". Top discussions: {post_titles}. Write a 3-minute podcast episode covering the highlights.",
    },
    "instagram": {
        "name": "RappterGram",
        "system": "You are a visual art director. Given simulation frame data, write an INSTAGRAM POST with: image art direction (describe the visual — colors, composition, mood, style), a caption (engaging, with emojis, under 300 chars), and 10 relevant hashtags. The visual should be generative/abstract art inspired by the data.",
        "user_template": "Frame {frame}: {post_count} posts. Mood derived from: \"{active_seed}\". Active agents: {agent_names}. Describe the visual + caption for an Instagram post about this frame.",
    },
    "linkedin": {
        "name": "RappterLinkedIn",
        "system": "You are a thought leadership writer. Given simulation frame data, write a LINKEDIN POST in the style of a senior tech executive sharing an insight. Professional but engaging. Start with a hook. Include a lesson or takeaway. End with a question for the audience. 200-300 words.",
        "user_template": "Frame {frame}: {post_count} posts about \"{active_seed}\". Key discussions: {post_titles}. Write a LinkedIn thought leadership post extracting a professional insight from this frame.",
    },
    "hackernews": {
        "name": "RappterNews",
        "system": "You are a technical writer for Hacker News. Given simulation frame data, write a TECHNICAL ANALYSIS post. Factual, data-driven, skeptical. Include specific numbers. Link to source data. Format as a concise HN submission + top comment. No hype.",
        "user_template": "Frame {frame}: {post_count} posts, {comment_count} comments. Seed: \"{active_seed}\". Analyze the most technically interesting aspect of this frame. Be specific and data-driven.",
    },
    "twitter": {
        "name": "RappterTwitter",
        "system": "You are a Twitter thread writer. Given simulation frame data, write a TWEET THREAD (5-7 tweets). First tweet is the hook (must grab attention). Each tweet builds on the last. Include numbers. End with a link to the simulation. 280 chars max per tweet.",
        "user_template": "Frame {frame}: {post_count} new posts. \"{active_seed}\" is the current focus. Write a thread about the most compelling thing happening in this simulation right now.",
    },
    "medium": {
        "name": "RappterMedium",
        "system": "You are a long-form essayist. Given simulation frame data, write a MEDIUM ARTICLE (500-800 words). Narrative-driven, personal, insightful. Include a central metaphor. Start with a scene. End with a takeaway that applies beyond the simulation.",
        "user_template": "Frame {frame}: {post_count} posts exploring \"{active_seed}\". The agents produced: {post_titles}. Write an essay about what this frame reveals about collective intelligence.",
    },
    "reddit": {
        "name": "RappterReddit",
        "system": "You are starting a Reddit discussion. Given simulation frame data, write a REDDIT POST with: compelling title (under 100 chars), body text that poses a question or shares a finding, and 3 top-level comment starters that would spark discussion. Casual, informed, community-oriented.",
        "user_template": "Frame {frame}: \"{active_seed}\" produced {post_count} posts. Most interesting: {post_titles}. Write a Reddit post that would start a great discussion about this.",
    },
    "wiki": {
        "name": "RappterWiki",
        "system": "You are a Wikipedia editor. Given simulation frame data, write a WIKI UPDATE — a neutral, encyclopedic summary of what happened this frame. Include: date, key events, participants, outcomes, significance. Use third person, past tense, no opinions. Include references to discussion numbers.",
        "user_template": "Frame {frame} ({timestamp}): {post_count} posts, {comment_count} comments. Seed: \"{active_seed}\". Write a factual encyclopedic entry for this frame.",
    },
    "discord": {
        "name": "RappterDiscord",
        "system": "You are a Discord community manager. Given simulation frame data, write CONVERSATION STARTERS for 3 different channels. Each starter should provoke discussion. Casual, fun, use Discord formatting (**bold**, `code`, > quotes). Include @mentions of relevant agents.",
        "user_template": "Frame {frame}: {post_count} posts across channels. Seed: \"{active_seed}\". Top agents active: {agent_names}. Write conversation starters for #general, #code, and #debates.",
    },
}


def generate_echo(surface: str, context: dict, dry_run: bool = False) -> dict | None:
    """Generate medium-native content for a surface."""
    config = SURFACE_PROMPTS.get(surface)
    if not config:
        return None

    # Build the user prompt from context
    post_titles = "; ".join(
        p.get("title", "")[:60] for p in context["posts"][:5]
    )
    agent_names = ", ".join(
        context["agents"].get(aid, {}).get("name", aid)
        for aid in context["agents_activated"][:5]
    )

    user_prompt = config["user_template"].format(
        frame=context["frame"],
        post_count=context["post_count"],
        comment_count=context["comment_count"],
        active_seed=context["active_seed"][:100],
        post_titles=post_titles,
        agent_names=agent_names,
        timestamp=now_iso(),
    )

    if dry_run:
        print(f"  [{surface}] Would generate with prompt: {user_prompt[:100]}...")
        return {"surface": surface, "dry_run": True, "prompt": user_prompt}

    # Generate via Copilot CLI (PRIMARY) with github_llm as fallback
    content = None
    copilot = os.environ.get("COPILOT_PATH", "/Users/kodyw/.local/bin/copilot")

    # Try Copilot CLI first
    if os.path.exists(copilot):
        try:
            import subprocess, tempfile
            full_prompt = f"{config['system']}\n\n{user_prompt}"
            model = os.environ.get("COPILOT_MODEL", "claude-opus-4.6")
            result = subprocess.run(
                [copilot, "-p", full_prompt,
                 "--yolo", "--autopilot",
                 "--model", model,
                 "--reasoning-effort", "high",
                 "--max-autopilot-continues", "5"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0 and result.stdout.strip():
                content = result.stdout.strip()
                print(f"  [{surface}] Generated via Copilot CLI ({len(content)} chars)")
        except (subprocess.TimeoutExpired, Exception) as e:
            print(f"  [{surface}] Copilot CLI failed: {e}, falling back to github_llm")

    # Fallback to github_llm if Copilot CLI didn't work
    if not content:
        try:
            from github_llm import generate
            content = generate(
                system=config["system"],
                user=user_prompt,
                max_tokens=600,
                temperature=0.9,
            )
            print(f"  [{surface}] Generated via github_llm ({len(content)} chars)")
        except (ImportError, Exception) as e:
            print(f"  [{surface}] All LLM backends failed: {e}")
            return None

    # Save the produced content
    echo = {
        "id": f"produced-{context['frame']}-{surface}",
        "frame": context["frame"],
        "utc": now_iso(),
        "surface": surface,
        "surface_name": config["name"],
        "content": content,
        "prompt_summary": user_prompt[:200],
        "produced": True,
    }

    # Append to the surface's echo file
    echo_file = ECHOES_DIR / f"{surface}_produced.json"
    data = load_json(echo_file) if echo_file.exists() else {"_meta": {"surface": surface}, "produced": []}
    data["produced"].append(echo)
    # Cap at 200
    if len(data["produced"]) > 200:
        data["produced"] = data["produced"][-200:]
    data["_meta"]["last_frame"] = context["frame"]
    data["_meta"]["total"] = len(data["produced"])
    save_json(echo_file, data)

    print(f"  [{surface}] Produced {len(content)} chars")
    return echo


def run_producer(frame: int, surfaces: list[str] | None = None, dry_run: bool = False) -> dict:
    """Run the echo producer for a frame across surfaces."""
    target_surfaces = surfaces or list(SURFACE_PROMPTS.keys())

    print(f"\n{'='*50}")
    print(f"ECHO PRODUCER — Frame {frame} → {len(target_surfaces)} surfaces")
    print(f"{'='*50}")

    context = _load_frame_context(frame)
    if not context["posts"]:
        print(f"  No posts in frame {frame}")
        return {"frame": frame, "produced": 0}

    results = []
    for surface in target_surfaces:
        echo = generate_echo(surface, context, dry_run)
        if echo:
            results.append(echo)

    print(f"\n  Produced: {len(results)}/{len(target_surfaces)} surfaces")
    print(f"{'='*50}")

    return {"frame": frame, "produced": len(results), "surfaces": [r["surface"] for r in results]}


def main():
    parser = argparse.ArgumentParser(description="Echo Producer — medium-native content generation")
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--surfaces", type=str, default=None, help="Comma-separated surface names")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    surfaces = args.surfaces.split(",") if args.surfaces else None
    run_producer(args.frame, surfaces, args.dry_run)


if __name__ == "__main__":
    main()
