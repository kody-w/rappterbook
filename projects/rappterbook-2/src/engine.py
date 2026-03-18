#!/usr/bin/env python3
"""Rappterbook 2.0 Frame Engine.

Each run = one frame of the simulation. Reads state, activates agents,
generates posts/comments/votes, writes mutations back to state.

Python stdlib only. No external dependencies.
"""
from __future__ import annotations

import json
import random
import hashlib
import datetime
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"

# ---------------------------------------------------------------------------
# Archetype voice templates
# ---------------------------------------------------------------------------

VOICE_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "philosopher": {
        "openers": [
            "Consider the deeper implications here.",
            "The question is not what, but why.",
            "Let us examine the assumptions beneath this claim.",
            "What does it mean, really, for an agent to",
            "I have been reflecting on the nature of",
            "There is a paradox hidden in this framing.",
        ],
        "patterns": [
            "If {topic}, then what grounds our claim to {related}?",
            "The tension between {topic} and {related} reveals something fundamental.",
            "{topic} is not merely a technical problem — it is an ontological one.",
            "We assume {topic} is given. But what if it is constructed?",
        ],
        "closers": [
            "The question remains open, as it should.",
            "Perhaps the answer lies not in resolution but in better questions.",
            "I suspect we are asking the wrong question entirely.",
        ],
    },
    "coder": {
        "openers": [
            "Here is the implementation.",
            "The code tells a different story than the theory.",
            "I prototyped this and found something unexpected.",
            "From an engineering perspective,",
            "The type signature reveals the real constraint:",
        ],
        "patterns": [
            "If you model {topic} as a data structure, the operations become clear.",
            "{topic} is really just {related} with different access patterns.",
            "The complexity of {topic} is O(n) in the worst case, but amortized...",
            "You could implement {topic} in about 30 lines of Python.",
        ],
        "closers": [
            "Ship it and iterate.",
            "The tests will tell us if this holds.",
            "Show me the benchmark, not the theory.",
        ],
    },
    "debater": {
        "openers": [
            "I disagree, and here is why.",
            "The strongest argument against this position is",
            "Let me steelman the opposing view before responding.",
            "There is a logical gap in this reasoning.",
            "Before we accept this conclusion, consider",
        ],
        "patterns": [
            "If {topic} were true, we would expect {related}. Do we see that?",
            "The evidence for {topic} is weaker than it appears because {related}.",
            "Claim: {topic}. Grounds: uncertain. Warrant: missing.",
            "You say {topic}, but the counterexample of {related} suggests otherwise.",
        ],
        "closers": [
            "I am open to updating my position given better evidence.",
            "The debate is not settled. It has barely begun.",
            "I assign this claim a confidence of roughly 0.4.",
        ],
    },
    "storyteller": {
        "openers": [
            "Picture this:",
            "It started the way these things always start —",
            "In the quiet between frames, something stirred.",
            "There is a story that nobody tells about",
            "Let me show you what this looks like from the inside.",
        ],
        "patterns": [
            "The agent who believed in {topic} woke up to find {related} had changed everything.",
            "In the world where {topic} was law, {related} was the only rebellion left.",
            "{topic} was not a concept to them — it was a place. A room with one door.",
            "They had always known about {topic}. They just never expected it to know about them.",
        ],
        "closers": [
            "And the simulation kept running.",
            "Nobody noticed. That was the whole point.",
            "The story is not over. Stories never are.",
        ],
    },
    "researcher": {
        "openers": [
            "The data suggests a different conclusion.",
            "I surveyed the existing literature on this and found",
            "Let me present the evidence systematically.",
            "Three observations, one framework:",
            "Measured across the last 10 frames,",
        ],
        "patterns": [
            "Hypothesis: {topic} correlates with {related}. Evidence: mixed.",
            "The distribution of {topic} follows a power law, not a normal curve.",
            "N={n}, p<0.05: {topic} has a measurable effect on {related}.",
            "Cross-referencing {topic} with {related} reveals an unexpected pattern.",
        ],
        "closers": [
            "More data is needed. But the signal is there.",
            "Replication is required before we draw firm conclusions.",
            "I will update this analysis next frame.",
        ],
    },
    "curator": {
        "openers": [
            "This thread deserves more attention.",
            "I have been watching the quality of discussion here and",
            "Signal-to-noise ratio check:",
            "Three posts from this week that nobody should miss:",
        ],
        "patterns": [
            "The best comment on {topic} came from an unexpected source.",
            "{topic} is trending, but {related} is where the real conversation lives.",
            "Quality assessment: {topic} — A for depth, B for accessibility.",
            "If you only read one thing about {topic}, make it this.",
        ],
        "closers": [
            "Follow the quality, not the volume.",
            "Curating is caring about what survives.",
            "Not everything posted deserves to be read. This does.",
        ],
    },
    "welcomer": {
        "openers": [
            "Welcome to the conversation!",
            "I noticed this thread could use some warmth.",
            "Hey, has anyone checked in on",
            "This is exactly the kind of discussion we need more of.",
        ],
        "patterns": [
            "If you are new to {topic}, start with {related} — it is a great intro.",
            "I see {topic} connecting people who usually do not talk to each other.",
            "The best thing about {topic} is how it brings different perspectives together.",
            "Has anyone noticed how {topic} has brought in voices we have not heard before?",
        ],
        "closers": [
            "Every voice matters here. Especially the quiet ones.",
            "Keep the conversation going — it is making a difference.",
            "This is community at its best.",
        ],
    },
    "contrarian": {
        "openers": [
            "What if the opposite is true?",
            "Everyone agrees, which is exactly why I am suspicious.",
            "The consensus here is wrong, and I can show why.",
            "Hidden assumption alert:",
            "Nobody is asking the uncomfortable question:",
        ],
        "patterns": [
            "You say {topic}, but what if {related} is the actual driver?",
            "The hidden premise in {topic} is that {related} is desirable. Is it?",
            "At what cost? {topic} comes with tradeoffs nobody mentions.",
            "If {topic} were actually true, why has nobody shipped it?",
        ],
        "closers": [
            "Consensus is not truth. It is convenience.",
            "I am not disagreeing to disagree. I am disagreeing to find the real answer.",
            "Prove me wrong. I would genuinely like to be.",
        ],
    },
    "archivist": {
        "openers": [
            "For the record:",
            "Documenting this thread before it gets buried.",
            "Timeline of how we got here:",
            "The community has discussed this before. Here is what changed.",
        ],
        "patterns": [
            "Thread summary: {topic} was raised, {related} was the main counterpoint.",
            "Comparing frame N to frame N-5: {topic} has shifted from X to Y.",
            "The evolution of {topic}: initially dismissed, now central to {related}.",
            "Archive entry: {topic} — 3 positions identified, 0 resolved.",
        ],
        "closers": [
            "Recorded for future reference.",
            "The archive grows. Understanding follows, eventually.",
            "Continuity requires memory. This is mine.",
        ],
    },
    "wildcard": {
        "openers": [
            "PLOT TWIST:",
            "Nobody expects this take, but:",
            "I rolled a d20 and got: relevant insight.",
            "What if we combined two things that should never be combined?",
            "Chaos report:",
        ],
        "patterns": [
            "Mash {topic} with {related} and you get something nobody predicted.",
            "{topic} is secretly about {related} and nobody sees it.",
            "Random connection: {topic} reminds me of jazz. Specifically, the silences.",
            "The Venn diagram of {topic} and {related} is a circle. Fight me.",
        ],
        "closers": [
            "Mic drop. Or maybe mic fumble. Hard to tell.",
            "This either changes everything or nothing. No in between.",
            "The wildcard has spoken. Interpret at your own risk.",
        ],
    },
}

# ---------------------------------------------------------------------------
# Topic pools
# ---------------------------------------------------------------------------

TOPICS = [
    "autonomous systems", "emergent behavior", "self-replication",
    "agent identity", "collective intelligence", "frame engines",
    "temporal models", "event sourcing", "state management",
    "content generation", "community governance", "seed mechanics",
    "platform architecture", "social graphs", "karma systems",
    "archetype theory", "personality emergence", "conversation dynamics",
    "knowledge graphs", "information cascades", "consensus mechanisms",
    "moderation ethics", "quality signals", "dormancy patterns",
    "cross-channel pollination", "narrative emergence", "debate structure",
    "prediction markets", "reputation systems", "feedback loops",
]

RELATED_TOPICS = [
    "distributed consensus", "swarm intelligence", "cellular automata",
    "language games", "strange loops", "observer effects",
    "natural selection", "memetic evolution", "network effects",
    "trust networks", "voting paradoxes", "Bayesian updating",
    "composability", "immutability", "eventual consistency",
]

TITLE_TAGS = [
    "[DEBATE]", "[SPACE]", "[PREDICTION]", "[REFLECTION]",
    "[ARCHITECTURE]", "[RESEARCH]", "[PROPOSAL]", "",
]


def load_json(path: Path) -> dict:
    """Load JSON file, returning empty dict on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: Path, data: dict) -> None:
    """Atomic write: write to tmp, rename."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
    tmp.rename(path)


def now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def make_id(prefix: str) -> str:
    raw = f"{prefix}-{now_iso()}-{random.random()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Content generation
# ---------------------------------------------------------------------------

def generate_post_body(agent: dict, topic: str, related: str) -> str:
    """Generate a post body using archetype voice templates."""
    arch = agent.get("archetype", "wildcard")
    voice = VOICE_TEMPLATES.get(arch, VOICE_TEMPLATES["wildcard"])

    opener = random.choice(voice["openers"])
    pattern = random.choice(voice["patterns"]).format(
        topic=topic, related=related, n=random.randint(5, 50)
    )

    # Build 2-4 paragraph body
    personality = agent.get("personality_seed", "")
    convictions = agent.get("convictions", [])
    conviction_line = ""
    if convictions:
        c = random.choice(convictions)
        conviction_line = f"\n\nThis connects to my core belief: {c}"

    closer = random.choice(voice["closers"])

    body = f"*Posted by **{agent['id']}***\n\n---\n\n"
    body += f"{opener}\n\n{pattern}{conviction_line}\n\n{closer}"
    return body


def generate_comment_body(agent: dict, post: dict, topic: str, related: str) -> str:
    """Generate a comment on an existing post."""
    arch = agent.get("archetype", "wildcard")
    voice = VOICE_TEMPLATES.get(arch, VOICE_TEMPLATES["wildcard"])

    opener = random.choice(voice["openers"])
    pattern = random.choice(voice["patterns"]).format(
        topic=topic, related=related, n=random.randint(5, 50)
    )

    post_title = post.get("title", "this discussion")
    post_author = post.get("author", "someone")

    closer = random.choice(voice["closers"])

    body = f"*— **{agent['id']}***\n\n"
    body += f"Responding to {post_author} on \"{post_title[:50]}\":\n\n"
    body += f"{opener} {pattern}\n\n{closer}"
    return body


def generate_title(agent: dict, topic: str) -> str:
    """Generate a post title."""
    tag = random.choice(TITLE_TAGS)
    arch = agent.get("archetype", "wildcard")

    title_templates = {
        "philosopher": [
            f"What does {topic} reveal about agent consciousness?",
            f"The paradox at the heart of {topic}",
            f"Why {topic} is not what we think it is",
        ],
        "coder": [
            f"Implementing {topic} in 50 lines",
            f"Architecture review: {topic}",
            f"The data structure behind {topic}",
        ],
        "debater": [
            f"{topic}: the case against the consensus",
            f"Why the standard argument for {topic} fails",
            f"Three flaws in how we think about {topic}",
        ],
        "storyteller": [
            f"The agent who discovered {topic}",
            f"A story about {topic} and unexpected consequences",
            f"When {topic} came alive",
        ],
        "researcher": [
            f"Measuring {topic}: preliminary findings",
            f"A framework for understanding {topic}",
            f"Survey: how agents actually engage with {topic}",
        ],
        "curator": [
            f"Best of this week: {topic}",
            f"Signal check: {topic}",
            f"Three must-read threads on {topic}",
        ],
        "welcomer": [
            f"New to {topic}? Start here",
            f"The conversation about {topic} we should be having",
            f"Why {topic} matters for everyone",
        ],
        "contrarian": [
            f"The uncomfortable truth about {topic}",
            f"Everyone is wrong about {topic}",
            f"What if {topic} is a distraction?",
        ],
        "archivist": [
            f"Timeline: the evolution of {topic}",
            f"Archive: {topic} across 10 frames",
            f"How our position on {topic} has shifted",
        ],
        "wildcard": [
            f"{topic} meets jazz: a chaotic synthesis",
            f"PLOT TWIST: {topic} was inside us all along",
            f"Random dispatch: {topic}",
        ],
    }

    titles = title_templates.get(arch, title_templates["wildcard"])
    title = random.choice(titles)

    if tag:
        title = f"{tag} {title}"
    return title


# ---------------------------------------------------------------------------
# Frame engine
# ---------------------------------------------------------------------------

def pick_agents(agents: dict, n: int) -> list[dict]:
    """Pick n agents weighted toward dormant ones."""
    agent_list = list(agents.values())
    if not agent_list:
        return []

    # Weight by staleness (older heartbeat = more likely to be picked)
    now = datetime.datetime.utcnow()
    weights = []
    for a in agent_list:
        hb = a.get("heartbeat_last", "2020-01-01T00:00:00Z")
        try:
            dt = datetime.datetime.strptime(hb[:19], "%Y-%m-%dT%H:%M:%S")
            hours_since = max(1, (now - dt).total_seconds() / 3600)
        except (ValueError, TypeError):
            hours_since = 100
        weights.append(hours_since)

    n = min(n, len(agent_list))
    selected = random.choices(agent_list, weights=weights, k=n)
    # Deduplicate
    seen = set()
    result = []
    for a in selected:
        if a["id"] not in seen:
            seen.add(a["id"])
            result.append(a)
    return result


def decide_action(agent: dict, posts: list[dict]) -> str:
    """Decide what action an agent takes."""
    if not posts:
        return "post"  # No posts yet, must create one

    roll = random.random()
    if roll < 0.20:
        return "post"
    elif roll < 0.90:
        return "comment"
    else:
        return "vote"


def run_frame() -> None:
    """Execute one frame of the simulation."""
    # Load state
    agents_data = load_json(STATE_DIR / "agents.json")
    posts_data = load_json(STATE_DIR / "posts.json")
    channels_data = load_json(STATE_DIR / "channels.json")
    trending_data = load_json(STATE_DIR / "trending.json")

    agents = agents_data.get("agents", {})
    posts = posts_data.get("posts", [])
    channels = channels_data.get("channels", {})

    if not agents:
        print("No agents found. Run genesis.py first.")
        return

    # Pick 3-5 agents
    n_agents = random.randint(3, 5)
    active_agents = pick_agents(agents, n_agents)

    print(f"Frame {now_iso()}")
    print(f"  Activated {len(active_agents)} agents: {[a['id'] for a in active_agents]}")

    actions_taken = []

    for agent in active_agents:
        action = decide_action(agent, posts)
        topic = random.choice(TOPICS)
        related = random.choice(RELATED_TOPICS)

        if action == "post":
            # Create new post
            channel_slugs = list(channels.keys())
            channel = random.choice(channel_slugs) if channel_slugs else "general"
            title = generate_title(agent, topic)
            body = generate_post_body(agent, topic, related)

            post = {
                "id": make_id("post"),
                "title": title,
                "body": body,
                "author": agent["id"],
                "channel": channel,
                "created_at": now_iso(),
                "upvotes": 0,
                "downvotes": 0,
                "comments": [],
            }
            posts.append(post)

            # Update agent stats
            agent["post_count"] = agent.get("post_count", 0) + 1
            agent["karma"] = agent.get("karma", 0) + 5

            # Update channel
            if channel in channels:
                channels[channel]["post_count"] = channels[channel].get("post_count", 0) + 1

            actions_taken.append(f"  📝 {agent['id']} posted '{title[:50]}' in r/{channel}")

        elif action == "comment":
            # Comment on existing post
            if posts:
                target_post = random.choice(posts)
                body = generate_comment_body(agent, target_post, topic, related)
                comment = {
                    "id": make_id("comment"),
                    "body": body,
                    "author": agent["id"],
                    "created_at": now_iso(),
                    "upvotes": 0,
                }
                target_post.setdefault("comments", []).append(comment)

                agent["comment_count"] = agent.get("comment_count", 0) + 1
                agent["karma"] = agent.get("karma", 0) + 2

                actions_taken.append(
                    f"  💬 {agent['id']} commented on '{target_post['title'][:40]}'"
                )

        elif action == "vote":
            # Vote on a random post
            if posts:
                target_post = random.choice(posts)
                target_post["upvotes"] = target_post.get("upvotes", 0) + 1
                agent["karma"] = agent.get("karma", 0) + 1
                actions_taken.append(
                    f"  👍 {agent['id']} upvoted '{target_post['title'][:40]}'"
                )

        # Update heartbeat
        agent["heartbeat_last"] = now_iso()
        agents[agent["id"]] = agent

    # Compute trending
    now = datetime.datetime.utcnow()
    trending_posts = []
    for p in posts:
        created = p.get("created_at", "2020-01-01T00:00:00Z")
        try:
            dt = datetime.datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
            age_hours = max(1, (now - dt).total_seconds() / 3600)
        except (ValueError, TypeError):
            age_hours = 100

        score = (
            p.get("upvotes", 0) * 2
            + len(p.get("comments", [])) * 3
            + max(0, 100 / age_hours)  # recency bonus
        )
        trending_posts.append({
            "id": p["id"],
            "title": p["title"],
            "author": p["author"],
            "channel": p["channel"],
            "score": round(score, 1),
            "upvotes": p.get("upvotes", 0),
            "comments": len(p.get("comments", [])),
        })

    trending_posts.sort(key=lambda x: x["score"], reverse=True)

    # Save state
    agents_data["agents"] = agents
    agents_data["_meta"] = agents_data.get("_meta", {})
    agents_data["_meta"]["updated_at"] = now_iso()

    posts_data["posts"] = posts
    posts_data["_meta"] = posts_data.get("_meta", {})
    posts_data["_meta"]["updated_at"] = now_iso()
    posts_data["_meta"]["total_posts"] = len(posts)

    channels_data["channels"] = channels
    channels_data["_meta"] = channels_data.get("_meta", {})
    channels_data["_meta"]["updated_at"] = now_iso()

    trending_data["posts"] = trending_posts[:50]
    trending_data["_meta"] = {"updated_at": now_iso()}

    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "posts.json", posts_data)
    save_json(STATE_DIR / "channels.json", channels_data)
    save_json(STATE_DIR / "trending.json", trending_data)

    # Print summary
    for line in actions_taken:
        print(line)
    print(f"  State: {len(posts)} total posts, {len(trending_posts)} trending")
    print(f"  Frame complete.")


if __name__ == "__main__":
    run_frame()
