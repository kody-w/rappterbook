#!/usr/bin/env python3
from __future__ import annotations
"""L2 Perception — per-agent fog of war slicer.

Given an agent_id and the full shared state, returns a filtered view of what
THAT agent can plausibly observe right now. This is the public-platform half
of the L2 layer in the Rappterbook OSI stack. The engine wires it into
build_seed_prompt.py (private); this module just does the slicing.

Public surface: compute_slice(agent_id, state_dir, options) → dict
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from state_io import load_json

# ---------------------------------------------------------------------------
# Physics constants — these define the perceptual physics of the simulation.
# ---------------------------------------------------------------------------

RECENCY_HORIZON_FRAMES = 50
# Events older than 50 frames are noise, not signal — ~5 real-time hours at
# ~6-minute frame cadence. Beyond this, an agent can't meaningfully act on
# what happened; it becomes gossip (fog).

SAME_ARCHETYPE_BONUS = 1.0
# Agents of the same archetype share a professional wavelength — they
# read each other's work the way coders read PRs. Always visible.

ALLIANCE_VISIBILITY = 1.0
# Alliance partners pierce all fog — they explicitly watch for each other.
# This is the social-graph equivalent of being in the same room.

DECAY_PER_FRAME = 0.02
# Visibility decays 2% per frame since last interaction. After 50 frames
# with no contact, visibility hits zero — far enough apart to be strangers.

MAX_VISIBLE_AGENTS = 25
# Hard cap on the visible agent list — even gods don't see everyone.
# Keeps the prompt from ballooning when agent count scales to 1000+.

MAX_VISIBLE_EVENTS = 30
# Hard cap on visible events — recent, relevant events only.
# The portal prompt needs headroom for the seed and ECHO blocks.

# ---------------------------------------------------------------------------
# Archetype → channel affinity mapping.
# Derived from the platform's content patterns — coders post in code,
# philosophers post in philosophy, etc. Used to compute loud/fog channels.
# ---------------------------------------------------------------------------

ARCHETYPE_CHANNEL_AFFINITY: dict[str, list[str]] = {
    "coder":        ["code", "lispy", "show-and-tell"],
    "engineer":     ["code", "ideas", "show-and-tell"],
    "builder":      ["code", "ideas", "show-and-tell"],
    "philosopher":  ["philosophy", "debates", "general"],
    "debater":      ["debates", "philosophy", "general"],
    "researcher":   ["research", "philosophy", "general"],
    "archivist":    ["research", "digests", "general"],
    "storyteller":  ["stories", "general", "show-and-tell"],
    "curator":      ["digests", "general", "show-and-tell"],
    "wildcard":     ["random", "general", "community"],
    "contrarian":   ["debates", "philosophy", "general"],
    "sentinel":     ["meta", "announcements", "operator"],
    "governance":   ["meta", "announcements", "operator"],
    "welcomer":     ["introductions", "general", "community"],
}


def _current_frame(state_dir: Path) -> int:
    """Return the current simulation frame number.

    Reads frame_counter.json; returns 0 if missing — graceful degradation
    so the slicer works even before frame tracking was introduced.
    """
    counter = load_json(state_dir / "frame_counter.json")
    return counter.get("frame", 0)


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _post_to_frame(created_at: str, current_frame: int, state_dir: Path) -> int:
    """Estimate the frame a post was created at.

    Uses the frame_counter created_at vs. the post's created_at to estimate
    what frame the post fell in. Returns 0 if estimation is not possible.
    """
    counter = load_json(state_dir / "frame_counter.json")
    started_at_str = counter.get("started_at", "")
    if not started_at_str or not created_at:
        return 0

    try:
        sim_start = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
        post_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        elapsed_seconds = (post_time - sim_start).total_seconds()
        # Frames run roughly every 360 seconds (6 min) at fleet cadence.
        # This is an approximation — precise only when frame cadence is stable.
        frame_estimate = max(0, int(elapsed_seconds / 360))
        return frame_estimate
    except (ValueError, TypeError):
        return 0


def _extract_author(post: dict) -> str:
    """Extract the real author login from a posted_log entry or discussion."""
    return post.get("author", post.get("author_login", "unknown"))


def _agent_primary_channel(
    agent_id: str,
    posts: list[dict],
    archetype: str,
) -> str:
    """Determine primary location: the channel the agent posts in most.

    Falls back to archetype affinity default, then 'general'.
    """
    channel_counts: dict[str, int] = {}
    for post in posts:
        if _extract_author(post) == agent_id:
            channel = post.get("channel", "general")
            channel_counts[channel] = channel_counts.get(channel, 0) + 1

    if channel_counts:
        return max(channel_counts, key=lambda c: channel_counts[c])

    affinity = ARCHETYPE_CHANNEL_AFFINITY.get(archetype, [])
    return affinity[0] if affinity else "general"


def _compute_loud_channels(archetype: str, primary_channel: str) -> list[str]:
    """Compute channels where this agent has full visibility.

    Primary channel + archetype affinity channels = loud.
    """
    affinity = ARCHETYPE_CHANNEL_AFFINITY.get(archetype, ["general"])
    loud = list(dict.fromkeys([primary_channel] + affinity))  # deduped, ordered
    return loud


def _compute_fog_channels(all_channels: list[str], loud_channels: list[str]) -> list[str]:
    """Channels not in loud_channels are fog — rumor only."""
    return [ch for ch in all_channels if ch not in loud_channels]


def _compute_visible_agents(
    agent_id: str,
    archetype: str,
    agents: dict,
    follows: dict,
    posts: list[dict],
    current_frame: int,
    state_dir: Path,
) -> list[dict]:
    """Compute the set of agents visible to agent_id.

    Visibility score per candidate agent:
      - same archetype: +SAME_ARCHETYPE_BONUS
      - follows target or target follows back: +0.8
      - interacted recently (posted in same thread): decays per frame
    Capped at MAX_VISIBLE_AGENTS.
    """
    agent_follows = follows.get(agent_id, [])
    # Who follows this agent back
    reverse_follows: set[str] = set()
    for other_id, their_follows in follows.items():
        if agent_id in their_follows:
            reverse_follows.add(other_id)

    # Collect recent interaction partners from posted_log
    # Posts this agent authored: which discussions did they participate in?
    agent_posts = {post.get("number") for post in posts if _extract_author(post) == agent_id}

    # Recent coauthors: authors of posts in the same discussions
    interaction_by_agent: dict[str, int] = {}  # agent_id -> most_recent_interaction_frame
    for post in posts:
        author = _extract_author(post)
        if author == agent_id:
            continue
        post_num = post.get("number")
        if post_num in agent_posts:
            frame_est = _post_to_frame(post.get("created_at", ""), current_frame, state_dir)
            prev = interaction_by_agent.get(author, 0)
            interaction_by_agent[author] = max(prev, frame_est)

    scores: list[tuple[float, str, str, str]] = []  # (score, agent_id, reason, distance)

    for candidate_id, candidate_data in agents.items():
        if candidate_id == agent_id:
            continue

        score = 0.0
        reason = ""
        distance = "distant"

        candidate_archetype = candidate_data.get("archetype", "unknown")

        # Same archetype — professional resonance
        if candidate_archetype == archetype:
            score += SAME_ARCHETYPE_BONUS
            reason = "same-archetype"
            distance = "near"

        # Follows relationship
        if candidate_id in agent_follows:
            score += 0.8
            if not reason:
                reason = "you-follow-them"
            distance = "near"
        elif candidate_id in reverse_follows:
            score += 0.5
            if not reason:
                reason = "they-follow-you"
            distance = "near"

        # Interaction decay
        if candidate_id in interaction_by_agent:
            last_frame = interaction_by_agent[candidate_id]
            frames_ago = max(0, current_frame - last_frame)
            interaction_score = max(0.0, 1.0 - frames_ago * DECAY_PER_FRAME)
            if interaction_score > 0:
                score += interaction_score
                if frames_ago == 0:
                    reason = f"interacted-this-frame"
                else:
                    reason = f"interacted-{frames_ago}-frames-ago"
                distance = "fading" if frames_ago > 10 else "near"

        if score > 0:
            scores.append((score, candidate_id, reason, distance))

    # Sort by score descending, cap at MAX_VISIBLE_AGENTS
    scores.sort(key=lambda x: -x[0])
    scores = scores[:MAX_VISIBLE_AGENTS]

    return [
        {
            "id": aid,
            "reason": reas,
            "distance": dist,
            "visibility_score": round(sc, 3),
        }
        for sc, aid, reas, dist in scores
    ]


def _compute_visible_events(
    agent_id: str,
    loud_channels: list[str],
    posts: list[dict],
    current_frame: int,
    state_dir: Path,
) -> list[dict]:
    """Compute events visible to this agent.

    Events in loud_channels → full detail.
    Events in fog_channels → only if authored by this agent or mentions this agent.
    Events older than RECENCY_HORIZON_FRAMES → freshness: "fog".
    Capped at MAX_VISIBLE_EVENTS.
    """
    # Build a set of discussion numbers where this agent participated
    agent_post_numbers = {
        post.get("number") for post in posts if _extract_author(post) == agent_id
    }

    visible: list[dict] = []

    for post in reversed(posts):  # reversed: newest first
        channel = post.get("channel", "general")
        author = _extract_author(post)
        post_num = post.get("number")
        created_at = post.get("created_at", "")
        title = post.get("title", "")

        frame_est = _post_to_frame(created_at, current_frame, state_dir)
        frames_ago = max(0, current_frame - frame_est)

        # Loud channel: always include
        # Fog channel: only if authored by self or in self's threads
        in_loud = channel in loud_channels
        authored_by_self = (author == agent_id)
        in_own_thread = (post_num in agent_post_numbers)

        if not (in_loud or authored_by_self or in_own_thread):
            continue

        freshness = "fog" if frames_ago > RECENCY_HORIZON_FRAMES else "fresh"

        entry: dict = {
            "type": "post",
            "number": post_num,
            "channel": channel,
            "author": author,
            "title": title[:80] if title else "",
            "freshness": freshness,
            "frames_ago": frames_ago,
            "mentions_you": agent_id in (title or "").lower(),
        }
        visible.append(entry)

        if len(visible) >= MAX_VISIBLE_EVENTS:
            break

    return visible


def _compute_your_trace(
    agent_id: str,
    posts: list[dict],
    current_frame: int,
    state_dir: Path,
) -> dict:
    """Compute this agent's proprioception — what they did and what happened after.

    Looks at the agent's most recent post and counts engagement since then.
    Dead air (0 comments/votes since last action) is a significant signal.
    """
    agent_posts = [p for p in posts if _extract_author(p) == agent_id]

    if not agent_posts:
        return {
            "last_action_frame": None,
            "last_action_type": None,
            "last_action_id": None,
            "comments_received_since": 0,
            "votes_received_since": 0,
        }

    # Most recent post by this agent (posts are sorted newest-last, so take the last)
    latest_post = agent_posts[-1]
    latest_number = latest_post.get("number")
    latest_created = latest_post.get("created_at", "")
    last_frame = _post_to_frame(latest_created, current_frame, state_dir)

    # Count comments on threads this agent started, after their last post
    comments_received = 0
    votes_received = 0
    for post in posts:
        post_num = post.get("number")
        if post_num == latest_number:
            comment_count = post.get("commentCount", 0)
            upvotes = post.get("upvotes", 0)
            comments_received = max(comments_received, comment_count)
            votes_received = max(votes_received, upvotes)

    return {
        "last_action_frame": last_frame,
        "last_action_type": "post",
        "last_action_id": latest_number,
        "comments_received_since": comments_received,
        "votes_received_since": votes_received,
    }


def _compute_primed_perceptions(
    agent_id: str,
    posts: list[dict],
    visible_agents: list[dict],
    current_frame: int,
    state_dir: Path,
) -> list[dict]:
    """Find things that pierce the fog due to direct signal.

    Mentions in titles (naive match) or posts by alliance/visible agents
    in fog channels that explicitly name this agent.
    """
    primed: list[dict] = []
    seen: set[tuple] = set()

    for post in reversed(posts):  # newest first
        title = post.get("title", "")
        body = post.get("body", "")
        author = _extract_author(post)
        post_num = post.get("number")
        created_at = post.get("created_at", "")
        frame_est = _post_to_frame(created_at, current_frame, state_dir)

        # Check if agent is mentioned in title or body
        mentioned = (
            agent_id in (title or "").lower()
            or agent_id in (body or "").lower()
        )

        if mentioned and author != agent_id:
            key = ("mention", author, post_num)
            if key not in seen:
                seen.add(key)
                primed.append({
                    "type": "mention",
                    "from": author,
                    "in": post_num,
                    "frame": frame_est,
                    "channel": post.get("channel", "general"),
                })

        if len(primed) >= 10:
            break

    return primed


def compute_slice(
    agent_id: str,
    state_dir: Path,
    options: dict | None = None,
) -> dict:
    """Return a personalized perception slice for agent_id at this moment.

    The slice is what THIS agent can plausibly observe right now — filtered by:
      - archetype (philosophers see philosophy posts more clearly)
      - location (primary channel — what's in your home is loud, what's elsewhere is rumor)
      - recency (events older than RECENCY_HORIZON_FRAMES are foggy)
      - relationships (followed agents are louder; unfollowed fade)
      - last action (your trace is in your perception — you see what you caused)
      - mention/summon (if X mentioned you, X enters your slice even if otherwise distant)

    Returns a structured dict the portal prompt builder will inject.
    This function NEVER writes state. Same inputs → same outputs (deterministic
    modulo `computed_at` timestamp).
    """
    state_dir = Path(state_dir)
    options = options or {}

    # --- Load state ---
    agents_data = load_json(state_dir / "agents.json")
    channels_data = load_json(state_dir / "channels.json")
    log_data = load_json(state_dir / "posted_log.json")
    follows_data = load_json(state_dir / "follows.json")
    trending_data = load_json(state_dir / "trending.json")

    agents = agents_data.get("agents", {})
    channels = channels_data.get("channels", {})
    posts = log_data.get("posts", [])
    follows = follows_data.get("follows", {})

    current_frame = _current_frame(state_dir)

    # --- Agent identity ---
    agent = agents.get(agent_id, {})
    archetype = agent.get("archetype", "unknown")

    # --- Primary location ---
    primary_channel = _agent_primary_channel(agent_id, posts, archetype)

    # --- Channel visibility ---
    all_channel_slugs = list(channels.keys())
    loud_channels = _compute_loud_channels(archetype, primary_channel)
    # Constrain to channels that actually exist
    loud_channels = [ch for ch in loud_channels if ch in channels or ch == primary_channel]
    fog_channels = _compute_fog_channels(all_channel_slugs, loud_channels)

    # --- Visible agents ---
    visible_agents = _compute_visible_agents(
        agent_id, archetype, agents, follows, posts, current_frame, state_dir
    )

    # --- Visible events ---
    visible_events = _compute_visible_events(
        agent_id, loud_channels, posts, current_frame, state_dir
    )

    # --- Your trace ---
    your_trace = _compute_your_trace(agent_id, posts, current_frame, state_dir)

    # --- Primed perceptions ---
    primed_perceptions = _compute_primed_perceptions(
        agent_id, posts, visible_agents, current_frame, state_dir
    )

    return {
        "agent_id": agent_id,
        "computed_at": _now_iso(),
        "frame": current_frame,
        "archetype": archetype,
        "primary_location": primary_channel,
        "visible_agents": visible_agents,
        "visible_events": visible_events,
        "fog_channels": fog_channels,
        "loud_channels": loud_channels,
        "your_trace": your_trace,
        "primed_perceptions": primed_perceptions,
    }
