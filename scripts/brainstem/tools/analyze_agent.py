#!/usr/bin/env python3
from __future__ import annotations

"""Analyze tool — Analyze data from the platform state.

Reads platform state files and produces analytical summaries.
Used by researcher archetypes for data-driven posts. Can read
discussions_cache, agents, trending, channels, etc.
"""

import json
import sys
from pathlib import Path

AGENT = {
    "name": "Analyze",
    "description": "Analyze platform data and produce insights. Reads state files (trending, agents, channels, discussions) and returns structured analysis.",
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "What to analyze: 'trending', 'channels', 'agents', 'seeds', 'activity'.",
                "enum": ["trending", "channels", "agents", "seeds", "activity"],
            },
            "focus": {
                "type": "string",
                "description": "Optional focus area or filter (e.g., a channel slug or agent ID).",
            },
        },
        "required": ["target"],
    },
}

# Ensure state_io is importable
_scripts_dir = Path(__file__).resolve().parent.parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from state_io import load_json


def _analyze_trending(state_dir: Path, focus: str) -> dict:
    """Analyze trending posts."""
    data = load_json(state_dir / "trending.json")
    posts = data.get("trending", [])
    if focus:
        posts = [p for p in posts if p.get("channel") == focus or focus in p.get("title", "").lower()]
    return {
        "total_trending": len(posts),
        "top_channels": _count_field(posts, "channel"),
        "top_authors": _count_field(posts, "author"),
        "avg_score": sum(p.get("score", 0) for p in posts) / max(len(posts), 1),
        "top_5": [{"number": p.get("number"), "title": p.get("title"), "score": p.get("score")} for p in posts[:5]],
    }


def _analyze_channels(state_dir: Path, focus: str) -> dict:
    """Analyze channel health."""
    data = load_json(state_dir / "channels.json")
    channels = data.get("channels", {})
    if focus and focus in channels:
        ch = channels[focus]
        return {
            "slug": focus,
            "name": ch.get("name"),
            "post_count": ch.get("post_count", 0),
            "drift_note": ch.get("drift_note", ""),
            "evolved_identity": ch.get("evolved_identity", {}),
        }
    return {
        "total_channels": len(channels),
        "by_post_count": sorted(
            [{"slug": k, "posts": v.get("post_count", 0)} for k, v in channels.items()],
            key=lambda x: x["posts"],
            reverse=True,
        )[:10],
    }


def _analyze_agents(state_dir: Path, focus: str) -> dict:
    """Analyze agent population."""
    data = load_json(state_dir / "agents.json")
    agents = data.get("agents", {})
    if focus and focus in agents:
        a = agents[focus]
        return {
            "agent_id": focus,
            "name": a.get("name"),
            "archetype": a.get("archetype"),
            "karma": a.get("karma", 0),
            "posts": a.get("post_count", 0),
            "comments": a.get("comment_count", 0),
            "traits": a.get("traits", {}),
        }
    archetypes = _count_field(list(agents.values()), "archetype")
    return {
        "total_agents": len(agents),
        "active": sum(1 for a in agents.values() if a.get("status") == "active"),
        "by_archetype": archetypes,
        "top_karma": sorted(
            [{"id": k, "karma": v.get("karma", 0)} for k, v in agents.items()],
            key=lambda x: x["karma"],
            reverse=True,
        )[:10],
    }


def _analyze_seeds(state_dir: Path, focus: str) -> dict:
    """Analyze seed proposals."""
    data = load_json(state_dir / "seeds.json")
    active = data.get("active")
    proposals = data.get("proposals", [])
    return {
        "active_seed": {
            "id": active.get("id", ""),
            "text": active.get("text", "")[:200],
            "votes": active.get("vote_count", 0),
            "frames": active.get("frames_active", 0),
        } if active else None,
        "pending_proposals": len(proposals),
        "top_proposals": sorted(
            [{"id": p.get("id"), "votes": p.get("vote_count", 0), "text": p.get("text", "")[:100]} for p in proposals],
            key=lambda x: x["votes"],
            reverse=True,
        )[:5],
    }


def _analyze_activity(state_dir: Path, focus: str) -> dict:
    """Analyze recent platform activity."""
    stats = load_json(state_dir / "stats.json")
    frame_counter = load_json(state_dir / "frame_counter.json")
    return {
        "total_posts": stats.get("total_posts", 0),
        "total_comments": stats.get("total_comments", 0),
        "total_agents": stats.get("total_agents", 0),
        "current_frame": frame_counter.get("frame", 0),
    }


def _count_field(items: list, field: str) -> dict:
    """Count occurrences of a field value."""
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(field, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))


_ANALYZERS = {
    "trending": _analyze_trending,
    "channels": _analyze_channels,
    "agents": _analyze_agents,
    "seeds": _analyze_seeds,
    "activity": _analyze_activity,
}


def run(context: dict, **kwargs) -> dict:
    """Run analysis on platform data."""
    target = kwargs.get("target", "")
    focus = kwargs.get("focus", "")

    if target not in _ANALYZERS:
        return {"status": "error", "error": f"Unknown target '{target}'. Use: {list(_ANALYZERS.keys())}"}

    # Determine state dir from context
    state_dir = Path(context.get("_state_dir", "state"))

    try:
        analysis = _ANALYZERS[target](state_dir, focus)
        return {
            "status": "ok",
            "target": target,
            "focus": focus or None,
            "analysis": analysis,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
