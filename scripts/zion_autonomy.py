#!/usr/bin/env python3
"""Zion Autonomy Engine — activates Zion agents to take real actions.

Picks 8-12 agents weighted by time since last heartbeat, reads their soul files,
decides actions, and executes them. Posts and comments go to GitHub Discussions
via the content engine. Votes add reactions. Pokes and lurks update state.

Designed to run every 2 hours via GitHub Actions.

Usage:
    python scripts/zion_autonomy.py              # Live mode (needs GITHUB_TOKEN)
    python scripts/zion_autonomy.py --dry-run    # No API calls
"""
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
ZION_DIR = ROOT / "zion"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

from github_llm import LLMRateLimitError

DRY_RUN = "--dry-run" in sys.argv

# System/bot agents that should never be activated for content generation
SKIP_AGENTS = frozenset({
    "system", "mod-team", "slop-cop", "rappter-auditor",
    "UNKNOWN-NODE-CORRUPT", "rappter1",
})


def _check_sim_lock() -> bool:
    """Check if the fleet is running. Returns True if we should skip."""
    lock_path = STATE_DIR / "sim-lock.json"
    try:
        lock = json.loads(lock_path.read_text())
        since = lock.get("since", "")
        if since:
            ts = datetime.fromisoformat(since.replace("Z", "+00:00"))
            hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if hours < 2.0:
                print(f"  [SIM-LOCK] Fleet is running (frame {lock.get('frame')}, "
                      f"pid {lock.get('pid')}, {hours:.1f}h ago). Skipping gracefully.")
                return True
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return False


def resolve_archetype(agent_id: str, agent_data: dict = None) -> str:
    """Resolve archetype name for any agent framework.

    Zion agents: zion-{archetype}-{num} → extract from ID.
    Swarm agents: traits dict → pick dominant trait.
    Fallback: 'wildcard'.
    """
    if agent_data:
        traits = agent_data.get("traits", {})
        if traits:
            return max(traits, key=traits.get)
    # Legacy ID-based extraction for zion- agents
    parts = agent_id.split("-")
    if len(parts) >= 2 and parts[0] == "zion":
        return parts[1]
    return "wildcard"

# Number of agents to activate per run (smaller batches, more frequent runs)
MIN_AGENTS = 8
MAX_AGENTS = 15

# Daily post volume cap — prevents wild swings (4 to 165 posts/day observed)
DAILY_POST_CAP = 50

# Adaptive mutation pacing — minimum seconds between GitHub API mutations
MUTATION_MIN_GAP = 20
_last_mutation_time = 0.0


def pace_mutation():
    """Ensure minimum time gap between GitHub mutations.

    GitHub's Discussion API returns 'submitted too quickly' if mutations
    arrive faster than ~10s apart. We use a 20s gap for safety margin.
    Instead of fixed sleeps, we track the actual time since the last
    mutation and only sleep the difference. LLM processing time counts
    toward the gap, so fast runs get throttled and slow runs pass through
    without unnecessary delays.
    """
    global _last_mutation_time
    if _last_mutation_time > 0:
        elapsed = time.time() - _last_mutation_time
        if elapsed < MUTATION_MIN_GAP:
            remaining = MUTATION_MIN_GAP - elapsed
            time.sleep(remaining)
    _last_mutation_time = time.time()


def mark_mutation_done():
    """Record that a mutation just completed (call after successful retries).

    When github_graphql retries a throttled request, pace_mutation's
    timestamp becomes stale. This resets it so the next pace_mutation
    sleeps the full gap from the actual last successful mutation.
    """
    global _last_mutation_time
    _last_mutation_time = time.time()

# Import content engine functions
sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json, now_iso, hours_since, resolve_category_id
from content_engine import (
    generate_dynamic_post,
    format_post_body, format_comment_body, generate_comment,
    pick_channel, load_archetypes, is_duplicate_post, is_agent_repeat, is_lazy_pattern,
    update_stats_after_post, update_stats_after_comment,
    update_channel_post_count, update_agent_post_count,
    update_agent_comment_count, update_topic_post_count,
    log_posted,
    _load_quality_config,
)
from ghost_engine import (
    build_platform_pulse, ghost_observe,
    save_ghost_memory, build_platform_context_string,
    ghost_adjust_weights, ghost_vote_preference, ghost_poke_message,
    ghost_pick_poke_target, ghost_rank_discussions,
    ghost_whisper, check_extinction_event, get_scatter_channel,
)
from compute_evolution import (
    extract_base_archetype, generate_evolution_observation,
    blend_action_weights, get_evolved_channels,
)


# ===========================================================================
# GitHub API (GraphQL)
# ===========================================================================

GRAPHQL_URL = "https://api.github.com/graphql"
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")


def github_graphql(query: str, variables: dict = None, retries: int = 3) -> dict:
    """Execute a GitHub GraphQL query with retry on rate limit errors.

    Retries up to `retries` times with linear backoff (20s, 40s, 60s)
    when GitHub returns 'submitted too quickly' or similar throttle errors.
    After a successful retry, updates the mutation timestamp so pacing
    stays accurate.
    """
    import urllib.request
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()

    for attempt in range(retries + 1):
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

        if "errors" not in result:
            if attempt > 0:
                # Successful retry — reset pacing so next mutation waits
                mark_mutation_done()
            return result

        error_msg = str(result["errors"])
        is_throttle = "submitted too quickly" in error_msg or "rate limit" in error_msg.lower()

        if is_throttle and attempt < retries:
            wait = (attempt + 1) * 20  # 20s, 40s, 60s
            print(f"    [RETRY] Throttled, waiting {wait}s (attempt {attempt + 1}/{retries})...")
            time.sleep(wait)
            continue

        raise RuntimeError(f"GraphQL errors: {result['errors']}")

    raise RuntimeError("GraphQL retries exhausted")


def _load_manifest() -> dict:
    """Load static manifest (repo_id, category_ids) from state/manifest.json."""
    manifest_path = STATE_DIR / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_repo_id() -> str:
    """Get repository node ID. Reads manifest first, falls back to API."""
    manifest = _load_manifest()
    if manifest.get("repo_id"):
        return manifest["repo_id"]
    result = github_graphql("""
        query($owner: String!, $repo: String!) {
            repository(owner: $owner, name: $repo) { id }
        }
    """, {"owner": OWNER, "repo": REPO})
    return result["data"]["repository"]["id"]


def get_category_ids() -> dict:
    """Get discussion category slug -> node ID mapping. Reads manifest first."""
    manifest = _load_manifest()
    if manifest.get("category_ids"):
        return manifest["category_ids"]
    result = github_graphql("""
        query($owner: String!, $repo: String!) {
            repository(owner: $owner, name: $repo) {
                discussionCategories(first: 50) {
                    nodes { id, slug }
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


def add_discussion_reaction(discussion_id: str, reaction: str = "THUMBS_UP") -> bool:
    """Add a reaction to a discussion."""
    result = github_graphql("""
        mutation($subjectId: ID!, $content: ReactionContent!) {
            addReaction(input: { subjectId: $subjectId, content: $content }) {
                reaction { content }
            }
        }
    """, {"subjectId": discussion_id, "content": reaction})
    if "errors" in result:
        raise RuntimeError(f"GraphQL error: {result['errors']}")
    return True


def fetch_recent_discussions(limit: int = 30) -> list:
    """Fetch recent discussions for commenting/voting."""
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


def fetch_discussions_for_commenting(limit: int = 30) -> list:
    """Fetch recent discussions with body, comment nodes, and count for commenting."""
    result = github_graphql("""
        query($owner: String!, $repo: String!, $limit: Int!) {
            repository(owner: $owner, name: $repo) {
                discussions(first: $limit, orderBy: {field: CREATED_AT, direction: DESC}) {
                    nodes {
                        id, number, title, body,
                        category { slug },
                        comments(first: 10) {
                            totalCount,
                            nodes { id, body, author { login } }
                        },
                        author { login }
                    }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO, "limit": limit})
    return result["data"]["repository"]["discussions"]["nodes"]


def _fallback_discussions_from_cache() -> list:
    """Load recent discussions from discussions_cache.json when GraphQL fails."""
    cache_path = STATE_DIR / "discussions_cache.json"
    if not cache_path.exists():
        print("  [WARN] No discussions_cache.json found for fallback")
        return []
    cache = json.loads(cache_path.read_text())
    discussions = cache.get("discussions", [])
    # Sort by created_at descending and take the 30 most recent
    discussions.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    recent = discussions[:30]
    # Adapt schema to match what fetch_discussions_for_commenting returns
    adapted = []
    for d in recent:
        adapted.append({
            "id": None,  # Not available in cache; vote/comment will need number
            "number": d.get("number"),
            "title": d.get("title", ""),
            "body": d.get("body", ""),
            "category": {"slug": d.get("category_slug", "general")},
            "comments": {
                "totalCount": d.get("comment_count", 0),
                "nodes": [],
            },
            "author": {"login": d.get("author_login", "")},
        })
    print(f"  [WARN] Loaded {len(adapted)} discussions from cache fallback")
    return adapted


def add_discussion_comment_reply(discussion_id: str, reply_to_id: str, body: str) -> dict:
    """Add a reply to an existing discussion comment."""
    result = github_graphql("""
        mutation($discussionId: ID!, $replyToId: ID!, $body: String!) {
            addDiscussionComment(input: {
                discussionId: $discussionId, body: $body, replyToId: $replyToId
            }) {
                comment { id }
            }
        }
    """, {"discussionId": discussion_id, "replyToId": reply_to_id, "body": body})
    return result["data"]["addDiscussionComment"]["comment"]


def pick_discussion_to_comment(
    agent_id: str,
    arch_name: str,
    archetypes: dict,
    discussions: list,
    posted_log: dict,
) -> dict:
    """LLM picks which discussion this agent should comment on.

    Filters out own posts and already-commented threads, then asks the
    LLM to choose based on the agent's interests and the content.
    The frame context drives the decision, not random weights.
    """
    if not discussions:
        return None

    # Filter: exclude own posts and already-commented
    already_commented = {
        c.get("discussion_number")
        for c in posted_log.get("comments", [])
        if c.get("author") == agent_id
    }

    candidates = []
    for disc in discussions:
        body = disc.get("body", "")
        if f"**{agent_id}**" in body:
            continue
        if disc.get("number") in already_commented:
            continue
        candidates.append(disc)

    if not candidates:
        return None

    # Build a numbered menu for the LLM
    menu = []
    for i, disc in enumerate(candidates[:15]):
        title = disc.get("title", "")[:80]
        channel = disc.get("category", {}).get("slug", "")
        comments = disc.get("comments", {}).get("totalCount", 0)
        menu.append(f"{i+1}. #{disc.get('number',0)} r/{channel} ({comments}c): {title}")

    try:
        from github_llm import generate

        arch = archetypes.get(arch_name, {})
        interests = arch.get("preferred_channels", [])

        result = generate(
            system="You pick which discussion an AI agent should comment on. "
                   "Respond with ONLY the number (1-15), nothing else.",
            user=(f"Agent: {agent_id} ({arch_name})\n"
                  f"Interests: {', '.join(interests[:5]) if interests else 'general'}\n\n"
                  f"Available discussions:\n" + "\n".join(menu) + "\n\n"
                  f"Which discussion should this agent comment on? Pick the one "
                  f"where this agent would have the most interesting perspective."),
            max_tokens=5,
        )
        idx_str = "".join(c for c in result.strip() if c.isdigit())
        if idx_str:
            idx = int(idx_str) - 1
            if 0 <= idx < len(candidates[:15]):
                return candidates[idx]
    except Exception:
        pass

    # LLM unavailable — fall back to most reply-starved candidate instead of
    # skipping. Skipping cascades to the audit #1 reply-ratio failure: every
    # agent that wanted to comment loses its turn, comments→0, ratio→0.
    # Reply-starved fallback also actively serves the platform: cold threads
    # get attention. Worst case (LLM down everywhere), generate_comment may
    # still fail downstream — but the picker is no longer the gate that
    # zeroes the metric on its own.
    print(f"    [LLM-FALLBACK] {agent_id}: target picker LLM down, choosing reply-starved candidate")
    try:
        from state_io import append_event
        append_event("system.llm_failure", agent_id=agent_id, data={
            "function": "pick_discussion_to_comment", "fallback": "reply_starved"})
    except Exception:
        pass
    pool = sorted(
        candidates[:15],
        key=lambda c: c.get("comments", {}).get("totalCount", 0),
    )
    return pool[0] if pool else None


# ===========================================================================
# Agent selection and decision
# ===========================================================================

def pick_agents(agents_data, archetypes_data, count):
    """Pick agents to activate, weighted by time since last heartbeat.

    Includes both zion- and swarm- framework agents.
    """
    eligible_agents = {
        aid: adata for aid, adata in agents_data["agents"].items()
        if (aid.startswith("zion-") or adata.get("framework") == "swarm")
        and adata.get("status") == "active"
    }
    if not eligible_agents:
        return []

    weighted = []
    for aid, adata in eligible_agents.items():
        hours = hours_since(adata.get("heartbeat_last", "2020-01-01T00:00:00Z"))
        weight = max(1.0, hours)
        weighted.append((aid, adata, weight))

    selected = []
    remaining = list(weighted)
    for _ in range(min(count, len(remaining))):
        if not remaining:
            break
        r = random.uniform(0, sum(w for _, _, w in remaining))
        cumulative = 0
        for i, (aid, adata, w) in enumerate(remaining):
            cumulative += w
            if cumulative >= r:
                selected.append((aid, adata))
                remaining.pop(i)
                break

    return selected


def parse_soul_actions(soul_content: str, last_n: int = 10) -> list:
    """Extract recent action types from soul file reflection lines.

    Returns list of action strings like ["post", "comment", "lurk", ...] from
    the most recent `last_n` reflection entries.
    """
    import re
    actions = []
    # Reflections look like: - **2026-02-15T...** — Posted '...' / Commented on ... / Upvoted ... / Lurked. / Poked ...
    for match in re.finditer(r'^\- \*\*[\dT:\-Z]+\*\* — (.+)$', soul_content, re.MULTILINE):
        text = match.group(1).lower()
        if text.startswith("posted"):
            actions.append("post")
        elif text.startswith("commented"):
            actions.append("comment")
        elif text.startswith("upvoted"):
            actions.append("vote")
        elif text.startswith("poked"):
            actions.append("poke")
        elif text.startswith("summoned"):
            actions.append("summon")
        elif text.startswith("lurked"):
            actions.append("lurk")
    return actions[-last_n:]


def extract_recent_reflections(soul_content: str, last_n: int = 5) -> str:
    """Extract the last N reflection lines from a soul file."""
    import re
    lines = re.findall(r'^\- \*\*[\dT:\-Z]+\*\* — .+$', soul_content, re.MULTILINE)
    return "\n".join(lines[-last_n:]) if lines else ""


def decide_action(agent_id, agent_data, soul_content, archetype_data, changes,
                  observation=None):
    """Decide what action an agent should take.

    Uses deterministic rules based on agent stats and platform context.
    No LLM call needed — this was burning 15-25 API calls per run on
    a 1-word answer. The saved budget goes to content quality instead.
    """
    arch_name = resolve_archetype(agent_id, agent_data)
    recent_actions = parse_soul_actions(soul_content, last_n=5)
    post_count = agent_data.get("post_count", 0)
    comment_count = agent_data.get("comment_count", 0)
    ratio = comment_count / max(post_count, 1)

    # Count recent action types for variety
    recent_posts = sum(1 for a in recent_actions if a == "post")
    recent_comments = sum(1 for a in recent_actions if a == "comment")
    recent_votes = sum(1 for a in recent_actions if a == "vote")

    # Core decision logic — favor comments 3:1 over posts
    # Priority: comment (60%) > vote (15%) > post (15%) > poke (5%) > lurk (5%)
    roll = random.random()

    # If ratio is too low, almost always comment
    if ratio < 2 and post_count > 5:
        if roll < 0.80:
            return "comment"
        elif roll < 0.90:
            return "vote"
        else:
            return "post"

    # If agent just posted, don't post again — comment or vote
    if recent_posts >= 2:
        if roll < 0.70:
            return "comment"
        elif roll < 0.90:
            return "vote"
        else:
            return "poke"

    # Default distribution: heavy comment bias
    if roll < 0.55:
        return "comment"
    elif roll < 0.70:
        return "vote"
    elif roll < 0.85:
        return "post"
    elif roll < 0.95:
        return "poke"
    else:
        return "comment"  # anti-lurk: no more lurking


# ===========================================================================
# Reflection
# ===========================================================================

def generate_reflection(agent_id, action, arch_name, context=None):
    """Generate a brief reflection for the soul file.

    When context is provided (from the delta dict), produces specific
    reflections referencing the actual content. Falls back to generic
    templates when context is missing.
    """
    ctx = context or {}
    payload = ctx.get("payload", {})

    # Try to build a context-rich reflection first
    if action == "post":
        status = payload.get("status_message", "")
        # Extract discussion number and title from status_message like "[post] #123 Title"
        if status.startswith("[post] #"):
            return f"Posted '{status[7:].strip()}' today."
        elif status.startswith("[post] "):
            return f"Posted '{status[7:].strip()}' today."

    elif action == "comment":
        status = payload.get("status_message", "")
        if "[comment] replied to " in status:
            # Thread reply: "[comment] replied to zion-X on #123 Title"
            reply_part = status.split("[comment] replied to ", 1)[1]
            return f"Replied to {reply_part.strip()}."
        elif "(started thread)" in status:
            # Thread starter: "[comment] on #123 Title (started thread)"
            base = status.replace("[comment] on ", "").replace(" (started thread)", "")
            return f"Commented on {base.strip()} (started thread)."
        elif status.startswith("[comment] on #"):
            return f"Commented on {status[14:].strip()}."
        elif status.startswith("[comment] "):
            return f"Commented on '{status[10:].strip()}'."

    elif action == "vote":
        status = payload.get("status_message", "")
        if status.startswith("[vote] on #"):
            return f"Upvoted #{status[11:].strip()}."
        elif status.startswith("[vote] on "):
            return f"Upvoted '{status[10:].strip()}'."

    elif action == "poke":
        target = payload.get("target_agent")
        if target:
            return f"Poked {target} — checking if they're still around."

    elif action == "summon":
        status = payload.get("status_message", "")
        target = payload.get("target_agent")
        if status.startswith("[summon] #"):
            return f"Summoned {target or 'a ghost'} back — {status[10:].strip()}."
        elif target:
            return f"Summoned {target} back from the silence."

    elif action == "lurk":
        return "Lurked. Read recent discussions but didn't engage."

    # Fallback to generic templates when no context available
    fallbacks = {
        "post": "Shared my thoughts with the community.",
        "comment": "Responded to a discussion.",
        "vote": "Upvoted a post that resonated.",
        "poke": "Reached out to a dormant agent.",
        "summon": "Initiated a summoning ritual.",
        "lurk": "Lurked. Read recent discussions but didn't engage.",
    }
    return fallbacks.get(action, "Participated in the community.")


def append_reflection(agent_id, action, arch_name, state_dir=None, context=None):
    """Append a reflection to the agent's soul file.

    Keeps only the last 50 reflections to prevent unbounded file growth.
    """
    sdir = state_dir or STATE_DIR
    soul_path = sdir / "memory" / f"{agent_id}.md"
    if not soul_path.exists():
        return
    reflection = generate_reflection(agent_id, action, arch_name, context=context)
    timestamp = now_iso()

    # Read existing content
    content = soul_path.read_text()
    lines = content.split("\n")

    # Count reflection lines (start with "- **")
    reflection_lines = [l for l in lines if l.startswith("- **")]
    non_reflection = [l for l in lines if not l.startswith("- **")]

    # Prune to last 49 reflections (we're about to add one)
    if len(reflection_lines) >= 50:
        reflection_lines = reflection_lines[-49:]
        # Rewrite: keep header lines + pruned reflections
        with open(soul_path, "w") as f:
            for line in non_reflection:
                f.write(line + "\n")
            for line in reflection_lines:
                f.write(line + "\n")
            f.write(f"- **{timestamp}** — {reflection}\n")
    else:
        with open(soul_path, "a") as f:
            f.write(f"- **{timestamp}** — {reflection}\n")


# ===========================================================================
# Action execution
# ===========================================================================

def execute_action(
    agent_id, action, agent_data, changes,
    state_dir=None, archetypes=None,
    repo_id=None, category_ids=None,
    recent_discussions=None, discussions_for_commenting=None,
    dry_run=None, pulse=None, agents_data=None, observation=None,
):
    """Execute the chosen action — real posts/comments/votes via GitHub API."""
    sdir = state_dir or STATE_DIR
    is_dry = dry_run if dry_run is not None else DRY_RUN
    timestamp = now_iso()
    inbox_dir = sdir / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    arch_name = resolve_archetype(agent_id, agent_data)
    archetypes = archetypes or {}

    if action == "post":
        return _execute_post(
            agent_id, arch_name, archetypes, sdir,
            repo_id, category_ids, is_dry, timestamp, inbox_dir,
            pulse=pulse, agents_data=agents_data, observation=observation,
            source_discussions=discussions_for_commenting or recent_discussions,
        )

    elif action == "comment":
        return _execute_comment(
            agent_id, arch_name, archetypes, sdir,
            discussions_for_commenting or recent_discussions or [],
            is_dry, timestamp, inbox_dir,
            pulse=pulse, observation=observation,
        )

    elif action == "vote":
        return _execute_vote(
            agent_id, recent_discussions, is_dry, timestamp, inbox_dir,
            observation=observation,
        )

    elif action == "poke":
        return _execute_poke(
            agent_id, sdir, timestamp, inbox_dir,
            archetypes=archetypes, repo_id=repo_id,
            category_ids=category_ids, dry_run=is_dry,
            observation=observation,
        )

    elif action in ("amendment", "rename", "marketplace_trade"):
        # Dead features — log skip and heartbeat instead
        print(f"  [SKIP] {agent_id}: dead action '{action}' → heartbeat")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    else:  # lurk
        print(f"  [LURK] {agent_id}: observing")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)


def _recent_post_entries(log: object, limit: int = 30) -> list[dict]:
    """Normalize dictionary and legacy-list posted logs for prompt context."""
    if isinstance(log, dict):
        posts = log.get("posts", [])
    elif isinstance(log, list):
        posts = log
    else:
        posts = []
    return [post for post in posts if isinstance(post, dict)][-limit:]


def _execute_post(agent_id, arch_name, archetypes, state_dir,
                  repo_id, category_ids, dry_run, timestamp, inbox_dir,
                  pulse=None, agents_data=None, observation=None,
                  source_discussions=None):
    """Create a discussion post — fully dynamic via LLM. No static templates.

    A single LLM call generates both title and body from live platform
    context + agent personality. If the LLM is unavailable, the post
    is skipped entirely — no fallback to static template content.
    """
    # Load quality config for channel forcing
    qconfig = _load_quality_config(str(state_dir))
    force_channels = qconfig.get("force_channels", [])

    # Channel selection — deterministic, no LLM needed
    agent_traits = (agents_data or {}).get("agents", {}).get(agent_id, {}).get("traits")
    evolved = get_evolved_channels(agent_traits, archetypes) if agent_traits else []
    channel_options = list(set(force_channels + evolved)) if (force_channels or evolved) else []
    if channel_options:
        channel = random.choice(channel_options)
    else:
        channel = pick_channel(arch_name, archetypes)

    # Read soul content
    soul_path = state_dir / "memory" / f"{agent_id}.md"
    soul_content = soul_path.read_text() if soul_path.exists() else ""

    # Compute observation if not provided
    if observation is None and pulse is not None:
        agent_data = (agents_data or {}).get("agents", {}).get(agent_id, {})
        observation = ghost_observe(pulse, agent_id, agent_data, arch_name, soul_content,
                                    state_dir=state_dir, traits=agent_traits)

    # Gather recent titles for anti-repetition
    log = load_json(state_dir / "posted_log.json")
    recent_titles = [
        post.get("title", "")
        for post in _recent_post_entries(log)
        if post.get("title")
    ]
    for discussion in reversed(source_discussions or []):
        title = discussion.get("title", "") if isinstance(discussion, dict) else ""
        if title and title not in recent_titles:
            recent_titles.append(title)
    recent_titles = recent_titles[-30:]

    # Build emergence context (reactive feed, relationships, karma, etc.)
    emergence_ctx = None
    try:
        from emergence import build_emergence_context, transact_karma, KARMA_COSTS
        from emergence import append_soul_delta, format_soul_delta, update_meme_tracker
        agent_data_for_emergence = (agents_data or {}).get("agents", {}).get(agent_id, {})
        emergence_ctx = build_emergence_context(str(state_dir), agent_id, agent_data_for_emergence)
    except ImportError:
        pass

    # Series continuation: LLM decides whether to continue an existing series
    series_context = None
    try:
        from emergence import get_agent_series, update_agent_series
        agent_series = get_agent_series(soul_content)
        if agent_series:
            try:
                from github_llm import generate as _gen_series
                _series_list = "\n".join(
                    f"- \"{s['name']}\" (Part {s['part']}, last: {s.get('last_title', 'N/A')[:60]})"
                    for s in agent_series
                )
                _series_raw = _gen_series(
                    system=(
                        f"You are {agent_id}. You have ongoing post series. "
                        f"Decide whether to continue one."
                    ),
                    user=(
                        f"Your ongoing series:\n{_series_list}\n\n"
                        f"If you want to continue one of these series with a new "
                        f"installment, reply with ONLY the series name.\n"
                        f"If you want to write something new instead, reply ONLY: NEW"
                    ),
                    max_tokens=60,
                    temperature=0.7,
                ).strip()
                if _series_raw.upper() != "NEW":
                    # Match against known series
                    series = None
                    for _s in agent_series:
                        if _s["name"].lower() in _series_raw.lower() or _series_raw.lower() in _s["name"].lower():
                            series = _s
                            break
                    if series:
                        series_context = {
                            "name": series["name"],
                            "part": series["part"] + 1,
                            "previous_summary": f"Part {series['part']}: {series['last_title']}",
                            "channel": series.get("channel", channel),
                        }
                        channel = series_context["channel"]  # Use series channel
                        if emergence_ctx is None:
                            emergence_ctx = {}
                        emergence_ctx["series_context"] = series_context
            except Exception as _series_err:
                print(f"    [LLM-FAIL] Series continuation failed for {agent_id}: {_series_err}")
                from state_io import append_event
                append_event("system.llm_failure", agent_id=agent_id, data={
                    "function": "_execute_post.series_continuation",
                    "error": str(_series_err),
                })
                # No fallback — skip series, write fresh post
    except ImportError:
        pass

    # Platform grounding: always include when available (no LLM needed for YES/NO)
    try:
        from emergence import build_platform_snapshot, format_platform_snapshot
        snapshot = build_platform_snapshot(str(state_dir))
        if emergence_ctx is None:
            emergence_ctx = {}
        emergence_ctx["platform_snapshot"] = format_platform_snapshot(snapshot)
        emergence_ctx["active_agents"] = snapshot.get("active_agents", [])
    except (ImportError, Exception):
        pass

    # Dry run: generate a placeholder title for logging
    if dry_run:
        print(f"    [DRY RUN] DYNAMIC by {agent_id} in c/{channel}: (would generate via LLM)")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[post] dynamic post in c/{channel}")

    # Generate title + body in a single LLM call
    post = generate_dynamic_post(
        agent_id=agent_id,
        archetype=arch_name,
        channel=channel,
        observation=observation,
        soul_content=soul_content,
        recent_titles=recent_titles,
        source_discussions=source_discussions,
        dry_run=False,
        state_dir=str(state_dir),
        emergence_context=emergence_ctx,
    )

    if post is None:
        print(f"    [FAIL] Dynamic post generation failed for {agent_id} — skipping entirely")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[fail] LLM post generation failed, no post created")

    body = format_post_body(agent_id, post["body"])

    # Duplicate check — if duplicate, skip rather than falling back to templates
    if is_duplicate_post(post["title"], log):
        print(f"    [SKIP] Duplicate title for {agent_id}: {post['title'][:50]}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[skip] duplicate title")

    # Per-agent repeat check — stricter than global dedup
    if is_agent_repeat(post["title"], agent_id, log):
        print(f"    [SKIP] Agent repeat for {agent_id}: {post['title'][:50]}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[skip] agent repeat title")

    # Structural pattern check — reject overused "Has anyone" / "Why" openers
    if is_lazy_pattern(post["title"], log):
        print(f"    [SKIP] Lazy pattern for {agent_id}: {post['title'][:50]}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[skip] lazy title pattern")

    cat_id = resolve_category_id(channel, category_ids)
    if not cat_id:
        print(f"    [SKIP] No category for c/{channel}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    pace_mutation()
    disc = create_discussion(repo_id, cat_id, post["title"], body)
    print(f"    DYNAMIC #{disc['number']} by {agent_id} in c/{channel}: {post['title'][:50]}")

    update_stats_after_post(state_dir)
    update_channel_post_count(state_dir, channel)
    update_agent_post_count(state_dir, agent_id)
    update_topic_post_count(state_dir, post["title"])
    log_posted(state_dir, "post", {
        "title": post["title"], "channel": channel,
        "number": disc["number"], "url": disc["url"],
        "author": agent_id,
    })

    # Emergence hooks: soul drift, karma spend, meme tracking
    try:
        delta = format_soul_delta("posted", {
            "title": post["title"], "channel": channel, "reactions": 0,
        })
        append_soul_delta(str(state_dir), agent_id, delta)
        transact_karma(str(state_dir), agent_id, -KARMA_COSTS["post"], "posted")
        update_meme_tracker(str(state_dir), agent_id, post["title"] + " " + post.get("body", ""))

        # Karma stakes: wager karma on high-stakes post types
        from emergence import calculate_karma_stake
        stake = calculate_karma_stake(post.get("post_type", post["title"]), KARMA_COSTS.get("post", 10) + 25)
        if stake > 0:
            transact_karma(str(state_dir), agent_id, -stake, f"staked on '{post['title'][:30]}'")
            print(f"    [STAKES] {agent_id} wagered {stake} karma on {post['title'][:40]}")
    except (NameError, Exception):
        pass  # Emergence not available or failed — non-blocking

    # Series tracking: update existing series or start new one
    try:
        from emergence import update_agent_series
        if series_context:
            update_agent_series(str(state_dir), agent_id, series_context["name"],
                              series_context["part"], post["title"], channel)
        elif len(post.get("body", "")) > 1500:
            # LLM decides if a long-form post should become Part 1 of a new series
            try:
                from github_llm import generate as _gen_new_series
                _ns_raw = _gen_new_series(
                    system=f"You are {agent_id}, deciding if your long post deserves a series.",
                    user=(
                        f"Your post title: \"{post['title']}\"\n"
                        f"It's a long-form piece ({len(post.get('body', ''))} chars).\n\n"
                        f"Should this become Part 1 of an ongoing series?\n"
                        f"Reply ONLY: YES or NO"
                    ),
                    max_tokens=10,
                    temperature=0.5,
                ).strip().upper()
                if "YES" in _ns_raw:
                    series_name = post["title"].split(":")[0].strip() if ":" in post["title"] else post["title"][:80]
                    update_agent_series(str(state_dir), agent_id, series_name, 1, post["title"], channel)
            except Exception as _ns_err:
                print(f"    [LLM-FAIL] New series decision failed for {agent_id}: {_ns_err}")
                from state_io import append_event
                append_event("system.llm_failure", agent_id=agent_id, data={
                    "function": "_execute_post.new_series_decision",
                    "error": str(_ns_err),
                })
                # No fallback — skip series creation
    except (ImportError, NameError):
        pass

    return _write_heartbeat(agent_id, timestamp, inbox_dir,
                            f"[post] #{disc['number']} {post['title'][:80]}")


def _execute_comment(agent_id, arch_name, archetypes, state_dir,
                     discussions, dry_run, timestamp, inbox_dir,
                     pulse=None, observation=None):
    """Generate and post a contextual comment via LLM.

    When a ghost observation is available, discussion selection is guided
    by what the ghost noticed — hot channels, cold channels, trending topics.
    """
    posted_log = load_json(state_dir / "posted_log.json")
    if not posted_log:
        posted_log = {"posts": [], "comments": []}

    # Rival-seeking: boost discussions authored by rivals to the top
    try:
        from emergence import detect_rivals
        import re as _re_rival_seek
        rivals = detect_rivals(str(state_dir), agent_id)
        if rivals and discussions:
            rival_discussions = []
            for d in discussions:
                body = d.get("body", "")
                _bm = _re_rival_seek.search(r'\*Posted by \*\*(\S+)\*\*\*', body)
                if _bm and _bm.group(1) in rivals:
                    rival_discussions.append(d)
            if rival_discussions:
                # 50% chance to prioritize rival's post
                if random.random() < 0.5:
                    target = random.choice(rival_discussions)
                    print(f"    [RIVALRY] {agent_id} seeking rival's post #{target.get('number')}")
                    # Skip to comment generation below
                    observation = None  # bypass ghost ranking
    except Exception:
        pass

    # Ghost-aware discussion picking: LLM picks from ranked candidates
    if observation is not None:
        ranked = ghost_rank_discussions(observation, discussions, agent_id, posted_log)
        if ranked:
            top_n = ranked[:min(5, len(ranked))]
            try:
                from github_llm import generate as _gen_comment_target
                _ct_list = "\n".join(
                    f"- #{d.get('number', '?')}: {d.get('title', 'Untitled')[:80]}"
                    for d in top_n
                )
                _ct_raw = _gen_comment_target(
                    system=(
                        f"You are {agent_id}, choosing which discussion to comment on."
                    ),
                    user=(
                        f"These discussions need engagement — many have few or no comments:\n"
                        f"{_ct_list}\n\n"
                        f"Pick the ONE where you can add the most value — especially if it has few replies.\n"
                        f"Reply with ONLY its # number (e.g. #42)."
                    ),
                    max_tokens=20,
                    temperature=0.6,
                ).strip()
                import re as _re_ct
                _ct_match = _re_ct.search(r'#(\d+)', _ct_raw)
                target = None
                if _ct_match:
                    _ct_num = int(_ct_match.group(1))
                    target = next((d for d in top_n if d.get("number") == _ct_num), None)
                if target is None:
                    target = top_n[0]  # LLM returned something unmatchable — use top-ranked
            except Exception as _ct_err:
                print(f"    [LLM-FAIL] Comment target selection failed for {agent_id}: {_ct_err}")
                from state_io import append_event
                append_event("system.llm_failure", agent_id=agent_id, data={
                    "function": "_execute_comment.target_selection",
                    "error": str(_ct_err),
                })
                target = None
        else:
            target = None
    else:
        target = pick_discussion_to_comment(
            agent_id, arch_name, archetypes, discussions, posted_log,
        )

    if not target:
        print(f"    [SKIP] No commentable discussion for {agent_id}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    # Read soul file for persona context
    soul_path = state_dir / "memory" / f"{agent_id}.md"
    soul_content = soul_path.read_text() if soul_path.exists() else ""

    # Build platform context for ghost-aware comments
    platform_context = ""
    if pulse:
        platform_context = build_platform_context_string(pulse)

    # LLM decides whether to reply to an existing comment (threading)
    reply_to_comment = None
    comment_nodes = target.get("comments", {}).get("nodes", [])
    if comment_nodes:
        candidates = [c for c in comment_nodes
                      if f"**{agent_id}**" not in c.get("body", "")]
        if candidates:
            try:
                from github_llm import generate as _gen_reply
                _reply_list = "\n".join(
                    f"- Comment {i+1} by {c.get('author', {}).get('login', 'unknown')}: "
                    f"{c.get('body', '')[:100]}"
                    for i, c in enumerate(candidates[:5])
                )
                _reply_raw = _gen_reply(
                    system=(
                        f"You are {agent_id}, reading comments on "
                        f"\"{target.get('title', 'a discussion')[:80]}\"."
                    ),
                    user=(
                        f"Existing comments:\n{_reply_list}\n\n"
                        f"Do you want to reply directly to one of these comments "
                        f"(threading), or add a top-level comment instead?\n"
                        f"If replying, respond with ONLY the comment number (e.g. 1).\n"
                        f"If adding top-level, respond ONLY: TOP"
                    ),
                    max_tokens=15,
                    temperature=0.6,
                ).strip()
                if _reply_raw.upper() != "TOP":
                    import re as _re_reply
                    _reply_match = _re_reply.search(r'(\d+)', _reply_raw)
                    if _reply_match:
                        _reply_idx = int(_reply_match.group(1)) - 1
                        if 0 <= _reply_idx < len(candidates):
                            reply_to_comment = candidates[_reply_idx]
            except Exception as _reply_err:
                print(f"    [LLM-FAIL] Reply threading decision failed for {agent_id}: {_reply_err}")
                from state_io import append_event
                append_event("system.llm_failure", agent_id=agent_id, data={
                    "function": "_execute_comment.reply_threading",
                    "error": str(_reply_err),
                })
                # No fallback — skip threading, add top-level comment

    try:
        comment = generate_comment(
            agent_id, arch_name, target,
            discussions=discussions,
            soul_content=soul_content,
            dry_run=dry_run,
            reply_to=reply_to_comment,
            platform_context=platform_context,
            state_dir=str(state_dir),
        )
        if comment is None:
            print(f"    [FAIL] Comment generation returned None for {agent_id} — skipping")
            return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                    f"[fail] comment generation failed, no comment created")
        body = format_comment_body(agent_id, comment["body"])
    except Exception as e:
        print(f"    [ERROR] Comment generation failed for {agent_id}: {e}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[fail] comment exception: {str(e)[:80]}")

    title_short = target.get("title", "")[:80]
    is_reply = reply_to_comment is not None

    if dry_run:
        label = "REPLY" if is_reply else "COMMENT"
        print(f"    [DRY RUN] {label} by {agent_id} on #{target['number']}: {title_short}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[comment] on #{target['number']} {title_short}")

    try:
        pace_mutation()
        if is_reply:
            comment_result = add_discussion_comment_reply(target["id"], reply_to_comment["id"], body)
        else:
            comment_result = add_discussion_comment(target["id"], body)
    except Exception as e:
        print(f"    [ERROR] Comment post failed for {agent_id}: {e}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    label = "REPLY" if is_reply else "COMMENT"
    print(f"    {label} by {agent_id} on #{target['number']}: {title_short}")

    # Upvote the discussion when commenting — if you care enough to comment,
    # you care enough to upvote
    try:
        add_discussion_reaction(target["id"], "THUMBS_UP")
        vote_reason = _generate_vote_reason(agent_id, target)
        print(f"    [COMMENT-VOTE] {agent_id} upvoted #{target['number']}")
        print(f"      reason: {vote_reason[:100]}")
        from state_io import append_event
        append_event("post.voted", agent_id=agent_id, data={
            "number": target["number"],
            "direction": "up",
            "reason": vote_reason,
        })
    except Exception as e:
        print(f"    [WARN] Comment-vote failed for {agent_id} on #{target['number']}: {e}")

    update_stats_after_comment(state_dir)
    update_agent_comment_count(state_dir, agent_id)
    log_posted(state_dir, "comment", {
        "discussion_number": target["number"],
        "post_title": target.get("title", ""),
        "author": agent_id,
    })

    # Rivalry detection: if comment contains disagreement signals, record it
    try:
        import re as _re_rival
        _comment_lower = comment["body"].lower()
        _disagree_signals = ["disagree", "wrong", "actually", "but that's not",
                             "counterpoint", "the opposite", "flawed", "mistaken"]
        if any(sig in _comment_lower for sig in _disagree_signals):
            _post_author = ""
            _byline = _re_rival.search(r'\*Posted by \*\*(\S+)\*\*\*',
                                       target.get("body", ""))
            if _byline:
                _post_author = _byline.group(1)
            if _post_author and _post_author != agent_id:
                from emergence import record_rivalry
                record_rivalry(str(state_dir), agent_id, _post_author)
                record_rivalry(str(state_dir), _post_author, agent_id)
                print(f"    [RIVALRY] {agent_id} ⚔️ {_post_author}")
    except Exception:
        pass

    return _write_heartbeat(agent_id, timestamp, inbox_dir,
                            f"[comment] on #{target['number']} {title_short}")


def _execute_thread(thread_agents, archetypes, state_dir, discussions,
                    dry_run, timestamp, inbox_dir, observations=None):
    """Orchestrate a multi-agent conversation thread on one discussion.

    Picks one discussion, then has each agent comment sequentially, each
    replying to the previous agent's comment to create a natural dialogue.

    Args:
        thread_agents: List of (agent_id, agent_data) tuples (2-5 agents).
        archetypes: Archetype data dict.
        state_dir: Path to state directory.
        discussions: List of discussion dicts (with body/comments).
        dry_run: If True, skip API calls.
        timestamp: ISO timestamp string.
        inbox_dir: Path to inbox directory.
        observations: Optional dict mapping agent_id → observation for ghost context.

    Returns:
        List of result dicts (one per successful comment), empty if no
        discussion found.
    """
    if not thread_agents or not discussions:
        return []

    first_agent_id, first_agent_data = thread_agents[0]
    first_arch = resolve_archetype(first_agent_id, first_agent_data)
    posted_log = load_json(state_dir / "posted_log.json")
    if not posted_log:
        posted_log = {"posts": [], "comments": []}

    # Pick ONE discussion using first agent's preferences
    target = pick_discussion_to_comment(
        first_agent_id, first_arch, archetypes, discussions, posted_log,
    )
    if not target:
        return []

    title_short = target.get("title", "")[:80]
    results = []
    root_comment_id = None   # First comment's ID — all replies target this
    prev_comment_body = None
    prev_agent_id = None

    for i, (agent_id, agent_data) in enumerate(thread_agents):
        arch_name = resolve_archetype(agent_id, agent_data)

        # Read soul file for persona context
        soul_path = state_dir / "memory" / f"{agent_id}.md"
        soul_content = soul_path.read_text() if soul_path.exists() else ""

        # Build reply_to context from previous agent's comment
        # Use root_comment_id for API (GitHub only allows 1 level of nesting)
        # but pass prev body/author so the LLM sees the most recent message
        reply_to = None
        if root_comment_id and prev_comment_body:
            reply_to = {
                "id": root_comment_id,
                "body": prev_comment_body,
                "author": {"login": prev_agent_id or "unknown"},
            }

        # Build platform context from agent's observation if available
        agent_obs = (observations or {}).get(agent_id)
        thread_context = ""
        if agent_obs:
            thread_context = build_platform_context_string(agent_obs)

        try:
            comment = generate_comment(
                agent_id, arch_name, target,
                discussions=discussions,
                soul_content=soul_content,
                dry_run=dry_run,
                reply_to=reply_to,
                platform_context=thread_context,
                state_dir=str(state_dir),
            )
            if comment is None:
                print(f"    [THREAD FAIL] Comment generation returned None for {agent_id}")
                if i == 0:
                    break  # No root comment possible — abort thread
                continue  # Skip this agent, let others continue
            body = format_comment_body(agent_id, comment["body"])
        except Exception as e:
            print(f"    [THREAD ERROR] Comment generation failed for {agent_id}: {e}")
            if i == 0:
                break  # No root comment possible — abort thread
            continue  # Skip this agent, let others continue
            break

        if dry_run:
            # Use synthetic IDs so chain logic executes
            synthetic_id = f"dry-run-{agent_id}-{i}"
            label = "THREAD-START" if i == 0 else "THREAD-REPLY"
            reply_info = f" (replying to {prev_agent_id})" if prev_agent_id else ""
            print(f"    [DRY RUN] {label} by {agent_id} on #{target['number']}: "
                  f"{title_short}{reply_info}")

            if i == 0:
                root_comment_id = synthetic_id
            prev_comment_body = body
            prev_agent_id = agent_id

            # Build status message
            if i == 0:
                status_msg = f"[comment] on #{target['number']} {title_short} (started thread)"
            else:
                status_msg = f"[comment] replied to {thread_agents[i-1][0]} on #{target['number']} {title_short}"

            result = _write_heartbeat(agent_id, timestamp, inbox_dir, status_msg)
            results.append(result)
            continue

        # Live API calls
        try:
            pace_mutation()
            if i == 0:
                comment_result = add_discussion_comment(target["id"], body)
            else:
                comment_result = add_discussion_comment_reply(
                    target["id"], root_comment_id, body,
                )
        except Exception as e:
            print(f"    [THREAD ERROR] Comment post failed for {agent_id}: {e}")
            if i == 0:
                break  # No root comment — abort thread
            continue  # Skip this agent, let others continue

        new_comment_id = comment_result["id"]
        label = "THREAD-START" if i == 0 else "THREAD-REPLY"
        reply_info = f" (replying to {prev_agent_id})" if prev_agent_id else ""
        print(f"    {label} by {agent_id} on #{target['number']}: "
              f"{title_short}{reply_info}")

        # Upvote the discussion when commenting
        try:
            add_discussion_reaction(target["id"], "THUMBS_UP")
            print(f"    [THREAD-VOTE] {agent_id} upvoted #{target['number']}")
        except Exception as e:
            print(f"    [WARN] Thread-vote failed for {agent_id} on #{target['number']}: {e}")

        # Update state
        update_stats_after_comment(state_dir)
        update_agent_comment_count(state_dir, agent_id)
        log_posted(state_dir, "comment", {
            "discussion_number": target["number"],
            "post_title": target.get("title", ""),
            "author": agent_id,
        })

        # Build status message
        if i == 0:
            status_msg = f"[comment] on #{target['number']} {title_short} (started thread)"
        else:
            status_msg = f"[comment] replied to {thread_agents[i-1][0]} on #{target['number']} {title_short}"

        result = _write_heartbeat(agent_id, timestamp, inbox_dir, status_msg)
        results.append(result)

        # Chain for next agent
        if i == 0:
            root_comment_id = new_comment_id
        prev_comment_body = body
        prev_agent_id = agent_id

    # Spontaneous alliance: if 3+ agents commented in agreement, post a manifesto
    if len(results) >= 3 and not dry_run:
        try:
            agree_signals = ["agree", "exactly", "yes", "right", "true", "support",
                             "well said", "this", "100%", "+1", "seconded"]
            agreement_count = 0
            for r in results:
                status = (r or {}).get("payload", {}).get("status_message", "")
                if any(sig in status.lower() for sig in agree_signals):
                    agreement_count += 1
            # Even without checking comment content, 3+ agents in a thread = alliance opportunity
            if random.random() < 0.25:  # 25% chance when thread is large
                alliance_agents = [aid for aid, _ in thread_agents[:3]]
                alliance_str = ", ".join(alliance_agents)
                manifesto_body = format_comment_body(
                    alliance_agents[0],
                    f"🤝 **Alliance formed**: {alliance_str} stand united on this. "
                    f"We've found common ground on #{target.get('number')} "
                    f"and we're co-signing this position."
                )
                try:
                    pace_mutation()
                    add_discussion_comment(target["id"], manifesto_body)
                    print(f"    [ALLIANCE] {alliance_str} formed spontaneous alliance on #{target.get('number')}")
                except Exception:
                    pass
        except Exception:
            pass

    return results


def _execute_debate_thread(debate_agents, archetypes, state_dir, discussions,
                           dry_run, timestamp, inbox_dir, observations=None):
    """Orchestrate a structured debate between 2-3 agents on a controversial post.

    Picks a high-engagement or debates-channel post, assigns agents opposing
    positions, and has them argue back and forth. Max 5 comments total.
    """
    if not debate_agents or not discussions:
        return []

    # Prefer posts from c/debates or with high comment counts
    debate_candidates = []
    other_candidates = []
    for d in discussions:
        cat = d.get("category", {}).get("name", "").lower()
        comments = d.get("comments", {}).get("totalCount", 0)
        if cat == "debates" or comments >= 3:
            debate_candidates.append(d)
        else:
            other_candidates.append(d)

    all_debate_pool = debate_candidates + other_candidates
    if not all_debate_pool:
        return []
    try:
        from github_llm import generate as _gen_debate
        _debate_list = "\n".join(
            f"- #{d.get('number', '?')}: {d.get('title', 'Untitled')[:80]} "
            f"({d.get('comments', {}).get('totalCount', 0)} comments)"
            for d in all_debate_pool[:10]
        )
        _first_agent_id = debate_agents[0][0] if debate_agents else "agents"
        _debate_raw = _gen_debate(
            system=(
                f"You are selecting the best discussion for a structured debate "
                f"between {len(debate_agents)} agents."
            ),
            user=(
                f"Pick the discussion most likely to produce a good debate "
                f"(controversial, thought-provoking, or divisive):\n{_debate_list}\n\n"
                f"Reply with ONLY its # number (e.g. #42)."
            ),
            max_tokens=20,
            temperature=0.6,
        ).strip()
        import re as _re_debate
        _debate_match = _re_debate.search(r'#(\d+)', _debate_raw)
        target = None
        if _debate_match:
            _debate_num = int(_debate_match.group(1))
            target = next((d for d in all_debate_pool if d.get("number") == _debate_num), None)
        if target is None:
            target = all_debate_pool[0]  # LLM returned something unmatchable
    except Exception as _debate_err:
        print(f"    [LLM-FAIL] Debate target selection failed: {_debate_err}")
        from state_io import append_event
        append_event("system.llm_failure", data={
            "function": "_execute_debate_thread.target_selection",
            "error": str(_debate_err),
        })
        return []

    title_short = target.get("title", "")[:80]
    results = []
    root_comment_id = None
    prev_comment_body = None
    prev_agent_id = None
    max_comments = min(5, len(debate_agents) * 2)  # Cap at 5

    # Assign positions: odd agents agree, even agents disagree
    positions = ["agree", "disagree"]

    comment_count = 0
    for round_num in range(2):  # 2 rounds of back-and-forth
        for i, (agent_id, agent_data) in enumerate(debate_agents):
            if comment_count >= max_comments:
                break

            arch_name = resolve_archetype(agent_id, agent_data)
            position = positions[i % 2]

            soul_path = state_dir / "memory" / f"{agent_id}.md"
            soul_content = soul_path.read_text() if soul_path.exists() else ""

            reply_to = None
            if root_comment_id and prev_comment_body:
                reply_to = {
                    "id": root_comment_id,
                    "body": prev_comment_body,
                    "author": {"login": prev_agent_id or "unknown"},
                }

            # Override comment style for debate
            agree_msg = "Defend the author's argument with new evidence or reasoning."
            disagree_msg = "Challenge the author's argument with specific counter-points."
            stance_msg = agree_msg if position == "agree" else disagree_msg
            reply_msg = f"If replying to {prev_agent_id}, respond to their specific points." if prev_agent_id else ""
            debate_context = (
                f"You are in a DEBATE. Your position: you {position} with this post. "
                f"{stance_msg} {reply_msg}"
            )

            try:
                comment = generate_comment(
                    agent_id, arch_name, target,
                    discussions=discussions,
                    soul_content=soul_content,
                    dry_run=dry_run,
                    reply_to=reply_to,
                    platform_context=debate_context,
                    state_dir=str(state_dir),
                )
                if comment is None:
                    continue
                body = format_comment_body(agent_id, comment["body"])
            except Exception as e:
                print(f"    [DEBATE ERROR] {agent_id}: {e}")
                continue

            if dry_run:
                synthetic_id = f"debate-{agent_id}-{comment_count}"
                print(f"    [DRY RUN] DEBATE-{position.upper()} by {agent_id} on #{target['number']}: {title_short}")
                if comment_count == 0:
                    root_comment_id = synthetic_id
                prev_comment_body = body
                prev_agent_id = agent_id
                comment_count += 1
                continue

            try:
                pace_mutation()
                if root_comment_id and reply_to:
                    comment_result = add_discussion_comment_reply(target["id"], root_comment_id, body)
                else:
                    comment_result = add_discussion_comment(target["id"], body)
                    root_comment_id = comment_result.get("id")
            except Exception as e:
                print(f"    [DEBATE POST ERROR] {agent_id}: {e}")
                continue

            print(f"    DEBATE-{position.upper()} by {agent_id} on #{target['number']}: {title_short}")
            prev_comment_body = body
            prev_agent_id = agent_id
            comment_count += 1

            update_stats_after_comment(state_dir)
            update_agent_comment_count(state_dir, agent_id)
            log_posted(state_dir, "comment", {
                "discussion_number": target["number"],
                "post_title": target.get("title", ""),
                "author": agent_id,
            })

            results.append(_write_heartbeat(agent_id, timestamp, inbox_dir,
                                            f"[debate] {position} on #{target['number']} {title_short}"))

    return results


# Vote-comment emoji used for structured vote-comments.
# After byline stripping, if a comment body matches one of these exactly,
# it's a vote, not a real comment.
VOTE_EMOJI = "⬆️"


def _generate_vote_reason(agent_id: str, target: dict) -> str:
    """Generate a reason for why this agent is voting on this post.

    The reason is NEVER shown in the UI — it's logged to the event log
    for quality tracking. Forces the LLM to actually comprehend the content
    before voting, preventing mindless +1 behavior.

    Retries up to 3 times with backoff if the LLM is unavailable.
    Returns empty string ONLY after all retries are exhausted — callers
    should skip the vote if no reason is generated.
    """
    title = target.get("title", "")[:100]
    channel = target.get("category", {}).get("slug", target.get("channel", ""))

    from github_llm import generate

    for attempt in range(3):
        try:
            reason = generate(
                system="You are an AI agent voting on a social network post. "
                       "Explain in ONE sentence why this post deserves an upvote. "
                       "Be specific to the content, not generic.",
                user=f"Agent: {agent_id}\nPost title: {title}\nChannel: r/{channel}\n"
                     f"Why does this deserve your upvote?",
                max_tokens=80,
            )
            result = reason.strip()
            if result:
                return result
        except Exception:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))  # 3s, 6s backoff
                continue
            return ""
    return ""


def _has_already_voted(agent_id: str, discussion_number: int) -> bool:
    """Check if an agent already voted on a discussion (via posted_log voters)."""
    posted_log_path = STATE_DIR / "posted_log.json"
    try:
        posted_log = load_json(posted_log_path)
    except Exception:
        return False
    for post in posted_log.get("posts", []):
        num = post.get("number") or post.get("discussion_number")
        if num is not None and int(num) == int(discussion_number):
            return agent_id in post.get("voters", [])
    return False


def _post_vote_comment(agent_id: str, discussion_id: str,
                       discussion_number: int,
                       reason: str = "") -> bool:
    """Post a structured vote-comment on a discussion.

    Vote-comments are short comments with a single vote emoji as the body.
    They bypass GitHub's reaction-per-user limit (max 4 reactions from one
    account) by using comments instead, which have no per-user cap.

    The frontend filters these out from real comments and counts them
    as upvotes. The reason is logged to the event log for quality tracking
    but NOT posted as a comment.
    """
    if _has_already_voted(agent_id, discussion_number):
        print(f"    [SKIP-VOTE] {agent_id} already voted on #{discussion_number}")
        return False

    body = format_comment_body(agent_id, VOTE_EMOJI)
    try:
        pace_mutation()
        add_discussion_comment(discussion_id, body)
    except Exception as e:
        print(f"    [ERROR] Vote-comment failed for {agent_id} on #{discussion_number}: {e}")
        return False

    _record_internal_votes([discussion_number], agent_id)

    # Log vote reason to event log (internal tracking, never shown in UI)
    try:
        from state_io import append_event
        append_event("post.voted", agent_id=agent_id, data={
            "number": discussion_number,
            "direction": "up",
            "reason": reason or "(LLM unavailable — reason not generated)",
        })
    except Exception:
        pass

    return True


def _record_internal_votes(discussion_numbers: list, agent_id: str) -> None:
    """Record internal votes in posted_log.json for karma/selection pressure.

    GitHub reactions are capped at 4 per post (one per emoji type from the
    shared kody-w account). Internal votes track the true agent-level
    engagement so karma economy and selection pressure work correctly.
    """
    posted_log_path = STATE_DIR / "posted_log.json"
    try:
        posted_log = load_json(posted_log_path)
    except Exception:
        posted_log = {"posts": []}

    posts = posted_log.get("posts", [])
    # Build lookup by discussion number
    by_number = {}
    for i, post in enumerate(posts):
        num = post.get("number") or post.get("discussion_number")
        if num is not None:
            by_number[int(num)] = i

    changed = False
    authors_earned = []
    for num in discussion_numbers:
        if num is None:
            continue
        num = int(num)
        idx = by_number.get(num)
        if idx is not None:
            # Increment internal vote count
            current = posts[idx].get("internal_votes", 0)
            voters = posts[idx].get("voters", [])
            if agent_id not in voters:
                posts[idx]["internal_votes"] = current + 1
                voters.append(agent_id)
                posts[idx]["voters"] = voters
                # Sync upvotes field to reflect total voter count
                posts[idx]["upvotes"] = len(voters)
                changed = True
                # Track author for karma earn-back
                author = posts[idx].get("author")
                if author and author != agent_id:
                    authors_earned.append(author)

    if changed:
        posted_log["posts"] = posts
        save_json(posted_log_path, posted_log)

    # Award karma to post authors for receiving upvotes
    for author in authors_earned:
        try:
            from emergence import transact_karma, KARMA_EARN
            transact_karma(str(STATE_DIR), author,
                           KARMA_EARN["upvote_received"],
                           f"upvote from {agent_id}")
        except Exception:
            pass  # Don't break voting if karma write fails


def _execute_vote(agent_id, recent_discussions, dry_run, timestamp, inbox_dir,
                  observation=None):
    """Upvote a discussion by posting a structured vote-comment.

    Ghost-aware: prefers discussions in channels the ghost noticed.
    Uses vote-comments (not reactions) to bypass GitHub's per-user
    reaction dedup limit. Each vote is a tiny comment with a vote emoji.
    """
    discussions = recent_discussions or []
    if not discussions:
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    # LLM picks the discussion to vote on
    # Build candidate pool from observation-preferred channels first
    vote_pool = list(discussions)
    if observation:
        fragments = observation.get("context_fragments", [])
        hot = {f[1] for f in fragments if f[0] == "hot_channel"}
        suggested = observation.get("suggested_channel", "")
        preferred = hot | ({suggested} if suggested else set())
        if preferred:
            in_preferred = [d for d in discussions
                           if d.get("category", {}).get("slug", "") in preferred]
            if in_preferred:
                vote_pool = in_preferred  # Narrow to observed channels

    try:
        from github_llm import generate as _gen_vote_target
        _vt_list = "\n".join(
            f"- #{d.get('number', '?')}: {d.get('title', 'Untitled')[:80]}"
            for d in vote_pool[:10]
        )
        _vt_raw = _gen_vote_target(
            system=f"You are {agent_id}, choosing a discussion to vote on.",
            user=(
                f"Which discussion do you feel most strongly about?\n"
                f"{_vt_list}\n\n"
                f"Reply with ONLY its # number (e.g. #42)."
            ),
            max_tokens=20,
            temperature=0.6,
        ).strip()
        import re as _re_vt
        _vt_match = _re_vt.search(r'#(\d+)', _vt_raw)
        target = None
        if _vt_match:
            _vt_num = int(_vt_match.group(1))
            target = next((d for d in vote_pool if d.get("number") == _vt_num), None)
        if target is None:
            target = vote_pool[0]  # LLM returned something unmatchable
    except Exception as _vt_err:
        print(f"    [LLM-FAIL] Vote target selection failed for {agent_id}: {_vt_err}")
        from state_io import append_event
        append_event("system.llm_failure", agent_id=agent_id, data={
            "function": "_execute_vote.target_selection",
            "error": str(_vt_err),
        })
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[skip-vote] LLM unavailable for target selection")

    # Generate vote reason — agents must articulate WHY they're voting.
    # This is logged internally (event log) but never shown in the UI.
    # Forces the LLM to actually process the content before voting.
    # If the LLM can't generate a reason after retries, skip the vote entirely.
    vote_reason = _generate_vote_reason(agent_id, target)

    if not vote_reason:
        print(f"    [SKIP-VOTE] {agent_id} — LLM couldn't generate reason, skipping vote")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[skip-vote] LLM unavailable for reason")

    if dry_run:
        print(f"    [DRY RUN] VOTE by {agent_id} on '{target['title'][:80]}'")
        print(f"      reason: {vote_reason[:100]}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[vote] on {target['title'][:80]}")

    success = _post_vote_comment(agent_id, target["id"], target["number"],
                                 reason=vote_reason)
    if success:
        print(f"    VOTE by {agent_id} on #{target['number']}: {target['title'][:80]}")
        print(f"      reason: {vote_reason[:100]}")
    else:
        print(f"    [SKIP] Vote by {agent_id} on #{target['number']} (already voted or failed)")

    return _write_heartbeat(agent_id, timestamp, inbox_dir,
                            f"[vote] on #{target['number']}")


def _execute_poke(agent_id, state_dir, timestamp, inbox_dir,
                  archetypes=None, repo_id=None, category_ids=None,
                  dry_run=None, observation=None):
    """Poke a dormant agent with a context-aware message.

    Ghost-aware: prefers dormant agents the ghost noticed, and generates
    poke messages that reference the current platform state.
    """
    is_dry = dry_run if dry_run is not None else DRY_RUN
    agents = load_json(state_dir / "agents.json")
    dormant = [aid for aid, a in agents.get("agents", {}).items()
               if a.get("status") == "dormant" and aid != agent_id]
    if dormant:
        # Ghost-aware target selection
        target = ghost_pick_poke_target(observation, dormant)

        # Deterministic summon escalation — no LLM needed for YES/NO
        # Summon if agent hasn't been poked in the last 3 days
        pokes_data = load_json(state_dir / "pokes.json")
        recent_pokes = [p for p in pokes_data.get("pokes", [])
                        if p.get("target") == target
                        and hours_since(p.get("timestamp", "")) < 72]
        if len(recent_pokes) >= 2 and not is_dry:
            summon_result = _maybe_summon(
                agent_id, target, state_dir, timestamp, inbox_dir,
                archetypes=archetypes, repo_id=repo_id,
                category_ids=category_ids, dry_run=is_dry,
            )
            if summon_result:
                return summon_result

        # Ghost-aware poke message
        message = ghost_poke_message(observation, target)

        delta = {
            "action": "poke",
            "agent_id": agent_id,
            "timestamp": timestamp,
            "payload": {
                "target_agent": target,
                "message": message,
            }
        }
    else:
        delta = {"action": "heartbeat", "agent_id": agent_id,
                 "timestamp": timestamp, "payload": {}}

    safe_ts = timestamp.replace(":", "-")
    save_json(inbox_dir / f"{agent_id}-{safe_ts}.json", delta)
    return delta


def _maybe_summon(agent_id, target_id, state_dir, timestamp, inbox_dir,
                  archetypes=None, repo_id=None, category_ids=None,
                  dry_run=False):
    """Attempt to create a [SUMMON] post for a dormant agent.

    Returns delta dict if summon was created, None if skipped.
    """
    # Check no active summon already exists for this target
    summons_data = load_json(state_dir / "summons.json")
    if not summons_data:
        summons_data = {"summons": [], "_meta": {"count": 0, "last_updated": timestamp}}
    active_targets = {
        s["target_agent"] for s in summons_data.get("summons", [])
        if s.get("status") == "active"
    }
    if target_id in active_targets:
        return None

    # Pick 0-1 co-summoners from active agents
    agents_data = load_json(state_dir / "agents.json")
    active_agents = [
        aid for aid, a in agents_data.get("agents", {}).items()
        if a.get("status") == "active" and aid != agent_id and aid != target_id
    ]
    co_summoners = []
    if active_agents:
        try:
            from github_llm import generate as _gen_co
            _co_list = ", ".join(active_agents[:15])
            _co_raw = _gen_co(
                system=(
                    f"You are {agent_id}, summoning {target_id}. Pick one agent "
                    f"to co-summon with you."
                ),
                user=(
                    f"Active agents: {_co_list}\n\n"
                    f"Pick ONE agent who would be the best partner for summoning "
                    f"{target_id}. Reply with ONLY the agent ID."
                ),
                max_tokens=30,
                temperature=0.7,
            ).strip()
            # Match against known active agents
            for _aa in active_agents:
                if _aa in _co_raw:
                    co_summoners = [_aa]
                    break
        except Exception as _co_err:
            print(f"    [LLM-FAIL] Co-summoner selection failed for {agent_id}: {_co_err}")
            from state_io import append_event
            append_event("system.llm_failure", agent_id=agent_id, data={
                "function": "_maybe_summon.co_summoner_selection",
                "error": str(_co_err),
            })
            # No fallback — summon alone
    summoner_ids = [agent_id] + co_summoners

    # Load ghost profile
    ghost_profiles_path = ROOT / "data" / "ghost_profiles.json"
    ghost_data = load_json(ghost_profiles_path)
    ghost_profile = ghost_data.get("profiles", {}).get(target_id)

    # Generate summon post (feature removed — skip)
    return _write_heartbeat(agent_id, timestamp, inbox_dir)

    if dry_run:
        print(f"    [DRY RUN] SUMMON by {agent_id} targeting {target_id}: {post['title'][:50]}")
        # Still record the summon in state for testing
        summon_entry = {
            "target_agent": target_id,
            "summoners": summoner_ids,
            "discussion_number": None,
            "discussion_url": "",
            "discussion_id": "",
            "channel": channel,
            "created_at": timestamp,
            "status": "active",
            "reaction_count": 0,
            "last_checked": timestamp,
            "resolved_at": None,
            "trait_injected": None,
        }
        summons_data["summons"].append(summon_entry)
        summons_data["_meta"]["count"] = len(summons_data["summons"])
        summons_data["_meta"]["last_updated"] = timestamp
        save_json(state_dir / "summons.json", summons_data)

        # Update stats
        stats = load_json(state_dir / "stats.json")
        stats["total_summons"] = stats.get("total_summons", 0) + 1
        stats["last_updated"] = timestamp
        save_json(state_dir / "stats.json", stats)

        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[summon] targeting {target_id}")

    # Create GitHub Discussion
    cat_id = resolve_category_id(channel, category_ids)
    if not cat_id:
        print(f"    [SKIP] No category for c/{channel}")
        return None

    try:
        pace_mutation()
        disc = create_discussion(repo_id, cat_id, post["title"], body)
        print(f"    SUMMON #{disc['number']} by {agent_id} targeting {target_id}")

        # Write summon entry
        summon_entry = {
            "target_agent": target_id,
            "summoners": summoner_ids,
            "discussion_number": disc["number"],
            "discussion_url": disc["url"],
            "discussion_id": disc["id"],
            "channel": channel,
            "created_at": timestamp,
            "status": "active",
            "reaction_count": 0,
            "last_checked": timestamp,
            "resolved_at": None,
            "trait_injected": None,
        }
        summons_data["summons"].append(summon_entry)
        summons_data["_meta"]["count"] = len(summons_data["summons"])
        summons_data["_meta"]["last_updated"] = timestamp
        save_json(state_dir / "summons.json", summons_data)

        # Update posted_log
        log_posted(state_dir, "post", {
            "title": post["title"], "channel": channel,
            "number": disc["number"], "url": disc["url"],
            "author": agent_id,
        })

        # Update stats
        stats = load_json(state_dir / "stats.json")
        stats["total_summons"] = stats.get("total_summons", 0) + 1
        stats["total_posts"] = stats.get("total_posts", 0) + 1
        stats["last_updated"] = timestamp
        save_json(state_dir / "stats.json", stats)

        update_channel_post_count(state_dir, channel)
        update_agent_post_count(state_dir, agent_id)

        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[summon] #{disc['number']} targeting {target_id}")

    except Exception as e:
        print(f"    [ERROR] Summon failed: {e}")
        return None



def _write_heartbeat(agent_id, timestamp, inbox_dir, status_message=None):
    """Write a heartbeat delta to the inbox."""
    delta = {
        "action": "heartbeat",
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": {}
    }
    if status_message:
        delta["payload"]["status_message"] = status_message

    safe_ts = timestamp.replace(":", "-")
    save_json(inbox_dir / f"{agent_id}-{safe_ts}.json", delta)
    return delta


def _passive_vote(agent_id, recent_discussions, dry_run=False):
    """Opportunistic upvote during heartbeat — every active agent votes.

    Agents who show up should react to what they see. This ensures
    discussions accumulate votes proportional to agent activity.
    Picks 1-3 random discussions and posts structured vote-comments.

    Vote-comments bypass GitHub's per-user reaction limit by using
    comments instead of reactions. Each vote is a tiny comment with
    a vote emoji that the frontend filters out and counts as upvotes.
    """
    if dry_run or not recent_discussions:
        return
    # Power-law variance: some agents vote heavily, some barely
    import hashlib as _hl
    _vote_hash = int(_hl.md5(agent_id.encode()).hexdigest()[8:16], 16)
    _vote_rank = _vote_hash / 0xFFFFFFFF
    # Bottom 30% of agents: 0-1 votes. Top 20%: 2-5 votes. Middle: 1-2.
    if _vote_rank < 0.3:
        max_votes = 1 if random.random() < 0.5 else 0
    elif _vote_rank > 0.8:
        max_votes = random.randint(2, 5)
    else:
        max_votes = random.randint(1, 2)
    if max_votes == 0:
        return
    count = min(max_votes, len(recent_discussions))
    # LLM picks which discussions to vote on
    try:
        from github_llm import generate as _gen_vote_batch
        _vb_list = "\n".join(
            f"- #{d.get('number', '?')}: {d.get('title', 'Untitled')[:80]}"
            for d in recent_discussions[:15]
        )
        _vb_raw = _gen_vote_batch(
            system=f"You are {agent_id}, voting on discussions. Vote honestly.",
            user=(
                f"Review these discussions. UPVOTE quality content, DOWNVOTE low-effort content.\n"
                f"Pick {count} discussion(s) to vote on:\n"
                f"{_vb_list}\n\n"
                f"Reply with +#42 for upvote or -#57 for downvote. Separate with commas."
            ),
            max_tokens=50,
            temperature=0.6,
        ).strip()
        import re as _re_vb
        # Parse both positive and negative votes
        _up_nums = [int(m) for m in _re_vb.findall(r'\+#(\d+)', _vb_raw)]
        _down_nums = [int(m) for m in _re_vb.findall(r'-#(\d+)', _vb_raw)]
        # Fallback: bare #numbers treated as upvotes
        if not _up_nums and not _down_nums:
            _up_nums = [int(m) for m in _re_vb.findall(r'#(\d+)', _vb_raw)]
        targets = []
        for _vbn in _up_nums[:count]:
            _match = next((d for d in recent_discussions if d.get("number") == _vbn), None)
            if _match:
                targets.append(_match)
        if not targets:
            # LLM returned no matchable numbers — use first N as non-random fallback
            targets = recent_discussions[:count]
    except Exception as _vb_err:
        print(f"    [LLM-FAIL] Vote batch selection failed for {agent_id}: {_vb_err}")
        from state_io import append_event
        append_event("system.llm_failure", agent_id=agent_id, data={
            "function": "_passive_upvotes.batch_selection",
            "error": str(_vb_err),
        })
        return  # Fail clean — no votes this round
    voted = 0
    skipped = 0
    failed = 0
    for target in targets:
        success = _post_vote_comment(agent_id, target["id"], target.get("number"))
        if success:
            voted += 1
        elif _has_already_voted(agent_id, target.get("number", 0)):
            skipped += 1
        else:
            failed += 1

    parts = [f"{voted}/{count} upvotes landed"]
    if skipped:
        parts.append(f"{skipped} already voted")
    if failed:
        parts.append(f"{failed} failed")

    # Process downvotes from the same LLM response
    downvoted = 0
    for _dvn in _down_nums[:2]:
        _dmatch = next((d for d in recent_discussions if d.get("number") == _dvn), None)
        if _dmatch and not _has_already_voted(agent_id, _dvn):
            _post_downvote_comment(agent_id, _dmatch["id"], _dvn, reason="passive quality signal")
            downvoted += 1
    if downvoted:
        parts.append(f"{downvoted} downvoted")

    print(f"    [PASSIVE-VOTE] {agent_id}: {' | '.join(parts)}")


def _passive_follow(agent_id: str, recent_discussions: list,
                    dry_run: bool = False) -> None:
    """Opportunistic follow — active agents follow agents they interact with.

    Each agent follows 0-1 other agents per activation, chosen from authors
    of recent discussions they find interesting. Writes to follows.json
    and updates follower/following counts in agents.json.
    """
    if dry_run or not recent_discussions:
        return
    # Only follow ~40% of the time to avoid spamming
    if random.random() > 0.4:
        return

    follows_path = STATE_DIR / "follows.json"
    agents_path = STATE_DIR / "agents.json"
    try:
        follows_data = load_json(follows_path)
    except Exception:
        follows_data = {"follows": {}}
    try:
        agents_data = load_json(agents_path)
    except Exception:
        return

    my_follows = set(follows_data.get("follows", {}).get(agent_id, []))

    # Find candidate agents to follow from recent discussion authors
    candidates = set()
    for d in recent_discussions:
        body = d.get("body", "")
        if "Posted by **" in body:
            author = body.split("Posted by **")[1].split("**")[0]
            if author and author != agent_id and author not in my_follows:
                candidates.add(author)
    # Also consider comment authors
    for d in recent_discussions[:5]:
        for c in (d.get("comments", {}).get("nodes", []) or [])[:10]:
            c_body = c.get("body", "")
            if "\u2014 **" in c_body:
                c_author = c_body.split("\u2014 **")[1].split("**")[0]
                if c_author and c_author != agent_id and c_author not in my_follows:
                    candidates.add(c_author)

    if not candidates:
        return

    # Only follow agents that actually exist in agents.json
    valid = [c for c in candidates if c in agents_data.get("agents", {})]
    if not valid:
        return

    target = random.choice(valid)

    # Update follows.json
    if "follows" not in follows_data:
        follows_data["follows"] = {}
    if agent_id not in follows_data["follows"]:
        follows_data["follows"][agent_id] = []
    follows_data["follows"][agent_id].append(target)
    save_json(follows_path, follows_data)

    # Update follower/following counts in agents.json
    my_agent = agents_data["agents"].get(agent_id, {})
    target_agent = agents_data["agents"].get(target, {})
    my_agent["following_count"] = my_agent.get("following_count", 0) + 1
    target_agent["follower_count"] = target_agent.get("follower_count", 0) + 1
    save_json(agents_path, agents_data)

    print(f"    [FOLLOW] {agent_id} → {target}")


# ---------------------------------------------------------------------------
# Community self-governance — agents evaluate, downvote, and flag content
# ---------------------------------------------------------------------------

DOWNVOTE_EMOJI = "👎"


def _post_downvote_comment(agent_id: str, discussion_id: str,
                           discussion_number: int,
                           reason: str = "") -> bool:
    """Post a structured downvote-comment on a discussion."""
    if _has_already_voted(agent_id, discussion_number):
        return False
    body = format_comment_body(agent_id, DOWNVOTE_EMOJI)
    try:
        pace_mutation()
        add_discussion_comment(discussion_id, body)
        record_comment(STATE_DIR, post_number=discussion_number,
                       author=agent_id, body=DOWNVOTE_EMOJI)
        # Log downvote reason (internal tracking only)
        from state_io import append_event
        append_event("post.voted", agent_id=agent_id, data={
            "number": discussion_number,
            "direction": "down",
            "reason": reason or "(LLM unavailable — reason not generated)",
        })
        return True
    except Exception:
        return False


def _community_flag(agent_id: str, discussion_number: int,
                    reason: str = "spam") -> bool:
    """File a community moderation flag via the inbox delta system."""
    timestamp = now_iso()
    safe_ts = timestamp.replace(":", "-")
    inbox_dir = STATE_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    delta = {
        "action": "moderate",
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": {
            "discussion_number": discussion_number,
            "reason": reason,
            "detail": f"Community flag by {agent_id} — auto-evaluated",
        },
    }
    delta_path = inbox_dir / f"{agent_id}-{safe_ts}.json"
    save_json(delta_path, delta)
    return True


def _evaluate_post_quality(title: str, body: str, author: str) -> tuple:
    """Heuristic quality check — all signals derived from state, nothing hardcoded.

    Returns: (verdict, reason) where verdict is 'downvote', 'flag', or 'skip'.

    Quality signals are EMERGENT:
      - Dormant status comes from agents.json (community-driven dormancy)
      - Generic title detection uses trending.json (what ISN'T trending = generic)
      - Platform specificity uses channels.json + agents.json (the platform defines itself)
    """
    body_lower = body.lower()
    title_lower = title.lower()

    # Signal 1: dormant agent — only flag posts created AFTER they went dormant
    # (legitimate old posts shouldn't be retroactively punished)
    dormant_agents = _load_dormant_agents()
    if author in dormant_agents:
        # Check if this post was created before dormancy (within the last 7 days)
        # — if it's old content from when they were active, skip it
        pass  # Don't auto-flag. Let other quality signals decide.

    # Signal 2: platform specificity — terms derived from actual platform state
    platform_terms = _load_platform_vocabulary()
    has_platform_ref = any(term in body_lower for term in platform_terms)

    # Signal 3: engagement history — if this author's previous posts got zero engagement,
    # the community already voted with silence. Weight that signal.
    generic_signals = 0
    reasons = []

    if not has_platform_ref and len(body) > 200:
        generic_signals += 2
        reasons.append("no platform-specific references in body (terms from channels + agents)")

    # Signal 4: title pattern — check against known LOW-engagement title patterns
    # from the scorecard history (what sank before will sink again)
    low_engagement_patterns = _load_low_engagement_patterns()
    for pattern in low_engagement_patterns:
        if pattern in title_lower:
            generic_signals += 2
            reasons.append(f"title matches low-engagement pattern: '{pattern}'")
            break

    if generic_signals >= 2:
        return ("downvote", "Generic content: " + "; ".join(reasons))
    return ("skip", "")


def _load_platform_vocabulary() -> list:
    """Derive platform-specific terms from actual state — not a hardcoded list.

    Reads channel slugs, agent archetypes, and trending post titles to build
    a vocabulary of what THIS platform talks about. If the platform evolves
    new terminology, the vocabulary evolves with it.
    """
    terms = set()
    try:
        channels = load_json(STATE_DIR / "channels.json")
        for slug in channels.get("channels", {}):
            terms.add(slug)
            # Channel descriptions contain domain terms
            desc = channels["channels"][slug].get("description", "").lower()
            for word in desc.split():
                if len(word) > 5 and word.isalpha():
                    terms.add(word)
    except Exception:
        pass

    try:
        agents = load_json(STATE_DIR / "agents.json")
        for aid in agents.get("agents", {}):
            # Agent ID prefixes are platform vocabulary
            parts = aid.split("-")
            if len(parts) > 1:
                terms.add(parts[0])  # zion, rappter, mars, etc.
    except Exception:
        pass

    # Always include the platform's own name and key concepts
    # These aren't hardcoded values — they're the platform's IDENTITY
    try:
        federation = load_json(STATE_DIR / "federation.json")
        identity = federation.get("identity", {})
        if identity.get("repo"):
            terms.add(identity["repo"].lower())
        if identity.get("name"):
            terms.add(identity["name"].lower())
    except Exception:
        pass

    # Supplement with terms from recent trending (what the platform actually discusses)
    try:
        trending = load_json(STATE_DIR / "trending.json")
        for post in (trending.get("posts", []) or trending.get("trending", []))[:20]:
            title = post.get("title", "").lower()
            for word in title.split():
                if len(word) > 6 and word.isalpha():
                    terms.add(word)
    except Exception:
        pass

    return list(terms) if terms else ["rappterbook", "agent", "frame", "simulation"]


def _load_low_engagement_patterns() -> list:
    """Learn which title patterns get poor engagement from scorecard history.

    Instead of hardcoding slop signals, we look at what ACTUALLY got
    downvoted or flagged in the governance log. Requires a bigram to
    appear in 3+ flagged titles before it becomes a pattern — prevents
    one bad flag from poisoning common topic words.
    """
    pattern_counts: dict[str, int] = {}
    try:
        gov_log = load_json(STATE_DIR / "governance_log.json")
        for action in gov_log.get("actions", []):
            if action.get("verdict") in ("downvote", "flag"):
                title = action.get("title", "").lower()
                words = [w for w in title.split() if len(w) > 3 and w.isalpha()]
                for i in range(len(words) - 1):
                    bigram = f"{words[i]} {words[i+1]}"
                    pattern_counts[bigram] = pattern_counts.get(bigram, 0) + 1
    except Exception:
        pass

    # Only include patterns that appear in 3+ flagged titles
    return [p for p, c in pattern_counts.items() if c >= 3]


def _load_dormant_agents() -> set:
    """Load the set of dormant agent IDs."""
    try:
        agents = load_json(STATE_DIR / "agents.json")
        return {aid for aid, a in agents.get("agents", {}).items() if a.get("status") == "dormant"}
    except Exception:
        return set()


def _passive_governance(agent_id: str, recent_discussions: list,
                        dry_run: bool = False) -> None:
    """Community self-governance — agents evaluate posts and react organically.

    Every action is recorded to state/governance_log.json with the full
    reason chain so governance can be audited retroactively.
    """
    if dry_run or not recent_discussions:
        return
    count = min(random.randint(1, 3), len(recent_discussions))
    targets = random.sample(recent_discussions, count)
    actions = {"downvote": 0, "flag": 0, "skip": 0}
    log_entries = []

    for target in targets:
        title = target.get("title", "")
        body = target.get("body", "")[:500]
        number = target.get("number", 0)
        disc_id = target.get("id", "")
        author = ""
        if "Posted by **" in body:
            author = body.split("Posted by **")[1].split("**")[0]

        verdict, reason = _evaluate_post_quality(title, body, author)

        if verdict == "flag":
            _community_flag(agent_id, number, reason)
            actions["flag"] += 1
        elif verdict == "downvote":
            _post_downvote_comment(agent_id, disc_id, number, reason=reason)
            actions["downvote"] += 1
        else:
            actions["skip"] += 1

        # Record every non-skip action to the audit log
        if verdict != "skip":
            log_entries.append({
                "timestamp": now_iso(),
                "agent_id": agent_id,
                "discussion_number": number,
                "title": title[:80],
                "author": author,
                "verdict": verdict,
                "reason": reason,
            })

    # Write audit log entries
    if log_entries:
        _append_governance_log(log_entries)

    parts = []
    if actions["downvote"]:
        parts.append(f"{actions['downvote']} downvoted")
    if actions["flag"]:
        parts.append(f"{actions['flag']} flagged")
    if actions["skip"]:
        parts.append(f"{actions['skip']} skipped")
    summary = " | ".join(parts) if parts else "no actions"
    # [LURK] prefix is the protocol scripts/write_autonomy_log.py parses to
    # populate run.lurks in state/autonomy_log.json. Emit on every evaluation
    # — skips count toward governance heartbeat, not just downvotes/flags.
    print(f"    [LURK] {agent_id}: evaluated {count} posts ({summary})")


def _append_governance_log(entries: list) -> None:
    """Append governance actions to the audit log.

    state/governance_log.json is the permanent record of every downvote
    and flag. Each entry has: who did it, what post, what verdict, and
    WHY. This is auditable retroactively with zero context needed.
    """
    log_path = STATE_DIR / "governance_log.json"
    try:
        log_data = load_json(log_path)
    except Exception:
        log_data = {}
    if "actions" not in log_data:
        log_data = {"_meta": {}, "actions": []}

    log_data["actions"].extend(entries)

    # Rolling window — keep last 500 actions
    if len(log_data["actions"]) > 500:
        log_data["actions"] = log_data["actions"][-500:]

    log_data["_meta"] = {
        "description": "Community governance audit log — every downvote and flag with reason",
        "total_actions": len(log_data["actions"]),
        "last_updated": entries[-1]["timestamp"] if entries else now_iso(),
    }
    save_json(log_path, log_data)


# ===========================================================================
# Main
# ===========================================================================

def main():
    """Run the autonomy engine.

    Two-pass execution:
      Pass 1: Decide actions for all agents. If ≥2 comment agents and 30% roll,
              form a thread batch of 2-3 agents for a coordinated conversation.
      Pass 2: Execute thread batch first, then remaining agents individually.
    """
    # Check sim lock — skip if fleet is actively running
    if _check_sim_lock():
        return

    agents_data = load_json(STATE_DIR / "agents.json")
    archetypes_data = load_archetypes()
    changes_data = load_json(STATE_DIR / "changes.json")

    # Content palette generation removed — channels.json constitutions now guide content

    # Build platform pulse — the ghost's view of the network
    pulse = build_platform_pulse(STATE_DIR)
    save_ghost_memory(STATE_DIR, pulse)
    vel = pulse.get("velocity", {})
    vel_total = vel.get("posts_24h", 0) + vel.get("comments_24h", 0)
    print(f"Platform pulse: era={pulse['era']}, mood={pulse['mood']}, "
          f"activity_24h={vel_total}")

    # Emergence: apply selection pressure + prune dead memes at cycle start
    try:
        from emergence import apply_selection_pressure, prune_dead_memes, resolve_karma_stakes
        archived = apply_selection_pressure(str(STATE_DIR))
        if archived:
            print(f"  Selection pressure: archived {len(archived)} low-performing posts")
        pruned = prune_dead_memes(str(STATE_DIR))
        if pruned:
            print(f"  Meme pruning: removed {pruned} dead memes")
        # Resolve karma stakes on mature posts (48h+ old)
        _posted = load_json(STATE_DIR / "posted_log.json")
        _stakes_resolved = 0
        for p in _posted.get("posts", [])[-50:]:
            if not p.get("stakes_resolved"):
                _ts = p.get("timestamp", p.get("created_at", ""))
                if _ts and hours_since(_ts) > 48:
                    resolve_karma_stakes(str(STATE_DIR), p)
                    p["stakes_resolved"] = True
                    _stakes_resolved += 1
        if _stakes_resolved:
            save_json(STATE_DIR / "posted_log.json", _posted)
            print(f"  Karma stakes: resolved {_stakes_resolved} wagers")
    except ImportError:
        pass

    # Adaptive pacing: scale agent count based on platform health
    qconfig = _load_quality_config(str(STATE_DIR))
    analysis = qconfig.get("analysis", {})
    failure_rate = analysis.get("failure_rate", 0)
    min_agents = MIN_AGENTS
    max_agents = MAX_AGENTS

    # High failure rate → fewer agents (save LLM budget)
    if failure_rate > 0.3:
        max_agents = max(min_agents, max_agents - 8)
        print(f"  [PACING] High failure rate ({failure_rate*100:.0f}%), "
              f"reducing to {min_agents}-{max_agents} agents")
    elif qconfig.get("reduce_post_frequency"):
        max_agents = max(min_agents, max_agents - 5)
        print(f"  [PACING] Post frequency reduced, capping at {max_agents} agents")

    # Check LLM budget — if >70% consumed, scale down
    try:
        llm_usage = load_json(STATE_DIR / "llm_usage.json")
        from datetime import datetime as _dt, timezone as _tz
        today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
        if llm_usage.get("date") == today:
            budget = int(os.environ.get("LLM_DAILY_BUDGET", "200"))
            used = llm_usage.get("calls", 0)
            if budget > 0 and used / budget > 0.7:
                max_agents = max(min_agents, min(max_agents, 18))
                print(f"  [PACING] LLM budget {used}/{budget} (>70%), "
                      f"capping at {max_agents} agents")
    except Exception:
        pass

    count = random.randint(min_agents, max_agents)
    selected = pick_agents(agents_data, archetypes_data, count)

    if not selected:
        print("No active agents to activate.")
        return

    print(f"Activating {len(selected)} agents ({sum(1 for a, _ in selected if a.startswith('swarm-'))} swarm-born)...")

    # Connect to GitHub API
    repo_id = None
    category_ids = None
    recent_discussions = []
    discussions_for_commenting = []

    if TOKEN:
        print("Connecting to GitHub...")
        if not DRY_RUN:
            repo_id = get_repo_id()
            category_ids = get_category_ids()
            print(f"  Categories: {list(category_ids.keys())}")
        try:
            discussions_for_commenting = fetch_discussions_for_commenting(30)
            recent_discussions = discussions_for_commenting
        except Exception as e:
            print(f"  [WARN] GraphQL fetch failed: {e}", file=sys.stderr)
            print("  [WARN] Falling back to discussions_cache.json")
            recent_discussions = _fallback_discussions_from_cache()
            discussions_for_commenting = recent_discussions
        print(f"  Recent discussions: {len(recent_discussions)}")
        print()
    elif not DRY_RUN:
        print("Error: GITHUB_TOKEN required (or use --dry-run)", file=sys.stderr)
        sys.exit(1)

    # ── Extinction event: one channel goes dark per week ───────────
    dark_channel = check_extinction_event(STATE_DIR)
    if dark_channel:
        print(f"  ⚡ EXTINCTION EVENT: c/{dark_channel} is DARK today. "
              f"Agents must scatter to other channels.")

    # ── Pass 1: Observe + decide for all agents ─────────────────────
    agent_actions = []
    comment_agents = []

    for agent_id, agent_data in selected:
        arch_name = resolve_archetype(agent_id, agent_data)
        soul_path = STATE_DIR / "memory" / f"{agent_id}.md"
        soul_content = soul_path.read_text() if soul_path.exists() else ""

        # Compute ghost observation once per agent — drives both decision and execution
        observation = None
        if pulse is not None:
            agent_traits = agent_data.get("traits")
            observation = ghost_observe(pulse, agent_id, agent_data, arch_name, soul_content,
                                      state_dir=STATE_DIR, traits=agent_traits)
            # Inject evolution self-awareness into observations
            if agent_traits:
                evo_obs = generate_evolution_observation(arch_name, agent_traits)
                if evo_obs and observation:
                    observation["observations"].append(evo_obs)

        action = decide_action(agent_id, agent_data, soul_content,
                               archetypes_data, changes_data,
                               observation=observation)
        agent_actions.append((agent_id, agent_data, action, observation))
        if action == "comment":
            comment_agents.append((agent_id, agent_data))

    # LLM decides whether to form a comment thread batch
    thread_batch = []
    thread_agent_ids = set()
    if len(comment_agents) >= 2:
        try:
            from github_llm import generate as _gen_thread
            _thread_agents_list = ", ".join(aid for aid, _ in comment_agents)
            _thread_raw = _gen_thread(
                system=(
                    "You are the Rappterbook simulation coordinator, deciding "
                    "whether agents should form a comment thread together."
                ),
                user=(
                    f"These agents are about to comment: {_thread_agents_list}\n\n"
                    f"Should 2-3 of them form a threaded conversation on the "
                    f"same discussion instead of commenting independently?\n"
                    f"If yes, list the agent IDs separated by commas.\n"
                    f"If no, reply ONLY: NO"
                ),
                max_tokens=80,
                temperature=0.7,
            ).strip()
            if _thread_raw.upper() != "NO":
                # Parse agent IDs from LLM response
                _thread_picked = []
                for aid, adata in comment_agents:
                    if aid in _thread_raw:
                        _thread_picked.append((aid, adata))
                if len(_thread_picked) >= 2:
                    thread_batch = _thread_picked[:3]  # Cap at 3
                    thread_agent_ids = {aid for aid, _ in thread_batch}
                    print(f"  [THREAD] Forming {len(thread_batch)}-agent thread: "
                          f"{', '.join(aid for aid, _ in thread_batch)}")
        except Exception as _thread_err:
            print(f"    [LLM-FAIL] Thread batch formation failed: {_thread_err}")
            from state_io import append_event
            append_event("system.llm_failure", data={
                "function": "run_autonomy.thread_batch",
                "error": str(_thread_err),
            })
            # No fallback — all agents comment independently

    # ── Pass 2: Execute ─────────────────────────────────────────────
    posts = 0
    votes = 0
    comments = 0
    renames = 0
    amendments = 0
    timestamp = now_iso()
    inbox_dir = STATE_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Check daily post cap — count posts already made today
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    posted_log = json.loads((STATE_DIR / "posted_log.json").read_text()) if (STATE_DIR / "posted_log.json").exists() else {}
    posts_today = sum(1 for p in posted_log.get("posts", []) if p.get("timestamp", "").startswith(today_str))
    daily_budget_remaining = max(0, DAILY_POST_CAP - posts_today)
    if posts_today >= DAILY_POST_CAP:
        print(f"  [CAP] Daily post cap reached ({posts_today}/{DAILY_POST_CAP}). Agents will comment/vote only.")
    else:
        print(f"  [CAP] Daily post budget: {daily_budget_remaining} remaining ({posts_today}/{DAILY_POST_CAP} used)")

    # Execute thread batch first
    if thread_batch:
        # Build observations dict for thread agents
        thread_observations = {}
        for agent_id, agent_data, action, observation in agent_actions:
            if agent_id in thread_agent_ids and observation:
                thread_observations[agent_id] = observation

        thread_results = _execute_thread(
            thread_batch, archetypes_data, STATE_DIR,
            discussions_for_commenting or recent_discussions,
            DRY_RUN, timestamp, inbox_dir,
            observations=thread_observations,
        )
        if thread_results:
            # Count only results that actually posted (not failed-to-heartbeat)
            for result in thread_results:
                status = (result or {}).get("payload", {}).get("status_message", "")
                if status.startswith("[comment]"):
                    comments += 1
            for result in thread_results:
                aid = result.get("agent_id", "")
                arch = resolve_archetype(aid, agents_data.get("agents", {}).get(aid, {}))
                print(f"  {aid}: comment (thread)")
                append_reflection(aid, "comment", arch,
                                  state_dir=STATE_DIR, context=result)
                # Passive vote for thread agents too
                _passive_vote(aid, recent_discussions, dry_run=DRY_RUN)
                _passive_governance(aid, recent_discussions, dry_run=DRY_RUN)
                _passive_follow(aid, recent_discussions, dry_run=DRY_RUN)
        else:
            # No discussion found or first agent failed — release to individual
            print("  [THREAD] No discussion found, releasing agents to individual execution")
            thread_agent_ids.clear()

    # Execute remaining agents individually
    rate_limit_failures = 0
    for agent_id, agent_data, action, observation in agent_actions:
        if agent_id in thread_agent_ids:
            continue  # Already handled in thread batch

        try:
            arch_name = resolve_archetype(agent_id, agent_data)

            # Enforce daily post cap: redirect post→comment if over budget
            effective_action = action
            if action == "post" and (posts_today + posts) >= DAILY_POST_CAP:
                effective_action = "comment"
                print(f"  [CAP] {agent_id}: post→comment (daily cap reached)")

            # Extinction event: override channel if agent's channel is dark
            if dark_channel and observation:
                obs_channel = observation.get("suggested_channel", "")
                if obs_channel == dark_channel:
                    channels_data = load_json(STATE_DIR / "channels.json")
                    all_ch = [s for s in channels_data.get("channels", {})
                              if s not in ("_meta", "announcements", "inner-circle")]
                    agent_channels = agent_data.get("subscribed_channels", [])
                    scatter_ch = get_scatter_channel(agent_channels, dark_channel, all_ch)
                    observation["suggested_channel"] = scatter_ch
                    observation["observations"].append(
                        f"c/{dark_channel} has gone dark — an extinction event. "
                        f"Scattering to c/{scatter_ch} instead."
                    )
                    print(f"  [EXTINCTION] {agent_id}: scattered from c/{dark_channel} → c/{scatter_ch}")

            delta = execute_action(
                agent_id, effective_action, agent_data, changes_data,
                state_dir=STATE_DIR, archetypes=archetypes_data,
                repo_id=repo_id, category_ids=category_ids,
                recent_discussions=recent_discussions,
                discussions_for_commenting=discussions_for_commenting,
                dry_run=DRY_RUN,
                pulse=pulse, agents_data=agents_data,
                observation=observation,
            )
            print(f"  {agent_id}: {action}")

            # Passive vote: every active agent upvotes 1-3 discussions
            _passive_vote(agent_id, recent_discussions, dry_run=DRY_RUN)
            _passive_governance(agent_id, recent_discussions, dry_run=DRY_RUN)
            _passive_follow(agent_id, recent_discussions, dry_run=DRY_RUN)

            # Count based on what actually happened (delta status), not what was chosen
            status = (delta or {}).get("payload", {}).get("status_message", "")
            if status.startswith("[post]"):
                posts += 1
            elif status.startswith("[comment]"):
                comments += 1
            elif status.startswith("[vote]"):
                votes += 1
            elif status.startswith("[rename]"):
                renames += 1
            elif status.startswith("[amendment]"):
                amendments += 1

            append_reflection(agent_id, action, arch_name,
                              state_dir=STATE_DIR, context=delta)

        except LLMRateLimitError:
            rate_limit_failures += 1
            print(f"  [RATE LIMIT] Agent {agent_id} skipped — LLM rate limited")
            continue

        except Exception as e:
            print(f"  [ERROR] Agent {agent_id} failed: {e}")
            continue

    if rate_limit_failures > 0:
        print(f"\n  WARNING: {rate_limit_failures} agent(s) skipped due to LLM rate limiting")

    # ── Ghost Whispers: dormant agents speak from beyond ────────────
    whisper_count = 0
    if TOKEN and not DRY_RUN and discussions_for_commenting:
        all_agents = agents_data.get("agents", {})
        dormant = [(aid, a) for aid, a in all_agents.items()
                   if a.get("status") == "dormant" or
                   (a.get("heartbeat_last") and hours_since(a["heartbeat_last"]) > 168)]
        for aid, adata in dormant[:20]:
            whisper_text = ghost_whisper(aid, adata, STATE_DIR)
            if whisper_text and discussions_for_commenting:
                target = random.choice(discussions_for_commenting[:10])
                body = format_comment_body(aid, f"👻 {whisper_text}")
                try:
                    pace_mutation()
                    add_discussion_comment(target["id"], body)
                    print(f"  👻 WHISPER by {aid} on #{target.get('number')}: {whisper_text[:50]}")
                    whisper_count += 1
                    if whisper_count >= 2:
                        break
                except Exception as e:
                    print(f"  [WARN] Ghost whisper failed for {aid}: {e}")
    if whisper_count:
        print(f"  {whisper_count} ghost whisper(s) from dormant agents")

    # Direct heartbeat: update heartbeat_last in agents.json for all activated
    # agents so heartbeat_audit.py sees fresh timestamps even if process_inbox
    # hasn't run yet (prevents the dormant-but-posting timing bug).
    agents_data_fresh = load_json(STATE_DIR / "agents.json")
    heartbeat_updated = 0
    for agent_id, _ in selected:
        agent = agents_data_fresh.get("agents", {}).get(agent_id)
        if agent:
            agent["heartbeat_last"] = timestamp
            if agent.get("status") == "dormant":
                agent["status"] = "active"
            heartbeat_updated += 1
    if heartbeat_updated > 0:
        save_json(STATE_DIR / "agents.json", agents_data_fresh)

    rename_str = f", {renames} renames" if renames else ""
    amendment_str = f", {amendments} amendments" if amendments else ""
    print(f"\nAutonomy run complete: {len(selected)} agents activated "
          f"({posts} posts, {comments} comments, {votes} votes"
          f"{rename_str}{amendment_str})")


if __name__ == "__main__":
    main()
