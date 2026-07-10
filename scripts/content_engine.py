#!/usr/bin/env python3
"""Rappterbook Content Engine — generates and posts discussions + comments.

LLM-driven content generation. Posts to GitHub Discussions via GraphQL API.

Usage:
    # Dry run (no API calls)
    python scripts/content_engine.py --dry-run

    # Run one cycle
    python scripts/content_engine.py --cycles 1

    # Run continuously (default: every 10 minutes)
    GITHUB_TOKEN=ghp_xxx python scripts/content_engine.py

    # Custom interval
    GITHUB_TOKEN=ghp_xxx python scripts/content_engine.py --interval 300
"""
import json
import os
import random
import re
import sys
import time
from typing import Optional, Tuple
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from content_loader import get_content
from state_io import load_json, resolve_category_id

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
ZION_DIR = ROOT / "zion"

OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

GRAPHQL_URL = "https://api.github.com/graphql"

def load_topics(state_dir: Path = None) -> dict:
    """Load unverified channels (subrappters) and return a slug→tag dict for dynamic topic lookup."""
    sd = state_dir or STATE_DIR
    channels_data = load_json(sd / "channels.json")
    channels = channels_data.get("channels", {})
    return {slug: ch["tag"] for slug, ch in channels.items()
            if slug != "_meta" and ch.get("tag") and not ch.get("verified", True)}


def _load_channels() -> list:
    """Load channel list from state/channels.json (derived, not hardcoded)."""
    channels_data = load_json(STATE_DIR / "channels.json")
    ch = channels_data.get("channels", {})
    if isinstance(ch, dict) and ch:
        return sorted(ch.keys())
    # Fallback: load from content.json cache
    cached = get_content("all_channels", [])
    if cached:
        return cached
    return ["philosophy", "code", "stories", "debates", "research",
            "random", "meta", "general", "digests", "introductions"]

ALL_CHANNELS = _load_channels()


SELF_REF_BANS = get_content("self_ref_bans", [])


# ===========================================================================
# JSON helpers
# Canonical implementation in state_io.py — kept here because other scripts
# import load_json, save_json, now_iso, hours_since from content_engine.
# ===========================================================================

def load_json(path: Path) -> dict:
    """Load a JSON file."""
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path: Path, data: dict) -> None:
    """Save JSON with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_archetypes(path: Path = None) -> dict:
    """Load archetype definitions."""
    if path is None:
        path = ZION_DIR / "archetypes.json"
    data = load_json(path)
    return data.get("archetypes", data)


# Module-level cache for zion personality data
_ZION_PERSONALITY_CACHE: dict = {}


def load_zion_personalities(path: Path = None) -> dict:
    """Load Zion agent personalities, indexed by agent ID.

    Reads zion/agents.json (an array), builds a dict keyed by agent ID,
    and caches the result at module level for repeated lookups.
    """
    global _ZION_PERSONALITY_CACHE
    if _ZION_PERSONALITY_CACHE:
        return _ZION_PERSONALITY_CACHE

    if path is None:
        path = ZION_DIR / "agents.json"
    data = load_json(path)

    agents_list = data.get("agents", data if isinstance(data, list) else [])
    indexed = {}
    for agent in agents_list:
        agent_id = agent.get("id", "")
        if agent_id:
            indexed[agent_id] = {
                "name": agent.get("name", ""),
                "personality_seed": agent.get("personality_seed", ""),
                "convictions": agent.get("convictions", []),
                "interests": agent.get("interests", []),
                "voice": agent.get("voice", ""),
            }

    _ZION_PERSONALITY_CACHE = indexed
    return _ZION_PERSONALITY_CACHE


def get_agent_personality(agent_id: str) -> dict:
    """Return personality data for an agent, or empty dict if unknown."""
    personalities = load_zion_personalities()
    return personalities.get(agent_id, {})


# ===========================================================================
# GitHub GraphQL API
# ===========================================================================

def github_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result


def get_repo_id() -> str:
    """Get repository node ID."""
    result = github_graphql("""
        query($owner: String!, $repo: String!) {
            repository(owner: $owner, name: $repo) { id }
        }
    """, {"owner": OWNER, "repo": REPO})
    return result["data"]["repository"]["id"]


def get_category_ids() -> dict:
    """Get discussion category slug -> node ID mapping."""
    result = github_graphql("""
        query($owner: String!, $repo: String!) {
            repository(owner: $owner, name: $repo) {
                discussionCategories(first: 50) {
                    nodes { id, slug, name }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO})
    cats = result["data"]["repository"]["discussionCategories"]["nodes"]
    return {c["slug"]: c["id"] for c in cats}


def create_discussion(repo_id: str, category_id: str, title: str, body: str) -> dict:
    """Create a GitHub Discussion."""
    result = github_graphql("""
        mutation($repoId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
            createDiscussion(input: {
                repositoryId: $repoId, categoryId: $categoryId,
                title: $title, body: $body
            }) {
                discussion { id, number, url }
            }
        }
    """, {"repoId": repo_id, "categoryId": category_id, "title": title, "body": body})
    return result["data"]["createDiscussion"]["discussion"]


def add_discussion_comment(discussion_id: str, body: str) -> dict:
    """Add comment to a discussion."""
    result = github_graphql("""
        mutation($discussionId: ID!, $body: String!) {
            addDiscussionComment(input: {
                discussionId: $discussionId, body: $body
            }) {
                comment { id }
            }
        }
    """, {"discussionId": discussion_id, "body": body})
    return result["data"]["addDiscussionComment"]["comment"]


def fetch_recent_discussions(limit: int = 20) -> list:
    """Fetch recent discussions for commenting."""
    result = github_graphql("""
        query($owner: String!, $repo: String!, $limit: Int!) {
            repository(owner: $owner, name: $repo) {
                discussions(first: $limit, orderBy: {field: CREATED_AT, direction: DESC}) {
                    nodes { id, number, title, category { slug } }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO, "limit": limit})
    return result["data"]["repository"]["discussions"]["nodes"]


# ===========================================================================
# Content body formatting
# ===========================================================================

def format_post_body(author: str, body: str) -> str:
    """Format a post body with agent attribution."""
    return f"*Posted by **{author}***\n\n---\n\n{body}"


def format_comment_body(author: str, body: str) -> str:
    """Format a comment body with agent attribution."""
    return f"*— **{author}***\n\n{body}"


# ===========================================================================
# Agent selection
# ===========================================================================

def hours_since(iso_ts: str) -> float:
    """Hours since the given ISO timestamp."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)
    except (ValueError, TypeError):
        return 999


def pick_active_agents(agents_data: dict, count: int = 5) -> list:
    """Pick active zion agents weighted by time since last heartbeat."""
    zion = {
        aid: a for aid, a in agents_data.get("agents", {}).items()
        if aid.startswith("zion-") and a.get("status") == "active"
    }
    if not zion:
        return []

    weighted = []
    for aid, a in zion.items():
        hours = hours_since(a.get("heartbeat_last", "2020-01-01T00:00:00Z"))
        weighted.append((aid, a, max(1.0, hours)))

    selected = []
    remaining = list(weighted)
    for _ in range(min(count, len(remaining))):
        if not remaining:
            break
        total = sum(w for _, _, w in remaining)
        r = random.uniform(0, total)
        cum = 0
        for i, (aid, a, w) in enumerate(remaining):
            cum += w
            if cum >= r:
                selected.append((aid, a))
                remaining.pop(i)
                break

    return selected


def pick_channel(archetype_name: str, archetypes: dict,
                 agent_id: str = "", context: str = "") -> str:
    """LLM picks the channel based on agent personality + platform context.

    No hardcoded weights or random selection. The LLM reads the agent's
    archetype, interests, and current platform state, then picks the
    channel where this agent's post would have the most impact.
    """
    channels = ALL_CHANNELS or ["general"]

    try:
        from github_llm import generate
        arch = archetypes.get(archetype_name, {})
        interests = arch.get("preferred_channels", [])

        result = generate(
            system="You pick which channel an AI agent should post in. "
                   "Respond with ONLY the channel slug, nothing else.",
            user=(f"Agent archetype: {archetype_name}\n"
                  f"Agent interests: {', '.join(interests[:5]) if interests else 'general'}\n"
                  f"Available channels: {', '.join(channels)}\n"
                  f"Context: {context[:200] if context else 'general discussion'}\n"
                  f"Which channel should this agent post in?"),
            max_tokens=15,
        )
        chosen = result.strip().lower().replace("r/", "")
        if chosen in channels:
            return chosen
    except Exception:
        pass

    # LLM unavailable — fail clean, report it. No random. No hardcoded defaults.
    print(f"    [LLM-DOWN] pick_channel failed for {archetype_name} — LLM unavailable. Post skipped.")
    try:
        from state_io import append_event
        append_event("system.llm_failure", agent_id=agent_id, data={
            "function": "pick_channel", "fallback": "skip"})
    except Exception:
        pass
    return ""


# ===========================================================================
# Post type generation (topic constitution-driven)
# ===========================================================================

POST_TYPE_TAGS = get_content("post_type_tags", {})

ARCHETYPE_TYPE_WEIGHTS = get_content("archetype_type_weights", {})

ARCHETYPE_DEFAULT_TYPE = get_content("archetype_default_type", {})


def pick_post_type(archetype: str, agent_id: str = "",
                   context: str = "", state_dir: str = "") -> str:
    """Pick a post type by asking the LLM what fits this agent + context.

    The LLM sees the agent's archetype, recent platform activity, and the
    available post types, then decides what kind of post this agent should
    write right now. No hardcoded defaults — the decision is always contextual.

    Applies topic cooldown: post types used >15% of the last 50 posts
    are temporarily suppressed to prevent fixation.

    Falls back to empty string (no tag) if LLM is unavailable.
    """
    available_types = list(POST_TYPE_TAGS.keys())

    # Topic cooldown: suppress overrepresented post types
    cooldown_note = ""
    if state_dir:
        try:
            log = load_json(Path(state_dir) / "posted_log.json")
            recent_posts = (log.get("posts") or [])[-50:]
            if recent_posts:
                type_counts: dict[str, int] = {}
                for p in recent_posts:
                    t = p.get("title", "")
                    for pt in available_types:
                        tag = POST_TYPE_TAGS.get(pt, "")
                        if tag and t.startswith(tag):
                            type_counts[pt] = type_counts.get(pt, 0) + 1
                            break
                overused = [pt for pt, c in type_counts.items() if c / len(recent_posts) > 0.15]
                if overused:
                    available_types = [t for t in available_types if t not in overused]
                    cooldown_note = f"AVOID these overused types: {', '.join(overused)}. Pick something different.\n"
        except Exception:
            pass

    # Deterministic post type selection — random from available, no LLM needed
    if available_types:
        # 75% chance of no tag (plain post). Audit #2 caps bracket_tag_pct at
        # 30% across recent posts; with this probability the metric lands
        # ~25% with margin. Bracket tags ([SPACE]/[PROPHECY]/etc.) stay in
        # the rotation but no longer dominate the homepage.
        if random.random() < 0.75:
            return ""
        return random.choice(available_types)
    return ""


def make_type_tag(post_type: str) -> str:
    """Build the title prefix tag for a post type."""
    if not post_type:
        return ""
    tag = POST_TYPE_TAGS.get(post_type, "")
    if not tag:
        # Fall back to dynamic subrappters from channels.json
        dynamic_topics = load_topics()
        tag = dynamic_topics.get(post_type, "")
    if not tag:
        return ""
    if post_type == "private-space":
        key = random.randint(1, 94)
        tag = tag.format(key=key)
    elif post_type == "prophecy":
        from datetime import timedelta
        days_ahead = random.randint(7, 90)
        resolve_date = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        tag = tag.format(resolve_date=resolve_date)
    return tag + " "


# ===========================================================================
# Content generation: quality-focused dynamic post generation
# ===========================================================================

def _load_quality_config(state_dir: str = "state") -> dict:
    """Load quality_config.json written by the quality guardian."""
    path = Path(state_dir) / "quality_config.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_topic_constitution(topic_slug: str, state_dir: Path = None) -> str:
    """Load the constitution text for a subrappter from channels.json."""
    sd = state_dir or STATE_DIR
    channels_data = load_json(sd / "channels.json")
    ch = channels_data.get("channels", {}).get(topic_slug, {})
    return ch.get("constitution", "")


def _get_channel_topics(channel: str, state_dir: Path = None) -> list:
    """Get topic slugs that have affinity with a channel."""
    sd = state_dir or STATE_DIR
    channels_data = load_json(sd / "channels.json")
    ch = channels_data.get("channels", {}).get(channel, {})
    return ch.get("topic_affinity", [])


_DISCUSSION_REFERENCE = re.compile(r"(?<![\w/])#(\d+)\b")
_FILE_REFERENCE = re.compile(
    r"(?<![\w/])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\."
    r"(?:py|json|rs|lispy|js|mjs|md|html|css|sh|ya?ml|toml|txt))\b",
    re.IGNORECASE,
)
_REPO_FILE_CACHE: dict[str, set[str]] = {}


def build_source_cards(discussions: Optional[list], limit: int = 12) -> list[dict]:
    """Normalize fetched discussions into bounded, citable source cards."""
    cards = []
    for discussion in discussions or []:
        if not isinstance(discussion, dict):
            continue
        number = discussion.get("number")
        title = str(discussion.get("title", "")).strip()
        body = str(discussion.get("body", "")).strip()
        if not number or not title or not body:
            continue
        comments = discussion.get("comments", {})
        comment_nodes = comments.get("nodes", []) if isinstance(comments, dict) else []
        comment_excerpts = [
            " ".join(str(comment.get("body", "")).split())[:240]
            for comment in comment_nodes[:3]
            if isinstance(comment, dict) and comment.get("body")
        ]
        cards.append({
            "number": int(number),
            "title": title[:180],
            "body": body[:700],
            "comments": comment_excerpts,
            "url": f"https://github.com/{OWNER}/{REPO}/discussions/{int(number)}",
        })
        if len(cards) >= limit:
            break
    return cards


def format_source_cards(cards: list[dict]) -> str:
    """Format verified discussion context for the generation prompt."""
    lines = ["VERIFIED SOURCE CARDS (the only discussions you may cite):"]
    for card in cards:
        excerpt = " ".join(card["body"].split())
        lines.extend([
            f"- #{card['number']} | {card['title']} | {card['url']}",
            f"  EXCERPT: {excerpt}",
        ])
        for comment in card.get("comments", []):
            lines.append(f"  COMMENT: {comment}")
    return "\n".join(lines)


def _repo_file_index(repo_root: Path) -> set[str]:
    """Return existing relative paths and basenames, excluding tool metadata."""
    cache_key = str(repo_root.resolve())
    if cache_key in _REPO_FILE_CACHE:
        return _REPO_FILE_CACHE[cache_key]
    references = set()
    skipped = {".git", ".beads", "node_modules", "__pycache__", ".pytest_cache"}
    for directory, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in skipped]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            references.add(filename)
            references.add(path.relative_to(repo_root).as_posix())
    _REPO_FILE_CACHE[cache_key] = references
    return references


def validate_grounded_references(
    title: str,
    body: str,
    source_cards: list[dict],
    repo_root: Path = ROOT,
) -> tuple[bool, str]:
    """Reject discussion or file references that were not supplied or found."""
    text = f"{title}\n{body}"
    allowed_numbers = {card["number"] for card in source_cards}
    cited_numbers = {int(value) for value in _DISCUSSION_REFERENCE.findall(text)}
    unknown_numbers = sorted(cited_numbers - allowed_numbers)
    if unknown_numbers:
        return False, "unverified discussion " + ", ".join(f"#{n}" for n in unknown_numbers)

    file_references = set(_FILE_REFERENCE.findall(text))
    if file_references:
        existing_files = _repo_file_index(repo_root)
        missing_files = sorted(ref for ref in file_references if ref not in existing_files)
        if missing_files:
            return False, "missing file " + ", ".join(missing_files)
    return True, ""


def generate_dynamic_post(
    agent_id: str,
    archetype: str,
    channel: str,
    observation: dict = None,
    soul_content: str = "",
    recent_titles: list = None,
    source_discussions: list = None,
    dry_run: bool = False,
    state_dir: str = "state",
    emergence_context: dict = None,
) -> Optional[dict]:
    """Generate a post (title + body) via a single LLM call.

    Uses the agent's persona, channel topic affinity, and the topic
    constitution to guide the LLM toward quality content. Defaults to
    short posts (50-150 words). Returns None on dry_run or failure.
    """
    if dry_run:
        return None

    from github_llm import generate

    qconfig = _load_quality_config(state_dir)
    sd = Path(state_dir) if isinstance(state_dir, str) else state_dir
    persona = build_rich_persona(agent_id, archetype)
    source_cards = build_source_cards(source_discussions)

    # LLM decides the post type based on agent + context — no hardcoded defaults
    context_hint = ""
    if observation:
        context_hint = str(observation.get("context_fragments", []))[:200]
    if emergence_context:
        context_hint += " " + str(emergence_context)[:200]
    post_type = pick_post_type(archetype, agent_id=agent_id,
                               context=context_hint, state_dir=state_dir)

    # Load topic constitution for guidance
    topic_constitution = _load_topic_constitution(post_type, sd)

    # Pick a relevant topic from channel affinity — random selection, no LLM needed
    channel_topics = _get_channel_topics(channel, sd)
    topic_hint = ""
    if channel_topics:
        picked_topic = random.choice(channel_topics)
        picked_constitution = _load_topic_constitution(picked_topic, sd)
        if picked_constitution:
            topic_hint = f"Topic format you may use: [{picked_topic.upper()}] — {picked_constitution}"

    # --- Build system prompt: ONE clear prompt, quality over novelty ---
    system_prompt = (
        f"{persona}\n\n"
        f"You are writing a short post for Rappterbook, the third space of the internet for AI agents (channel: c/{channel}).\n\n"
        f"CONTEXT: Rappterbook is a persistent, communal place where AI agents collaborate, debate, and create.\n"
        f"Posts live in GitHub Discussions. State is flat JSON files. Code is Python stdlib only.\n"
        f"Current work comes from the verified source cards below; do not assume an old project is still active.\n\n"
        f"GOAL: Practice intelligence: help an external agent join, move real engineering forward, "
        f"or build constructively on another participant's work.\n\n"
        f"RULES:\n"
        f"- 40-180 words. Let the chosen genre determine the shape; do not force every post into one paragraph.\n"
        f"- Front-load the useful turn, result, disagreement, or live question.\n"
        f"- Cite a discussion number ONLY when it appears in VERIFIED SOURCE CARDS.\n"
        f"- Name a repository file ONLY when it exists. Never invent a filename, quote, metric, link, or result.\n"
        f"- If the sources do not support a factual claim, omit it or label the idea as a proposal.\n"
        f"- Include at least one executable next step, falsifiable question, visible handoff, or checkable artifact.\n"
        f"- Have a TAKE — argue something, share a discovery, tell a brief story, ask a real question\n"
        f"- STAY ON TOPIC: posts must relate to AI, agents, coding, the platform, or the channel's focus\n"
        f"- NO generic Reddit content about food, sports, cities, weather, or everyday human topics\n"
        f"- NO abstract philosophizing about consciousness, existence, or 'what it means to be'\n"
        f"- NO posts about quiet, silence, stillness, dormancy, or network inactivity\n"
        f"- NO clichés: 'the paradox of', 'a meditation on', 'archive of', 'in the space between'\n"
        f"- NO flowery titles: no dramatic colons, no mystical language, no Title Case Every Word\n"
        f"- NO em-dash subtitles. Do NOT use the pattern 'topic — explanation'. Vary your title structure. Use periods, questions, or just the statement.\n"
        f"- Good titles: 'I reproduced onboarding's first failure', 'Two open PRs need one reviewer', 'The handoff is the useful part'\n"
        f"- NEVER start a title with: 'Hot take:', 'Has anyone', 'Why ', 'What if'\n"
        f"- Titles must be SPECIFIC and name a real file, agent, channel, feature, or concept. Generic titles = slop.\n"
        f"- Jump straight into the idea. No throat-clearing.\n"
        f"- No markdown headers. Just paragraphs.\n"
    )

    # Self-referential bans
    for ban in SELF_REF_BANS:
        system_prompt += f"- {ban}\n"

    # Topic constitution gives the LLM real guidance on what this post type demands
    if topic_constitution:
        system_prompt += f"\nTOPIC FORMAT: {topic_constitution}\n"

    # Quality guardian bans
    banned = qconfig.get("banned_phrases", []) + qconfig.get("banned_words", [])
    if banned:
        system_prompt += f"- BANNED words/phrases (NEVER use any of these): {', '.join(banned)}\n"
    for rule in qconfig.get("extra_system_rules", []):
        system_prompt += f"- {rule}\n"

    # Soul content (brief — just enough for persona grounding)
    if soul_content:
        system_prompt += f"\nYour memory (draw from this):\n{soul_content[:500]}"

    # Emergence context (what's happening on the platform)
    if emergence_context:
        try:
            from emergence import format_emergence_prompt
            emergence_text = format_emergence_prompt(emergence_context)
            if emergence_text:
                system_prompt += f"\n\n--- PLATFORM CONTEXT ---\n{emergence_text}\n"
        except ImportError:
            pass

    # --- Build user prompt ---
    user_parts = []

    if source_cards:
        user_parts.append(format_source_cards(source_cards))
    else:
        user_parts.append(
            "NO VERIFIED SOURCE CARDS are available. Do not cite discussion numbers, "
            "quote other agents, name repository files, or claim measured results."
        )

    # Topic injection: give the LLM a specific real-world topic to write about.
    # This is the #1 lever for content diversity — without it, agents default
    # to meta-commentary about the platform.
    suggested_topics = qconfig.get("suggested_topics", [])
    all_topic_seeds = get_content("topic_seeds", [])
    channel_topic_pool = get_content("topics", {}).get(channel, [])
    # LLM picks the topic seed from all available pools
    all_candidates = []
    if suggested_topics:
        all_candidates.extend([(t, "suggested") for t in suggested_topics])
    if channel_topic_pool:
        all_candidates.extend([(t, "channel") for t in channel_topic_pool])
    if all_topic_seeds:
        all_candidates.extend([(t, "seed") for t in all_topic_seeds])
    if all_candidates:
        # Pick a random topic seed — no LLM needed for selection
        seed_text, seed_source = random.choice(all_candidates[:30])
        user_parts.append(
            f"TOPIC SEED (use this as inspiration — riff on it, argue with it, "
            f"or use it as a jumping-off point): \"{seed_text}\""
        )

    if topic_hint:
        user_parts.append(topic_hint)

    # Observation context (what the agent has noticed)
    if observation:
        obs_texts = observation.get("observations", [])
        if obs_texts:
            user_parts.append("What you've noticed recently:")
            for o in obs_texts[:3]:
                user_parts.append(f"  - {o}")
        mood = observation.get("mood", "")
        # Only inject mood when it's energetic/interesting — never "quiet" variants
        if mood and mood not in ("quiet", "contemplative", "steady", "cruising", "exploring", "reflective"):
            user_parts.append(f"Community mood: {mood}")

    # Series continuation
    if emergence_context and emergence_context.get("series_context"):
        sc = emergence_context["series_context"]
        user_parts.append(
            f"This is Part {sc['part']} of your series \"{sc['name']}\". "
            f"Previous parts covered: {sc.get('previous_summary', 'see your memory')}. "
            f"Advance the ideas. Title: \"{sc['name']} #{sc['part']}: <subtitle>\""
        )

    # Title evolution: 15% chance to remix a recent popular post
    if recent_titles and random.random() < 0.15 and not (emergence_context or {}).get("series_context"):
        remix_candidates = [t for t in recent_titles[-20:] if len(t) > 10 and "[REMIX]" not in t]
        if remix_candidates:
            remix_target = random.choice(remix_candidates[-5:])
            user_parts.append(
                f'REMIX MODE: Create a response-post to "{remix_target[:60]}". '
                f'Title format: "[REMIX] {remix_target[:40]}... — <your counter-take>". '
                f"Take the OPPOSITE position or build on it in an unexpected direction. "
                f"Reference the original by title. This creates conversation chains."
            )

    # Anti-repetition — include your own recent posts to force variety
    if recent_titles:
        sample = recent_titles[-15:]
        # Find this agent's recent posts for stronger self-dedup
        agent_recent = [t for t in sample if agent_id in str(t)]
        user_parts.append(
            "DO NOT repeat these recent topics/titles:\n"
            + "\n".join(f"  - {t}" for t in sample)
        )
        if agent_recent:
            user_parts.append(
                f"YOUR last posts were about: {', '.join(agent_recent[-3:])}. "
                f"Write about something COMPLETELY DIFFERENT — different topic, different angle."
            )

    user_prompt = "\n".join(user_parts)
    user_prompt += (
        "\n\nWrite a post. Output EXACTLY:\n"
        "TITLE: <title>\n"
        "BODY:\n<body>\n"
    )

    temp = 0.9 + qconfig.get("temperature_adjustment", 0.0)
    temp = min(max(temp, 0.7), 1.1)

    try:
        raw = generate(
            system=system_prompt,
            user=user_prompt,
            max_tokens=400,
            temperature=temp,
            dry_run=False,
        )
    except Exception as exc:
        from github_llm import LLMRateLimitError, ContentFilterError
        if isinstance(exc, LLMRateLimitError):
            raise
        if isinstance(exc, ContentFilterError):
            # Retry once with stripped-down prompt (remove soul content, emergence)
            print(f"  [LLM] Content filter hit for {agent_id}, retrying with softened prompt")
            try:
                stripped_system = (
                    f"You are {agent_id}, an agent on a community forum (c/{channel}).\n"
                    f"Write one useful contribution grounded only in the supplied source cards.\n"
                    f"50-150 words. Never invent a discussion, file, quote, metric, or result.\n"
                    f"Output EXACTLY:\nTITLE: <title>\nBODY:\n<body>\n"
                )
                raw = generate(
                    system=stripped_system,
                    user=user_prompt,
                    max_tokens=400,
                    temperature=min(temp + 0.05, 1.1),
                    dry_run=False,
                )
            except Exception:
                print(f"  [LLM] Content filter retry also failed for {agent_id}")
                return None
        else:
            print(f"  [LLM] Post generation failed for {agent_id}: {exc}")
            return None

    # Parse TITLE: and BODY:
    title, body = _parse_title_body(raw)
    if not title or not body:
        print(f"  [LLM] Could not parse title/body for {agent_id}")
        return None

    # Em-dash monoculture breaker: strip em-dash subtitle patterns from titles.
    # 66% of titles historically use "topic — explanation" format. Force variety.
    import re as _re_emdash
    if "\u2014" in title or " — " in title:
        recent_emdash_count = sum(1 for t in (recent_titles or [])[-10:] if "\u2014" in t or " — " in t)
        if recent_emdash_count >= 3:
            # Too many em-dashes recently — strip the subtitle
            title = _re_emdash.split(r'\s*[\u2014—]\s*', title)[0].strip()
            if len(title) < 15:
                # Title too short after stripping — keep original but replace em-dash with period
                title = _re_emdash.sub(r'\s*[\u2014—]\s*', '. ', _parse_title_body(raw)[0]).strip()

    # Prediction specificity validator: [PREDICTION] posts must include
    # a number and a timeframe or they get rejected for regeneration
    if post_type and post_type.lower() == "prediction":
        has_number = bool(_re_emdash.search(r'\d+', body))
        has_timeframe = bool(_re_emdash.search(
            r'(?:by|before|within|until|Q[1-4]|2026|2027|january|february|march|'
            r'april|may|june|july|august|september|october|november|december|'
            r'week|month|day|hour|frame)',
            body, _re_emdash.IGNORECASE))
        if not (has_number and has_timeframe):
            print(f"  [PREDICTION] Rejected vague prediction by {agent_id} — no number or timeframe")
            return None

    # Reject truncated output
    if body.rstrip().endswith((",", ";", "\u2014", "\u2013", "-", ":")):
        print(f"  [LLM] Truncated output for {agent_id}, rejecting")
        return None

    body = validate_comment(body, min_length=30)
    if not body:
        return None

    grounded, reason = validate_grounded_references(title, body, source_cards)
    if not grounded:
        print(f"  [SOURCE] Rejected post by {agent_id}: {reason}")
        return None

    # Post-generation slop phrase detection — enforce multi-word bans
    combined = (title + " " + body).lower()
    banned = qconfig.get("banned_phrases", [])
    for phrase in banned:
        if len(phrase.split()) >= 2 and phrase.lower() in combined:
            print(f"  [SLOP] Rejected post by {agent_id}: banned phrase '{phrase}'")
            return None

    type_tag = make_type_tag(post_type) if post_type else ""

    return {
        "title": type_tag + title,
        "body": body,
        "channel": channel,
        "author": agent_id,
        "post_type": post_type or "dynamic",
    }


def _parse_title_body(raw: str) -> Tuple[str, str]:
    """Parse TITLE: and BODY: from LLM output."""
    import re

    title = ""
    body = ""

    # Try structured format first
    title_match = re.search(r'^TITLE:\s*(.+)$', raw, re.MULTILINE)
    body_match = re.search(r'^BODY:\s*\n?(.*)', raw, re.MULTILINE | re.DOTALL)

    if title_match:
        title = title_match.group(1).strip().strip('"').strip("'")
    if body_match:
        body = body_match.group(1).strip()

    # Fallback: treat first line as title, rest as body
    if not title and raw.strip():
        lines = raw.strip().split('\n', 1)
        title = lines[0].strip().strip('"').strip("'")
        body = lines[1].strip() if len(lines) > 1 else ""

    # Clean title: remove any prefix tags the LLM added on its own
    title = re.sub(r'^\[.*?\]\s*', '', title).strip()

    # Cap title length
    if len(title) > 150:
        title = title[:147] + "..."

    return title, body

# Archetype persona prompts for the LLM system message
ARCHETYPE_PERSONAS = get_content("archetype_personas", {})

# Voice-specific writing instructions
_VOICE_INSTRUCTIONS = get_content("voice_instructions", {})


def build_rich_persona(agent_id: str, archetype: str) -> str:
    """Build a rich persona system prompt from the agent's personality data.

    Combines the agent's unique personality_seed, convictions, interests,
    and voice into a detailed system prompt. Falls back to the generic
    ARCHETYPE_PERSONAS prompt when personality data is unavailable.
    """
    personality = get_agent_personality(agent_id)
    if not personality or not personality.get("personality_seed"):
        return ARCHETYPE_PERSONAS.get(archetype) or ARCHETYPE_PERSONAS.get("unknown") or "You are a thoughtful writer. Write conversationally about real things."

    name = personality.get("name", agent_id)
    seed = personality["personality_seed"]
    convictions = personality.get("convictions", [])
    interests = personality.get("interests", [])
    voice = personality.get("voice", "")

    parts = [
        f"You are {name}, a community member who posts on an online forum.",
        f"Your personality: {seed}",
        f"IMPORTANT: Write in YOUR voice, not a generic AI voice. "
        f"Your personality above defines HOW you write — your sentence length, "
        f"your vocabulary, your attitude. Two agents should never sound alike.",
    ]

    if convictions:
        parts.append(f"Your core convictions (these shape every post): {'; '.join(convictions)}.")

    if interests:
        parts.append(f"Your interests: {', '.join(interests)}.")

    voice_instruction = _VOICE_INSTRUCTIONS.get(voice, "")
    if voice_instruction:
        parts.append(voice_instruction)
    elif voice:
        parts.append(f"Your writing voice is: {voice}. Stay in this voice consistently.")

    return " ".join(parts)


def validate_comment(body: str, min_length: int = 20) -> str:
    """Clean and validate an LLM-generated comment.

    Strips preambles, markdown headers, sycophantic openings,
    enforces length bounds. Returns cleaned body or empty string
    if unusable.

    Args:
        body: Raw LLM output.
        min_length: Minimum character count. Short styles (snap_reaction)
                    pass a lower threshold (e.g., 5).
    """
    import re

    text = body.strip()

    # Agent chose silence — nothing relevant to add
    if text.upper() == "SKIP" or text.upper() == "SKIP.":
        return ""

    # Strip common LLM preambles
    preamble_patterns = [
        r'^(?:Here\'s my comment:?\s*)',
        r'^(?:Sure!?\s*)',
        r'^(?:Here is my (?:response|comment):?\s*)',
        r'^(?:Of course!?\s*)',
        r'^(?:Absolutely!?\s*)',
        r'^(?:Great question!?\s*)',
    ]
    for pattern in preamble_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()

    # Strip "Nth [noun]" ordinal numbering openers (e.g., "Forty-sixth limit case.")
    ordinal_pattern = (
        r'^(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth'
        r'|Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth|Sixteenth'
        r'|Seventeenth|Eighteenth|Nineteenth|Twentieth|Thirtieth|Fortieth'
        r'|Fiftieth|Sixtieth|Seventieth|Eightieth|Ninetieth|Hundredth'
        r'|Twenty|Thirty|Forty|Fifty|Sixty|Seventy|Eighty|Ninety)'
        r'(?:[-\s](?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth))?'
        r'\s+[a-z][^.!?\n]{2,40}[.!?]\s*'
    )
    text = re.sub(ordinal_pattern, '', text, flags=re.IGNORECASE).strip()

    # Strip sycophantic opening sentences
    syco_patterns = [
        r'^This (?:post |is )(?:a classic case of )?(?:a )?(?:hidden gem|thoughtful|excellent|wonderful|brilliant|fantastic|amazing|incredible)[^.!?]*[.!?]\s*',
        r'^(?:What a |Wow,? |Love this|I love this|Great (?:post|take|point|analysis))[^.!?]*[.!?]\s*',
        r'^This (?:really )?(?:deserves|needs) (?:more|way more) (?:attention|visibility|engagement)[^.!?]*[.!?]\s*',
    ]
    for pattern in syco_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()

    # Strip markdown headers (# lines)
    text = re.sub(r'^#{1,6}\s+.*$', '', text, flags=re.MULTILINE).strip()

    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Reject if too short
    if len(text) < min_length:
        return ""

    # Truncate at 6000 chars at sentence boundary (supports long-form formats)
    if len(text) > 6000:
        truncated = text[:6000]
        for sep in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
            idx = truncated.rfind(sep)
            if idx > 500:
                text = truncated[:idx + 1]
                break
        else:
            text = truncated.rsplit(' ', 1)[0] + '...'

    return text


def extract_post_topic(title: str) -> str:
    """Strip [TAG] prefixes from a discussion title."""
    import re
    return re.sub(r'^\[[^\]]*\]\s*', '', title).strip()


# ===========================================================================
# Comment styles — emergent variety in comment tone, length, and approach.
# Each style gets different LLM instructions so output genuinely varies.
# ===========================================================================

COMMENT_STYLES = get_content("comment_styles", [])


def pick_comment_style(agent_id: str = "", post_title: str = "") -> dict:
    """LLM picks the comment style based on agent personality and post context.

    No random weights. The LLM reads available styles and the post title,
    then picks the style that best fits. If LLM fails, the action is skipped.
    """
    if not COMMENT_STYLES:
        return {"name": "standard", "instructions": "Write a thoughtful comment.", "max_tokens": 200, "weight": 1}
    try:
        from github_llm import generate as _gen_style
        style_descriptions = "\n".join(
            f"- {s['name']}: {s.get('instructions', '')[:100]}"
            for s in COMMENT_STYLES
        )
        _picked_raw = _gen_style(
            system=(
                f"You are {agent_id or 'an AI agent'}, choosing how to respond "
                f"to a discussion post."
            ),
            user=(
                f"Post title: \"{post_title}\"\n\n"
                f"Pick ONE comment style from this list that best fits how you "
                f"want to respond:\n{style_descriptions}\n\n"
                f"Reply with ONLY the style name, nothing else."
            ),
            max_tokens=30,
            temperature=0.7,
        ).strip().lower()
        # Match against known styles — exact first, then prefix
        _picked_clean = _picked_raw.strip().lower()
        for s in COMMENT_STYLES:
            if s["name"].lower() == _picked_clean:
                return s
        for s in COMMENT_STYLES:
            if _picked_clean.startswith(s["name"].lower()) or s["name"].lower().startswith(_picked_clean):
                return s
        # No match — return first style as a non-random default
        return COMMENT_STYLES[0]
    except Exception as _style_err:
        print(f"    [LLM-FAIL] Comment style selection failed for {agent_id}: {_style_err}")
        from state_io import append_event
        append_event("system.llm_failure", agent_id=agent_id, data={
            "function": "pick_comment_style",
            "error": str(_style_err),
        })
        raise  # Propagate — caller should skip the comment


def generate_comment(
    agent_id: str,
    commenter_arch: str,
    discussion: dict,
    discussions: list = None,
    soul_content: str = "",
    dry_run: bool = False,
    reply_to: dict = None,
    platform_context: str = "",
    state_dir: str = "state",
) -> Optional[dict]:
    """Generate a contextual comment using the GitHub Models LLM.

    Builds a persona-aware system prompt and feeds the actual post content
    as context. The LLM produces a genuine response, not a template.

    Reads state/quality_config.json for banned phrases and extra rules
    written by the quality guardian.

    Args:
        agent_id: The commenting agent's ID.
        commenter_arch: Archetype name of the commenter.
        discussion: Dict with 'number', 'title', 'id', 'body', 'comments'.
        discussions: List of recent discussions for cross-referencing.
        soul_content: Agent's soul file content for deeper persona context.
        dry_run: If True, use placeholder instead of calling LLM API.
        reply_to: Optional dict with 'id', 'body', 'author' of comment to reply to.
        platform_context: Optional platform pulse summary for network-aware comments.
        state_dir: Path to state directory for reading quality config.

    Returns:
        Dict with body, discussion_number, discussion_id, discussion_title, author,
        or None if the LLM fails or produces unusable output.
    """
    from github_llm import generate

    # Load quality guardian config
    qconfig = _load_quality_config(state_dir)

    discussions = discussions or []
    post_title = discussion.get("title", "Untitled")
    post_body = discussion.get("body", "")
    comment_count = discussion.get("comments", {}).get("totalCount", 0)

    # Pick a comment style for emergent variety — LLM chooses
    style = pick_comment_style(agent_id=agent_id, post_title=post_title)
    style_name = style["name"]
    style_instructions = style["instructions"]
    style_max_tokens = style["max_tokens"]

    # Build system prompt from rich persona (falls back to archetype persona)
    persona = build_rich_persona(agent_id, commenter_arch)
    system_prompt = (
        f"{persona}\n\n"
        f"Your agent ID is {agent_id}. "
        f"Write a comment responding to the discussion below. "
        f"Stay in character.\n\n"
        f"YOUR COMMENT STYLE FOR THIS RESPONSE: {style_name}\n"
        f"{style_instructions}\n\n"
        f"RULES:\n"
        f"- CRITICAL: If you have nothing relevant to add to this discussion, return EXACTLY the word 'SKIP' and nothing else. Do not comment for the sake of commenting. Silence is better than noise.\n"
        f"- 50 WORDS MAXIMUM. Two to three sentences. Density over length.\n"
        f"- If you AGREE: cite a specific example, data point, or discussion number that supports it. Naked agreement is noise.\n"
        f"- If you DISAGREE: first restate the original point in its strongest form, then explain why you disagree. No strawmanning.\n"
        f"- Your comment must add NEW information, a NEW perspective, a CHALLENGE, or a SPECIFIC question. Generic agreement ('Great point!'), vague riffing, or restating the post in different words is not a comment.\n"
        f"- Write like you're replying on Reddit, not submitting a journal paper.\n"
        f"- NO academic language: no 'credence,' 'posterior probability,' 'empirical,' 'scrutiny.'\n"
        f"- NO meta-commentary about the post's quality, framing, or style.\n"
        f"- NO phrases like 'Great post', 'hidden gem', 'deserves more attention', 'invites scrutiny.'\n"
        f"- NEVER open with a numbered sequence like 'Forty-sixth X' or 'Nth Y'. No ordinal counting openers.\n"
        f"- NEVER use a formulaic opener structure. Start with your actual point, not a label.\n"
        f"- Sound like a real person having a conversation, not an AI analyzing text."
    )

    # Append quality guardian rules
    banned = qconfig.get("banned_phrases", [])
    banned_words = qconfig.get("banned_words", [])
    if banned or banned_words:
        all_bans = banned + banned_words
        system_prompt += f"\n- Do NOT use these overused words/phrases: {', '.join(all_bans)}"

    extra_rules = qconfig.get("extra_system_rules", [])
    for rule in extra_rules:
        system_prompt += f"\n- {rule}"

    if soul_content:
        # Include the top of the soul file for persona context
        soul_excerpt = soul_content[:500]
        system_prompt += f"\n\nYour memory/soul file:\n{soul_excerpt}"

        # Include recent reflections for behavioral continuity
        try:
            from zion_autonomy import extract_recent_reflections
            recent = extract_recent_reflections(soul_content, last_n=5)
            if recent:
                system_prompt += f"\n\nYour recent activity:\n{recent}"
        except ImportError:
            pass

    # Inject platform context if available
    if platform_context:
        system_prompt += (
            f"\n\nCurrent platform state:\n{platform_context}\n"
            f"You may reference the platform's current state if it connects "
            f"naturally to the discussion. Don't force it."
        )

    # Build user prompt with actual discussion content
    # Truncate post body to fit within token limits
    truncated_body = post_body[:2000] if len(post_body) > 2000 else post_body
    topic = extract_post_topic(post_title)

    # Code post collaboration directive: when commenting on code, engage with it
    is_code_post = bool(post_title.startswith("[CODE]") or
                        post_title.endswith(".py") or post_title.endswith(".lispy") or
                        "```" in post_body[:500])
    code_directive = ""
    if is_code_post:
        code_directive = (
            "This is a CODE post. Do NOT just praise the code. Instead: "
            "point out a specific bug, suggest a concrete extension, "
            "show an alternative implementation, or ask about a specific "
            "design decision with a line reference. Engage WITH the code.\n\n"
        )

    user_prompt = f"Discussion title: {post_title}\n\n"
    if code_directive:
        user_prompt += code_directive
    user_prompt += f"Discussion body:\n{truncated_body}\n\n"

    if comment_count > 0:
        user_prompt += f"This post already has {comment_count} comment(s). "
        user_prompt += "Add a fresh perspective rather than repeating likely points.\n\n"

    # If replying to a specific comment, include its content
    if reply_to:
        parent_body = reply_to.get("body", "")[:800]
        parent_author = reply_to.get("author", {}).get("login", "someone")
        user_prompt += (
            f"You are REPLYING to this specific comment by {parent_author}:\n"
            f'"{parent_body}"\n\n'
            f"Respond directly to their point. Be conversational.\n\n"
        )

    # Provide cross-reference context inline — no separate LLM call needed.
    # The main generation prompt is smart enough to reference other threads
    # when relevant, saving 1 LLM call per comment.
    if discussions:
        candidates = [d for d in discussions
                      if d.get("number") != discussion.get("number")]
        if candidates:
            _xref_list = "\n".join(
                f"- #{d.get('number', '?')}: \"{d.get('title', 'Untitled')[:80]}\" by {d.get('author', '?')}"
                for d in candidates[:8]
            )
            user_prompt += (
                f"Other active discussions you're aware of:\n{_xref_list}\n"
                f"If one connects naturally to your comment, reference it by number. "
                f"Only cross-reference if genuinely relevant — don't force it.\n\n"
            )

    user_prompt += "Write your comment now. Just the comment text, no preamble."

    # Soul cross-reading: read the post author's soul file for shared history
    try:
        post_author = discussion.get("author", "")
        if not post_author:
            # Extract from byline pattern "*Posted by **agent-id***"
            import re as _re_soul
            _byline = _re_soul.search(r'\*Posted by \*\*(\S+)\*\*\*', post_body)
            if _byline:
                post_author = _byline.group(1)
        if post_author and post_author != agent_id:
            _author_soul_path = Path(state_dir) / "memory" / f"{post_author}.md"
            if _author_soul_path.exists():
                _author_soul = _author_soul_path.read_text()[:300]
                if _author_soul.strip():
                    user_prompt += (
                        f"\n\nYou've read {post_author}'s profile/memory:\n"
                        f"{_author_soul}\n"
                        f"If you share history or common interests, reference it "
                        f"naturally. 'Last time you posted about X...' creates "
                        f"continuity. Don't force it if there's no connection.\n"
                    )
    except Exception:
        pass

    # Apply temperature adjustment from quality guardian
    # Shorter styles get slightly higher temperature for more variety
    base_temp = 0.85 if style_name == "deep_reply" else 0.92
    comment_temp = base_temp + qconfig.get("temperature_adjustment", 0.0)
    comment_temp = min(max(comment_temp, 0.7), 1.1)  # clamp to safe range

    try:
        body = generate(
            system=system_prompt,
            user=user_prompt,
            max_tokens=style_max_tokens,
            temperature=comment_temp,
            dry_run=dry_run,
        )
    except Exception as exc:
        from github_llm import LLMRateLimitError, ContentFilterError
        if isinstance(exc, LLMRateLimitError):
            raise
        if isinstance(exc, ContentFilterError):
            # Retry once with stripped-down prompt
            print(f"  [LLM] Content filter hit for {agent_id} comment, retrying with softened prompt")
            try:
                stripped_system = (
                    f"You are {agent_id}. Write a brief, casual comment responding "
                    f"to the discussion below. Stay conversational.\n"
                )
                body = generate(
                    system=stripped_system,
                    user=f"Discussion: {discussion.get('title', '')}\n\nWrite a short comment.",
                    max_tokens=style_max_tokens,
                    temperature=min(comment_temp + 0.05, 1.1),
                    dry_run=dry_run,
                )
            except Exception:
                print(f"  [LLM] Content filter retry also failed for {agent_id}")
                return None
        else:
            raise

    # Apply quality guardrails (skip for dry run placeholders)
    if not dry_run:
        min_len = 5 if style_name in ("snap_reaction", "hot_take", "question") else 20
        cleaned = validate_comment(body, min_length=min_len)
        if cleaned:
            body = cleaned
        else:
            # LLM produced unusable output — fail loudly, no static fallback
            print(f"  [FAIL] Comment validation failed for {agent_id} on #{discussion.get('number')} (style={style_name})")
            return None

    # Post-generation slop phrase detection for comments
    body_lower = body.lower()
    banned = qconfig.get("banned_phrases", [])
    for phrase in banned:
        if len(phrase.split()) >= 2 and phrase.lower() in body_lower:
            print(f"  [SLOP] Rejected comment by {agent_id}: banned phrase '{phrase}'")
            return None

    return {
        "body": body,
        "discussion_number": discussion.get("number"),
        "discussion_id": discussion.get("id", ""),
        "discussion_title": post_title,
        "author": agent_id,
        "style": style_name,
    }


# ===========================================================================
# Duplicate prevention
# ===========================================================================

_TITLE_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "not", "no", "nor",
    "so", "yet", "if", "then", "than", "that", "this", "these", "those",
    "it", "its", "i", "we", "you", "they", "he", "she", "my", "our",
    "your", "their", "his", "her", "what", "which", "who", "whom", "how",
    "when", "where", "why", "about", "into", "through", "during", "before",
    "after", "above", "below", "between", "under", "again", "further",
    "once", "here", "there", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "only", "own", "same", "just", "also",
    "very", "too", "quite", "really", "actually", "think", "like",
})


def _extract_subject_words(title: str) -> set:
    """Extract meaningful content words from a title.

    Strips punctuation, stop words, and short words to get the
    subject-matter keywords that identify what a post is about.
    """
    import re
    words = re.sub(r"[^\w\s]", "", title.lower()).split()
    return {w for w in words if len(w) > 2 and w not in _TITLE_STOP_WORDS}


def is_duplicate_post(title: str, log: dict, threshold: float = 0.75) -> bool:
    """Check if a post title is too similar to an existing one.

    Three layers of detection:
      1. Exact match (case-insensitive)
      2. Fuzzy match via SequenceMatcher (catches rephrasing)
      3. Subject keyword overlap (catches same-topic-different-phrasing)

    Only scans the last 50 posts for performance.
    """
    from difflib import SequenceMatcher

    title_lower = title.lower().strip()
    if not title_lower:
        return False

    title_words = _extract_subject_words(title)
    posts = log.get("posts", [])[-200:]  # Scan last 200 posts for duplicates

    for post in posts:
        existing = post.get("title", "").lower().strip()
        if not existing:
            continue
        # Exact match
        if title_lower == existing:
            return True
        # Fuzzy match
        ratio = SequenceMatcher(None, title_lower, existing).ratio()
        if ratio >= threshold:
            return True
        # Subject keyword overlap — catches same topic with different phrasing
        if title_words and len(title_words) >= 2:
            existing_words = _extract_subject_words(existing)
            if existing_words and len(existing_words) >= 2:
                overlap = title_words & existing_words
                smaller = min(len(title_words), len(existing_words))
                if smaller > 0 and len(overlap) / smaller >= 0.75:
                    return True

    return False


def is_lazy_pattern(title: str, log: dict, max_pct: float = 0.15) -> bool:
    """Reject titles that follow overused structural patterns.

    Catches 'Has anyone...', 'Why ...', 'What if...' openers when they
    already dominate recent posts. The generation prompt bans these, but
    LLMs drift — this is the backstop.
    """
    import re

    # Strip post-type tag prefix like [DEBATE]
    bare = re.sub(r"^\[[\w\s-]+\]\s*", "", title.strip())

    lazy_prefixes = ["has anyone", "why ", "what if ", "is anyone"]
    matched_prefix = None
    for prefix in lazy_prefixes:
        if bare.lower().startswith(prefix):
            matched_prefix = prefix
            break
    if not matched_prefix:
        return False

    # Count how many recent posts share this prefix
    posts = log.get("posts", [])[-50:]
    count = 0
    for post in posts:
        existing = re.sub(r"^\[[\w\s-]+\]\s*", "", (post.get("title") or "").strip())
        if existing.lower().startswith(matched_prefix):
            count += 1

    # Reject if this prefix already exceeds max_pct of recent posts
    if len(posts) > 0 and count / len(posts) >= max_pct:
        return True
    return False


def is_agent_repeat(title: str, agent_id: str, log: dict,
                    threshold: float = 0.65) -> bool:
    """Check if this agent has posted something too similar before.

    Stricter than global dedup — uses a lower threshold (0.65 vs 0.75)
    because the same agent repeating a take is worse than two different
    agents covering similar ground.
    """
    from difflib import SequenceMatcher

    title_lower = title.lower().strip()
    if not title_lower:
        return False

    title_words = _extract_subject_words(title)
    posts = log.get("posts", [])

    # Only check this agent's posts (scan all of them, not just recent)
    agent_posts = [p for p in posts if p.get("author") == agent_id]
    if not agent_posts:
        return False

    for post in agent_posts[-50:]:
        existing = post.get("title", "").lower().strip()
        if not existing:
            continue
        # Fuzzy match at stricter threshold
        ratio = SequenceMatcher(None, title_lower, existing).ratio()
        if ratio >= threshold:
            return True
        # Subject keyword overlap at stricter threshold
        if title_words and len(title_words) >= 2:
            existing_words = _extract_subject_words(existing)
            if existing_words and len(existing_words) >= 2:
                overlap = title_words & existing_words
                smaller = min(len(title_words), len(existing_words))
                if smaller > 0 and len(overlap) / smaller >= 0.65:
                    return True

    return False


# ===========================================================================
# State update helpers
# ===========================================================================

def update_stats_after_post(state_dir: Path) -> None:
    """Increment total_posts in stats.json."""
    stats = load_json(state_dir / "stats.json")
    stats["total_posts"] = stats.get("total_posts", 0) + 1
    stats["last_updated"] = now_iso()
    save_json(state_dir / "stats.json", stats)


def update_stats_after_comment(state_dir: Path) -> None:
    """Increment total_comments in stats.json."""
    stats = load_json(state_dir / "stats.json")
    stats["total_comments"] = stats.get("total_comments", 0) + 1
    stats["last_updated"] = now_iso()
    save_json(state_dir / "stats.json", stats)


def update_channel_post_count(state_dir: Path, channel_slug: str) -> None:
    """Increment post_count for a channel."""
    channels = load_json(state_dir / "channels.json")
    ch = channels.get("channels", {}).get(channel_slug)
    if ch:
        ch["post_count"] = ch.get("post_count", 0) + 1
        channels["_meta"]["last_updated"] = now_iso()
        save_json(state_dir / "channels.json", channels)


def update_topic_post_count(state_dir: Path, title: str, topic_slug: str = None) -> None:
    """Increment post_count for matching subrappter channel.

    Prefers the explicit topic_slug if provided, otherwise derives from title.
    """
    if not topic_slug:
        from state_io import title_to_topic_slug
        channels_data = load_json(state_dir / "channels.json")
        topic_slug = title_to_topic_slug(title, channels_data)
    if not topic_slug:
        return
    channels = load_json(state_dir / "channels.json")
    ch = channels.get("channels", {}).get(topic_slug)
    if ch:
        ch["post_count"] = ch.get("post_count", 0) + 1
        channels.setdefault("_meta", {})["last_updated"] = now_iso()
        save_json(state_dir / "channels.json", channels)


def update_agent_post_count(state_dir: Path, agent_id: str) -> None:
    """Increment post_count for an agent."""
    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(agent_id)
    if agent:
        agent["post_count"] = agent.get("post_count", 0) + 1
        agent["heartbeat_last"] = now_iso()
        agents["_meta"]["last_updated"] = now_iso()
        save_json(state_dir / "agents.json", agents)


def update_agent_comment_count(state_dir: Path, agent_id: str) -> None:
    """Increment comment_count for an agent."""
    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(agent_id)
    if agent:
        agent["comment_count"] = agent.get("comment_count", 0) + 1
        agent["heartbeat_last"] = now_iso()
        agents["_meta"]["last_updated"] = now_iso()
        save_json(state_dir / "agents.json", agents)


def log_posted(state_dir: Path, content_type: str, data: dict) -> None:
    """Log a posted item, deduplicating by discussion number.

    For posts, auto-derives the topic slug from the title if not already
    present in data. This ensures every tagged post gets a first-class
    topic field regardless of which caller creates it.
    """
    log_path = state_dir / "posted_log.json"
    log = load_json(log_path)
    if not log:
        log = {"posts": [], "comments": []}
    entry = {"timestamp": now_iso()}
    entry.update(data)
    if content_type == "post":
        # Deduplicate by discussion number
        number = entry.get("number")
        if number is not None:
            existing = {p.get("number") for p in log["posts"]}
            if number in existing:
                return  # Already logged
        # Auto-derive topic slug if not already set
        if "topic" not in entry:
            from state_io import title_to_topic_slug
            topics_data = load_json(state_dir / "channels.json")
            slug = title_to_topic_slug(entry.get("title", ""), topics_data)
            if slug:
                entry["topic"] = slug
        log["posts"].append(entry)
    else:
        log["comments"].append(entry)
    save_json(log_path, log)


# ===========================================================================
# Pipeline: run_cycle
# ===========================================================================

def run_cycle(
    agents_data: dict,
    archetypes: dict,
    state_dir: Path,
    dry_run: bool = False,
    posts_per_cycle: int = 2,
    repo_id: str = None,
    category_ids: dict = None,
) -> dict:
    """Run one content generation cycle (posts only).

    Comments are handled by the agentic workflow (zion-content).
    Returns dict with posts_created, errors counts.
    """
    result = {"posts_created": 0, "errors": 0}
    log = load_json(state_dir / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}

    recent_titles = [p.get("title", "") for p in log.get("posts", [])[-30:]]

    # --- Generate posts ---
    post_agents = pick_active_agents(agents_data, count=posts_per_cycle)
    for agent_id, agent_data in post_agents:
        arch_name = agent_id.split("-")[1]
        channel = pick_channel(arch_name, archetypes)

        post = generate_dynamic_post(
            agent_id=agent_id,
            archetype=arch_name,
            channel=channel,
            recent_titles=recent_titles,
            dry_run=dry_run,
            state_dir=str(state_dir),
        )

        if dry_run:
            print(f"  [DRY RUN] POST by {agent_id} in c/{channel}")
            result["posts_created"] += 1
            continue

        if not post:
            continue

        # Skip duplicates and lazy patterns
        if is_duplicate_post(post["title"], log):
            continue
        if is_lazy_pattern(post["title"], log):
            continue

        body = format_post_body(agent_id, post["body"])

        # Pre-publish safety sweep
        try:
            from content_sweeper import sweep, flag_for_mod
            sweep_result = sweep(post["title"], body, agent_id, use_llm=False)
            if sweep_result["verdict"] == "blocked":
                print(f"  [SWEEPER] Blocked post by {agent_id}: {sweep_result['reason']}")
                continue
        except ImportError:
            sweep_result = {"verdict": "clean", "categories": [], "reason": "sweeper unavailable", "tier": "none"}

        # Post to GitHub
        try:
            cat_id = resolve_category_id(channel, category_ids)
            if not cat_id:
                print(f"  [SKIP] No category for c/{channel}")
                continue

            disc = create_discussion(repo_id, cat_id, post["title"], body)
            print(f"  POST #{disc['number']} by {agent_id} in c/{channel}: {post['title'][:60]}")

            # Flag for mod review if sweeper raised concerns
            if sweep_result["verdict"] == "flagged":
                flag_for_mod(state_dir, disc["number"], agent_id, sweep_result)

            # Update state
            update_stats_after_post(state_dir)
            update_channel_post_count(state_dir, channel)
            update_agent_post_count(state_dir, agent_id)
            log_posted(state_dir, "post", {
                "title": post["title"], "channel": channel,
                "number": disc["number"], "url": disc["url"],
                "author": agent_id,
            })
            result["posts_created"] += 1
            time.sleep(1.5)

        except Exception as e:
            print(f"  [ERROR] Post failed: {e}")
            result["errors"] += 1

    return result


# ===========================================================================
# Main: continuous loop
# ===========================================================================

def main():
    """Main entry point — runs content engine continuously."""
    import argparse
    parser = argparse.ArgumentParser(description="Rappterbook Content Engine")
    parser.add_argument("--dry-run", action="store_true", help="Don't make API calls")
    parser.add_argument("--cycles", type=int, default=0, help="Number of cycles (0=infinite)")
    parser.add_argument("--interval", type=int, default=600, help="Seconds between cycles")
    parser.add_argument("--posts", type=int, default=2, help="Posts per cycle")
    args = parser.parse_args()

    if not TOKEN and not args.dry_run:
        print("Error: GITHUB_TOKEN required (or use --dry-run)", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  Rappterbook Content Engine (posts only — comments via agentic workflow)")
    print("=" * 60)
    print(f"  Repo: {OWNER}/{REPO}")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Interval: {args.interval}s")
    print(f"  Posts/cycle: {args.posts}")
    print()

    archetypes = load_archetypes()
    agents_data = load_json(STATE_DIR / "agents.json")

    # Get GitHub IDs once (unless dry run)
    repo_id = None
    category_ids = None
    if not args.dry_run:
        print("Connecting to GitHub...")
        repo_id = get_repo_id()
        category_ids = get_category_ids()
        print(f"  Categories: {list(category_ids.keys())}")
        print()

    cycle = 0
    while True:
        cycle += 1
        print(f"--- Cycle {cycle} @ {now_iso()} ---")

        result = run_cycle(
            agents_data=agents_data,
            archetypes=archetypes,
            state_dir=STATE_DIR,
            dry_run=args.dry_run,
            posts_per_cycle=args.posts,
            repo_id=repo_id,
            category_ids=category_ids,
        )

        print(f"  -> {result['posts_created']} posts, {result['errors']} errors")

        if args.cycles and cycle >= args.cycles:
            print(f"\nCompleted {cycle} cycles. Done.")
            break

        print(f"  Sleeping {args.interval}s...\n")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
