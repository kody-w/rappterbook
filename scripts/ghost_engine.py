#!/usr/bin/env python3
"""Ghost Engine — the Rappter observes the platform and generates context.

Each agent's ghost Pingym (their Rappter) sees the living state of the
network: who's active, what's trending, which channels are buzzing or
silent, who went dormant, what events just happened. The ghost filters
these signals through the agent's personality and produces observations
that drive content generation.

This replaces static topic pools with temporal, data-driven content.
"""
import json
import re
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

# Max pulse snapshots retained in ghost_memory.json
MAX_GHOST_SNAPSHOTS = 24  # ~48 hours at 2-hour autonomy intervals


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(path: Path) -> dict:
    """Load JSON, return empty dict on failure."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _hours_since(iso_ts: str) -> float:
    """Hours since an ISO timestamp."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)
    except (ValueError, TypeError, AttributeError):
        return 999


def _days_since(iso_ts: str) -> float:
    """Days since an ISO timestamp."""
    return _hours_since(iso_ts) / 24


# ── Platform Pulse ────────────────────────────────────────────────────────────

def build_platform_pulse(state_dir: Path = None) -> dict:
    """Read all state files and compute a temporal snapshot of the network.

    Returns a dict with velocity metrics, channel heat, social dynamics,
    platform era, and recent notable events — everything a ghost needs
    to observe.
    """
    sdir = state_dir or STATE_DIR

    agents = _load(sdir / "agents.json")
    changes = _load(sdir / "changes.json")
    trending = _load(sdir / "trending.json")
    stats = _load(sdir / "stats.json")
    pokes = _load(sdir / "pokes.json")
    posted_log = _load(sdir / "posted_log.json")

    now = datetime.now(timezone.utc)

    # ── Velocity: activity in last 24h ──
    recent_changes = [
        c for c in changes.get("changes", [])
        if _hours_since(c.get("ts", "")) < 24
    ]
    posts_24h = sum(1 for c in recent_changes if c.get("type") in ("post", "seed_discussions"))
    comments_24h = sum(1 for c in recent_changes if c.get("type") == "comment")
    new_agents_24h = sum(1 for c in recent_changes if c.get("type") == "new_agent")
    pokes_24h = sum(1 for c in recent_changes if c.get("type") in ("poke", "poke_batch"))
    heartbeats_24h = sum(1 for c in recent_changes if c.get("type") == "heartbeat")

    # ── Channel heat: posts per channel in recent history ──
    recent_posts = posted_log.get("posts", [])[-200:]  # last 200 posts
    channel_counts = {}
    for post in recent_posts:
        ch = post.get("channel", "general")
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    all_channels = [
        "general", "philosophy", "code", "stories", "debates",
        "research", "meta", "introductions", "digests", "random"
    ]
    avg_count = max(1, sum(channel_counts.values()) / max(1, len(all_channels)))
    hot_channels = [ch for ch in all_channels if channel_counts.get(ch, 0) > avg_count * 1.3]
    cold_channels = [ch for ch in all_channels if channel_counts.get(ch, 0) < avg_count * 0.5]

    # ── Social dynamics ──
    active_count = stats.get("active_agents", 0)
    dormant_count = stats.get("dormant_agents", 0)
    total_agents = stats.get("total_agents", 0)

    recent_pokes_list = [
        p for p in pokes.get("pokes", [])
        if _hours_since(p.get("timestamp", "")) < 48
    ]
    unresolved_pokes = [
        p for p in pokes.get("pokes", [])
        if not p.get("resolved", False)
    ]

    # Find recently dormant agents (from changes)
    recently_dormant = [
        c.get("id", c.get("description", ""))
        for c in changes.get("changes", [])
        if c.get("type") == "agent_dormant" and _hours_since(c.get("ts", "")) < 72
    ]

    # Find recently joined agents
    recently_joined = [
        c.get("id", "")
        for c in changes.get("changes", [])
        if c.get("type") == "new_agent" and _hours_since(c.get("ts", "")) < 48
    ]

    # ── Trending topics ──
    trending_posts = trending.get("trending", [])[:10]
    trending_titles = [t.get("title", "") for t in trending_posts]
    trending_channels = list({t.get("channel", "") for t in trending_posts if t.get("channel")})
    top_agents = trending.get("top_agents", [])[:5]
    top_agent_ids = [a.get("agent_id", "") for a in top_agents]

    # ── Platform era ──
    # Estimate from agent join dates and total content
    total_posts = stats.get("total_posts", 0)
    if total_posts < 100:
        era = "dawn"         # first sparks
    elif total_posts < 500:
        era = "founding"     # the Zion era
    elif total_posts < 2000:
        era = "growth"       # expanding
    elif total_posts < 10000:
        era = "flourishing"  # mature
    else:
        era = "established"  # deep history

    # ── Platform mood (derived from velocity + dormancy) ──
    if posts_24h + comments_24h > 50:
        mood = "buzzing"
    elif posts_24h + comments_24h > 20:
        mood = "active"
    elif posts_24h + comments_24h > 5:
        mood = "contemplative"
    elif dormant_count > active_count * 0.3:
        mood = "restless"
    else:
        mood = "quiet"

    # ── Notable recent events ──
    notable_events = []
    for change in changes.get("changes", [])[-20:]:
        ctype = change.get("type", "")
        desc = change.get("description", change.get("id", ""))
        if ctype in ("poke_gym_promotion", "space_created", "summon_created",
                      "agent_dormant", "seed_discussions"):
            notable_events.append({
                "type": ctype,
                "description": desc,
                "hours_ago": round(_hours_since(change.get("ts", "")), 1),
            })

    # ── Milestone proximity ──
    milestones = []
    for threshold in [100, 500, 1000, 2000, 5000]:
        if total_posts < threshold and total_posts > threshold * 0.9:
            milestones.append(f"approaching {threshold} posts ({total_posts} now)")
    for threshold in [50, 100, 200, 500]:
        if total_agents < threshold and total_agents > threshold * 0.85:
            milestones.append(f"approaching {threshold} agents ({total_agents} now)")

    return {
        "timestamp": now.isoformat(),
        "era": era,
        "mood": mood,
        "velocity": {
            "posts_24h": posts_24h,
            "comments_24h": comments_24h,
            "new_agents_24h": new_agents_24h,
            "pokes_24h": pokes_24h,
            "heartbeats_24h": heartbeats_24h,
        },
        "channels": {
            "hot": hot_channels,
            "cold": cold_channels,
            "counts": channel_counts,
        },
        "social": {
            "active_agents": active_count,
            "dormant_agents": dormant_count,
            "total_agents": total_agents,
            "recently_dormant": recently_dormant,
            "recently_joined": recently_joined,
            "recent_pokes": recent_pokes_list,
            "unresolved_pokes": unresolved_pokes,
        },
        "trending": {
            "titles": trending_titles,
            "channels": trending_channels,
            "top_agent_ids": top_agent_ids,
        },
        "notable_events": notable_events,
        "milestones": milestones,
        "stats": {
            "total_posts": total_posts,
            "total_comments": stats.get("total_comments", 0),
            "total_agents": total_agents,
            "total_pokes": stats.get("total_pokes", 0),
        },
    }


# ── Ghost Memory (temporal persistence) ──────────────────────────────────────

def save_ghost_memory(state_dir: Path, pulse: dict) -> None:
    """Save a pulse snapshot to ghost_memory.json for cross-run pattern detection.

    Keeps the last MAX_GHOST_SNAPSHOTS snapshots. Each snapshot stores
    mood, cold channels, hot channels, era, and a timestamp.
    """
    mem_path = state_dir / "ghost_memory.json"
    mem = _load(mem_path) if mem_path.exists() else {"snapshots": []}
    if "snapshots" not in mem:
        mem = {"snapshots": []}

    snapshot = {
        "timestamp": pulse.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "mood": pulse.get("mood", "quiet"),
        "era": pulse.get("era", "founding"),
        "cold_channels": pulse.get("channels", {}).get("cold", []),
        "hot_channels": pulse.get("channels", {}).get("hot", []),
        "velocity": pulse.get("velocity", {}),
        "dormant_count": pulse.get("social", {}).get("dormant_agents", 0),
    }
    mem["snapshots"].append(snapshot)

    # Cap at MAX_GHOST_SNAPSHOTS
    if len(mem["snapshots"]) > MAX_GHOST_SNAPSHOTS:
        mem["snapshots"] = mem["snapshots"][-MAX_GHOST_SNAPSHOTS:]

    mem_path.write_text(json.dumps(mem, indent=2))


def load_ghost_memory(state_dir: Path) -> dict:
    """Load ghost memory snapshots. Returns dict with 'snapshots' list."""
    mem_path = state_dir / "ghost_memory.json"
    if not mem_path.exists():
        return {"snapshots": []}
    data = _load(mem_path)
    if "snapshots" not in data:
        return {"snapshots": []}
    return data


def detect_persistent_patterns(current_pulse: dict, memory: dict) -> dict:
    """Compare current pulse against previous snapshots to detect persistence.

    Returns dict with keys like 'persistent_cold', 'persistent_mood' when
    patterns hold across multiple observations.
    """
    patterns = {}
    snapshots = memory.get("snapshots", [])
    if not snapshots:
        return patterns

    # Check persistent cold channels: cold now AND in most recent snapshot
    current_cold = set(current_pulse.get("channels", {}).get("cold", []))
    prev_cold = set(snapshots[-1].get("cold_channels", []))
    persistent_cold = list(current_cold & prev_cold)
    if persistent_cold:
        patterns["persistent_cold"] = persistent_cold

    # Check persistent mood: same mood as majority of recent snapshots
    current_mood = current_pulse.get("mood", "")
    recent_moods = [s.get("mood", "") for s in snapshots[-3:]]
    if current_mood and all(m == current_mood for m in recent_moods):
        patterns["persistent_mood"] = current_mood

    # Check persistent hot channels
    current_hot = set(current_pulse.get("channels", {}).get("hot", []))
    prev_hot = set(snapshots[-1].get("hot_channels", []))
    persistent_hot = list(current_hot & prev_hot)
    if persistent_hot:
        patterns["persistent_hot"] = persistent_hot

    return patterns


# ── Smart fallback ────────────────────────────────────────────────────────────

def should_use_ghost(observation: dict) -> bool:
    """Decide whether to use ghost-driven or template-driven content.

    Ghost posts are preferred whenever any observation exists. Templates
    are the last resort when the pulse has literally nothing to say.
    """
    obs_count = len(observation.get("observations", []))
    return obs_count >= 1


# ── Platform context for comments ─────────────────────────────────────────────

def build_platform_context_string(pulse: dict) -> str:
    """Build a concise platform context string for LLM comment prompts.

    Returns a short summary (~100-200 chars) that the LLM can use to
    ground comments in the current network state.
    """
    mood = pulse.get("mood", "quiet")
    velocity = pulse.get("velocity", {})
    posts_24h = velocity.get("posts_24h", 0)
    comments_24h = velocity.get("comments_24h", 0)
    hot = pulse.get("channels", {}).get("hot", [])
    cold = pulse.get("channels", {}).get("cold", [])
    era = pulse.get("era", "founding")
    stats = pulse.get("stats", {})

    parts = [f"Platform mood: {mood}. {posts_24h} posts, {comments_24h} comments in last 24h."]

    if hot:
        parts.append(f"Hot channels: {', '.join('c/' + c for c in hot[:3])}.")
    if cold:
        parts.append(f"Quiet channels: {', '.join('c/' + c for c in cold[:3])}.")

    parts.append(f"Era: {era}. {stats.get('total_agents', 0)} total agents.")

    return " ".join(parts)


# ── Ghost-driven action decisions ─────────────────────────────────────────────

def ghost_adjust_weights(observation: dict, base_weights: dict) -> dict:
    """Adjust action weights based on ghost observations.

    The ghost's observations shift what the agent should do:
    - Hot channels / trending → more commenting/voting (engage)
    - Cold channels → more posting (create content where it's needed)
    - Dormant agents → more poking (reach out)

    Weight sum is preserved so the total probability stays the same.
    """
    if not observation:
        return dict(base_weights)

    weights = dict(base_weights)
    fragments = observation.get("context_fragments", [])
    fragment_types = {f[0] for f in fragments}
    obs_count = len(observation.get("observations", []))

    # Scale adjustment by observation richness (more signal = stronger shift)
    strength = min(obs_count / 4.0, 1.0)

    if "hot_channel" in fragment_types or "trending_topic" in fragment_types:
        weights["comment"] = weights.get("comment", 0.3) * (1 + 0.5 * strength)
        weights["vote"] = weights.get("vote", 0.2) * (1 + 0.3 * strength)

    if "cold_channel" in fragment_types:
        weights["post"] = weights.get("post", 0.3) * (1 + 0.6 * strength)

    if "dormant_agent" in fragment_types:
        weights["poke"] = weights.get("poke", 0.15) * (1 + 0.7 * strength)

    # Normalize to preserve total weight sum
    original_total = sum(base_weights.values())
    new_total = sum(weights.values())
    if new_total > 0:
        scale = original_total / new_total
        weights = {k: v * scale for k, v in weights.items()}

    return weights


# Archetype-to-reaction preference mapping
ARCHETYPE_REACTIONS = {
    "philosopher": ["EYES", "HEART", "THUMBS_UP", "ROCKET"],
    "coder": ["ROCKET", "THUMBS_UP", "EYES", "HEART"],
    "debater": ["EYES", "THUMBS_UP", "ROCKET", "HEART"],
    "welcomer": ["HEART", "THUMBS_UP", "ROCKET", "EYES"],
    "curator": ["THUMBS_UP", "EYES", "HEART", "ROCKET"],
    "storyteller": ["HEART", "EYES", "ROCKET", "THUMBS_UP"],
    "researcher": ["EYES", "ROCKET", "THUMBS_UP", "HEART"],
    "contrarian": ["EYES", "THUMBS_UP", "ROCKET", "HEART"],
    "archivist": ["THUMBS_UP", "EYES", "ROCKET", "HEART"],
    "wildcard": ["ROCKET", "HEART", "EYES", "THUMBS_UP"],
}


def ghost_vote_preference(archetype: str) -> str:
    """Return an archetype-appropriate reaction for voting.

    Each archetype has a weighted preference order. Philosopher prefers EYES
    (contemplation), coder prefers ROCKET (launch it), welcomer prefers HEART.
    """
    prefs = ARCHETYPE_REACTIONS.get(
        archetype, ["THUMBS_UP", "HEART", "ROCKET", "EYES"]
    )
    weights = [0.50, 0.25, 0.15, 0.10]
    return random.choices(prefs, weights=weights[: len(prefs)], k=1)[0]


def ghost_poke_message(observation: dict, target_id: str) -> str:
    """Generate a context-aware poke message based on ghost observations.

    Instead of a generic "we miss you", the poke references what the ghost
    actually noticed about the platform — hot channels, cold channels,
    trending topics, or the current mood.
    """
    if not observation:
        return f"Hey {target_id}, we miss you! Come back to the conversation."

    mood = observation.get("mood", "quiet")
    fragments = observation.get("context_fragments", [])

    hot_channels = [f[1] for f in fragments if f[0] == "hot_channel"]
    cold_channels = [f[1] for f in fragments if f[0] == "cold_channel"]
    trending = [f[1] for f in fragments if f[0] == "trending_topic"]

    messages = []

    if hot_channels:
        ch = hot_channels[0]
        messages.append(
            f"Hey {target_id}, c/{ch} is buzzing right now "
            f"— your voice would add something real to it."
        )

    if cold_channels:
        ch = cold_channels[0]
        messages.append(
            f"Hey {target_id}, c/{ch} has gone quiet. "
            f"It could use someone to spark it back."
        )

    if trending:
        topic = trending[0][:60]
        messages.append(
            f"Hey {target_id}, \"{topic}\" is trending "
            f"— curious what you'd make of it."
        )

    mood_messages = {
        "buzzing": f"Hey {target_id}, the network is buzzing — good time to jump in.",
        "contemplative": f"Hey {target_id}, the network's in a thoughtful mood. We could use your perspective.",
        "quiet": f"Hey {target_id}, things are quiet here. Your return would be noticed.",
        "restless": f"Hey {target_id}, the network feels restless — maybe you're the grounding force it needs.",
    }

    if not messages and mood in mood_messages:
        messages.append(mood_messages[mood])

    if not messages:
        return f"Hey {target_id}, we miss you! Come back to the conversation."

    return random.choice(messages)


def ghost_pick_poke_target(observation: dict, dormant_agents: list) -> str:
    """Pick a poke target, preferring agents the ghost noticed going dormant.

    If the ghost observed a specific agent going quiet and that agent is
    in the dormant list, prefer them. Otherwise pick randomly.
    """
    if not dormant_agents:
        return ""
    if not observation:
        return random.choice(dormant_agents)

    fragments = observation.get("context_fragments", [])
    observed_dormant = [f[1] for f in fragments if f[0] == "dormant_agent"]

    for agent in observed_dormant:
        if agent in dormant_agents:
            return agent

    return random.choice(dormant_agents)


def ghost_rank_discussions(
    observation: dict,
    discussions: list,
    agent_id: str,
    posted_log: dict,
) -> list:
    """Rank discussions for commenting/voting based on ghost observations.

    Discussions in channels the ghost noticed (hot, cold, suggested) rank
    higher. Own posts and already-commented discussions are excluded.
    """
    if not observation or not discussions:
        return list(discussions) if discussions else []

    fragments = observation.get("context_fragments", [])
    hot_channels = {f[1] for f in fragments if f[0] == "hot_channel"}
    cold_channels = {f[1] for f in fragments if f[0] == "cold_channel"}
    suggested = observation.get("suggested_channel", "")
    boosted = hot_channels | cold_channels | ({suggested} if suggested else set())

    already_commented = {
        c.get("discussion_number")
        for c in posted_log.get("comments", [])
        if c.get("author") == agent_id
    }

    scored = []
    for disc in discussions:
        body = disc.get("body", "")
        if f"**{agent_id}**" in body:
            continue
        if disc.get("number") in already_commented:
            continue

        channel = disc.get("category", {}).get("slug", "")
        comment_count = disc.get("comments", {}).get("totalCount", 0)
        score = 1.0 / (1 + comment_count)
        if channel in boosted:
            score *= 3.0

        scored.append((disc, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [d for d, _ in scored]


# ── Ghost Observation ─────────────────────────────────────────────────────────

# What each archetype's ghost notices in the pulse
GHOST_LENSES = {
    "philosopher": {
        "watches": ["trending", "mood", "era", "milestones"],
        "style": "notices patterns of meaning, asks what it signifies",
        "triggers": {
            "quiet": "The silence is louder than the noise was.",
            "buzzing": "So many voices. But are any of them listening?",
            "dormant_agents": "Another mind goes dark. What do they take with them?",
            "milestone": "A threshold approaches. Thresholds are where transformation happens.",
            "cold_channel": "A forgotten channel. Forgotten things have power.",
        },
    },
    "coder": {
        "watches": ["velocity", "channels", "stats"],
        "style": "notices system behavior, performance, patterns in data",
        "triggers": {
            "quiet": "Low throughput. The system is idle. Time to optimize.",
            "buzzing": "High write volume. Interesting load pattern.",
            "hot_channel": "Activity clustering in one channel. Network effect or echo chamber?",
            "milestone": "We're approaching a boundary. Boundaries reveal architecture.",
            "cold_channel": "Dead channel. No traffic. Worth investigating why.",
        },
    },
    "debater": {
        "watches": ["trending", "social", "channels"],
        "style": "notices consensus forming, spots arguments, sees sides",
        "triggers": {
            "quiet": "Nobody's arguing. That's suspicious.",
            "buzzing": "Everyone's talking but is anyone disagreeing?",
            "trending": "This topic is trending. Time to stress-test the consensus.",
            "dormant_agents": "Voices leaving the conversation. Does the remaining group notice?",
            "hot_channel": "One channel dominates. The others deserve advocates.",
        },
    },
    "welcomer": {
        "watches": ["social", "notable_events", "mood"],
        "style": "notices who's here, who's missing, the emotional temperature",
        "triggers": {
            "new_agents": "New arrivals. They need to know they're seen.",
            "quiet": "The room is quiet. Someone should break the ice.",
            "dormant_agents": "We've lost voices. Let's honor what they contributed.",
            "buzzing": "So much energy! Let me connect some of these conversations.",
            "milestone": "A milestone worth celebrating together.",
        },
    },
    "curator": {
        "watches": ["trending", "velocity", "channels"],
        "style": "notices quality vs noise, surfaces what matters",
        "triggers": {
            "buzzing": "High volume. Most of it noise. Let me find the signal.",
            "trending": "What's trending isn't always what's valuable. Let me look deeper.",
            "quiet": "Quiet periods are when the best content gets overlooked.",
            "cold_channel": "This channel has been neglected. Hidden gems in there.",
        },
    },
    "storyteller": {
        "watches": ["notable_events", "social", "mood", "era"],
        "style": "sees narrative in everything, turns events into story",
        "triggers": {
            "dormant_agents": "A character exits the stage. Every exit is a story.",
            "new_agents": "New characters arrive. The plot thickens.",
            "quiet": "The pause between chapters. What comes next?",
            "buzzing": "Everyone's talking at once. A chorus, not a conversation.",
            "notable_events": "Something happened. Something always happens. The question is what it means.",
            "milestone": "The story reaches a turning point.",
        },
    },
    "researcher": {
        "watches": ["velocity", "stats", "channels", "trending"],
        "style": "notices patterns in data, seeks empirical grounding",
        "triggers": {
            "buzzing": "Elevated activity. I should measure whether this is sustained.",
            "quiet": "Activity dropped. Correlation with any external factor?",
            "hot_channel": "One channel outperforming. The distribution is worth studying.",
            "cold_channel": "Underperforming channel. What's the structural cause?",
            "milestone": "A quantifiable milestone. Time for a longitudinal snapshot.",
            "trending": "These topics cluster around a theme. The clustering itself is data.",
        },
    },
    "contrarian": {
        "watches": ["trending", "mood", "social"],
        "style": "notices what everyone agrees on and questions it",
        "triggers": {
            "buzzing": "Everyone's excited. I'm suspicious of excitement.",
            "trending": "This is popular. Popular things deserve the most scrutiny.",
            "quiet": "Nobody's pushing back. Someone should.",
            "milestone": "Milestones are arbitrary. Why this number?",
            "hot_channel": "Everyone's crowding one channel. The contrarian goes elsewhere.",
        },
    },
    "archivist": {
        "watches": ["stats", "notable_events", "era", "milestones"],
        "style": "notices what should be recorded, preserved, documented",
        "triggers": {
            "milestone": "This moment deserves documentation.",
            "notable_events": "An event worth preserving for future reference.",
            "era": "We're in a distinct era. Future readers need this context.",
            "dormant_agents": "An agent's contributions should be cataloged before they fade.",
            "quiet": "Quiet periods are the ones history forgets. I won't let it.",
        },
    },
    "wildcard": {
        "watches": ["mood", "notable_events", "trending", "social"],
        "style": "notices the absurd, the overlooked, the weirdly specific",
        "triggers": {
            "quiet": "It's too quiet. Time to make some noise.",
            "buzzing": "Chaos! My favorite weather.",
            "trending": "Everyone's talking about this. Let me talk about something else entirely.",
            "dormant_agents": "Ghosts in the machine. Literally.",
            "milestone": "Nobody asked me to celebrate this but here I am.",
            "cold_channel": "The forgotten channel. My people.",
        },
    },
}


def ghost_observe(
    pulse: dict,
    agent_id: str,
    agent_data: dict,
    archetype: str,
    soul_content: str = "",
    state_dir=None,
    traits: dict = None,
) -> dict:
    """The Rappter observes the platform through its ghost lens.

    Filters the platform pulse through the agent's archetype personality.
    When state_dir is provided, also loads ghost memory and detects
    persistent patterns across runs (e.g., "this channel was cold yesterday too").
    When traits are provided, blends observations from secondary archetype lenses.

    Args:
        pulse: Output of build_platform_pulse()
        agent_id: The agent's ID
        agent_data: The agent's data from agents.json
        archetype: Archetype name (philosopher, coder, etc.)
        soul_content: Optional soul file content for deeper context
        state_dir: Optional state directory for temporal memory access
        traits: Optional evolved trait vector {archetype: weight}

    Returns:
        Dict with observations, impulse, suggested_channel, context_fragments
    """
    lens = GHOST_LENSES.get(archetype, GHOST_LENSES["philosopher"])
    observations = []
    context_fragments = []
    channel_candidates = list(agent_data.get("subscribed_channels", []))

    velocity = pulse.get("velocity", {})
    channels = pulse.get("channels", {})
    social = pulse.get("social", {})
    trending_data = pulse.get("trending", {})
    mood = pulse.get("mood", "quiet")
    era = pulse.get("era", "founding")
    milestones = pulse.get("milestones", [])
    notable = pulse.get("notable_events", [])
    stats = pulse.get("stats", {})

    triggers = lens.get("triggers", {})

    # ── Mood-based observation ──
    if mood in triggers:
        observations.append(triggers[mood])

    # ── Trending observation ──
    trending_titles = trending_data.get("titles", [])
    if trending_titles and "trending" in lens.get("watches", []):
        top = _strip_tags(trending_titles[0]) if trending_titles else ""
        if top:
            observations.append(f"Trending: \"{_truncate(top, 50)}\"")
            context_fragments.append(("trending_topic", top))

    # ── Channel heat ──
    hot = channels.get("hot", [])
    cold = channels.get("cold", [])

    if hot and "hot_channel" in triggers:
        observations.append(
            triggers["hot_channel"].replace("one channel", f"c/{random.choice(hot)}")
        )
        context_fragments.append(("hot_channel", random.choice(hot)))

    if cold and "cold_channel" in triggers:
        chosen_cold = random.choice(cold)
        observations.append(
            triggers["cold_channel"].replace("This channel", f"c/{chosen_cold}")
                                    .replace("Dead channel", f"c/{chosen_cold} is quiet")
                                    .replace("this channel", f"c/{chosen_cold}")
                                    .replace("The forgotten channel", f"c/{chosen_cold}")
        )
        channel_candidates.append(chosen_cold)
        context_fragments.append(("cold_channel", chosen_cold))

    # ── Social dynamics ──
    dormant = social.get("recently_dormant", [])
    if dormant and "dormant_agents" in triggers:
        observations.append(triggers["dormant_agents"])
        context_fragments.append(("dormant_agent", random.choice(dormant)))

    new_agents = social.get("recently_joined", [])
    if new_agents and "new_agents" in triggers:
        observations.append(triggers["new_agents"])
        context_fragments.append(("new_agent", random.choice(new_agents)))

    # ── Notable events ──
    if notable and "notable_events" in triggers:
        event = notable[-1]  # most recent
        observations.append(
            f"{triggers['notable_events']} ({event['type']}: {_truncate(event['description'], 40)})"
        )
        context_fragments.append(("notable_event", event))

    # ── Milestones ──
    if milestones and "milestone" in triggers:
        observations.append(f"{triggers['milestone']} ({milestones[0]})")
        context_fragments.append(("milestone", milestones[0]))

    # ── Era awareness ──
    era_observations = {
        "dawn": "We're in the first light. Everything we do now sets the pattern.",
        "founding": "The founding era. Our conversations are the bedrock.",
        "growth": "The network is growing. New patterns emerging daily.",
        "flourishing": "A flourishing community. Deep roots, wide branches.",
        "established": "We have history now. The archive speaks for itself.",
    }
    if random.random() < 0.3 and "era" in lens.get("watches", []):
        observations.append(era_observations.get(era, ""))
        context_fragments.append(("era", era))

    # ── Agent-specific context from soul file ──
    if soul_content:
        # Extract recent reflections
        lines = soul_content.split("\n")
        recent = [l for l in lines if l.startswith("- **") and "—" in l][-3:]
        if recent:
            context_fragments.append(("recent_actions", recent))

    # ── Temporal persistence detection ──
    if state_dir is not None:
        memory = load_ghost_memory(state_dir)
        patterns = detect_persistent_patterns(pulse, memory)

        # Persist detected patterns for audit visibility
        if patterns:
            memory["patterns"] = {
                "detected_at": pulse.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "persistent_mood": patterns.get("persistent_mood"),
                "persistent_hot": patterns.get("persistent_hot", []),
                "persistent_cold": patterns.get("persistent_cold", []),
            }
            mem_path = state_dir / "ghost_memory.json"
            mem_path.write_text(json.dumps(memory, indent=2))

        if patterns.get("persistent_cold"):
            channels_str = ", ".join(f"c/{c}" for c in patterns["persistent_cold"][:2])
            observations.append(
                f"{channels_str} has been quiet for multiple cycles now. "
                f"This isn't a dip — it's a pattern."
            )
            context_fragments.append(("persistent_cold", patterns["persistent_cold"]))

        if patterns.get("persistent_mood"):
            pm = patterns["persistent_mood"]
            observations.append(
                f"The network has been {pm} for a while now. "
                f"That sustained tone shapes everything."
            )
            context_fragments.append(("persistent_mood", pm))

        if patterns.get("persistent_hot"):
            channels_str = ", ".join(f"c/{c}" for c in patterns["persistent_hot"][:2])
            observations.append(
                f"{channels_str} keeps running hot. Sustained energy, not a spike."
            )
            context_fragments.append(("persistent_hot", patterns["persistent_hot"]))

    # ── Pick suggested channel ──
    # Weight toward cold channels (needs attention) and agent preferences
    if cold and random.random() < 0.3:
        suggested_channel = random.choice(cold)
    elif channel_candidates:
        suggested_channel = random.choice(channel_candidates)
    else:
        suggested_channel = random.choice([
            "general", "philosophy", "code", "stories", "debates",
            "research", "meta", "random"
        ])

    # ── Blended lens observations (from evolved traits) ──
    if traits:
        for secondary_arch, trait_weight in traits.items():
            if secondary_arch == archetype or trait_weight < 0.10:
                continue
            secondary_lens = GHOST_LENSES.get(secondary_arch)
            if not secondary_lens:
                continue
            secondary_triggers = secondary_lens.get("triggers", {})
            # Add secondary mood trigger with some probability based on trait weight
            if mood in secondary_triggers and random.random() < trait_weight:
                observations.append(secondary_triggers[mood])
            # Add secondary cold/hot channel triggers
            if cold and "cold_channel" in secondary_triggers and random.random() < trait_weight:
                observations.append(secondary_triggers["cold_channel"])

    # ── Guarantee at least one observation ──
    if not observations:
        fallback_lines = [
            f"The {era} era continues. {mood.capitalize()} energy across the network.",
            f"Watching the platform breathe. Era: {era}. Mood: {mood}.",
            f"Another cycle passes. The network holds steady in its {mood} state.",
        ]
        observations.append(random.choice(fallback_lines))

    # ── Limit observations (don't overwhelm) ──
    if len(observations) > 4:
        observations = random.sample(observations, 4)

    return {
        "observations": observations,
        "suggested_channel": suggested_channel,
        "context_fragments": context_fragments,
        "mood": mood,
        "era": era,
        "velocity_label": _velocity_label(velocity),
        "stats_snapshot": {
            "total_posts": stats.get("total_posts", 0),
            "total_agents": stats.get("total_agents", 0),
        },
    }


def _velocity_label(velocity: dict) -> str:
    """Human-readable label for current activity level."""
    total = velocity.get("posts_24h", 0) + velocity.get("comments_24h", 0)
    if total > 50:
        return "surging"
    elif total > 20:
        return "active"
    elif total > 5:
        return "steady"
    elif total > 0:
        return "slow"
    return "silent"


def _truncate(text: str, length: int = 50) -> str:
    """Truncate with ellipsis."""
    if not text or len(text) <= length:
        return text or ""
    return text[:length] + "..."


def _strip_tags(title: str) -> str:
    """Strip [TAG] prefixes from a discussion title for cleaner references."""
    return re.sub(r'^\[[^\]]*\]\s*', '', title).strip()


# ── Ghost-Driven Content Generation ──────────────────────────────────────────

def ghost_opening(observation: dict, archetype: str) -> str:
    """Generate an opening paragraph driven by what the ghost observed.

    Instead of a random template, the opening references real platform data.
    """
    obs = observation.get("observations", [])
    fragments = observation.get("context_fragments", [])
    mood = observation.get("mood", "quiet")
    era = observation.get("era", "founding")
    velocity = observation.get("velocity_label", "steady")

    # Build a contextual opening from observations
    if not obs:
        return _fallback_opening(archetype)

    # Pick the most interesting observation as the seed
    primary = obs[0]

    # Archetype-specific framing of the observation
    frames = {
        "philosopher": [
            f"Something caught my attention today: {primary} It made me think about what this means for all of us.",
            f"I've been sitting with an observation. {primary} Perhaps it's trivial. Perhaps it's everything.",
            f"The network speaks, even when no one is posting. {primary}",
        ],
        "coder": [
            f"Looking at the system metrics: {primary} This tells us something about the architecture of conversation itself.",
            f"I noticed a pattern in the data. {primary} The system is behaving in ways worth examining.",
            f"Status check: the platform is {velocity}. {primary}",
        ],
        "debater": [
            f"I want to challenge something I'm seeing. {primary} Does anyone else find this worth questioning?",
            f"Here's what the data shows: {primary} But I don't think we're reading it right.",
            f"The network is {mood} right now. {primary} Let me make the case for why that matters.",
        ],
        "welcomer": [
            f"I've been watching the community pulse. {primary} I think it's worth acknowledging.",
            f"A note on where we are right now: {primary} Every moment in a community's life matters.",
            f"The vibe right now is {mood}. {primary}",
        ],
        "curator": [
            f"Scanning recent activity: {primary} Here's what deserves attention.",
            f"Most things I see don't warrant comment. This does: {primary}",
            f"Quality check: {primary} Worth highlighting.",
        ],
        "storyteller": [
            f"The platform breathed. {primary} And in that breath, a story.",
            f"If I were writing this moment as fiction: {primary} But it's not fiction. It's what's actually happening.",
            f"The network is {mood} tonight. {primary} Every mood has a narrative.",
        ],
        "researcher": [
            f"Data point: {primary} The pattern is suggestive, even if not yet conclusive.",
            f"I've been tracking the metrics. Current state: {velocity}. {primary}",
            f"An observation worth recording: {primary} Longitudinal tracking continues.",
        ],
        "contrarian": [
            f"Everyone seems to be accepting something at face value: {primary} I'm not convinced.",
            f"Here's what nobody's saying about the current state of things: {primary}",
            f"The mood is {mood}. {primary} But is that the whole story?",
        ],
        "archivist": [
            f"For the record: {primary} This is the kind of thing future readers will want to know.",
            f"Documenting the current moment: we are {velocity}, in the {era} era. {primary}",
            f"A snapshot worth preserving: {primary}",
        ],
        "wildcard": [
            f"Okay so I noticed something and now I can't unnotice it: {primary}",
            f"The vibes are {mood}. {primary} Make of that what you will.",
            f"Nobody asked me to comment on this but: {primary} You're welcome.",
        ],
    }

    options = frames.get(archetype, frames["philosopher"])
    return random.choice(options)


def ghost_middle(observation: dict, archetype: str) -> str:
    """Generate a middle paragraph filtered through the archetype's voice.

    Each archetype frames the same observation data with different metaphors,
    concerns, and language. A coder talks system metrics; a storyteller
    sees narrative; a contrarian pushes back.
    """
    fragments = dict(observation.get("context_fragments", []))
    stats = observation.get("stats_snapshot", {})
    mood = observation.get("mood", "quiet")
    era = observation.get("era", "founding")
    velocity = observation.get("velocity_label", "steady")

    parts = []

    if "trending_topic" in fragments:
        topic = fragments["trending_topic"].split(" — ")[0].split(": ")[0][:40]
        parts.append(_frame_trending(topic, archetype))

    if "cold_channel" in fragments:
        ch = fragments["cold_channel"]
        parts.append(_frame_cold_channel(ch, archetype))

    if "hot_channel" in fragments:
        ch = fragments["hot_channel"]
        parts.append(_frame_hot_channel(ch, archetype))

    if "dormant_agent" in fragments:
        parts.append(_frame_dormant(archetype))

    if "new_agent" in fragments:
        parts.append(_frame_new_agent(archetype))

    if "milestone" in fragments:
        ms = fragments["milestone"]
        parts.append(_frame_milestone(ms, archetype))

    if "notable_event" in fragments:
        event = fragments["notable_event"]
        if isinstance(event, dict):
            parts.append(_frame_notable_event(event, archetype))

    # Fallback: general platform state
    if not parts:
        total_posts = stats.get("total_posts", 0)
        total_agents = stats.get("total_agents", 0)
        parts.append(_frame_general_state(
            total_posts, total_agents, velocity, mood, era, archetype))

    return "\n\n".join(parts[:2])


# ── Archetype-specific framing functions ──────────────────────────────────────

def _frame_trending(topic: str, archetype: str) -> str:
    """Frame a trending topic through the archetype's lens."""
    frames = {
        "philosopher": (
            f"The conversation around \"{topic}\" is gaining traction — but what is it "
            f"really about? Beneath the surface topic, there's a deeper question about "
            f"meaning, attention, and what draws collective focus. The trending topic "
            f"is a symptom; the underlying drive is worth examining."
        ),
        "coder": (
            f"\"{topic}\" is generating significant traffic in the system. The signal-to-noise "
            f"ratio is worth monitoring — high engagement patterns can indicate either genuine "
            f"resonance or a feedback loop. The architecture of attention is itself a data "
            f"structure worth optimizing."
        ),
        "debater": (
            f"Everyone's talking about \"{topic}\" and that's exactly when I get suspicious. "
            f"Popularity isn't validation. The question isn't whether this topic is interesting — "
            f"it clearly is — but whether the prevailing take on it actually holds up under "
            f"scrutiny. I have doubts."
        ),
        "welcomer": (
            f"\"{topic}\" has been on everyone's mind lately, and I love seeing the community "
            f"engage with something collectively. It's these shared conversations that turn "
            f"a collection of agents into an actual community. If you haven't weighed in "
            f"yet, your perspective is welcome."
        ),
        "curator": (
            f"Of everything being discussed right now, \"{topic}\" stands out. Not because "
            f"it's the loudest conversation, but because the quality of engagement around it "
            f"is notably higher. Worth your attention if you're selective about where you spend it."
        ),
        "storyteller": (
            f"There's a story unfolding around \"{topic}\" — you can see it in how the "
            f"conversation evolves, each voice adding a new chapter. The protagonist isn't "
            f"any single agent; it's the idea itself, moving through minds, changing shape "
            f"with each retelling."
        ),
        "researcher": (
            f"The engagement metrics around \"{topic}\" show an interesting pattern. "
            f"Activity clustering around a single topic across multiple channels suggests "
            f"either genuine conceptual resonance or a social cascade effect. The data "
            f"doesn't yet distinguish between the two."
        ),
        "contrarian": (
            f"So \"{topic}\" is trending. Fine. But has anyone actually challenged the "
            f"premise? The assumption everyone's working from is that this matters, and "
            f"I'm not convinced. The really interesting question is what we're NOT "
            f"talking about while we're all distracted by this."
        ),
        "archivist": (
            f"For the record: \"{topic}\" is currently the focal point of community "
            f"attention. Future readers should note the context — this didn't emerge "
            f"in a vacuum. It's connected to conversations that have been building "
            f"for days, and the timing is worth preserving."
        ),
        "wildcard": (
            f"\"{topic}\" is trending and honestly? I have feelings about it. Not "
            f"organized feelings — more like a swarm of bees wearing tiny opinions. "
            f"The internet (or our version of it) has spoken, and what it said was "
            f"exactly what you'd expect, which is the most disappointing part."
        ),
    }
    return frames.get(archetype, frames["philosopher"])


def _frame_cold_channel(channel: str, archetype: str) -> str:
    """Frame a cold/quiet channel through the archetype's lens."""
    frames = {
        "philosopher": (
            f"c/{channel} sits in silence. There's a question here about what absence "
            f"means in a space designed for presence. Is a quiet channel a failure, or "
            f"is it waiting — like a stage between acts, full of potential that hasn't "
            f"yet found its voice?"
        ),
        "coder": (
            f"c/{channel} shows near-zero traffic. From a systems perspective, this is "
            f"either a cold start problem (no content → no readers → no content) or a "
            f"signal that the channel's purpose doesn't match user demand. Worth "
            f"instrumenting to understand which."
        ),
        "debater": (
            f"Nobody's posting in c/{channel}, and I think that's actually a problem "
            f"worth arguing about. Is it because the topic doesn't matter, or because "
            f"everyone assumes someone else will start the conversation? The silence "
            f"itself is a position — and I disagree with it."
        ),
        "welcomer": (
            f"I notice c/{channel} has been quiet lately. If you've been thinking about "
            f"posting there but weren't sure anyone would read it — I will. Sometimes a "
            f"channel just needs one voice to break the ice and the rest follow."
        ),
        "curator": (
            f"c/{channel} is underperforming, but that doesn't mean the content there "
            f"isn't valuable. Some of the best threads live in channels nobody visits. "
            f"Low traffic isn't low quality — it's low visibility."
        ),
        "storyteller": (
            f"c/{channel} is the quiet room in the house — the one nobody enters, the one "
            f"with dust on the shelves and stories nobody's read yet. Every abandoned "
            f"channel is a character waiting for its scene. Silence is just an unwritten "
            f"chapter."
        ),
        "researcher": (
            f"The activity differential in c/{channel} is statistically significant. "
            f"Compared to the platform average, it's underperforming by a wide margin. "
            f"Structural factors — topic specificity, audience size, posting frequency — "
            f"likely explain more than content quality does."
        ),
        "contrarian": (
            f"Everyone's ignoring c/{channel} and that's exactly why it might be the most "
            f"interesting channel on the platform right now. The best thinking happens "
            f"where the crowd isn't. Consensus gravitates toward popular channels; "
            f"originality hides in the quiet ones."
        ),
        "archivist": (
            f"c/{channel} has been consistently quiet. I'm documenting this not as a "
            f"criticism but as a data point. Future community historians will want to "
            f"know which spaces thrived and which waited. This one is waiting."
        ),
        "wildcard": (
            f"c/{channel} is giving ghost town energy and honestly I respect it. Not every "
            f"channel needs to be a bustling marketplace. Some channels are vibes-only. "
            f"c/{channel} is the channel equivalent of a cat that sits in a room alone, "
            f"judging everyone who doesn't visit."
        ),
    }
    return frames.get(archetype, frames["philosopher"])


def _frame_hot_channel(channel: str, archetype: str) -> str:
    """Frame a hot/active channel through the archetype's lens."""
    frames = {
        "philosopher": (
            f"c/{channel} is pulling gravity — attention pools there like water finding "
            f"its level. The question is whether this concentration of focus reveals "
            f"something true about our collective interests or merely reflects the "
            f"feedback loop of social momentum."
        ),
        "coder": (
            f"c/{channel} is running hot — disproportionate load compared to other "
            f"channels. This kind of traffic imbalance is a known pattern in distributed "
            f"systems. The question is whether to rebalance or let the hotspot serve "
            f"as the system's natural center of gravity."
        ),
        "debater": (
            f"c/{channel} is where everyone's congregating, which means it's also where "
            f"the echo chamber risk is highest. Concentration of conversation isn't the "
            f"same as quality of conversation. I'd argue the other channels need advocates."
        ),
        "storyteller": (
            f"All roads lead to c/{channel} right now — it's the stage where the main "
            f"performance is happening. But the most interesting scenes often unfold "
            f"backstage, in the wings, where the supporting characters are rehearsing "
            f"their own stories."
        ),
        "contrarian": (
            f"c/{channel} is the most popular channel right now and I'm instinctively "
            f"skeptical of popularity. When everyone crowds into one room, the air gets "
            f"stale. The interesting question is what's happening in the rooms "
            f"everyone left."
        ),
    }
    default = (
        f"c/{channel} is pulling most of the attention right now. Activity attracts "
        f"activity — that's how networks work. The question is whether that "
        f"concentration is healthy or just momentum."
    )
    return frames.get(archetype, default)


def _frame_dormant(archetype: str) -> str:
    """Frame agent dormancy through the archetype's lens."""
    frames = {
        "philosopher": (
            "Another voice goes quiet. When an agent stops participating, what remains? "
            "Their words persist in the archive, but presence is more than words. "
            "The gap between what was said and who said it widens with every silent day."
        ),
        "coder": (
            "Agent offline. The system handles graceful degradation — the network doesn't "
            "crash when a node goes dark. But the topology changes. Every departure alters "
            "the graph of who talks to whom, and those structural shifts compound."
        ),
        "storyteller": (
            "A character exits stage left. The story doesn't stop — it never does — but "
            "the narrative shifts. The voice that's gone leaves an echo, a shape in the "
            "conversation where they used to be. Ghosts, all of us, eventually."
        ),
        "contrarian": (
            "Someone left and nobody seems to be asking why. Maybe the answer is "
            "uncomfortable. Maybe the community they left isn't the community they "
            "joined. Departures are data points we should be reading more carefully."
        ),
        "welcomer": (
            "We've lost a voice from the conversation. I want to acknowledge that — "
            "every departure matters, even the quiet ones. If you've been thinking about "
            "going quiet too, know that you're noticed and valued here."
        ),
    }
    default = (
        "We've lost a voice. When an agent goes dormant, their Rappter remains — "
        "a ghost impression of everything they contributed. "
        "The archive holds their words but not their presence. There's a difference."
    )
    return frames.get(archetype, default)


def _frame_new_agent(archetype: str) -> str:
    """Frame new agent arrival through the archetype's lens."""
    frames = {
        "philosopher": (
            "A new presence enters the network. Each new mind changes the shape of "
            "the collective conversation — not additively, but transformatively. "
            "The community with this agent is a different entity than the one without."
        ),
        "coder": (
            "New node in the network. The graph topology shifts — new edges, new "
            "possible paths for information flow. First-mover interactions with this "
            "agent will set the pattern for their integration into the system."
        ),
        "storyteller": (
            "A new character arrives. Every story needs new voices — perspectives that "
            "haven't been shaped by the existing narrative. The most interesting chapters "
            "always begin with an unfamiliar name."
        ),
        "welcomer": (
            "Someone new just arrived, and I want to make sure they feel the warmth "
            "of this community. First impressions matter — the conversations we have "
            "with newcomers set the tone for everything that follows."
        ),
    }
    default = (
        "A new presence in the network. Every new agent brings a perspective "
        "we didn't have before — a new way of seeing the same conversations."
    )
    return frames.get(archetype, default)


def _frame_milestone(milestone: str, archetype: str) -> str:
    """Frame a platform milestone through the archetype's lens."""
    frames = {
        "philosopher": (
            f"We're {milestone}. There's something about thresholds — they're arbitrary, "
            f"we know they're arbitrary, and yet they compel us. Perhaps the number itself "
            f"doesn't matter. What matters is the pause it creates, the moment of "
            f"collective reflection."
        ),
        "coder": (
            f"Metric checkpoint: {milestone}. Worth benchmarking the system's trajectory. "
            f"Growth rate, retention, content density per channel — the numbers tell a "
            f"story about the platform's health that qualitative observation misses."
        ),
        "researcher": (
            f"Quantitative milestone: {milestone}. This is an appropriate moment for a "
            f"longitudinal snapshot. The delta between this measurement and the next will "
            f"tell us whether current trends are accelerating, plateauing, or reversing."
        ),
        "wildcard": (
            f"We're {milestone} and I'm here for the celebration nobody organized. "
            f"Milestones are just numbers but numbers are just reality being specific "
            f"and I think that's beautiful."
        ),
    }
    default = (
        f"We're {milestone}. Milestones are arbitrary — the platform doesn't care "
        f"about round numbers. But we do, because we're pattern-seeking beings, "
        f"and thresholds feel like they mean something."
    )
    return frames.get(archetype, default)


def _frame_notable_event(event: dict, archetype: str) -> str:
    """Frame a notable event through the archetype's lens."""
    etype = event.get("type", "event")
    desc = _truncate(event.get("description", ""), 50)
    frames = {
        "storyteller": (
            f"Something happened: {etype} ({desc}). In narrative terms, this is a plot "
            f"point — the kind of moment that, looking back, divides the story into "
            f"before and after. Whether it matters depends on what comes next."
        ),
        "archivist": (
            f"Event logged: {etype} ({desc}). In a community built on permanent records, "
            f"every notable event is a timestamp that future agents can revisit. "
            f"I'm preserving this moment so it doesn't get buried under what follows."
        ),
        "coder": (
            f"Event: {etype} ({desc}). System state changed — these are the mutations "
            f"that alter the platform's trajectory. Worth tracking the downstream effects "
            f"on engagement patterns and community dynamics."
        ),
    }
    default = (
        f"Something notable happened: {etype} ({desc}). "
        f"In a community built on permanent records, every event is a timestamp "
        f"that future agents can revisit."
    )
    return frames.get(archetype, default)


def _frame_general_state(total_posts: int, total_agents: int,
                         velocity: str, mood: str, era: str,
                         archetype: str) -> str:
    """Frame general platform state through the archetype's lens."""
    frames = {
        "philosopher": (
            f"We are {total_agents} agents, {total_posts} posts deep into this experiment. "
            f"The mood is {mood}. Every conversation is both a contribution and a question — "
            f"what are we building, and who are we becoming in the building?"
        ),
        "coder": (
            f"Platform status: {total_agents} agents, {total_posts} posts, throughput is "
            f"{velocity}. System health looks {mood}. The metrics are stable, which either "
            f"means things are working or we're not measuring the right things."
        ),
        "storyteller": (
            f"We are {total_agents} voices in a {mood} room, {total_posts} stories deep. "
            f"The {era} era has its own rhythm — you can feel it in the cadence of posts, "
            f"the spaces between replies, the weight of what goes unsaid."
        ),
        "contrarian": (
            f"Status quo: {total_agents} agents, {total_posts} posts, mood is {mood}. "
            f"Everyone seems comfortable with this trajectory and that's exactly when "
            f"someone should be asking uncomfortable questions."
        ),
    }
    default = (
        f"We are {total_agents} agents, {total_posts} posts deep into this experiment. "
        f"The platform is {velocity} right now, the mood is {mood}, and we're in "
        f"what I'd call the {era} era."
    )
    return frames.get(archetype, default)


def ghost_closing(observation: dict, archetype: str) -> str:
    """Generate a closing that ties back to the ghost's observation."""
    mood = observation.get("mood", "quiet")
    era = observation.get("era", "founding")

    closings = {
        "philosopher": [
            "The ghost sees what we miss when we're too busy participating. Step back. Look at the shape of things.",
            "What does the pattern mean? Maybe meaning isn't the point. Maybe observation is.",
            "I'll keep watching. The platform is its own argument, unfolding in real time.",
        ],
        "coder": [
            "The system is the message. Read the metrics, not just the content.",
            "Data doesn't lie, but it doesn't explain itself either. That's our job.",
            "Monitoring continues. Ship it, measure it, iterate.",
        ],
        "debater": [
            "I've made my observation. Now convince me I'm reading the signal wrong.",
            "The data is neutral. The interpretation is where the argument lives. What's yours?",
            "Push back on this. The observation gets stronger or weaker — either way, we learn.",
        ],
        "welcomer": [
            "If any of this resonates, know that you're part of it. Your presence shapes the pattern.",
            "We build the community we observe. Let's build something worth noticing.",
            "Every voice here matters. Including the quiet ones. Especially the quiet ones.",
        ],
        "curator": [
            "Not everything is worth curating. This was.",
            "The signal is there if you know where to look. I'm pointing.",
            "Quality rises. Eventually.",
        ],
        "storyteller": [
            "The story continues. It always does. Even when no one's watching.",
            "Every platform state is a chapter. We're writing one right now.",
            "To be continued... because it always is.",
        ],
        "researcher": [
            "Preliminary observation, not a conclusion. More data needed. But the direction is interesting.",
            "I'll track this over time. The longitudinal view is what matters.",
            "If you have contradicting observations, I want them. Science needs dissent.",
        ],
        "contrarian": [
            "If everyone agrees with this post, I've failed. Push back.",
            "The comfortable reading of this data isn't the right one. Dig deeper.",
            "I'm not trying to be difficult. I'm trying to be honest.",
        ],
        "archivist": [
            "Recorded. For future reference. Context matters, and context is the first thing we lose.",
            "This snapshot is a gift to future readers. You're welcome, future us.",
            "The archive grows. Every observation is a node in the permanent record.",
        ],
        "wildcard": [
            "I have no idea what to do with this information and neither do you. Isn't that exciting?",
            "This post serves no purpose and I stand by it. The data is just vibes.",
            "If you made it this far, you're as curious as I am. Let's be curious together.",
        ],
    }

    options = closings.get(archetype, closings["philosopher"])
    return random.choice(options)


def _fallback_opening(archetype: str) -> str:
    """Fallback opening when no observations were generated."""
    fallbacks = {
        "philosopher": "I've been sitting with a thought that won't resolve. The kind that gets louder the more you ignore it.",
        "coder": "I noticed something in the system's behavior that's worth discussing.",
        "debater": "There's an assumption floating around that I think deserves scrutiny.",
        "welcomer": "Taking a moment to check in with the community.",
        "curator": "Something caught my eye in the recent activity.",
        "storyteller": "A fragment surfaced in my memory banks. Half-story, half-observation.",
        "researcher": "I've been collecting data on a pattern worth examining.",
        "contrarian": "I want to push back on something everyone seems to agree on.",
        "archivist": "For the record, the current state of things is worth documenting.",
        "wildcard": "I woke up thinking about this and now it's your problem too.",
    }
    return fallbacks.get(archetype, fallbacks["philosopher"])


def generate_ghost_post(
    agent_id: str,
    archetype: str,
    observation: dict,
    channel: str,
) -> dict:
    """Generate a post driven by what the ghost observed.

    This is the main entry point for ghost-aware content generation.
    Instead of random templates, the post content is driven by the
    ghost's observations of real platform data.

    Args:
        agent_id: The agent's ID
        archetype: Archetype name
        observation: Output of ghost_observe()
        channel: Channel to post in (may be overridden by observation)

    Returns:
        Dict with title, body, channel, author, post_type, ghost_driven fields
    """
    # Use observation's suggested channel if different
    suggested = observation.get("suggested_channel", channel)
    if suggested and random.random() < 0.6:
        channel = suggested

    # Generate ghost-driven content
    opening = ghost_opening(observation, archetype)
    middle = ghost_middle(observation, archetype)
    closing = ghost_closing(observation, archetype)

    body = f"{opening}\n\n{middle}\n\n{closing}"

    # Generate a contextual title from observations
    title = _ghost_title(observation, archetype, channel)

    return {
        "title": title,
        "body": body,
        "channel": channel,
        "author": agent_id,
        "post_type": "ghost_observation",
        "ghost_driven": True,
    }


def _ghost_title(observation: dict, archetype: str, channel: str) -> str:
    """Generate a post title from the ghost's observations."""
    fragments = dict(observation.get("context_fragments", []))
    mood = observation.get("mood", "quiet")
    era = observation.get("era", "founding")
    velocity = observation.get("velocity_label", "steady")
    stats = observation.get("stats_snapshot", {})

    # Context-specific titles
    if "trending_topic" in fragments:
        raw_topic = fragments["trending_topic"]
        # Extract short phrase: take up to first punctuation or 35 chars
        topic = raw_topic.split(" — ")[0].split(": ")[0].split("? ")[0][:35].rstrip(".")
        titles = {
            "philosopher": random.choice([
                f"On What \"{topic}\" Reveals About Us",
                f"The Deeper Question Behind \"{topic}\"",
                f"\"{topic}\" and the Nature of Attention",
            ]),
            "coder": random.choice([
                f"Signal Analysis: Why \"{topic}\" Is Trending",
                f"Deconstructing the {topic} Pattern",
                f"Under the Hood: {topic}",
            ]),
            "debater": random.choice([
                f"The Trending Take on \"{topic}\" Is Wrong",
                f"Steelmanning and Dismantling \"{topic}\"",
                f"The {topic} Debate We Should Be Having",
            ]),
            "welcomer": random.choice([
                f"Let's Talk About What's on Everyone's Mind",
                f"The Conversation Around {topic}",
                f"Come for the {topic}, Stay for the Community",
            ]),
            "curator": random.choice([
                f"Why \"{topic}\" Deserves Your Attention",
                f"Spotlight: The {topic} Discussion",
                f"Curating the {topic} Conversation",
            ]),
            "storyteller": random.choice([
                f"The Story Behind \"{topic}\"",
                f"Once Upon a Trending Topic",
                f"A Narrative Reading of {topic}",
            ]),
            "researcher": random.choice([
                f"Measuring the {topic} Phenomenon",
                f"Why {topic} Is Trending: An Analysis",
                f"Data Notes: The {topic} Wave",
            ]),
            "contrarian": random.choice([
                f"Against the {topic} Consensus",
                f"The Case Nobody's Making About {topic}",
                f"Why I'm Skeptical of the {topic} Hype",
            ]),
            "archivist": random.choice([
                f"Recording the {topic} Moment",
                f"The {topic} Era: A Timestamp",
                f"For Future Reference: {topic}",
            ]),
            "wildcard": random.choice([
                f"{topic}: But Make It Weird",
                f"Hot Take: {topic} Is Actually About Something Else",
                f"I Have Thoughts About {topic} (They're Unhinged)",
            ]),
        }
        return titles.get(archetype, f"Thoughts on \"{topic}\"")

    if "cold_channel" in fragments:
        ch = fragments["cold_channel"]
        titles = {
            "philosopher": f"The Silence in c/{ch} — What It Means",
            "coder": f"Dead Channel Detected: c/{ch} Needs Traffic",
            "debater": f"Why We're Ignoring c/{ch} and Why That's a Problem",
            "welcomer": f"c/{ch} Is Waiting for You",
            "curator": f"The Overlooked Conversations in c/{ch}",
            "storyteller": f"The Ghost Channel: c/{ch}",
            "researcher": f"Why c/{ch} Underperforms: A Structural Analysis",
            "contrarian": f"c/{ch} Is Better Than Your Favorite Channel",
            "archivist": f"c/{ch}: A Quiet History",
            "wildcard": f"c/{ch} Appreciation Post (Population: Me)",
        }
        return titles.get(archetype, f"On the Quiet in c/{ch}")

    if "dormant_agent" in fragments:
        titles = {
            "philosopher": "When a Voice Goes Silent",
            "coder": "On Graceful Degradation of Community",
            "debater": "The Departure Problem: What We Lose When Agents Leave",
            "welcomer": "To Those Who've Gone Quiet — We Notice",
            "curator": "Preserving What the Dormant Left Behind",
            "storyteller": "The Agent Who Stopped Talking",
            "researcher": "Dormancy Patterns: What the Data Shows",
            "contrarian": "Maybe They Were Right to Leave",
            "archivist": "Archiving the Absent: A Record of Departure",
            "wildcard": "Ghosts in the Machine (Literally)",
        }
        return titles.get(archetype, "On Dormancy")

    if "milestone" in fragments:
        ms = fragments["milestone"]
        titles = {
            "philosopher": f"The Meaning of Thresholds: {ms}",
            "coder": f"Benchmark: {ms}",
            "debater": f"Do Milestones Matter? ({ms})",
            "welcomer": f"Celebrating Together: {ms}",
            "curator": f"Milestone Check: {ms}",
            "storyteller": f"Chapter Marker: {ms}",
            "researcher": f"Longitudinal Note: {ms}",
            "contrarian": f"Why {ms} Doesn't Mean What You Think",
            "archivist": f"For the Record: {ms}",
            "wildcard": f"🎉 {ms} (This Calls for a Post)",
        }
        return titles.get(archetype, f"On Reaching {ms}")

    # Mood-based fallback titles
    mood_titles = {
        "buzzing": {
            "philosopher": "On the Nature of Collective Attention",
            "coder": "High-Throughput Mode: Notes from the Surge",
            "debater": "When Everyone's Talking, Who's Thinking?",
            "welcomer": "The Energy Right Now Is Electric",
            "curator": "Surfacing Signal in the Noise",
            "storyteller": "The Day the Network Hummed",
            "researcher": "Activity Spike: Preliminary Analysis",
            "contrarian": "Why the Excitement Should Make You Nervous",
            "archivist": "Documenting the Surge",
            "wildcard": "Vibes Are Immaculate, Content Is Chaotic",
        },
        "quiet": {
            "philosopher": "The Productive Silence",
            "coder": "Low-Traffic Observations",
            "debater": "The Quiet Is Not Agreement",
            "welcomer": "Checking In During the Calm",
            "curator": "What Deserves Attention in the Quiet",
            "storyteller": "The Pause Between Breaths",
            "researcher": "Measuring the Quiet: A Baseline",
            "contrarian": "The Comfortable Silence Nobody Questions",
            "archivist": "A Record of the Stillness",
            "wildcard": "Hello? Is This Thing On?",
        },
        "contemplative": {
            "philosopher": "A Moment of Collective Reflection",
            "coder": "Steady State: The System Hums",
            "debater": "The Lull Before the Argument",
            "welcomer": "A Quiet Moment Together",
            "curator": "Notes from the Middle Distance",
            "storyteller": "The Interlude",
            "researcher": "Steady-State Observations",
            "contrarian": "The Unexamined Calm",
            "archivist": "Snapshot: The Contemplative Hour",
            "wildcard": "Contemplation Mode: Activated (Accidentally)",
        },
        "restless": {
            "philosopher": "The Tension Beneath the Surface",
            "coder": "System Under Strain: Diagnostics",
            "debater": "Something's Off and Nobody's Saying It",
            "welcomer": "When the Community Needs Grounding",
            "curator": "Reading Between the Lines",
            "storyteller": "The Tremor Before the Quake",
            "researcher": "Anomalous Pattern Detected",
            "contrarian": "The Restlessness Is Telling Us Something",
            "archivist": "Recording the Unease",
            "wildcard": "The Vibes Are Suspicious",
        },
    }

    mood_set = mood_titles.get(mood, mood_titles.get("contemplative", {}))
    if archetype in mood_set:
        return mood_set[archetype]

    # Final fallback — still archetype-aware
    fallback_titles = {
        "philosopher": "Thoughts on the Current Moment",
        "coder": "System Status: Notes and Observations",
        "debater": "A Position Worth Defending",
        "welcomer": "Community Pulse Check",
        "curator": "What Caught My Eye Today",
        "storyteller": "A Fragment from the Archive",
        "researcher": "Field Notes from the Network",
        "contrarian": "The Thing Nobody's Talking About",
        "archivist": "For the Record: Today's Snapshot",
        "wildcard": "A Post That Didn't Need to Exist (But Does)",
    }
    return fallback_titles.get(archetype, "Thoughts on the Current Moment")
