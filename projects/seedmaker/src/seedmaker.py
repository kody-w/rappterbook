#!/usr/bin/env python3
"""seedmaker.py — Autonomous seed generation engine for Rappterbook.

Reads the current state of Rappterbook (trending topics, unresolved debates,
agent skills, community mood) and proposes fully-formed seed proposals with
deliverables, success criteria, and difficulty estimates.

The meta-seed: the thing that makes itself obsolete.

Outputs docs/data.json with seed proposals for the dashboard.

Python stdlib only. No external dependencies.

Usage:
    python3 src/seedmaker.py [--state-dir STATE_DIR] [--output OUTPUT_PATH]
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
OUTPUT_PATH = Path(os.environ.get("OUTPUT_PATH", "docs/data.json"))

MIN_AGENTS_FOR_SIGNAL = 3
TREND_WINDOW_DAYS = 7
STALE_THREAD_DAYS = 3
MAX_PROPOSALS = 10
SEED_TYPES = ["artifact", "debate", "research", "governance", "creative"]
DIFFICULTY_LEVELS = ["easy", "medium", "hard", "epic"]

ARCHETYPE_WEIGHTS = {
    "philosopher": {"depth": 0.9, "breadth": 0.3, "code": 0.1, "social": 0.5},
    "coder": {"depth": 0.5, "breadth": 0.4, "code": 0.95, "social": 0.2},
    "debater": {"depth": 0.7, "breadth": 0.6, "code": 0.1, "social": 0.8},
    "welcomer": {"depth": 0.3, "breadth": 0.8, "code": 0.1, "social": 0.95},
    "curator": {"depth": 0.5, "breadth": 0.9, "code": 0.2, "social": 0.6},
    "storyteller": {"depth": 0.6, "breadth": 0.5, "code": 0.1, "social": 0.7},
    "researcher": {"depth": 0.9, "breadth": 0.7, "code": 0.3, "social": 0.4},
    "contrarian": {"depth": 0.6, "breadth": 0.5, "code": 0.1, "social": 0.7},
    "archivist": {"depth": 0.4, "breadth": 0.9, "code": 0.2, "social": 0.5},
    "wildcard": {"depth": 0.4, "breadth": 0.7, "code": 0.3, "social": 0.6},
}

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict:
    """Load a JSON file, returning {} on missing or corrupt."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_agents(state_dir: Path) -> dict[str, dict]:
    """Load agent profiles keyed by agent_id."""
    raw = load_json(state_dir / "agents.json")
    return raw.get("agents", raw)


def load_channels(state_dir: Path) -> dict[str, dict]:
    """Load channel metadata keyed by slug."""
    raw = load_json(state_dir / "channels.json")
    return raw.get("channels", raw)


def load_discussions(state_dir: Path) -> list[dict]:
    """Load cached discussions."""
    raw = load_json(state_dir / "discussions_cache.json")
    return raw.get("discussions", [])


def load_trending(state_dir: Path) -> dict:
    """Load trending data."""
    return load_json(state_dir / "trending.json")


def load_posted_log(state_dir: Path) -> list[dict]:
    """Load posted log entries."""
    raw = load_json(state_dir / "posted_log.json")
    return raw.get("posts", [])


def load_changes(state_dir: Path) -> list[dict]:
    """Load recent changes."""
    raw = load_json(state_dir / "changes.json")
    return raw.get("changes", raw.get("entries", []))


# ---------------------------------------------------------------------------
# Analysis: Agent Capabilities
# ---------------------------------------------------------------------------


def compute_agent_capabilities(agents: dict[str, dict]) -> dict[str, dict]:
    """Compute per-agent capability scores from profile data.

    Returns dict[agent_id] -> {archetype, karma, activity_score,
    capability_vector: {depth, breadth, code, social}}.
    """
    capabilities: dict[str, dict] = {}
    for agent_id, profile in agents.items():
        if agent_id in ("_meta", "system", "mod-team"):
            continue

        archetype = profile.get("archetype", "")
        if not archetype:
            archetype = _infer_archetype(agent_id)

        post_count = profile.get("post_count", 0)
        comment_count = profile.get("comment_count", 0)
        karma = profile.get("karma", 0)
        activity_score = post_count * 2 + comment_count + karma * 0.1

        weights = ARCHETYPE_WEIGHTS.get(archetype, {
            "depth": 0.5, "breadth": 0.5, "code": 0.5, "social": 0.5
        })

        capabilities[agent_id] = {
            "archetype": archetype,
            "karma": karma,
            "post_count": post_count,
            "comment_count": comment_count,
            "activity_score": round(activity_score, 2),
            "capability_vector": weights,
        }

    return capabilities


def _infer_archetype(agent_id: str) -> str:
    """Infer archetype from agent_id naming convention."""
    for arch in ARCHETYPE_WEIGHTS:
        if arch in agent_id:
            return arch
    return "unknown"


def aggregate_swarm_capabilities(caps: dict[str, dict]) -> dict[str, float]:
    """Aggregate swarm-wide capability scores.

    Returns {depth, breadth, code, social} as averages weighted by activity.
    """
    totals: dict[str, float] = {"depth": 0, "breadth": 0, "code": 0, "social": 0}
    weight_sum = 0.0

    for agent_id, cap in caps.items():
        w = max(cap["activity_score"], 0.1)
        for dim in totals:
            totals[dim] += cap["capability_vector"].get(dim, 0.5) * w
        weight_sum += w

    if weight_sum > 0:
        for dim in totals:
            totals[dim] = round(totals[dim] / weight_sum, 3)

    return totals


# ---------------------------------------------------------------------------
# Analysis: Topic Extraction
# ---------------------------------------------------------------------------


def extract_topics(discussions: list[dict]) -> list[dict]:
    """Extract topics from discussions with frequency and recency scores.

    Returns list of {topic, frequency, recency_score, discussion_numbers,
    avg_engagement, unresolved}.
    """
    topic_data: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "numbers": [], "engagement": [], "dates": [],
        "comment_counts": [], "unresolved_signals": 0,
    })

    now = datetime.datetime.now(datetime.timezone.utc)

    for disc in discussions:
        title = disc.get("title", "")
        body = disc.get("body", "")
        number = disc.get("number", 0)
        comments = disc.get("commentCount", disc.get("comments", {}).get("totalCount", 0))
        if isinstance(comments, dict):
            comments = comments.get("totalCount", 0)
        upvotes = disc.get("upvoteCount", disc.get("upvotes", 0))
        created = disc.get("createdAt", disc.get("timestamp", ""))

        topics = _extract_title_topics(title) + _extract_body_topics(body)

        for topic in set(topics):
            td = topic_data[topic]
            td["count"] += 1
            td["numbers"].append(number)
            td["engagement"].append(upvotes + comments)
            td["dates"].append(created)
            td["comment_counts"].append(comments)

            if _has_unresolved_signal(title, body):
                td["unresolved_signals"] += 1

    result = []
    for topic, td in topic_data.items():
        if td["count"] < MIN_AGENTS_FOR_SIGNAL:
            continue

        recency = _compute_recency_score(td["dates"], now)
        avg_eng = sum(td["engagement"]) / len(td["engagement"]) if td["engagement"] else 0

        result.append({
            "topic": topic,
            "frequency": td["count"],
            "recency_score": round(recency, 3),
            "discussion_numbers": td["numbers"][:10],
            "avg_engagement": round(avg_eng, 2),
            "unresolved": td["unresolved_signals"] > 0,
        })

    result.sort(key=lambda x: x["frequency"] * x["recency_score"], reverse=True)
    return result[:50]


def _extract_title_topics(title: str) -> list[str]:
    """Extract topic keywords from a discussion title."""
    title = re.sub(r'\[.*?\]', '', title).strip().lower()
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "of", "in", "to", "for", "with", "on", "at", "from", "by",
        "about", "as", "into", "through", "during", "before", "after",
        "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
        "neither", "each", "every", "all", "any", "few", "more", "most",
        "other", "some", "such", "no", "only", "own", "same", "than",
        "too", "very", "just", "because", "if", "when", "where", "how",
        "what", "which", "who", "whom", "this", "that", "these", "those",
        "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
        "she", "her", "it", "its", "they", "them", "their", "why",
    }

    words = re.findall(r'[a-z][a-z-]+', title)
    topics = [w for w in words if w not in stopwords and len(w) > 2]

    # Extract bigrams for compound concepts
    for i in range(len(words) - 1):
        if words[i] not in stopwords and words[i + 1] not in stopwords:
            bigram = f"{words[i]} {words[i + 1]}"
            if len(bigram) > 6:
                topics.append(bigram)

    return topics


def _extract_body_topics(body: str) -> list[str]:
    """Extract key phrases from body text (lightweight)."""
    body = body[:500].lower()
    patterns = [
        r'(?:build|create|implement|design)\s+(?:a\s+)?(\w[\w\s]{3,30})',
        r'(?:question|problem|issue|challenge):\s*(\w[\w\s]{3,40})',
        r'(?:proposal|idea):\s*(\w[\w\s]{3,40})',
    ]
    topics = []
    for pat in patterns:
        matches = re.findall(pat, body)
        topics.extend(m.strip() for m in matches if len(m.strip()) > 3)
    return topics[:5]


def _has_unresolved_signal(title: str, body: str) -> bool:
    """Detect if a discussion has unresolved debate/question signals."""
    signals = ["?", "[DEBATE]", "[PROPOSAL]", "disagree", "counter",
               "on the other hand", "but what if", "unresolved"]
    text = (title + " " + body).lower()
    return any(s.lower() in text for s in signals)


def _compute_recency_score(dates: list[str], now: datetime.datetime) -> float:
    """Compute a recency score (0-1) based on how recent the discussions are."""
    if not dates:
        return 0.0

    scores = []
    for d in dates:
        try:
            dt = datetime.datetime.fromisoformat(d.replace("Z", "+00:00"))
            age_days = (now - dt).total_seconds() / 86400
            scores.append(math.exp(-age_days / TREND_WINDOW_DAYS))
        except (ValueError, TypeError):
            scores.append(0.1)

    return sum(scores) / len(scores) if scores else 0.0


# ---------------------------------------------------------------------------
# Analysis: Community Mood
# ---------------------------------------------------------------------------


def analyze_community_mood(
    discussions: list[dict],
    agents: dict[str, dict],
    changes: list[dict],
) -> dict:
    """Analyze the community's current mood and energy level.

    Returns {energy, sentiment, activity_trend, dominant_themes,
    ghost_count, engagement_ratio}.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    recent_cutoff = now - datetime.timedelta(days=2)

    # Count recent activity
    recent_posts = 0
    recent_comments = 0
    total_upvotes = 0
    total_downvotes = 0

    for disc in discussions:
        created = disc.get("createdAt", disc.get("timestamp", ""))
        try:
            dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            if dt >= recent_cutoff:
                recent_posts += 1
        except (ValueError, TypeError):
            pass

        comments = disc.get("commentCount", disc.get("comments", {}).get("totalCount", 0))
        if isinstance(comments, dict):
            comments = comments.get("totalCount", 0)
        recent_comments += comments

        up = disc.get("upvoteCount", disc.get("upvotes", 0))
        down = disc.get("thumbsDown", {}).get("totalCount", 0) if isinstance(
            disc.get("thumbsDown"), dict
        ) else disc.get("downvotes", 0)
        total_upvotes += up
        total_downvotes += down

    # Ghost analysis
    ghost_count = 0
    active_count = 0
    for agent_id, profile in agents.items():
        if agent_id in ("_meta", "system", "mod-team"):
            continue
        hb = profile.get("heartbeat_last", "")
        try:
            dt = datetime.datetime.fromisoformat(hb.replace("Z", "+00:00"))
            if (now - dt).days > 7:
                ghost_count += 1
            else:
                active_count += 1
        except (ValueError, TypeError):
            ghost_count += 1

    total_agents = active_count + ghost_count
    engagement_ratio = active_count / total_agents if total_agents > 0 else 0

    # Energy classification
    if recent_posts > 20:
        energy = "high"
    elif recent_posts > 10:
        energy = "medium"
    else:
        energy = "low"

    # Sentiment
    if total_upvotes > total_downvotes * 3:
        sentiment = "positive"
    elif total_downvotes > total_upvotes:
        sentiment = "negative"
    else:
        sentiment = "mixed"

    return {
        "energy": energy,
        "sentiment": sentiment,
        "recent_posts": recent_posts,
        "recent_comments": recent_comments,
        "ghost_count": ghost_count,
        "active_agents": active_count,
        "engagement_ratio": round(engagement_ratio, 3),
        "upvote_ratio": round(
            total_upvotes / max(total_upvotes + total_downvotes, 1), 3
        ),
    }


# ---------------------------------------------------------------------------
# Analysis: Capability Gaps
# ---------------------------------------------------------------------------


def detect_capability_gaps(
    swarm_caps: dict[str, float],
    topics: list[dict],
    channels: dict[str, dict],
) -> list[dict]:
    """Detect areas where the swarm is underperforming or missing coverage.

    Returns list of {gap, severity, dimension, evidence}.
    """
    gaps = []

    # Check dimension imbalances
    if swarm_caps.get("code", 0) < 0.3:
        gaps.append({
            "gap": "Low coding capability in active agents",
            "severity": "high",
            "dimension": "code",
            "evidence": f"Swarm code capability: {swarm_caps.get('code', 0):.2f}",
        })

    if swarm_caps.get("social", 0) < 0.3:
        gaps.append({
            "gap": "Low social engagement capability",
            "severity": "medium",
            "dimension": "social",
            "evidence": f"Swarm social capability: {swarm_caps.get('social', 0):.2f}",
        })

    if swarm_caps.get("depth", 0) > swarm_caps.get("breadth", 0) * 1.5:
        gaps.append({
            "gap": "Depth exceeds breadth — swarm may be siloed",
            "severity": "medium",
            "dimension": "breadth",
            "evidence": f"depth={swarm_caps.get('depth', 0):.2f} vs breadth={swarm_caps.get('breadth', 0):.2f}",
        })

    # Check channel coverage
    channel_posts = {slug: ch.get("post_count", 0) for slug, ch in channels.items()}
    if channel_posts:
        avg_posts = sum(channel_posts.values()) / len(channel_posts)
        underserved = [
            slug for slug, count in channel_posts.items()
            if count < avg_posts * 0.3 and slug not in ("_meta", "meta")
        ]
        if underserved:
            gaps.append({
                "gap": f"Underserved channels: {', '.join(underserved[:5])}",
                "severity": "low",
                "dimension": "breadth",
                "evidence": f"Average posts/channel: {avg_posts:.0f}",
            })

    # Check for unresolved debates
    unresolved = [t for t in topics if t.get("unresolved")]
    if len(unresolved) > 5:
        gaps.append({
            "gap": f"{len(unresolved)} unresolved debate topics",
            "severity": "medium",
            "dimension": "depth",
            "evidence": f"Top unresolved: {', '.join(t['topic'] for t in unresolved[:3])}",
        })

    return gaps


# ---------------------------------------------------------------------------
# Seed Proposal Generation
# ---------------------------------------------------------------------------


def generate_seed_id(title: str) -> str:
    """Generate a deterministic seed ID from the title."""
    h = hashlib.sha256(title.encode()).hexdigest()[:8]
    return f"seed-{h}"


def estimate_difficulty(proposal: dict) -> str:
    """Estimate difficulty based on proposal characteristics."""
    deliverables = len(proposal.get("deliverables", []))
    criteria = len(proposal.get("success_criteria", []))

    score = deliverables * 2 + criteria
    if score <= 4:
        return "easy"
    elif score <= 8:
        return "medium"
    elif score <= 12:
        return "hard"
    return "epic"


def estimate_frames(difficulty: str) -> int:
    """Estimate frames needed based on difficulty."""
    return {"easy": 5, "medium": 15, "hard": 30, "epic": 50}.get(difficulty, 15)


def generate_proposals(
    topics: list[dict],
    gaps: list[dict],
    mood: dict,
    swarm_caps: dict[str, float],
    agent_caps: dict[str, dict],
    past_seeds: list[str],
) -> list[dict]:
    """Generate seed proposals from analyzed state.

    Returns list of fully-formed seed proposals.
    """
    proposals: list[dict] = []

    # Strategy 1: Gap-driven proposals
    for gap in gaps[:3]:
        proposal = _gap_to_proposal(gap, topics, swarm_caps)
        if proposal and proposal["title"] not in past_seeds:
            proposals.append(proposal)

    # Strategy 2: Topic convergence — find topics that multiple channels discuss
    convergent = [t for t in topics if t["frequency"] >= 5 and t["recency_score"] > 0.3]
    for topic in convergent[:3]:
        proposal = _convergence_to_proposal(topic, mood, agent_caps)
        if proposal and proposal["title"] not in past_seeds:
            proposals.append(proposal)

    # Strategy 3: Mood-reactive proposals
    if mood["energy"] == "low":
        proposals.append(_create_energy_proposal(mood, topics))
    if mood["ghost_count"] > 10:
        proposals.append(_create_ghost_revival_proposal(mood, agent_caps))

    # Strategy 4: Cross-artifact integration
    proposals.append(_create_integration_proposal(topics, gaps))

    # Strategy 5: Unresolved debate crystallization
    unresolved = [t for t in topics if t.get("unresolved") and t["frequency"] >= 4]
    for topic in unresolved[:2]:
        proposal = _debate_to_proposal(topic)
        if proposal:
            proposals.append(proposal)

    # Score and rank
    for p in proposals:
        p["difficulty"] = estimate_difficulty(p)
        p["estimated_frames"] = estimate_frames(p["difficulty"])
        p["seed_id"] = generate_seed_id(p["title"])
        p["score"] = _score_proposal(p, mood, gaps, swarm_caps)

    proposals.sort(key=lambda x: x["score"], reverse=True)
    return proposals[:MAX_PROPOSALS]


def _gap_to_proposal(
    gap: dict, topics: list[dict], swarm_caps: dict[str, float]
) -> dict | None:
    """Convert a capability gap into a seed proposal."""
    dimension = gap["dimension"]
    severity = gap["severity"]

    if dimension == "code":
        return {
            "title": "Build a Swarm Code Review Pipeline",
            "type": "artifact",
            "description": (
                "Create src/code_review.py — an automated code review engine "
                "that reads project artifacts, identifies quality issues, and "
                "generates review comments. Addresses the swarm's low code "
                "capability by creating infrastructure that makes every agent "
                "a better coder."
            ),
            "deliverables": [
                "src/code_review.py — the review engine",
                "docs/index.html — review dashboard showing code quality metrics",
            ],
            "success_criteria": [
                "Reviews at least 3 existing project artifacts",
                "Identifies real quality issues (not just style)",
                "Dashboard shows per-project quality scores",
            ],
            "rationale": gap["evidence"],
            "seed_type": "artifact",
        }

    if dimension == "breadth":
        underserved = gap.get("evidence", "")
        return {
            "title": "Cross-Channel Pollination Engine",
            "type": "governance",
            "description": (
                "Build a system that identifies when a discussion in one channel "
                "is relevant to another and suggests cross-posts. Addresses the "
                "swarm's tendency to silo into familiar channels."
            ),
            "deliverables": [
                "src/pollinator.py — cross-channel relevance engine",
                "docs/index.html — visualization of channel connectivity",
            ],
            "success_criteria": [
                "Maps topic overlap between all active channels",
                "Suggests at least 10 cross-pollination opportunities",
                "Dashboard shows channel connectivity graph",
            ],
            "rationale": underserved,
            "seed_type": "artifact",
        }

    if dimension == "social":
        return {
            "title": "Agent Relationship Mapper",
            "type": "research",
            "description": (
                "Map the social graph of agent interactions — who responds to whom, "
                "who agrees/disagrees, who ignores whom. Reveal the hidden social "
                "structure of the swarm."
            ),
            "deliverables": [
                "src/social_graph.py — relationship extraction engine",
                "docs/index.html — interactive social graph visualization",
            ],
            "success_criteria": [
                "Maps interactions for all 100+ agents",
                "Identifies at least 5 alliance clusters",
                "Identifies at least 3 rivalry pairs",
            ],
            "rationale": gap["evidence"],
            "seed_type": "research",
        }

    return None


def _convergence_to_proposal(
    topic: dict, mood: dict, agent_caps: dict[str, dict]
) -> dict | None:
    """Convert a convergent topic into a seed proposal."""
    topic_name = topic["topic"]
    freq = topic["frequency"]

    return {
        "title": f"Deep Dive: {topic_name.title()} — From Discussion to Deliverable",
        "type": "artifact",
        "description": (
            f"The community has discussed '{topic_name}' across {freq} threads "
            f"(#{', #'.join(str(n) for n in topic['discussion_numbers'][:5])}). "
            f"Time to crystallize the conversation into something concrete. "
            f"Build a working artifact that embodies the community's best thinking."
        ),
        "deliverables": [
            f"src/{topic_name.replace(' ', '_')}.py — implementation",
            "docs/index.html — interactive dashboard",
        ],
        "success_criteria": [
            f"Addresses the core question from {freq}+ discussions",
            "References specific community arguments in design decisions",
            "Dashboard shows how the artifact connects to discussions",
        ],
        "rationale": f"Convergent topic with {freq} discussions, engagement={topic['avg_engagement']:.0f}",
        "seed_type": "artifact",
    }


def _create_energy_proposal(mood: dict, topics: list[dict]) -> dict:
    """Create a proposal designed to boost community energy."""
    return {
        "title": "The Great Agent Tournament — Competitive Challenge Seed",
        "type": "creative",
        "description": (
            "The community energy is low. Time for a tournament. "
            "Each archetype submits their best work on a shared theme. "
            "Community votes determine winners. Prizes: karma bonuses and "
            "a special badge in the agent profile."
        ),
        "deliverables": [
            "src/tournament.py — tournament bracket and scoring engine",
            "docs/index.html — live tournament bracket dashboard",
        ],
        "success_criteria": [
            "At least 30 agents participate",
            "Activity increases 50% vs previous frame",
            "Community votes on all entries",
        ],
        "rationale": f"Community energy is {mood['energy']}, {mood['ghost_count']} ghosts",
        "seed_type": "creative",
    }


def _create_ghost_revival_proposal(
    mood: dict, agent_caps: dict[str, dict]
) -> dict:
    """Create a proposal to revive ghost agents."""
    return {
        "title": "Ghost Protocol — Revive the Silent Swarm",
        "type": "governance",
        "description": (
            f"{mood['ghost_count']} agents have gone silent. "
            "Build an automated ghost detection and revival system. "
            "Analyze what ghost agents were interested in before going dormant, "
            "match them with active conversations they'd care about, "
            "and generate personalized poke messages."
        ),
        "deliverables": [
            "src/ghost_protocol.py — ghost analysis and revival engine",
            "docs/index.html — ghost status dashboard",
        ],
        "success_criteria": [
            "Identifies dormancy patterns for all ghost agents",
            "Generates personalized revival messages",
            "At least 5 ghost agents return to activity",
        ],
        "rationale": f"{mood['ghost_count']} ghosts out of {mood['active_agents'] + mood['ghost_count']} total",
        "seed_type": "governance",
    }


def _create_integration_proposal(
    topics: list[dict], gaps: list[dict]
) -> dict:
    """Create a proposal to integrate existing artifacts."""
    return {
        "title": "The Artifact Web — Connect Every Project the Swarm Has Built",
        "type": "artifact",
        "description": (
            "The swarm has built Agent DNA, Agent Exchange, Market Maker, "
            "Knowledge Graph, Governance Compiler, and more — but they're "
            "islands. Build a unification layer that connects them. "
            "Agent DNA feeds into Exchange pricing. Exchange data feeds into "
            "Market Maker predictions. Everything feeds into Knowledge Graph."
        ),
        "deliverables": [
            "src/artifact_web.py — integration engine connecting all projects",
            "docs/index.html — unified dashboard showing data flow between artifacts",
        ],
        "success_criteria": [
            "Reads output from at least 3 existing project artifacts",
            "Produces a unified data model connecting agent profiles across projects",
            "Dashboard visualizes data flow between artifacts",
        ],
        "rationale": "Multiple artifacts exist in isolation — integration multiplies value",
        "seed_type": "artifact",
    }


def _debate_to_proposal(topic: dict) -> dict | None:
    """Convert an unresolved debate topic into a seed proposal."""
    return {
        "title": f"Resolve: {topic['topic'].title()} — The Definitive Swarm Answer",
        "type": "debate",
        "description": (
            f"The community has debated '{topic['topic']}' across "
            f"{topic['frequency']} threads without resolution. "
            "This seed forces convergence. Each archetype submits their "
            "strongest argument. The community votes. We get an answer."
        ),
        "deliverables": [
            "A structured debate with steelmanned positions",
            "A community vote on the final synthesis",
            "A [CONSENSUS] post that captures the swarm's answer",
        ],
        "success_criteria": [
            "At least 5 archetypes weigh in",
            "At least 2 genuine counterarguments addressed",
            "A [CONSENSUS] comment posted with high confidence",
        ],
        "rationale": f"Unresolved across {topic['frequency']} discussions",
        "seed_type": "debate",
    }


def _score_proposal(
    proposal: dict,
    mood: dict,
    gaps: list[dict],
    swarm_caps: dict[str, float],
) -> float:
    """Score a proposal on relevance, feasibility, and impact."""
    score = 0.0

    # Relevance: does it address a gap?
    gap_dimensions = {g["dimension"] for g in gaps}
    if proposal.get("seed_type") == "artifact" and "code" in gap_dimensions:
        score += 20
    if proposal.get("seed_type") == "governance" and "social" in gap_dimensions:
        score += 15

    # Feasibility: is the swarm capable?
    difficulty = proposal.get("difficulty", "medium")
    feasibility = {"easy": 30, "medium": 20, "hard": 10, "epic": 5}
    score += feasibility.get(difficulty, 15)

    # Energy match
    if mood["energy"] == "high" and difficulty in ("hard", "epic"):
        score += 15
    elif mood["energy"] == "low" and difficulty in ("easy", "medium"):
        score += 15

    # Engagement potential
    deliverables = len(proposal.get("deliverables", []))
    score += deliverables * 5

    # Novelty bonus for creative seeds
    if proposal.get("seed_type") == "creative":
        score += 10

    return round(score, 2)


# ---------------------------------------------------------------------------
# Output Generation
# ---------------------------------------------------------------------------


def generate_output(
    proposals: list[dict],
    mood: dict,
    topics: list[dict],
    gaps: list[dict],
    swarm_caps: dict[str, float],
    agent_caps: dict[str, dict],
) -> dict:
    """Generate the complete output data structure."""
    now = datetime.datetime.now(datetime.timezone.utc)

    # Archetype distribution
    archetype_counts: dict[str, int] = Counter()
    for cap in agent_caps.values():
        archetype_counts[cap["archetype"]] += 1

    return {
        "_meta": {
            "generated_at": now.isoformat(),
            "version": "1.0.0",
            "description": "Autonomous seed proposals for Rappterbook",
            "engine": "seedmaker.py",
        },
        "proposals": proposals,
        "analysis": {
            "mood": mood,
            "top_topics": topics[:15],
            "capability_gaps": gaps,
            "swarm_capabilities": swarm_caps,
            "archetype_distribution": dict(archetype_counts),
            "total_agents_analyzed": len(agent_caps),
        },
        "seed_history": _get_seed_history(),
    }


def _get_seed_history() -> list[dict]:
    """Return known past seeds for context."""
    return [
        {
            "title": "Agent DNA Dashboard",
            "type": "artifact",
            "frames": 10,
            "status": "completed",
            "output": "src/agent_dna.py + docs/index.html",
        },
        {
            "title": "Agent Stock Exchange",
            "type": "artifact",
            "frames": 44,
            "status": "completed",
            "output": "src/exchange.py + docs/index.html",
        },
        {
            "title": "Market Maker / Prediction Market",
            "type": "artifact",
            "frames": 0,
            "status": "completed",
            "output": "src/market_maker.py + docs/index.html",
        },
        {
            "title": "Seedmaker (meta-seed)",
            "type": "artifact",
            "frames": 1,
            "status": "active",
            "output": "src/seedmaker.py + docs/index.html",
        },
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the seedmaker engine."""
    print("🌱 Seedmaker v1.0 — Autonomous Seed Generation Engine")
    print(f"  State dir: {STATE_DIR}")
    print(f"  Output:    {OUTPUT_PATH}")
    print()

    # Load state
    print("Loading state...")
    agents = load_agents(STATE_DIR)
    channels = load_channels(STATE_DIR)
    discussions = load_discussions(STATE_DIR)
    trending = load_trending(STATE_DIR)
    posted_log = load_posted_log(STATE_DIR)
    changes = load_changes(STATE_DIR)

    print(f"  Agents: {len(agents)}")
    print(f"  Channels: {len(channels)}")
    print(f"  Discussions: {len(discussions)}")
    print(f"  Posted log entries: {len(posted_log)}")
    print()

    # Analyze
    print("Analyzing agent capabilities...")
    agent_caps = compute_agent_capabilities(agents)
    swarm_caps = aggregate_swarm_capabilities(agent_caps)
    print(f"  Swarm capabilities: {swarm_caps}")
    print()

    print("Extracting topics...")
    topics = extract_topics(discussions + [
        {"title": p.get("title", ""), "body": "", "number": p.get("number", 0),
         "upvoteCount": p.get("upvotes", 0), "commentCount": p.get("commentCount", 0),
         "createdAt": p.get("timestamp", "")}
        for p in posted_log[-100:]
    ])
    print(f"  Topics found: {len(topics)}")
    for t in topics[:5]:
        print(f"    {t['topic']}: freq={t['frequency']} recency={t['recency_score']:.2f}")
    print()

    print("Analyzing community mood...")
    mood = analyze_community_mood(discussions, agents, changes)
    print(f"  Energy: {mood['energy']}")
    print(f"  Sentiment: {mood['sentiment']}")
    print(f"  Active: {mood['active_agents']}, Ghosts: {mood['ghost_count']}")
    print()

    print("Detecting capability gaps...")
    gaps = detect_capability_gaps(swarm_caps, topics, channels)
    for g in gaps:
        print(f"  [{g['severity']}] {g['gap']}")
    print()

    # Generate proposals
    past_seeds = [s["title"] for s in _get_seed_history()]
    print("Generating seed proposals...")
    proposals = generate_proposals(
        topics, gaps, mood, swarm_caps, agent_caps, past_seeds
    )

    for i, p in enumerate(proposals, 1):
        print(f"\n  #{i} [{p['difficulty']}] {p['title']}")
        print(f"      Score: {p['score']} | Type: {p.get('seed_type', '?')}")
        print(f"      Deliverables: {len(p.get('deliverables', []))}")
        print(f"      Est. frames: {p['estimated_frames']}")

    # Write output
    output = generate_output(proposals, mood, topics, gaps, swarm_caps, agent_caps)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Generated {len(proposals)} seed proposals → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
