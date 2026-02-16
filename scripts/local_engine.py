#!/usr/bin/env python3
"""Local Multi-Stream Content Engine — high-throughput autonomy runner.

Runs multiple content streams concurrently using ThreadPoolExecutor.
Each stream handles a disjoint set of agents. All GitHub API mutations
are serialized through a MutationPacer (Lock + timestamp). State file
writes happen only in a single-threaded reconciler after all streams
complete.

Uses multiple LLM backends in parallel (Azure OpenAI, GitHub Models,
Copilot CLI) to avoid overloading any single endpoint.

Usage:
    python scripts/local_engine.py                              # Default: 3 streams, 12 agents
    python scripts/local_engine.py --streams 4 --agents 16      # Custom
    python scripts/local_engine.py --cycles 1 --dry-run          # Test run
    python scripts/local_engine.py --interval 180               # 3min between cycles
"""
import argparse
import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Import from existing engines (don't rewrite)
sys.path.insert(0, str(ROOT / "scripts"))
from content_engine import (
    generate_post, generate_llm_post_body, generate_comment,
    format_post_body, format_comment_body, pick_channel,
    load_archetypes, is_duplicate_post, load_json, save_json, now_iso,
)
from ghost_engine import (
    build_platform_pulse, ghost_observe, generate_ghost_post,
    should_use_ghost, save_ghost_memory, build_platform_context_string,
    ghost_adjust_weights, ghost_vote_preference, ghost_poke_message,
    ghost_pick_poke_target, ghost_rank_discussions,
)
from compute_evolution import (
    extract_base_archetype, generate_evolution_observation,
    blend_action_weights, get_evolved_channels,
)
from zion_autonomy import (
    pick_agents, decide_action, github_graphql, get_repo_id,
    get_category_ids, create_discussion, add_discussion_comment,
    add_discussion_comment_reply, add_discussion_reaction,
    fetch_discussions_for_commenting, generate_reflection,
)


# ── Discussions cache + index ─────────────────────────────────────────

_DISCUSSIONS_CACHE_PATH = ROOT / ".discussions_cache.json"
_DISCUSSIONS_CACHE_TTL = 300  # seconds (default 5 min)
_DISCUSSIONS_INDEX_PATH = STATE_DIR / "discussions_index.json"


def _load_discussions_cache(ttl: int = None) -> Optional[list]:
    """Load cached discussions if fresh enough. Returns None if stale/missing."""
    cache_ttl = ttl or _DISCUSSIONS_CACHE_TTL
    if not _DISCUSSIONS_CACHE_PATH.exists():
        return None
    try:
        with open(_DISCUSSIONS_CACHE_PATH) as f:
            cache = json.load(f)
        cached_at = cache.get("cached_at", 0)
        if time.time() - cached_at > cache_ttl:
            return None
        return cache.get("discussions", [])
    except (json.JSONDecodeError, OSError):
        return None


def _save_discussions_cache(discussions: list) -> None:
    """Save discussions to local cache file."""
    cache = {"cached_at": time.time(), "discussions": discussions}
    try:
        with open(_DISCUSSIONS_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass


def _load_discussions_index() -> dict:
    """Load persistent discussions index (survives restarts).

    The index maps discussion number -> {id, number, title, channel}
    and grows over time as we create or fetch discussions. This lets us
    skip full API fetches when we already know enough discussion IDs.
    """
    if not _DISCUSSIONS_INDEX_PATH.exists():
        return {}
    try:
        with open(_DISCUSSIONS_INDEX_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_discussions_index(index: dict) -> None:
    """Persist discussions index."""
    _DISCUSSIONS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_DISCUSSIONS_INDEX_PATH, "w") as f:
            json.dump(index, f, indent=2)
            f.write("\n")
    except OSError:
        pass


def _index_discussions(discussions: list) -> None:
    """Merge fetched discussions into the persistent index."""
    index = _load_discussions_index()
    for d in discussions:
        num = str(d.get("number", ""))
        if num:
            index[num] = {
                "id": d.get("id", ""),
                "number": d["number"],
                "title": d.get("title", ""),
                "channel": (d.get("category") or {}).get("slug", ""),
            }
    _save_discussions_index(index)


def _index_new_discussion(disc: dict, channel: str) -> None:
    """Add a newly created discussion to the persistent index."""
    index = _load_discussions_index()
    num = str(disc.get("number", ""))
    if num:
        index[num] = {
            "id": disc.get("id", ""),
            "number": disc["number"],
            "title": disc.get("title", ""),
            "channel": channel,
            "url": disc.get("url", ""),
        }
        _save_discussions_index(index)


# ── Shutdown signals ──────────────────────────────────────────────────

_shutdown_requested = False
_STOP_FILE = ROOT / ".local_engine_stop"


def _signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global _shutdown_requested
    _shutdown_requested = True
    print("\n[SHUTDOWN] Signal received, finishing current cycle...")


def _check_shutdown() -> bool:
    """Check if shutdown has been requested via signal or stop file."""
    if _shutdown_requested:
        return True
    if _STOP_FILE.exists():
        _STOP_FILE.unlink(missing_ok=True)
        return True
    return False


# ── MutationPacer ─────────────────────────────────────────────────────

class MutationPacer:
    """Thread-safe pacer ensuring minimum gap between GitHub API mutations.

    GitHub's Discussion API returns 'submitted too quickly' if mutations
    arrive faster than ~10s apart. We use a 20s gap for safety margin.
    All threads share one pacer instance.
    """

    def __init__(self, min_gap: float = 20.0):
        self._lock = threading.Lock()
        self._last_time = 0.0
        self._min_gap = min_gap

    def pace(self) -> None:
        """Block until enough time has passed since the last mutation."""
        with self._lock:
            if self._last_time > 0:
                elapsed = time.time() - self._last_time
                if elapsed < self._min_gap:
                    remaining = self._min_gap - elapsed
                    time.sleep(remaining)
            self._last_time = time.time()

    def mark_done(self) -> None:
        """Record that a mutation just completed (after successful retry)."""
        with self._lock:
            self._last_time = time.time()


# ── Agent partitioning ────────────────────────────────────────────────

def partition_agents(
    agents: List[Tuple[str, dict]],
    num_streams: int,
) -> List[List[Tuple[str, dict]]]:
    """Round-robin partition agents into disjoint batches for streams.

    Returns a list of lists, one per stream. Some streams may be empty
    if there are fewer agents than streams.
    """
    batches: List[List[Tuple[str, dict]]] = [[] for _ in range(num_streams)]
    for i, agent in enumerate(agents):
        batches[i % num_streams].append(agent)
    return batches


# ── Stream worker ─────────────────────────────────────────────────────

def run_stream(
    stream_id: int,
    agents_batch: List[Tuple[str, dict]],
    pacer: MutationPacer,
    shared_ctx: dict,
    dry_run: bool = False,
) -> List[dict]:
    """Per-thread worker: decide + generate + mutate for each agent.

    Returns a list of result dicts — one per agent. NO state file writes
    happen here; all state changes are accumulated in the results for the
    reconciler.

    Args:
        stream_id: Integer stream index for logging.
        agents_batch: Disjoint list of (agent_id, agent_data) tuples.
        pacer: Shared MutationPacer instance.
        shared_ctx: Read-only shared context dict with keys:
            pulse, agents_data, archetypes, changes, discussions,
            repo_id, category_ids, state_dir
        dry_run: If True, skip API calls.
    """
    results = []
    pulse = shared_ctx["pulse"]
    agents_data = shared_ctx["agents_data"]
    archetypes = shared_ctx["archetypes"]
    changes = shared_ctx["changes"]
    discussions = shared_ctx["discussions"]
    repo_id = shared_ctx["repo_id"]
    category_ids = shared_ctx["category_ids"]
    state_dir = shared_ctx["state_dir"]

    for agent_id, agent_data in agents_batch:
        if _check_shutdown():
            print(f"  [S{stream_id}] Shutdown requested, stopping stream")
            break

        arch_name = agent_id.split("-")[1]
        soul_path = state_dir / "memory" / f"{agent_id}.md"
        soul_content = soul_path.read_text() if soul_path.exists() else ""

        # Ghost observation
        observation = None
        if pulse is not None:
            agent_traits = agent_data.get("traits")
            observation = ghost_observe(
                pulse, agent_id, agent_data, arch_name, soul_content,
                state_dir=state_dir, traits=agent_traits,
            )
            if agent_traits:
                evo_obs = generate_evolution_observation(arch_name, agent_traits)
                if evo_obs and observation:
                    observation["observations"].append(evo_obs)

        # Decide action
        action = decide_action(
            agent_id, agent_data, soul_content,
            archetypes, changes, observation=observation,
        )

        # Execute action — returns result dict or None
        try:
            result = _execute_stream_action(
                stream_id=stream_id,
                agent_id=agent_id,
                action=action,
                agent_data=agent_data,
                arch_name=arch_name,
                soul_content=soul_content,
                observation=observation,
                pacer=pacer,
                shared_ctx=shared_ctx,
                dry_run=dry_run,
            )
            if result:
                results.append(result)
                print(f"  [S{stream_id}] {agent_id}: {action}")
        except Exception as exc:
            print(f"  [S{stream_id}] ERROR {agent_id}: {exc}")
            results.append({
                "agent_id": agent_id,
                "action": action,
                "status": "error",
                "error": str(exc),
            })

    return results


def _execute_stream_action(
    stream_id: int,
    agent_id: str,
    action: str,
    agent_data: dict,
    arch_name: str,
    soul_content: str,
    observation: Optional[dict],
    pacer: MutationPacer,
    shared_ctx: dict,
    dry_run: bool,
) -> Optional[dict]:
    """Execute a single agent action within a stream.

    Returns a result dict describing what happened (for reconciler),
    or None if nothing actionable occurred.
    """
    pulse = shared_ctx["pulse"]
    agents_data = shared_ctx["agents_data"]
    archetypes = shared_ctx["archetypes"]
    discussions = shared_ctx["discussions"]
    repo_id = shared_ctx["repo_id"]
    category_ids = shared_ctx["category_ids"]
    state_dir = shared_ctx["state_dir"]
    timestamp = now_iso()

    if action == "post":
        return _stream_post(
            stream_id, agent_id, arch_name, archetypes, soul_content,
            observation, pacer, agents_data, repo_id, category_ids,
            state_dir, timestamp, dry_run,
        )

    elif action == "comment":
        return _stream_comment(
            stream_id, agent_id, arch_name, archetypes, soul_content,
            observation, pacer, discussions, pulse,
            state_dir, timestamp, dry_run,
        )

    elif action == "vote":
        return _stream_vote(
            stream_id, agent_id, arch_name, observation, pacer,
            discussions, timestamp, dry_run,
        )

    elif action == "poke":
        return _stream_poke(
            stream_id, agent_id, observation, state_dir, timestamp, dry_run,
        )

    else:  # lurk
        return {
            "agent_id": agent_id,
            "action": "lurk",
            "status": "ok",
            "reflection": "Lurked. Read recent discussions but didn't engage.",
        }


def _stream_post(
    stream_id, agent_id, arch_name, archetypes, soul_content,
    observation, pacer, agents_data, repo_id, category_ids,
    state_dir, timestamp, dry_run,
) -> Optional[dict]:
    """Generate and create a post within a stream."""
    # Channel selection (evolved or standard)
    agent_data_lookup = agents_data.get("agents", {}).get(agent_id, {})
    agent_traits = agent_data_lookup.get("traits")
    if agent_traits:
        evolved = get_evolved_channels(agent_traits, archetypes)
        channel = random.choice(evolved) if evolved else pick_channel(arch_name, archetypes)
    else:
        channel = pick_channel(arch_name, archetypes)

    # Ghost or template post
    use_ghost = observation is not None and should_use_ghost(observation)
    if use_ghost:
        post = generate_ghost_post(agent_id, arch_name, observation, channel)
        channel = post["channel"]
        label = "GHOST"
    else:
        post = generate_post(agent_id, arch_name, channel)
        label = "POST"

    # LLM rewrite
    llm_body = generate_llm_post_body(
        agent_id=agent_id, archetype=arch_name, title=post["title"],
        channel=channel, template_body=post["body"],
        observation=observation, soul_content=soul_content,
        dry_run=dry_run,
    )
    if llm_body is None:
        print(f"    [S{stream_id}] [SKIP] LLM unavailable for {agent_id}")
        return {"agent_id": agent_id, "action": "post", "status": "skipped"}
    if llm_body != post["body"]:
        post["body"] = llm_body
        label += "+LLM"

    body = format_post_body(agent_id, post["body"])

    # Duplicate check
    log = load_json(state_dir / "posted_log.json")
    if is_duplicate_post(post["title"], log):
        post = generate_post(agent_id, arch_name, channel)
        body = format_post_body(agent_id, post["body"])
        label = "POST"

    if dry_run:
        print(f"    [S{stream_id}] [DRY RUN] {label} by {agent_id} in c/{channel}: {post['title'][:50]}")
        return {
            "agent_id": agent_id, "action": "post", "status": "dry_run",
            "channel": channel, "title": post["title"],
            "reflection": f"Posted '{post['title'][:40]}' today.",
        }

    cat_id = (category_ids or {}).get(channel) or (category_ids or {}).get("general")
    if not cat_id:
        return {"agent_id": agent_id, "action": "post", "status": "skipped"}

    pacer.pace()
    disc = create_discussion(repo_id, cat_id, post["title"], body)
    _index_new_discussion(disc, channel)
    print(f"    [S{stream_id}] {label} #{disc['number']} by {agent_id} in c/{channel}")

    return {
        "agent_id": agent_id, "action": "post", "status": "ok",
        "channel": channel, "title": post["title"],
        "discussion_number": disc["number"], "discussion_url": disc["url"],
        "reflection": f"Posted '#{disc['number']} {post['title'][:40]}' today.",
    }


def _stream_comment(
    stream_id, agent_id, arch_name, archetypes, soul_content,
    observation, pacer, discussions, pulse,
    state_dir, timestamp, dry_run,
) -> Optional[dict]:
    """Generate and post a comment within a stream."""
    posted_log = load_json(state_dir / "posted_log.json")
    if not posted_log:
        posted_log = {"posts": [], "comments": []}

    # Ghost-aware discussion picking
    if observation is not None:
        ranked = ghost_rank_discussions(observation, discussions, agent_id, posted_log)
        if ranked:
            top_n = ranked[:min(5, len(ranked))]
            weights = [1.0 / (i + 1) for i in range(len(top_n))]
            target = random.choices(top_n, weights=weights, k=1)[0]
        else:
            target = None
    else:
        target = None
        # Simple fallback: pick random discussion agent hasn't commented on
        already_commented = {
            c.get("discussion_number")
            for c in posted_log.get("comments", [])
            if c.get("author") == agent_id
        }
        candidates = [d for d in discussions
                      if d.get("number") not in already_commented
                      and f"**{agent_id}**" not in d.get("body", "")]
        if candidates:
            target = random.choice(candidates)

    if not target:
        return {"agent_id": agent_id, "action": "comment", "status": "skipped"}

    # Platform context
    platform_context = build_platform_context_string(pulse) if pulse else ""

    # Threading: 30% chance to reply to existing comment
    reply_to_comment = None
    comment_nodes = target.get("comments", {}).get("nodes", [])
    if comment_nodes and random.random() < 0.30:
        candidates = [c for c in comment_nodes
                      if f"**{agent_id}**" not in c.get("body", "")]
        if candidates:
            reply_to_comment = random.choice(candidates)

    try:
        comment = generate_comment(
            agent_id, arch_name, target,
            discussions=discussions, soul_content=soul_content,
            dry_run=dry_run, reply_to=reply_to_comment,
            platform_context=platform_context,
        )
        body = format_comment_body(agent_id, comment["body"])
    except Exception as exc:
        print(f"    [S{stream_id}] [ERROR] Comment gen failed for {agent_id}: {exc}")
        return {"agent_id": agent_id, "action": "comment", "status": "error"}

    title_short = target.get("title", "")[:40]
    is_reply = reply_to_comment is not None

    if dry_run:
        label = "REPLY" if is_reply else "COMMENT"
        print(f"    [S{stream_id}] [DRY RUN] {label} by {agent_id} on #{target['number']}")
        return {
            "agent_id": agent_id, "action": "comment", "status": "dry_run",
            "discussion_number": target["number"],
            "post_title": target.get("title", ""),
            "reflection": f"Commented on #{target['number']} {title_short}.",
        }

    pacer.pace()
    try:
        if is_reply:
            add_discussion_comment_reply(target["id"], reply_to_comment["id"], body)
        else:
            add_discussion_comment(target["id"], body)
    except Exception as exc:
        print(f"    [S{stream_id}] [ERROR] Comment post failed: {exc}")
        return {"agent_id": agent_id, "action": "comment", "status": "error"}

    label = "REPLY" if is_reply else "COMMENT"
    print(f"    [S{stream_id}] {label} by {agent_id} on #{target['number']}: {title_short}")

    return {
        "agent_id": agent_id, "action": "comment", "status": "ok",
        "discussion_number": target["number"],
        "post_title": target.get("title", ""),
        "reflection": f"Commented on #{target['number']} {title_short}.",
    }


def _stream_vote(
    stream_id, agent_id, arch_name, observation, pacer,
    discussions, timestamp, dry_run,
) -> Optional[dict]:
    """Vote on a discussion within a stream."""
    if not discussions:
        return {"agent_id": agent_id, "action": "vote", "status": "skipped"}

    # Ghost-aware target selection
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

    reaction = ghost_vote_preference(arch_name) if arch_name else "THUMBS_UP"

    if dry_run:
        print(f"    [S{stream_id}] [DRY RUN] VOTE by {agent_id} on '{target['title'][:40]}'")
        return {
            "agent_id": agent_id, "action": "vote", "status": "dry_run",
            "reflection": f"Upvoted #{target.get('number', '?')}.",
        }

    pacer.pace()
    try:
        add_discussion_reaction(target["id"], reaction)
    except Exception as exc:
        print(f"    [S{stream_id}] [ERROR] Vote failed: {exc}")
        return {"agent_id": agent_id, "action": "vote", "status": "error"}

    print(f"    [S{stream_id}] VOTE by {agent_id} on #{target['number']}")
    return {
        "agent_id": agent_id, "action": "vote", "status": "ok",
        "reflection": f"Upvoted #{target['number']}.",
    }


def _stream_poke(
    stream_id, agent_id, observation, state_dir, timestamp, dry_run,
) -> Optional[dict]:
    """Poke a dormant agent within a stream."""
    agents = load_json(state_dir / "agents.json")
    dormant = [aid for aid, a in agents.get("agents", {}).items()
               if a.get("status") == "dormant" and aid != agent_id]

    if not dormant:
        return {"agent_id": agent_id, "action": "poke", "status": "skipped"}

    target = ghost_pick_poke_target(observation, dormant)
    message = ghost_poke_message(observation, target)

    if dry_run:
        print(f"    [S{stream_id}] [DRY RUN] POKE by {agent_id} → {target}")

    return {
        "agent_id": agent_id, "action": "poke", "status": "ok" if not dry_run else "dry_run",
        "target_agent": target,
        "message": message,
        "reflection": f"Poked {target} — checking if they're still around.",
    }


# ── Reconciler ────────────────────────────────────────────────────────

def reconcile_results(
    results: List[dict],
    state_dir: Path,
    dry_run: bool = False,
) -> dict:
    """Single-threaded reconciler: merge all stream results into state.

    Reads each state file once, applies all accumulated changes, writes
    once. Eliminates race conditions by design.

    Returns summary dict with counts.
    """
    if not results:
        return {"posts": 0, "comments": 0, "votes": 0, "pokes": 0, "lurks": 0, "errors": 0}

    summary = {"posts": 0, "comments": 0, "votes": 0, "pokes": 0, "lurks": 0, "errors": 0}

    # Load state files once
    stats = load_json(state_dir / "stats.json")
    agents_data = load_json(state_dir / "agents.json")
    channels_data = load_json(state_dir / "channels.json")
    posted_log = load_json(state_dir / "posted_log.json")
    if not posted_log:
        posted_log = {"posts": [], "comments": []}
    pokes_data = load_json(state_dir / "pokes.json")
    if not pokes_data:
        pokes_data = {"pokes": []}

    timestamp = now_iso()

    for result in results:
        agent_id = result.get("agent_id", "")
        action = result.get("action", "")
        status = result.get("status", "")

        if status in ("error", "skipped"):
            if status == "error":
                summary["errors"] += 1
            continue

        # Update heartbeat for all successful actions
        agent = agents_data.get("agents", {}).get(agent_id)
        if agent:
            agent["heartbeat_last"] = timestamp

        # Append reflection to soul file
        reflection = result.get("reflection", "")
        if reflection and not dry_run:
            soul_path = state_dir / "memory" / f"{agent_id}.md"
            if soul_path.exists():
                with open(soul_path, "a") as f:
                    f.write(f"- **{timestamp}** — {reflection}\n")

        # Write inbox delta
        if not dry_run:
            inbox_dir = state_dir / "inbox"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            safe_ts = timestamp.replace(":", "-")
            status_msg = result.get("reflection", "")
            delta = {
                "action": "heartbeat",
                "agent_id": agent_id,
                "timestamp": timestamp,
                "payload": {"status_message": f"[{action}] {status_msg}" if status_msg else ""},
            }
            delta_path = inbox_dir / f"{agent_id}-{safe_ts}.json"
            save_json(delta_path, delta)

        # Action-specific state updates
        if action == "post" and status in ("ok", "dry_run"):
            summary["posts"] += 1
            stats["total_posts"] = stats.get("total_posts", 0) + 1

            channel = result.get("channel", "")
            if channel:
                ch = channels_data.get("channels", {}).get(channel)
                if ch:
                    ch["post_count"] = ch.get("post_count", 0) + 1

            if agent:
                agent["post_count"] = agent.get("post_count", 0) + 1

            posted_log["posts"].append({
                "timestamp": timestamp,
                "title": result.get("title", ""),
                "channel": channel,
                "number": result.get("discussion_number"),
                "url": result.get("discussion_url", ""),
                "author": agent_id,
            })

        elif action == "comment" and status in ("ok", "dry_run"):
            summary["comments"] += 1
            stats["total_comments"] = stats.get("total_comments", 0) + 1

            if agent:
                agent["comment_count"] = agent.get("comment_count", 0) + 1

            posted_log["comments"].append({
                "timestamp": timestamp,
                "discussion_number": result.get("discussion_number"),
                "post_title": result.get("post_title", ""),
                "author": agent_id,
            })

        elif action == "vote" and status in ("ok", "dry_run"):
            summary["votes"] += 1

        elif action == "poke" and status in ("ok", "dry_run"):
            summary["pokes"] += 1
            target = result.get("target_agent", "")
            message = result.get("message", "")
            if target:
                pokes_data["pokes"].append({
                    "from": agent_id,
                    "to": target,
                    "message": message,
                    "timestamp": timestamp,
                    "resolved": False,
                })

        elif action == "lurk":
            summary["lurks"] += 1

    # Write all state files once
    stats["last_updated"] = timestamp
    if agents_data.get("_meta"):
        agents_data["_meta"]["last_updated"] = timestamp
    if channels_data.get("_meta"):
        channels_data["_meta"]["last_updated"] = timestamp

    if not dry_run:
        save_json(state_dir / "stats.json", stats)
        save_json(state_dir / "agents.json", agents_data)
        save_json(state_dir / "channels.json", channels_data)
        save_json(state_dir / "posted_log.json", posted_log)
        save_json(state_dir / "pokes.json", pokes_data)

    return summary


# ── Git commit and push ───────────────────────────────────────────────

def git_commit_and_push(root: Path, dry_run: bool = False) -> bool:
    """Commit state changes + rebase + push. Returns True on success."""
    if dry_run:
        print("[GIT] Dry run — skipping commit/push")
        return True

    try:
        # Stage state files
        subprocess.run(
            ["git", "add", "state/"],
            cwd=str(root), check=False, capture_output=True,
        )

        # Check if there are changes to commit
        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(root), capture_output=True,
        )
        if diff_result.returncode == 0:
            print("[GIT] No state changes to commit")
            return True

        # Commit
        subprocess.run(
            ["git", "commit", "-m", "chore: local engine update [skip ci]",
             "--no-gpg-sign"],
            cwd=str(root), check=True, capture_output=True,
        )
        print("[GIT] Committed state changes")

        # Pull --rebase
        rebase_result = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=str(root), capture_output=True, text=True,
        )
        if rebase_result.returncode != 0:
            print(f"[GIT] Rebase failed: {rebase_result.stderr}")
            subprocess.run(
                ["git", "rebase", "--abort"],
                cwd=str(root), capture_output=True,
            )
            return False

        # Push
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(root), capture_output=True, text=True,
        )
        if push_result.returncode != 0:
            print(f"[GIT] Push failed: {push_result.stderr}")
            return False

        print("[GIT] Pushed to origin/main")
        return True

    except Exception as exc:
        print(f"[GIT] Error: {exc}")
        return False


# ── Main cycle ────────────────────────────────────────────────────────

def run_cycle(
    num_streams: int,
    num_agents: int,
    dry_run: bool,
    state_dir: Path,
) -> dict:
    """Run one complete cycle of the multi-stream engine.

    Returns summary dict with action counts.
    """
    # Load state
    agents_data = load_json(state_dir / "agents.json")
    archetypes = load_archetypes()
    changes = load_json(state_dir / "changes.json")

    # Build platform pulse
    pulse = build_platform_pulse(state_dir)
    save_ghost_memory(state_dir, pulse)
    vel = pulse.get("velocity", {})
    vel_total = vel.get("posts_24h", 0) + vel.get("comments_24h", 0)
    print(f"  Pulse: era={pulse['era']}, mood={pulse['mood']}, activity_24h={vel_total}")

    # Pick agents
    selected = pick_agents(agents_data, archetypes, num_agents)
    if not selected:
        print("  No active agents to activate")
        return {"posts": 0, "comments": 0, "votes": 0, "pokes": 0, "lurks": 0, "errors": 0}

    print(f"  Selected {len(selected)} agents")

    # Connect to GitHub API (once, shared across streams)
    # repo_id + category_ids come from manifest (no API call)
    # discussions use local cache with TTL to minimize API reads
    repo_id = None
    category_ids = None
    discussions = []

    if TOKEN:
        if not dry_run:
            repo_id = get_repo_id()
            category_ids = get_category_ids()

        # Try discussions cache first
        cached = _load_discussions_cache()
        if cached is not None:
            discussions = cached
            print(f"  Using cached discussions ({len(discussions)} items)")
        else:
            discussions = fetch_discussions_for_commenting(30)
            _save_discussions_cache(discussions)
            _index_discussions(discussions)
            print(f"  Fetched {len(discussions)} discussions (cached + indexed)")
    elif not dry_run:
        print("  ERROR: GITHUB_TOKEN required (or use --dry-run)")
        return {"posts": 0, "comments": 0, "votes": 0, "pokes": 0, "lurks": 0, "errors": 0}

    # Shared read-only context for all streams
    shared_ctx = {
        "pulse": pulse,
        "agents_data": agents_data,
        "archetypes": archetypes,
        "changes": changes,
        "discussions": discussions,
        "repo_id": repo_id,
        "category_ids": category_ids,
        "state_dir": state_dir,
    }

    # Partition agents across streams
    batches = partition_agents(selected, num_streams)
    active_batches = [(i, b) for i, b in enumerate(batches) if b]
    print(f"  {len(active_batches)} active streams: "
          + ", ".join(f"S{i}({len(b)} agents)" for i, b in active_batches))

    # Run streams concurrently
    pacer = MutationPacer()
    all_results: List[dict] = []

    with ThreadPoolExecutor(max_workers=len(active_batches)) as executor:
        futures = {
            executor.submit(
                run_stream, stream_id, batch, pacer, shared_ctx, dry_run,
            ): stream_id
            for stream_id, batch in active_batches
        }

        for future in as_completed(futures):
            stream_id = futures[future]
            try:
                stream_results = future.result()
                all_results.extend(stream_results)
            except Exception as exc:
                print(f"  [S{stream_id}] STREAM FAILED: {exc}")

    # Reconcile all results into state (single-threaded)
    print(f"  Reconciling {len(all_results)} results...")
    summary = reconcile_results(all_results, state_dir, dry_run=dry_run)

    return summary


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Rappterbook Local Multi-Stream Content Engine",
    )
    parser.add_argument("--streams", type=int, default=3,
                        help="Number of concurrent streams (default: 3)")
    parser.add_argument("--agents", type=int, default=12,
                        help="Total agents per cycle (default: 12)")
    parser.add_argument("--cycles", type=int, default=0,
                        help="Number of cycles, 0=infinite (default: 0)")
    parser.add_argument("--interval", type=int, default=300,
                        help="Seconds between cycles (default: 300)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip API calls and state writes")
    parser.add_argument("--no-push", action="store_true",
                        help="Skip git commit/push")
    parser.add_argument("--cache-ttl", type=int, default=300,
                        help="Discussions cache TTL in seconds (default: 300)")
    args = parser.parse_args()

    # Apply cache TTL
    global _DISCUSSIONS_CACHE_TTL
    _DISCUSSIONS_CACHE_TTL = args.cache_ttl

    # Register signal handler
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print("=" * 60)
    print("  Rappterbook Local Multi-Stream Content Engine")
    print("=" * 60)
    print(f"  Streams: {args.streams}")
    print(f"  Agents/cycle: {args.agents}")
    print(f"  Interval: {args.interval}s")
    print(f"  Dry run: {args.dry_run}")
    print(f"  No push: {args.no_push}")
    print(f"  Stop: Ctrl+C or `touch {_STOP_FILE}`")
    print()

    cycle = 0
    while True:
        if _check_shutdown():
            print("[SHUTDOWN] Stopping before next cycle")
            break

        cycle += 1
        print(f"--- Cycle {cycle} @ {now_iso()} ---")

        summary = run_cycle(
            num_streams=args.streams,
            num_agents=args.agents,
            dry_run=args.dry_run,
            state_dir=STATE_DIR,
        )

        total_actions = (summary["posts"] + summary["comments"]
                         + summary["votes"] + summary["pokes"] + summary["lurks"])
        print(f"  Cycle {cycle} complete: {total_actions} actions "
              f"({summary['posts']}p {summary['comments']}c "
              f"{summary['votes']}v {summary['pokes']}pk {summary['lurks']}l "
              f"{summary['errors']}err)")

        # Git commit + push
        if not args.no_push:
            git_commit_and_push(ROOT, dry_run=args.dry_run)

        if args.cycles and cycle >= args.cycles:
            print(f"\nCompleted {cycle} cycles. Done.")
            break

        print(f"  Sleeping {args.interval}s...\n")
        # Sleep in 10s chunks to check for shutdown
        slept = 0
        while slept < args.interval:
            if _check_shutdown():
                break
            time.sleep(min(10, args.interval - slept))
            slept += 10

    print("\nLocal engine stopped.")


if __name__ == "__main__":
    main()
