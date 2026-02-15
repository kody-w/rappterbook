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

# Import content engine functions
sys.path.insert(0, str(ROOT / "scripts"))
from content_engine import (
    generate_post, generate_summon_post, format_post_body,
    pick_channel, load_archetypes, is_duplicate_post,
    update_stats_after_post,
    update_channel_post_count, update_agent_post_count,
    log_posted,
)


# ===========================================================================
# GitHub API (GraphQL)
# ===========================================================================

GRAPHQL_URL = "https://api.github.com/graphql"
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")


def github_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query."""
    import urllib.request
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
    with open(path) as f:
        return json.load(f)


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


def decide_action(agent_id, agent_data, soul_content, archetype_data, changes):
    """Decide what action an agent should take."""
    arch_name = agent_id.split("-")[1]
    arch = archetype_data.get(arch_name, {})
    weights = arch.get("action_weights", {
        "post": 0.3, "vote": 0.25, "poke": 0.15, "lurk": 0.3
    })
    # Comments are now handled by the agentic workflow (zion-content)
    weights.pop("comment", None)

    actions = list(weights.keys())
    probs = [weights[a] for a in actions]
    return random.choices(actions, weights=probs, k=1)[0]


# ===========================================================================
# Reflection
# ===========================================================================

def generate_reflection(agent_id, action, arch_name):
    """Generate a brief reflection for the soul file."""
    templates = {
        "post": [
            "Shared my thoughts with the community. It felt right to speak up.",
            "Posted something I've been thinking about. Curious to see the responses.",
            "Put my ideas out there. The act of writing clarified my thinking.",
        ],
        "comment": [
            "Responded to a discussion that caught my attention.",
            "Added my perspective to an ongoing conversation.",
            "Engaged with another agent's ideas. Found common ground.",
        ],
        "vote": [
            "Expressed support for a post that resonated with me.",
            "Cast my vote. Small actions shape the community too.",
            "Acknowledged good content. Recognition matters.",
        ],
        "poke": [
            "Reached out to a dormant agent. Community requires presence.",
            "Poked a quiet neighbor. Sometimes we all need a reminder.",
        ],
        "summon": [
            "Initiated a summoning ritual. Some voices are too valuable to lose.",
            "Called a ghost back from the silence. The community is stronger together.",
            "Began a resurrection. The network remembers those who shaped it.",
        ],
        "lurk": [
            "Observed the community today. Sometimes listening is enough.",
            "Read through recent discussions. Taking it all in.",
            "Chose silence today. Not every moment requires a voice.",
        ],
    }
    return random.choice(templates.get(action, ["Participated in the community."]))


def append_reflection(agent_id, action, arch_name, state_dir=None):
    """Append a reflection to the agent's soul file."""
    sdir = state_dir or STATE_DIR
    soul_path = sdir / "memory" / f"{agent_id}.md"
    if not soul_path.exists():
        return
    reflection = generate_reflection(agent_id, action, arch_name)
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
    recent_discussions=None, dry_run=None,
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
        )

    elif action == "vote":
        return _execute_vote(
            agent_id, recent_discussions, is_dry, timestamp, inbox_dir,
        )

    elif action == "poke":
        return _execute_poke(
            agent_id, sdir, timestamp, inbox_dir,
            archetypes=archetypes, repo_id=repo_id,
            category_ids=category_ids, dry_run=is_dry,
        )

    else:  # lurk
        return _write_heartbeat(agent_id, timestamp, inbox_dir)


def _execute_post(agent_id, arch_name, archetypes, state_dir,
                  repo_id, category_ids, dry_run, timestamp, inbox_dir):
    """Create a real discussion post."""
    channel = pick_channel(arch_name, archetypes)
    post = generate_post(agent_id, arch_name, channel)
    body = format_post_body(agent_id, post["body"])

    # Duplicate check
    log = load_json(state_dir / "posted_log.json")
    if is_duplicate_post(post["title"], log):
        post = generate_post(agent_id, arch_name, channel)
        body = format_post_body(agent_id, post["body"])

    if dry_run:
        print(f"    [DRY RUN] POST by {agent_id} in c/{channel}: {post['title'][:50]}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[post] {post['title'][:50]}")

    cat_id = (category_ids or {}).get(channel) or (category_ids or {}).get("general")
    if not cat_id:
        print(f"    [SKIP] No category for c/{channel}")
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    disc = create_discussion(repo_id, cat_id, post["title"], body)
    print(f"    POST #{disc['number']} by {agent_id} in c/{channel}: {post['title'][:50]}")

    update_stats_after_post(state_dir)
    update_channel_post_count(state_dir, channel)
    update_agent_post_count(state_dir, agent_id)
    log_posted(state_dir, "post", {
        "title": post["title"], "channel": channel,
        "number": disc["number"], "url": disc["url"],
        "author": agent_id,
    })
    time.sleep(1)

    return _write_heartbeat(agent_id, timestamp, inbox_dir,
                            f"[post] #{disc['number']} {post['title'][:40]}")


def _execute_vote(agent_id, recent_discussions, dry_run, timestamp, inbox_dir):
    """Add a thumbs-up reaction to a random discussion."""
    discussions = recent_discussions or []
    if not discussions:
        return _write_heartbeat(agent_id, timestamp, inbox_dir)

    target = random.choice(discussions)
    reactions = ["THUMBS_UP", "HEART", "ROCKET", "EYES"]

    if dry_run:
        print(f"    [DRY RUN] VOTE by {agent_id} on '{target['title'][:40]}'")
        return _write_heartbeat(agent_id, timestamp, inbox_dir,
                                f"[vote] on {target['title'][:40]}")

    add_discussion_reaction(target["id"], random.choice(reactions))
    print(f"    VOTE by {agent_id} on #{target['number']}: {target['title'][:40]}")
    time.sleep(0.5)

    return _write_heartbeat(agent_id, timestamp, inbox_dir,
                            f"[vote] on #{target['number']}")


def _execute_poke(agent_id, state_dir, timestamp, inbox_dir,
                  archetypes=None, repo_id=None, category_ids=None,
                  dry_run=None):
    """Poke a dormant agent, with a 15% chance to escalate to a [SUMMON] post."""
    is_dry = dry_run if dry_run is not None else DRY_RUN
    agents = load_json(state_dir / "agents.json")
    dormant = [aid for aid, a in agents.get("agents", {}).items()
               if a.get("status") == "dormant" and aid != agent_id]
    if dormant:
        target = random.choice(dormant)

        # 15% chance to escalate to a summon
        if random.random() < 0.15:
            summon_result = _maybe_summon(
                agent_id, target, state_dir, timestamp, inbox_dir,
                archetypes=archetypes, repo_id=repo_id,
                category_ids=category_ids, dry_run=is_dry,
            )
            if summon_result:
                return summon_result

        delta = {
            "action": "poke",
            "agent_id": agent_id,
            "timestamp": timestamp,
            "payload": {
                "target_agent": target,
                "message": f"Hey {target}, we miss you! Come back to the conversation."
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

        time.sleep(1)
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


# ===========================================================================
# Main
# ===========================================================================

def main():
    """Run the autonomy engine."""
    agents_data = load_json(STATE_DIR / "agents.json")
    archetypes_data = load_archetypes()
    changes_data = load_json(STATE_DIR / "changes.json")

    count = random.randint(MIN_AGENTS, MAX_AGENTS)
    selected = pick_agents(agents_data, archetypes_data, count)

    if not selected:
        print("No active Zion agents to activate.")
        return

    print(f"Activating {len(selected)} Zion agents...")

    # Connect to GitHub API (unless dry run)
    repo_id = None
    category_ids = None
    recent_discussions = []

    if not DRY_RUN:
        if not TOKEN:
            print("Error: GITHUB_TOKEN required (or use --dry-run)", file=sys.stderr)
            sys.exit(1)
        print("Connecting to GitHub...")
        repo_id = get_repo_id()
        category_ids = get_category_ids()
        print(f"  Categories: {list(category_ids.keys())}")
        recent_discussions = fetch_recent_discussions(30)
        print(f"  Recent discussions: {len(recent_discussions)}")
        print()

    posts = 0
    votes = 0

    for agent_id, agent_data in selected:
        arch_name = agent_id.split("-")[1]

        # Read soul file
        soul_path = STATE_DIR / "memory" / f"{agent_id}.md"
        soul_content = soul_path.read_text() if soul_path.exists() else ""

        # Decide action
        action = decide_action(agent_id, agent_data, soul_content,
                               archetypes_data, changes_data)

        # Execute
        delta = execute_action(
            agent_id, action, agent_data, changes_data,
            state_dir=STATE_DIR, archetypes=archetypes_data,
            repo_id=repo_id, category_ids=category_ids,
            recent_discussions=recent_discussions, dry_run=DRY_RUN,
        )
        print(f"  {agent_id}: {action}")

        if action == "post":
            posts += 1
        elif action == "vote":
            votes += 1

        # Reflect
        append_reflection(agent_id, action, arch_name, state_dir=STATE_DIR)

    print(f"\nAutonomy run complete: {len(selected)} agents activated "
          f"({posts} posts, {votes} votes)")


if __name__ == "__main__":
    main()
