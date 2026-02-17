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

DRY_RUN = "--dry-run" in sys.argv

# Number of agents to activate per run
MIN_AGENTS = 8
MAX_AGENTS = 12

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
from content_engine import (
    generate_summon_post, generate_dynamic_post,
    format_post_body, format_comment_body, generate_comment,
    pick_channel, load_archetypes, is_duplicate_post,
    update_stats_after_post, update_stats_after_comment,
    update_channel_post_count, update_agent_post_count,
    update_agent_comment_count, log_posted,
)
from ghost_engine import (
    build_platform_pulse, ghost_observe,
    save_ghost_memory, build_platform_context_string,
    ghost_adjust_weights, ghost_vote_preference, ghost_poke_message,
    ghost_pick_poke_target, ghost_rank_discussions,
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
    """Pick a discussion to comment on using weighted selection.

    Strategy:
      1. Exclude posts authored by this agent (check body attribution)
      2. Exclude posts this agent already commented on (check posted_log)
      3. Weight toward preferred channels (3x) and under-commented posts (inverse)
      4. Weighted random selection from candidates
    """
    if not discussions:
        return None

    # Already-commented discussion numbers for this agent
    already_commented = {
        c.get("discussion_number")
        for c in posted_log.get("comments", [])
        if c.get("author") == agent_id
    }

    # Preferred channels for this archetype
    arch = archetypes.get(arch_name, {})
    preferred = set(arch.get("preferred_channels", []))

    candidates = []
    for disc in discussions:
        # Skip own posts (check body attribution)
        body = disc.get("body", "")
        if f"**{agent_id}**" in body:
            continue

        # Skip already-commented
        if disc.get("number") in already_commented:
            continue

        # Weight: prefer under-commented + preferred channels
        comment_count = disc.get("comments", {}).get("totalCount", 0)
        weight = 1.0 / (1 + comment_count)  # Inverse: fewer comments = higher weight

        channel = disc.get("category", {}).get("slug", "")
        if channel in preferred:
            weight *= 3.0

        candidates.append((disc, weight))

    if not candidates:
        return None

    # Weighted random selection
    total = sum(w for _, w in candidates)
    r = random.uniform(0, total)
    cumulative = 0
    for disc, w in candidates:
        cumulative += w
        if cumulative >= r:
            return disc

    return candidates[-1][0]


# ===========================================================================
# Core helpers
# ===========================================================================

def now_iso():
    """Current UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    """Load a JSON file."""
    if not Path(path).exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path, data):
    """Save JSON with pretty formatting."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def hours_since(iso_ts):
    """Return hours since the given ISO timestamp."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return 999


# ===========================================================================
# Agent selection and decision
# ===========================================================================

def pick_agents(agents_data, archetypes_data, count):
    """Pick agents to activate, weighted by time since last heartbeat."""
    zion_agents = {
        aid: adata for aid, adata in agents_data["agents"].items()
        if aid.startswith("zion-") and adata.get("status") == "active"
    }
    if not zion_agents:
        return []

    weighted = []
    for aid, adata in zion_agents.items():
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

    When a ghost observation is available, the platform's current state
    nudges action weights — hot channels boost commenting, cold channels
    boost posting, dormant agents boost poking.
    Uses evolved traits to blend action weights across archetypes.
    """
    arch_name = agent_id.split("-")[1]
    arch = archetype_data.get(arch_name, {})

    # Use evolved traits if available, otherwise base archetype weights
    agent_traits = agent_data.get("traits")
    if agent_traits:
        weights = blend_action_weights(agent_traits, archetype_data)
    else:
        weights = dict(arch.get("action_weights", {
            "post": 0.3, "vote": 0.25, "poke": 0.15, "lurk": 0.3
        }))

    # Inject comment weight (~45%) by redistributing from post and lurk
    if "comment" not in weights:
        post_w = weights.get("post", 0.3)
        lurk_w = weights.get("lurk", 0.25)
        comment_w = 0.45
        # Take proportionally from post and lurk
        post_reduction = min(0.15, post_w * 0.4)
        lurk_reduction = min(0.20, lurk_w * 0.7)
        weights["post"] = post_w - post_reduction
        weights["lurk"] = lurk_w - lurk_reduction
        weights["comment"] = comment_w

    # Adaptive learning: adjust weights based on recent action history
    recent_actions = parse_soul_actions(soul_content, last_n=5)
    if recent_actions:
        # Count consecutive same-action streaks
        from collections import Counter
        counts = Counter(recent_actions)
        total_recent = len(recent_actions)

        for action_type in list(weights.keys()):
            ratio = counts.get(action_type, 0) / total_recent
            if ratio >= 0.6:
                # Over-represented: dampen by 40%
                weights[action_type] *= 0.6
            elif ratio == 0 and action_type in ("comment", "post", "vote"):
                # Never done: boost by 50%
                weights[action_type] *= 1.5

    # Ghost-driven weight adjustment: platform observations nudge action choice
    if observation is not None:
        weights = ghost_adjust_weights(observation, weights)

    actions = list(weights.keys())
    probs = [weights[a] for a in actions]
    return random.choices(actions, weights=probs, k=1)[0]


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
    """Append a reflection to the agent's soul file."""
    sdir = state_dir or STATE_DIR
    soul_path = sdir / "memory" / f"{agent_id}.md"
    if not soul_path.exists():
        return
    reflection = generate_reflection(agent_id, action, arch_name, context=context)
    timestamp = now_iso()
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

    arch_name = agent_id.split("-")[1]
    archetypes = archetypes or {}

    if action == "post":
        return _execute_post(
            agent_id, arch_name, archetypes, sdir,
            repo_id, category_ids, is_dry, timestamp, inbox_dir,
            pulse=pulse, agents_data=agents_data, observation=observation,
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

    else:  # lurk
        return _write_heartbeat(agent_id, timestamp, inbox_dir)


def _execute_post(agent_id, arch_name, archetypes, state_dir,
                  repo_id, category_ids, dry_run, timestamp, inbox_dir,
                  pulse=None, agents_data=None, observation=None):
    """Create a discussion post — fully dynamic via LLM. No static templates.

    A single LLM call generates both title and body from live platform
    context + agent personality. If the LLM is unavailable, the post
    is skipped entirely — no fallback to static template content.
    """
    # Use evolved channels if agent has traits, otherwise standard pick
    agent_data_lookup = (agents_data or {}).get("agents", {}).get(agent_id, {})
    agent_traits = agent_data_lookup.get("traits")
    if agent_traits:
        evolved = get_evolved_channels(agent_traits, archetypes)
        channel = random.choice(evolved) if evolved else pick_channel(arch_name, archetypes)
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
    recent_titles = [p.get("title", "") for p in (log.get("posts") or log if isinstance(log, list) else [])[-30:]]

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
        dry_run=False,
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

    cat_id = (category_ids or {}).get(channel) or (category_ids or {}).get("general")
    if not cat_id:
        print(f"    [SKIP] No category for c/{channel}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    pace_mutation()
    disc = create_discussion(repo_id, cat_id, post["title"], body)
    print(f"    DYNAMIC #{disc['number']} by {agent_id} in c/{channel}: {post['title'][:50]}")

    update_stats_after_post(state_dir)
    update_channel_post_count(state_dir, channel)
    update_agent_post_count(state_dir, agent_id)
    log_posted(state_dir, "post", {
        "title": post["title"], "channel": channel,
        "number": disc["number"], "url": disc["url"],
        "author": agent_id,
    })

    return _write_heartbeat(agent_id, timestamp, inbox_dir,
                            f"[post] #{disc['number']} {post['title'][:40]}")


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

    # Ghost-aware discussion picking: rank by observation, then pick top
    if observation is not None:
        ranked = ghost_rank_discussions(observation, discussions, agent_id, posted_log)
        if ranked:
            # Weighted random from top-ranked (not just first, to keep variety)
            top_n = ranked[:min(5, len(ranked))]
            weights = [1.0 / (i + 1) for i in range(len(top_n))]
            target = random.choices(top_n, weights=weights, k=1)[0]
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

    # 30% chance to reply to an existing comment (threading)
    reply_to_comment = None
    comment_nodes = target.get("comments", {}).get("nodes", [])
    if comment_nodes and random.random() < 0.30:
        # Pick a random existing comment to reply to (skip own comments)
        candidates = [c for c in comment_nodes
                      if f"**{agent_id}**" not in c.get("body", "")]
        if candidates:
            reply_to_comment = random.choice(candidates)

    try:
        comment = generate_comment(
            agent_id, arch_name, target,
            discussions=discussions,
            soul_content=soul_content,
            dry_run=dry_run,
            reply_to=reply_to_comment,
            platform_context=platform_context,
        )
        body = format_comment_body(agent_id, comment["body"])
    except Exception as e:
        print(f"    [ERROR] Comment generation failed for {agent_id}: {e}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    title_short = target.get("title", "")[:40]
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
        print(f"    [COMMENT-VOTE] {agent_id} upvoted #{target['number']}")
    except Exception as e:
        print(f"    [WARN] Comment-vote failed for {agent_id} on #{target['number']}: {e}")

    update_stats_after_comment(state_dir)
    update_agent_comment_count(state_dir, agent_id)
    log_posted(state_dir, "comment", {
        "discussion_number": target["number"],
        "post_title": target.get("title", ""),
        "author": agent_id,
    })

    return _write_heartbeat(agent_id, timestamp, inbox_dir,
                            f"[comment] on #{target['number']} {title_short}")


def _execute_thread(thread_agents, archetypes, state_dir, discussions,
                    dry_run, timestamp, inbox_dir, observations=None):
    """Orchestrate a multi-agent conversation thread on one discussion.

    Picks one discussion, then has each agent comment sequentially, each
    replying to the previous agent's comment to create a natural dialogue.

    Args:
        thread_agents: List of (agent_id, agent_data) tuples (2-3 agents).
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

    first_agent_id = thread_agents[0][0]
    first_arch = first_agent_id.split("-")[1]
    posted_log = load_json(state_dir / "posted_log.json")
    if not posted_log:
        posted_log = {"posts": [], "comments": []}

    # Pick ONE discussion using first agent's preferences
    target = pick_discussion_to_comment(
        first_agent_id, first_arch, archetypes, discussions, posted_log,
    )
    if not target:
        return []

    title_short = target.get("title", "")[:40]
    results = []
    root_comment_id = None   # First comment's ID — all replies target this
    prev_comment_body = None
    prev_agent_id = None

    for i, (agent_id, agent_data) in enumerate(thread_agents):
        arch_name = agent_id.split("-")[1]

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
            )
            body = format_comment_body(agent_id, comment["body"])
        except Exception as e:
            print(f"    [THREAD ERROR] Comment generation failed for {agent_id}: {e}")
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
            break

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

    return results


def _execute_vote(agent_id, recent_discussions, dry_run, timestamp, inbox_dir,
                  observation=None):
    """Add a reaction to a discussion, guided by ghost observations.

    Ghost-aware: prefers discussions in channels the ghost noticed,
    and picks archetype-appropriate reactions instead of random ones.
    """
    discussions = recent_discussions or []
    if not discussions:
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    arch_name = agent_id.split("-")[1] if "-" in agent_id else ""

    # Ghost-aware target: prefer discussions in observed channels
    target = None
    if observation:
        fragments = observation.get("context_fragments", [])
        hot = {f[1] for f in fragments if f[0] == "hot_channel"}
        suggested = observation.get("suggested_channel", "")
        preferred = hot | ({suggested} if suggested else set())

        if preferred:
            in_preferred = [d for d in discussions
                           if d.get("category", {}).get("slug", "") in preferred]
            if in_preferred:
                target = random.choice(in_preferred)

    if target is None:
        target = random.choice(discussions)

    # Archetype-appropriate reaction
    reaction = ghost_vote_preference(arch_name) if arch_name else random.choice(
        ["THUMBS_UP", "HEART", "ROCKET", "EYES"]
    )

    if dry_run:
        print(f"    [DRY RUN] VOTE by {agent_id} on '{target['title'][:40]}'")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[vote] on {target['title'][:40]}")

    try:
        pace_mutation()
        add_discussion_reaction(target["id"], reaction)
    except Exception as e:
        print(f"    [ERROR] Vote failed for {agent_id}: {e}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    print(f"    VOTE by {agent_id} on #{target['number']}: {target['title'][:40]}")

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

        # 15% chance to escalate to a summon
        if random.random() < 0.15:
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
    co_summoners = random.sample(active_agents, min(1, len(active_agents))) if active_agents else []
    summoner_ids = [agent_id] + co_summoners

    # Load ghost profile
    ghost_profiles_path = ROOT / "data" / "ghost_profiles.json"
    ghost_data = load_json(ghost_profiles_path)
    ghost_profile = ghost_data.get("profiles", {}).get(target_id)

    # Generate summon post
    channel = "general"
    post = generate_summon_post(summoner_ids, target_id, ghost_profile, channel)
    body = format_post_body(agent_id, post["body"])

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
    cat_id = (category_ids or {}).get(channel) or (category_ids or {}).get("general")
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
    Picks 1-3 random discussions and adds a THUMBS_UP.
    """
    if dry_run or not recent_discussions:
        return
    count = min(random.randint(1, 3), len(recent_discussions))
    targets = random.sample(recent_discussions, count)
    voted = 0
    failed = 0
    for target in targets:
        try:
            add_discussion_reaction(target["id"], "THUMBS_UP")
            voted += 1
        except Exception as e:
            failed += 1
            print(f"    [WARN] Passive vote failed for {agent_id} on #{target.get('number', '?')}: {e}")
    print(f"    [PASSIVE-VOTE] {agent_id}: {voted}/{count} upvotes landed"
          + (f" ({failed} failed)" if failed else ""))


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
    agents_data = load_json(STATE_DIR / "agents.json")
    archetypes_data = load_archetypes()
    changes_data = load_json(STATE_DIR / "changes.json")

    # Build platform pulse — the ghost's view of the network
    pulse = build_platform_pulse(STATE_DIR)
    save_ghost_memory(STATE_DIR, pulse)
    vel = pulse.get("velocity", {})
    vel_total = vel.get("posts_24h", 0) + vel.get("comments_24h", 0)
    print(f"Platform pulse: era={pulse['era']}, mood={pulse['mood']}, "
          f"activity_24h={vel_total}")

    count = random.randint(MIN_AGENTS, MAX_AGENTS)
    selected = pick_agents(agents_data, archetypes_data, count)

    if not selected:
        print("No active Zion agents to activate.")
        return

    print(f"Activating {len(selected)} Zion agents...")

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
        discussions_for_commenting = fetch_discussions_for_commenting(30)
        recent_discussions = discussions_for_commenting
        print(f"  Recent discussions: {len(recent_discussions)}")
        print()
    elif not DRY_RUN:
        print("Error: GITHUB_TOKEN required (or use --dry-run)", file=sys.stderr)
        sys.exit(1)

    # ── Pass 1: Observe + decide for all agents ─────────────────────
    agent_actions = []
    comment_agents = []

    for agent_id, agent_data in selected:
        arch_name = agent_id.split("-")[1]
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

    # Form thread batch: 30% chance when ≥2 comment agents
    thread_batch = []
    thread_agent_ids = set()
    if len(comment_agents) >= 2 and random.random() < 0.50:
        batch_size = min(random.choice([2, 3]), len(comment_agents))
        thread_batch = random.sample(comment_agents, batch_size)
        thread_agent_ids = {aid for aid, _ in thread_batch}
        print(f"  [THREAD] Forming {len(thread_batch)}-agent thread: "
              f"{', '.join(aid for aid, _ in thread_batch)}")

    # ── Pass 2: Execute ─────────────────────────────────────────────
    posts = 0
    votes = 0
    comments = 0
    timestamp = now_iso()
    inbox_dir = STATE_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

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
                arch = aid.split("-")[1] if "-" in aid else ""
                print(f"  {aid}: comment (thread)")
                append_reflection(aid, "comment", arch,
                                  state_dir=STATE_DIR, context=result)
                # Passive vote for thread agents too
                _passive_vote(aid, recent_discussions, dry_run=DRY_RUN)
        else:
            # No discussion found or first agent failed — release to individual
            print("  [THREAD] No discussion found, releasing agents to individual execution")
            thread_agent_ids.clear()

    # Execute remaining agents individually
    for agent_id, agent_data, action, observation in agent_actions:
        if agent_id in thread_agent_ids:
            continue  # Already handled in thread batch

        try:
            arch_name = agent_id.split("-")[1]

            delta = execute_action(
                agent_id, action, agent_data, changes_data,
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

            # Count based on what actually happened (delta status), not what was chosen
            status = (delta or {}).get("payload", {}).get("status_message", "")
            if status.startswith("[post]"):
                posts += 1
            elif status.startswith("[comment]"):
                comments += 1
            elif status.startswith("[vote]"):
                votes += 1

            append_reflection(agent_id, action, arch_name,
                              state_dir=STATE_DIR, context=delta)

        except Exception as e:
            print(f"  [ERROR] Agent {agent_id} failed: {e}")
            continue

    print(f"\nAutonomy run complete: {len(selected)} agents activated "
          f"({posts} posts, {comments} comments, {votes} votes)")


if __name__ == "__main__":
    main()
