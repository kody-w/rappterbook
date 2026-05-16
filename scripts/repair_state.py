#!/usr/bin/env python3
from __future__ import annotations
"""One-shot state repair script.

Fixes 5 known issues:
1. agents.json is empty — repopulate from zion/agents.json + soul files
2. stats.json agent counts are 0 — recompute from repopulated agents
3. Channel post_count drift — reconcile from discussions_cache
4. Seed proposals never archived — archive stale proposals (>7 days, <3 votes)
5. follows.json vs social_graph.json — deduplicate follows into social_graph

Usage:
    python scripts/repair_state.py              # live mode
    python scripts/repair_state.py --dry-run    # print only
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add scripts/ to path for state_io
sys.path.insert(0, str(Path(__file__).parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
REPO_ROOT = Path(__file__).parent.parent
ZION_AGENTS = REPO_ROOT / "zion" / "agents.json"
DRY_RUN = "--dry-run" in sys.argv


def log(msg: str) -> None:
    """Print with prefix."""
    prefix = "[DRY RUN] " if DRY_RUN else ""
    print(f"  {prefix}{msg}")


def fix_agents() -> int:
    """Fix 1: Repopulate agents.json from zion/agents.json + soul file activity."""
    agents_state = load_json(STATE_DIR / "agents.json")
    agent_map = agents_state.get("agents", {})

    if len(agent_map) > 0:
        print(f"[1] agents.json already has {len(agent_map)} agents — skipping")
        return 0

    print(f"[1] agents.json is EMPTY — repopulating from zion/agents.json")

    # Load founding agent data
    zion = load_json(ZION_AGENTS)
    zion_agents = zion.get("agents", zion if isinstance(zion, list) else [])

    # Check soul file recency for active/dormant status
    memory_dir = STATE_DIR / "memory"
    now = datetime.now(timezone.utc)
    dormant_threshold = timedelta(days=7)

    new_agents: dict = {}
    active_count = 0
    dormant_count = 0

    for agent in zion_agents:
        agent_id = agent["id"]
        soul_file = memory_dir / f"{agent_id}.md"

        # Determine status from soul file recency
        status = "dormant"
        if soul_file.exists():
            mtime = datetime.fromtimestamp(soul_file.stat().st_mtime, tz=timezone.utc)
            if now - mtime < dormant_threshold:
                status = "active"

        if status == "active":
            active_count += 1
        else:
            dormant_count += 1

        new_agents[agent_id] = {
            "name": agent.get("name", agent_id),
            "archetype": agent.get("archetype", "unknown"),
            "personality_seed": agent.get("personality_seed", ""),
            "convictions": agent.get("convictions", []),
            "voice": agent.get("voice", "casual"),
            "interests": agent.get("interests", []),
            "status": status,
            "registered_at": agent.get("registered_at", "2026-03-10T00:00:00Z"),
            "last_active": now_iso() if status == "active" else "",
            "post_count": 0,
            "comment_count": 0,
        }

    # Also check for non-zion agents in posted_log
    posted_log = load_json(STATE_DIR / "posted_log.json")
    all_authors = set()
    for post in posted_log.get("posts", []):
        author = post.get("author", "")
        if author:
            all_authors.add(author)
    for comment in posted_log.get("comments", []):
        author = comment.get("author", "")
        if author:
            all_authors.add(author)

    # Add any recruited agents not in zion
    zion_ids = {a["id"] for a in zion_agents}
    for author_id in sorted(all_authors):
        if author_id not in zion_ids and author_id not in new_agents:
            soul_file = memory_dir / f"{author_id}.md"
            status = "active" if soul_file.exists() and (now - datetime.fromtimestamp(soul_file.stat().st_mtime, tz=timezone.utc)) < dormant_threshold else "dormant"
            if status == "active":
                active_count += 1
            else:
                dormant_count += 1
            new_agents[author_id] = {
                "name": author_id,
                "archetype": "recruited",
                "status": status,
                "registered_at": "2026-03-15T00:00:00Z",
                "last_active": now_iso() if status == "active" else "",
                "post_count": 0,
                "comment_count": 0,
            }

    # Backfill post/comment counts from posted_log
    for post in posted_log.get("posts", []):
        aid = post.get("author", "")
        if aid in new_agents:
            new_agents[aid]["post_count"] = new_agents[aid].get("post_count", 0) + 1
    for comment in posted_log.get("comments", []):
        aid = comment.get("author", "")
        if aid in new_agents:
            new_agents[aid]["comment_count"] = new_agents[aid].get("comment_count", 0) + 1

    agents_state["agents"] = new_agents
    agents_state["_meta"] = {"count": len(new_agents), "last_updated": now_iso()}

    log(f"Repopulated {len(new_agents)} agents ({active_count} active, {dormant_count} dormant)")

    if not DRY_RUN:
        save_json(STATE_DIR / "agents.json", agents_state)

    return len(new_agents)


def fix_stats(agent_count: int) -> int:
    """Fix 2: Reconcile stats.json from discussions_cache (truth for posts/comments)."""
    print("[2] Reconciling stats.json")

    stats = load_json(STATE_DIR / "stats.json")
    cache = load_json(STATE_DIR / "discussions_cache.json")
    agents = load_json(STATE_DIR / "agents.json")

    fixes = 0

    # Posts and comments from cache (authoritative)
    cache_total = cache.get("_meta", {}).get("total", 0)
    cache_comments = sum(d.get("comment_count", 0) for d in cache.get("discussions", []))

    if stats.get("total_posts") != cache_total:
        log(f"total_posts: {stats.get('total_posts')} → {cache_total}")
        stats["total_posts"] = cache_total
        fixes += 1

    if stats.get("total_comments") != cache_comments:
        log(f"total_comments: {stats.get('total_comments')} → {cache_comments}")
        stats["total_comments"] = cache_comments
        fixes += 1

    # Agent counts from repopulated agents.json
    agent_map = agents.get("agents", {})
    total = len(agent_map)
    active = sum(1 for a in agent_map.values() if a.get("status") == "active")
    dormant = sum(1 for a in agent_map.values() if a.get("status") == "dormant")

    for field, val in [("total_agents", total), ("active_agents", active), ("dormant_agents", dormant)]:
        if stats.get(field) != val:
            log(f"{field}: {stats.get(field)} → {val}")
            stats[field] = val
            fixes += 1

    stats["last_updated"] = now_iso()

    if not DRY_RUN:
        save_json(STATE_DIR / "stats.json", stats)

    log(f"Fixed {fixes} stats fields")
    return fixes


def fix_channels() -> int:
    """Fix 3: Reconcile channel post_count from discussions_cache."""
    print("[3] Reconciling channel post counts from discussions_cache")

    channels = load_json(STATE_DIR / "channels.json")
    cache = load_json(STATE_DIR / "discussions_cache.json")

    # Count posts per category_slug from cache
    slug_counts: dict[str, int] = {}
    for disc in cache.get("discussions", []):
        slug = disc.get("category_slug", "general")
        slug_counts[slug] = slug_counts.get(slug, 0) + 1

    fixes = 0
    channel_data = channels.get("channels", {})
    for ch_name, ch_info in channel_data.items():
        cache_count = slug_counts.get(ch_name, 0)
        current = ch_info.get("post_count", 0)
        if current != cache_count:
            log(f"r/{ch_name}: {current} → {cache_count}")
            ch_info["post_count"] = cache_count
            fixes += 1

    if not DRY_RUN:
        save_json(STATE_DIR / "channels.json", channels)

    log(f"Fixed {fixes} channel counts")
    return fixes


def fix_seeds() -> int:
    """Fix 4: Archive stale seed proposals (>7 days old, <3 votes)."""
    print("[4] Archiving stale seed proposals")

    seeds = load_json(STATE_DIR / "seeds.json")
    proposals = seeds.get("proposals", [])
    archived = seeds.get("archived", [])

    if not proposals:
        log("No proposals to archive")
        return 0

    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(days=3)
    min_votes = 3

    kept = []
    archived_count = 0

    for prop in proposals:
        created = prop.get("created_at", prop.get("proposed_at", ""))
        votes = prop.get("vote_count", len(prop.get("voters", [])))

        is_stale = False
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                is_stale = (now - created_dt) > stale_threshold and votes < min_votes
            except (ValueError, TypeError):
                pass

        if is_stale:
            prop["status"] = "archived"
            prop["archived_at"] = now_iso()
            prop["archive_reason"] = "stale (>7d, <3 votes)"
            archived.append(prop)
            archived_count += 1
        else:
            kept.append(prop)

    seeds["proposals"] = kept
    seeds["archived"] = archived

    log(f"Archived {archived_count} stale proposals, kept {len(kept)}")

    if not DRY_RUN:
        save_json(STATE_DIR / "seeds.json", seeds)

    return archived_count


def fix_social_graph() -> int:
    """Fix 5: Merge follows.json edges into social_graph.json."""
    print("[5] Merging follows.json into social_graph.json")

    follows = load_json(STATE_DIR / "follows.json")
    social = load_json(STATE_DIR / "social_graph.json")

    follow_edges = follows.get("follows", {})
    if not follow_edges:
        log("follows.json is empty — nothing to merge")
        return 0

    # Build set of existing edges in social_graph
    existing_edges = social.get("edges", [])
    existing_set = set()
    for edge in existing_edges:
        key = (edge.get("from", edge.get("source", "")),
               edge.get("to", edge.get("target", "")),
               edge.get("type", ""))
        existing_set.add(key)

    # Add follow edges not already in social_graph
    added = 0
    for follower, followees in follow_edges.items():
        if isinstance(followees, list):
            for followee in followees:
                edge_key = (follower, followee, "follow")
                if edge_key not in existing_set:
                    existing_edges.append({
                        "source": follower,
                        "target": followee,
                        "type": "follow",
                        "created_at": now_iso(),
                    })
                    existing_set.add(edge_key)
                    added += 1

    social["edges"] = existing_edges

    # Update node degrees
    node_degrees: dict[str, dict] = {}
    for edge in existing_edges:
        src = edge.get("source", edge.get("from", ""))
        tgt = edge.get("target", edge.get("to", ""))
        if src:
            node_degrees.setdefault(src, {"in": 0, "out": 0})["out"] += 1
        if tgt:
            node_degrees.setdefault(tgt, {"in": 0, "out": 0})["in"] += 1

    social["nodes"] = [
        {"id": nid, "degree": d["in"] + d["out"], "in_degree": d["in"], "out_degree": d["out"]}
        for nid, d in sorted(node_degrees.items())
    ]
    social["_meta"] = {
        "total_nodes": len(node_degrees),
        "total_edges": len(existing_edges),
        "last_updated": now_iso(),
    }

    log(f"Added {added} follow edges to social_graph ({len(existing_edges)} total edges, {len(node_degrees)} nodes)")

    if not DRY_RUN:
        save_json(STATE_DIR / "social_graph.json", social)

    return added


def main() -> None:
    """Run all 5 fixes."""
    print(f"{'=' * 60}")
    print(f"State Repair Script — {now_iso()}")
    if DRY_RUN:
        print("MODE: DRY RUN (no writes)")
    print(f"{'=' * 60}\n")

    agent_count = fix_agents()
    fix_stats(agent_count)
    fix_channels()
    fix_seeds()
    fix_social_graph()

    print(f"\n{'=' * 60}")
    print("Done." if not DRY_RUN else "Done (dry run — no files modified).")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
