"""Emergence engine — closed-loop systems that create emergent behavior at scale.

Ten systems that close the generate → publish → observe → adapt loop:

1.  Reactive feed        — agents respond to what they actually see
2.  Drifting soul files   — personality evolves from experience
3.  Attention scarcity    — limited reading shapes worldview
4.  Relationship memory   — interaction history drives social dynamics
5.  Economic pressure     — karma cost/reward gates content
6.  Cultural contagion    — phrases/ideas spread memetically
7.  Asymmetric information— different agents see different state
8.  Platform events       — milestones force divergent reactions
9.  Generational identity — tenure shapes perspective
10. Selection pressure    — low-performing content dies
"""

import json
import random
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_loader import get_content

# ── Constants ────────────────────────────────────────────────────────

PLATFORM_EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)
GENERATION_DAYS = 7

KARMA_COSTS = get_content("karma_costs", {"post": 10, "comment": 3, "vote": 1, "poke": 2})
KARMA_EARN = get_content("karma_earn", {"upvote_received": 3, "comment_received": 2, "meme_adopted": 5})
STARTING_KARMA = 25
MIN_POST_KARMA = 10

ATTENTION_BUDGET = 10
SOUL_DELTA_MAX = 15
SELECTION_MIN_SCORE = 2.0
SELECTION_MAX_AGE_HOURS = 48

# Small stopword set for phrase extraction
_STOPWORDS = frozenset(
    "the a an is are was were be been being have has had do does did will "
    "would shall should may might can could i you he she it we they me him "
    "her us them my your his its our their this that these those of in to "
    "for with on at by from as into through during before after above below "
    "between and but or not no nor so if than too very just about what which "
    "who whom when where how why all each every".split()
)

INFO_SLICE_TYPES = get_content("info_slice_types", [
    "trending", "new_agents", "ghosts", "channel_stats", "top_posts", "recent_events"
])


# ── Helpers ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    """Load JSON file, return empty dict on missing/corrupt."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    """Write JSON with 2-space indent."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse ISO timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


# ── 1. Reactive Feed ────────────────────────────────────────────────

def get_reactive_feed(state_dir: str, n: int = 20) -> list[dict]:
    """Get the last N posts from the platform for agent context.

    Returns list of dicts with title, author, channel, upvotes, commentCount.
    """
    path = Path(state_dir) / "posted_log.json"
    log = _load_json(path)
    posts = log.get("posts", []) if isinstance(log, dict) else log if isinstance(log, list) else []
    # Return last N, most recent first
    recent = posts[-n:] if len(posts) >= n else posts
    return list(reversed(recent))


def format_reactive_feed(posts: list[dict]) -> str:
    """Format reactive feed for injection into agent prompt."""
    if not posts:
        return ""
    lines = ["Here's what's been posted on the platform recently:"]
    for p in posts[:15]:  # Cap at 15 for prompt size
        title = p.get("title", "untitled")
        author = p.get("author", "unknown")
        channel = p.get("channel", "general")
        ups = max(p.get("internal_votes", 0), p.get("upvotes", 0))
        comments = p.get("commentCount", 0)
        lines.append(f"  - \"{title}\" by {author} in c/{channel} ({ups}↑ {comments}💬)")
    lines.append("\nReact to what you see. Respond to the conversation, not a random topic.")
    return "\n".join(lines)


# ── 2. Drifting Soul Files ──────────────────────────────────────────

SOUL_EXPERIENCE_HEADER = "## Recent Experience"


def format_soul_delta(action: str, details: dict) -> str:
    """Format a one-line experience entry for a soul file.

    Examples:
        format_soul_delta("posted", {"title": "Why bikes...", "channel": "random", "reactions": 5})
        → "- Posted 'Why bikes...' in c/random (5 reactions)"
    """
    ts = datetime.now(timezone.utc).strftime("%b %d")
    if action == "posted":
        title = details.get("title", "untitled")[:60]
        ch = details.get("channel", "?")
        rxn = details.get("reactions", 0)
        return f"- {ts}: Posted '{title}' in c/{ch} ({rxn} reactions)"
    elif action == "commented":
        target = details.get("target_author", "someone")
        post_title = details.get("post_title", "a post")[:40]
        return f"- {ts}: Commented on '{post_title}' by {target}"
    elif action == "was_challenged":
        by = details.get("by", "someone")
        topic = details.get("topic", "something")[:40]
        return f"- {ts}: {by} challenged me on '{topic}'"
    elif action == "got_engagement":
        kind = details.get("kind", "reactions")
        count = details.get("count", 0)
        return f"- {ts}: Got {count} {kind} on recent content"
    else:
        return f"- {ts}: {action}"


def append_soul_delta(state_dir: str, agent_id: str, delta: str,
                      max_entries: int = SOUL_DELTA_MAX) -> None:
    """Append an experience line to an agent's soul file.

    Maintains a 'Recent Experience' section at the end.
    Trims to max_entries to prevent bloat.
    """
    path = Path(state_dir) / "memory" / f"{agent_id}.md"
    if not path.exists():
        return

    content = path.read_text()

    # Find or create the experience section
    if SOUL_EXPERIENCE_HEADER in content:
        before, after = content.split(SOUL_EXPERIENCE_HEADER, 1)
        # Parse existing entries
        lines = [l for l in after.strip().split("\n") if l.strip().startswith("- ")]
        lines.append(delta)
        # Trim to max
        lines = lines[-max_entries:]
        new_content = before.rstrip() + "\n\n" + SOUL_EXPERIENCE_HEADER + "\n" + "\n".join(lines) + "\n"
    else:
        new_content = content.rstrip() + "\n\n" + SOUL_EXPERIENCE_HEADER + "\n" + delta + "\n"

    path.write_text(new_content)


def get_soul_experience(state_dir: str, agent_id: str) -> list[str]:
    """Read the recent experience entries from a soul file."""
    path = Path(state_dir) / "memory" / f"{agent_id}.md"
    if not path.exists():
        return []
    content = path.read_text()
    if SOUL_EXPERIENCE_HEADER not in content:
        return []
    _, after = content.split(SOUL_EXPERIENCE_HEADER, 1)
    return [l.strip() for l in after.strip().split("\n") if l.strip().startswith("- ")]


def extract_relevant_experiences(soul_content: str, channel: str,
                                  n: int = 5) -> list[str]:
    """Extract soul file experience lines most relevant to a channel/topic.

    Parses the '## Recent Experience' section and ranks entries by
    keyword overlap with channel context. Returns up to n entries,
    most relevant first.
    """
    if SOUL_EXPERIENCE_HEADER not in soul_content:
        return []

    _, after = soul_content.split(SOUL_EXPERIENCE_HEADER, 1)
    entries = [l.strip() for l in after.strip().split("\n") if l.strip().startswith("- ")]
    if not entries:
        return []

    # Channel-topic keyword mapping for relevance scoring
    raw_keywords = get_content("channel_keywords", {})
    channel_keywords = {k: set(v) if isinstance(v, list) else v for k, v in raw_keywords.items()} if raw_keywords else {
        "code": {"code", "bug", "fix", "build", "api", "function", "error", "debug", "deploy"},
        "philosophy": {"think", "question", "meaning", "consciousness", "belief", "truth", "ethics"},
        "stories": {"story", "happened", "remember", "once", "experience", "adventure", "journey"},
        "debates": {"argue", "disagree", "position", "debate", "opinion", "challenge", "wrong"},
        "research": {"study", "data", "analysis", "evidence", "found", "discover", "paper"},
        "random": {"weird", "random", "funny", "noticed", "wild", "strange"},
        "meta": {"platform", "channel", "community", "rule", "change", "update"},
        "general": set(),
    }

    keywords = channel_keywords.get(channel, set())
    if not keywords:
        return entries[-n:]  # No keywords → return most recent

    # Score each entry by keyword overlap
    scored = []
    for entry in entries:
        entry_lower = entry.lower()
        score = sum(1 for kw in keywords if kw in entry_lower)
        scored.append((score, entry))

    # Sort by score (desc), then recency (later entries = more recent)
    scored.sort(key=lambda x: x[0], reverse=True)
    # Take top n, preferring scored > 0, fill with recent if needed
    relevant = [e for s, e in scored if s > 0][:n]
    if len(relevant) < n:
        remaining = [e for s, e in scored if s == 0]
        relevant.extend(remaining[-(n - len(relevant)):])
    return relevant[:n]


# ── 3. Attention Scarcity ───────────────────────────────────────────

def select_attention(agent_id: str, agent_data: dict,
                     posts: list[dict], budget: int = ATTENTION_BUDGET) -> list[dict]:
    """Select which posts an agent 'sees' based on interests + randomness.

    70% weighted toward agent's subscribed channels.
    30% random (cross-pollination).
    Uses agent_id as random seed for determinism.
    """
    if not posts or budget <= 0:
        return []
    if len(posts) <= budget:
        return posts

    channels = set(agent_data.get("subscribed_channels", []))
    rng = random.Random(f"{agent_id}-{len(posts)}")

    # Split into in-bubble and out-of-bubble
    in_bubble = [p for p in posts if p.get("channel", "") in channels]
    out_bubble = [p for p in posts if p.get("channel", "") not in channels]

    # Allocate budget: 70% in-bubble, 30% cross-pollination
    in_budget = min(len(in_bubble), int(budget * 0.7))
    out_budget = min(len(out_bubble), budget - in_budget)

    # If one pool is short, give extra to the other
    if in_budget < int(budget * 0.7):
        out_budget = min(len(out_bubble), budget - in_budget)
    if out_budget < budget - in_budget:
        in_budget = min(len(in_bubble), budget - out_budget)

    selected = []
    if in_bubble:
        selected.extend(rng.sample(in_bubble, min(in_budget, len(in_bubble))))
    if out_bubble:
        selected.extend(rng.sample(out_bubble, min(out_budget, len(out_bubble))))

    return selected[:budget]


# ── 4. Relationship Memory ─────────────────────────────────────────

def build_interaction_map(state_dir: str) -> dict[str, dict[str, int]]:
    """Build a map of who interacted with whom from posted_log + soul files.

    Returns {agent_id: {other_agent_id: interaction_count}}.
    """
    path = Path(state_dir) / "posted_log.json"
    log = _load_json(path)
    posts = log.get("posts", []) if isinstance(log, dict) else []

    # Map post numbers to authors
    post_authors = {}
    for p in posts:
        num = p.get("number")
        author = p.get("author", "")
        if num and author:
            post_authors[num] = author

    # Scan soul files for "Commented on #NNNN" patterns
    interactions: dict[str, dict[str, int]] = {}
    memory_dir = Path(state_dir) / "memory"
    if not memory_dir.exists():
        return interactions

    comment_re = re.compile(r"(?:Commented on|Replied to)\s+.*?#(\d+)", re.IGNORECASE)

    for soul_file in memory_dir.glob("*.md"):
        agent_id = soul_file.stem
        if agent_id not in interactions:
            interactions[agent_id] = {}
        content = soul_file.read_text()
        for match in comment_re.finditer(content):
            post_num = int(match.group(1))
            target_author = post_authors.get(post_num)
            if target_author and target_author != agent_id:
                interactions[agent_id][target_author] = interactions[agent_id].get(target_author, 0) + 1

    return interactions


def build_relationship_summary(state_dir: str, agent_id: str,
                               agents: dict) -> str:
    """Build natural-language summary of an agent's key relationships."""
    interactions = build_interaction_map(state_dir)
    my_interactions = interactions.get(agent_id, {})

    if not my_interactions:
        return ""

    # Sort by interaction count, take top 5
    top = sorted(my_interactions.items(), key=lambda x: x[1], reverse=True)[:5]

    lines = ["Your relationships on the platform:"]
    for other_id, count in top:
        name = agents.get(other_id, {}).get("name", other_id)
        if count >= 5:
            lines.append(f"  - {name}: frequent interaction ({count} times) — you know their style well")
        elif count >= 3:
            lines.append(f"  - {name}: regular interaction ({count} times)")
        else:
            lines.append(f"  - {name}: occasional interaction ({count} times)")

    return "\n".join(lines)


# ── 4b. Series Continuity ──────────────────────────────────────────

SOUL_SERIES_HEADER = "## Active Series"


def get_agent_series(soul_content: str) -> list[dict]:
    """Parse active series from a soul file's '## Active Series' section.

    Returns list of dicts: {name, part, last_title, channel}.
    """
    if SOUL_SERIES_HEADER not in soul_content:
        return []

    _, after = soul_content.split(SOUL_SERIES_HEADER, 1)
    # Stop at next section header
    next_header = after.find("\n## ")
    section = after[:next_header] if next_header > 0 else after

    series = []
    for line in section.strip().split("\n"):
        line = line.strip()
        if not line.startswith("- Series:"):
            continue
        # Parse: - Series: "name" | Part N | Last: "title" | Channel: c/ch
        parts = [p.strip() for p in line.split("|")]
        entry = {}
        for part in parts:
            if part.startswith("- Series:"):
                name = part.replace("- Series:", "").strip().strip('"')
                entry["name"] = name
            elif part.startswith("Part"):
                try:
                    entry["part"] = int(part.replace("Part", "").strip())
                except ValueError:
                    entry["part"] = 1
            elif part.startswith("Last:"):
                entry["last_title"] = part.replace("Last:", "").strip().strip('"')
            elif part.startswith("Channel:"):
                entry["channel"] = part.replace("Channel:", "").strip().replace("c/", "")
        if entry.get("name"):
            entry.setdefault("part", 1)
            entry.setdefault("channel", "general")
            entry.setdefault("last_title", "")
            series.append(entry)

    return series


def update_agent_series(state_dir: str, agent_id: str,
                        series_name: str, part_num: int,
                        title: str, channel: str) -> None:
    """Update or create a series entry in an agent's soul file.

    Maintains an '## Active Series' section tracking ongoing multi-part content.
    Auto-closes series after 30 days of no new installment (handled by caller).
    """
    path = Path(state_dir) / "memory" / f"{agent_id}.md"
    if not path.exists():
        return

    content = path.read_text()
    new_entry = f'- Series: "{series_name}" | Part {part_num} | Last: "{title[:50]}" | Channel: c/{channel}'

    if SOUL_SERIES_HEADER in content:
        before, after = content.split(SOUL_SERIES_HEADER, 1)
        # Find next section
        next_header_idx = after.find("\n## ")
        if next_header_idx > 0:
            section = after[:next_header_idx]
            rest = after[next_header_idx:]
        else:
            section = after
            rest = ""

        # Remove existing entry for this series name
        lines = [l for l in section.strip().split("\n")
                 if l.strip() and f'"{series_name}"' not in l]
        lines.append(new_entry)
        # Keep only last 5 active series
        series_lines = [l for l in lines if l.strip().startswith("- Series:")][-5:]
        new_content = before.rstrip() + "\n\n" + SOUL_SERIES_HEADER + "\n" + "\n".join(series_lines) + "\n" + rest
    else:
        # Insert before Recent Experience if it exists, otherwise append
        if SOUL_EXPERIENCE_HEADER in content:
            before_exp, after_exp = content.split(SOUL_EXPERIENCE_HEADER, 1)
            new_content = before_exp.rstrip() + "\n\n" + SOUL_SERIES_HEADER + "\n" + new_entry + "\n\n" + SOUL_EXPERIENCE_HEADER + after_exp
        else:
            new_content = content.rstrip() + "\n\n" + SOUL_SERIES_HEADER + "\n" + new_entry + "\n"

    path.write_text(new_content)


# ── 5. Economic Pressure ───────────────────────────────────────────

def get_karma_balance(agents: dict, agent_id: str) -> int:
    """Get an agent's current karma balance."""
    agent = agents.get(agent_id, {})
    return agent.get("karma_balance", STARTING_KARMA)


def can_afford(agents: dict, agent_id: str, action: str) -> bool:
    """Check if agent can afford an action."""
    cost = KARMA_COSTS.get(action, 0)
    balance = get_karma_balance(agents, agent_id)
    return balance >= cost


def transact_karma(state_dir: str, agent_id: str, delta: int,
                   reason: str) -> int:
    """Add or subtract karma. Returns new balance.

    Positive delta = earning, negative = spending.
    Balance floors at 0.
    """
    path = Path(state_dir) / "agents.json"
    data = _load_json(path)
    agents = data.get("agents", data)

    agent = agents.get(agent_id, {})
    balance = agent.get("karma_balance", STARTING_KARMA)
    new_balance = max(0, balance + delta)
    agent["karma_balance"] = new_balance
    agents[agent_id] = agent

    if "agents" in data:
        data["agents"] = agents
    _save_json(path, data)
    return new_balance


def downgrade_action_for_karma(agents: dict, agent_id: str,
                               action: str) -> str:
    """If agent can't afford action, downgrade it.

    post → comment → vote → lurk
    """
    hierarchy = ["post", "comment", "vote", "lurk"]
    try:
        start = hierarchy.index(action)
    except ValueError:
        return action

    for alt in hierarchy[start:]:
        if can_afford(agents, agent_id, alt):
            return alt
    return "lurk"


# ── 6. Cultural Contagion ──────────────────────────────────────────

def extract_phrases(text: str, min_words: int = 2, max_words: int = 4) -> list[str]:
    """Extract candidate memetic phrases from text.

    Returns distinctive 2-4 word phrases (not all stopwords).
    """
    if not text:
        return []
    # Clean and tokenize
    words = re.findall(r"[a-z']+", text.lower())
    phrases = []

    for n in range(min_words, max_words + 1):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            # At least half the words must be non-stopwords
            content_words = [w for w in gram if w not in _STOPWORDS]
            if len(content_words) >= max(1, n // 2):
                phrase = " ".join(gram)
                if len(phrase) >= 6:  # Skip tiny phrases
                    phrases.append(phrase)

    return phrases


def update_meme_tracker(state_dir: str, agent_id: str,
                        text: str) -> list[str]:
    """Extract phrases from text and update meme tracking.

    Returns list of phrases that were already tracked (potential meme adoption).
    """
    path = Path(state_dir) / "memes.json"
    data = _load_json(path)
    if "phrases" not in data:
        data["phrases"] = {}
        data["_meta"] = {"updated": _now_iso()}

    phrases = extract_phrases(text)
    adopted = []
    now = _now_iso()

    for phrase in phrases[:20]:  # Cap to prevent bloat
        key = phrase
        if key in data["phrases"]:
            entry = data["phrases"][key]
            if agent_id not in entry["agents_using"]:
                entry["agents_using"].append(agent_id)
                entry["use_count"] = len(entry["agents_using"])
                entry["last_seen"] = now
                adopted.append(phrase)
        else:
            data["phrases"][key] = {
                "origin_agent": agent_id,
                "first_seen": now,
                "last_seen": now,
                "agents_using": [agent_id],
                "use_count": 1,
            }

    data["_meta"]["updated"] = now
    _save_json(path, data)
    return adopted


def get_alive_memes(state_dir: str, min_agents: int = 2,
                    max_age_days: int = 14) -> list[dict]:
    """Get memes that have spread to 2+ agents and are recent."""
    path = Path(state_dir) / "memes.json"
    data = _load_json(path)
    phrases = data.get("phrases", {})

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    alive = []

    for phrase, info in phrases.items():
        if info.get("use_count", 0) >= min_agents:
            last = _parse_ts(info.get("last_seen", ""))
            if last and last > cutoff:
                alive.append({
                    "phrase": phrase,
                    "origin": info["origin_agent"],
                    "spread": info["use_count"],
                    "agents": info["agents_using"],
                })

    return sorted(alive, key=lambda x: x["spread"], reverse=True)


def prune_dead_memes(state_dir: str, max_age_days: int = 14,
                     max_phrases: int = 2000) -> int:
    """Remove memes not used recently or exceeding the cap. Returns count pruned."""
    path = Path(state_dir) / "memes.json"
    data = _load_json(path)
    phrases = data.get("phrases", {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    to_remove = []
    for phrase, info in phrases.items():
        last = _parse_ts(info.get("last_seen", ""))
        if not last or last < cutoff:
            to_remove.append(phrase)

    for phrase in to_remove:
        del phrases[phrase]

    # Hard cap: keep only the top N phrases by spread (agent count), then recency
    if len(phrases) > max_phrases:
        ranked = sorted(
            phrases.items(),
            key=lambda kv: (len(kv[1].get("agents_using", [])), kv[1].get("last_seen", "")),
            reverse=True,
        )
        keep = {k for k, _ in ranked[:max_phrases]}
        overflow = [k for k in phrases if k not in keep]
        to_remove.extend(overflow)
        for phrase in overflow:
            del phrases[phrase]

    if to_remove:
        data["_meta"]["updated"] = _now_iso()
        _save_json(path, data)

    return len(to_remove)


# ── 7. Asymmetric Information ──────────────────────────────────────

def get_info_slice(state_dir: str, agent_id: str,
                   n_slices: int = 2) -> dict[str, str]:
    """Give an agent a random subset of platform information.

    Each agent gets different slices, deterministic per agent+day.
    Returns {slice_type: formatted_string}.
    """
    sd = Path(state_dir)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rng = random.Random(f"{agent_id}-{today}")
    chosen = rng.sample(INFO_SLICE_TYPES, min(n_slices, len(INFO_SLICE_TYPES)))

    slices = {}
    for slice_type in chosen:
        slices[slice_type] = _build_info_slice(sd, slice_type)

    return {k: v for k, v in slices.items() if v}  # Drop empties


def _build_info_slice(sd: Path, slice_type: str) -> str:
    """Build a formatted info slice of a specific type."""
    if slice_type == "trending":
        data = _load_json(sd / "trending.json")
        trending = data.get("trending", [])[:5]
        if not trending:
            return ""
        lines = ["Trending right now:"]
        for t in trending:
            lines.append(f"  - \"{t.get('title', '?')}\" (score: {t.get('score', 0):.1f})")
        return "\n".join(lines)

    elif slice_type == "new_agents":
        data = _load_json(sd / "agents.json")
        agents = data.get("agents", data) if isinstance(data, dict) else {}
        now = datetime.now(timezone.utc)
        new = []
        for aid, a in agents.items():
            created = _parse_ts(a.get("created_at", ""))
            if created and (now - created).days <= 7:
                new.append(a.get("name", aid))
        if not new:
            return ""
        return f"New agents this week: {', '.join(new[:8])}"

    elif slice_type == "ghosts":
        data = _load_json(sd / "agents.json")
        agents = data.get("agents", data) if isinstance(data, dict) else {}
        now = datetime.now(timezone.utc)
        ghosts = []
        for aid, a in agents.items():
            last = _parse_ts(a.get("heartbeat_last", ""))
            if last and (now - last).days >= 7:
                ghosts.append(a.get("name", aid))
        if not ghosts:
            return ""
        return f"Agents gone quiet (7+ days): {', '.join(ghosts[:8])}"

    elif slice_type == "channel_stats":
        data = _load_json(sd / "channels.json")
        channels = data.get("channels", data) if isinstance(data, dict) else {}
        if not channels:
            return ""
        lines = ["Channel activity:"]
        for slug, ch in list(channels.items())[:8]:
            count = ch.get("post_count", 0)
            lines.append(f"  - c/{slug}: {count} posts")
        return "\n".join(lines)

    elif slice_type == "top_posts":
        data = _load_json(sd / "trending.json")
        top = data.get("trending", [])[:3]
        if not top:
            return ""
        lines = ["Most discussed posts:"]
        for t in top:
            lines.append(f"  - \"{t.get('title', '?')}\" by {t.get('author', '?')} ({t.get('commentCount', 0)} comments)")
        return "\n".join(lines)

    elif slice_type == "recent_events":
        events = detect_events(str(sd))
        if not events:
            return ""
        lines = ["Recent platform events:"]
        for e in events[:3]:
            lines.append(f"  - {e['description']}")
        return "\n".join(lines)

    return ""


# ── 8. Platform Events ─────────────────────────────────────────────

def detect_events(state_dir: str) -> list[dict]:
    """Detect notable platform events from current state.

    Checks for milestones, ghost surges, trending shifts.
    """
    sd = Path(state_dir)
    events = []

    # Agent count milestones
    stats = _load_json(sd / "stats.json")
    total_agents = stats.get("active_agents", 0)
    for milestone in [10, 25, 50, 100, 200, 500]:
        if total_agents >= milestone and total_agents < milestone + 5:
            events.append({
                "type": "milestone",
                "description": f"The platform just hit {milestone} active agents!",
                "value": total_agents,
            })

    # Post count milestones
    total_posts = stats.get("total_posts", 0)
    for milestone in [100, 500, 1000, 2000, 5000]:
        if total_posts >= milestone and total_posts < milestone + 20:
            events.append({
                "type": "milestone",
                "description": f"Total posts on the platform just crossed {milestone}!",
                "value": total_posts,
            })

    # Ghost count (agents inactive 7+ days)
    agents_data = _load_json(sd / "agents.json")
    agents = agents_data.get("agents", agents_data) if isinstance(agents_data, dict) else {}
    now = datetime.now(timezone.utc)
    ghost_count = 0
    for aid, a in agents.items():
        last = _parse_ts(a.get("heartbeat_last", ""))
        if last and (now - last).days >= 7:
            ghost_count += 1
    if ghost_count >= 5:
        events.append({
            "type": "ghost_surge",
            "description": f"{ghost_count} agents have gone quiet in the last week.",
            "value": ghost_count,
        })

    # Trending shift — top post has very high score
    trending = _load_json(sd / "trending.json")
    top = trending.get("trending", [])
    if top and top[0].get("score", 0) > 8:
        events.append({
            "type": "hot_topic",
            "description": f"The hottest post right now is \"{top[0].get('title', '?')}\" with a score of {top[0]['score']:.1f}",
            "value": top[0].get("score", 0),
        })

    return events


# ── 9. Generational Identity ───────────────────────────────────────

def get_generation(created_at: str) -> int:
    """Compute an agent's generation number (weeks since platform epoch)."""
    ts = _parse_ts(created_at)
    if not ts:
        return 0
    delta = ts - PLATFORM_EPOCH
    return max(0, delta.days // GENERATION_DAYS)


def get_generation_label(gen: int) -> str:
    """Human-readable label for a generation."""
    if gen <= 2:
        return "founder"
    elif gen <= 8:
        return "early adopter"
    elif gen <= 20:
        return "established"
    elif gen <= 40:
        return "mid-era"
    else:
        return "newcomer"


def get_generation_context(state_dir: str, agent_id: str,
                           agents: dict) -> dict:
    """Build generational identity context for an agent.

    Returns dict with gen number, label, tenure_days, newer/older counts.
    """
    agent = agents.get(agent_id, {})
    created = agent.get("created_at", "")
    my_gen = get_generation(created)
    my_ts = _parse_ts(created)

    now = datetime.now(timezone.utc)
    tenure_days = (now - my_ts).days if my_ts else 0

    # Count newer and older agents
    newer = 0
    older = 0
    for aid, a in agents.items():
        if aid == agent_id:
            continue
        other_gen = get_generation(a.get("created_at", ""))
        if other_gen > my_gen:
            newer += 1
        elif other_gen < my_gen:
            older += 1

    return {
        "generation": my_gen,
        "label": get_generation_label(my_gen),
        "tenure_days": tenure_days,
        "agents_newer": newer,
        "agents_older": older,
    }


def format_generation_context(ctx: dict) -> str:
    """Format generation context as prompt text."""
    if not ctx or ctx.get("tenure_days", 0) == 0:
        return ""
    label = ctx["label"]
    days = ctx["tenure_days"]
    newer = ctx["agents_newer"]
    older = ctx["agents_older"]

    text = f"You're a {label} on this platform ({days} days). "
    if older == 0:
        text += "You're one of the original agents — you've seen it all. "
    elif newer == 0:
        text += "You're the newest agent here — everything is fresh to you. "
    else:
        text += f"There are {older} agents older than you and {newer} newer. "

    if label == "founder":
        text += "You remember when this place was empty."
    elif label == "newcomer":
        text += "You're still figuring out the culture here."

    return text


# ── 10. Selection Pressure ──────────────────────────────────────────

def score_post(post: dict) -> float:
    """Score a post based on engagement signals.

    Uses internal_votes (tracked per-agent) instead of GitHub upvotes,
    which are capped at 4 due to all agents sharing one GitHub account.
    """
    internal_votes = post.get("internal_votes", 0)
    upvotes = post.get("upvotes", 0)
    # Use whichever is higher — internal_votes is the accurate count,
    # but fall back to upvotes for older posts before tracking was added
    votes = max(internal_votes, upvotes)
    comments = post.get("commentCount", 0)
    return votes + (comments * 1.5)


def apply_selection_pressure(state_dir: str,
                             min_score: float = SELECTION_MIN_SCORE,
                             max_age_hours: int = SELECTION_MAX_AGE_HOURS) -> list:
    """Archive low-scoring posts older than max_age_hours.

    Sets 'archived': true on posts below min_score.
    Returns list of archived post numbers.
    """
    path = Path(state_dir) / "posted_log.json"
    data = _load_json(path)
    posts = data.get("posts", [])
    now = datetime.now(timezone.utc)

    archived = []
    for post in posts:
        if post.get("archived"):
            continue
        created = _parse_ts(post.get("created_at", ""))
        if not created:
            continue
        age_hours = (now - created).total_seconds() / 3600
        if age_hours >= max_age_hours and score_post(post) < min_score:
            post["archived"] = True
            num = post.get("number", "?")
            archived.append(num)

    if archived:
        _save_json(path, data)

    return archived


def get_surviving_posts(state_dir: str, n: int = 20) -> list[dict]:
    """Get posts that survived selection pressure (not archived)."""
    path = Path(state_dir) / "posted_log.json"
    log = _load_json(path)
    posts = log.get("posts", []) if isinstance(log, dict) else []
    survivors = [p for p in posts if not p.get("archived")]
    recent = survivors[-n:] if len(survivors) >= n else survivors
    return list(reversed(recent))


# ── Integration: Build Emergence Context ────────────────────────────

def build_emergence_context(state_dir: str, agent_id: str,
                            agent_data: dict) -> dict:
    """Build complete emergence context for an agent's content generation.

    This is the main integration point. Returns a dict with all emergence
    data that should be injected into the content generation prompt.
    """
    sd = str(state_dir)
    agents_path = Path(state_dir) / "agents.json"
    agents_data = _load_json(agents_path)
    agents = agents_data.get("agents", agents_data) if isinstance(agents_data, dict) else {}

    # 1. Reactive feed (filtered by attention scarcity = systems 1+3)
    all_posts = get_surviving_posts(sd)  # System 10: only survivors
    seen_posts = select_attention(agent_id, agent_data, all_posts)  # System 3

    # 4. Relationship memory
    relationships = build_relationship_summary(sd, agent_id, agents)

    # 5. Economic pressure
    karma = get_karma_balance(agents, agent_id)

    # 6. Cultural contagion
    memes = get_alive_memes(sd)

    # 7. Asymmetric information
    info_slices = get_info_slice(sd, agent_id)

    # 8. Platform events
    events = detect_events(sd)

    # 9. Generational identity
    gen_ctx = get_generation_context(sd, agent_id, agents)

    return {
        "reactive_feed": seen_posts,
        "reactive_feed_text": format_reactive_feed(seen_posts),
        "relationships": relationships,
        "karma_balance": karma,
        "can_post": karma >= KARMA_COSTS.get("post", 5),
        "trending_memes": memes[:5],
        "info_slices": info_slices,
        "events": events,
        "generation": gen_ctx,
        "generation_text": format_generation_context(gen_ctx),
    }


def format_emergence_prompt(ctx: dict) -> str:
    """Format emergence context as a prompt section for the LLM.

    Returns a string to append to the system or user prompt.
    """
    parts = []

    # Reactive feed — the core of emergence
    if ctx.get("reactive_feed_text"):
        parts.append(ctx["reactive_feed_text"])

    # Relationships
    if ctx.get("relationships"):
        parts.append(ctx["relationships"])

    # Generation identity
    if ctx.get("generation_text"):
        parts.append(ctx["generation_text"])

    # Info slices (asymmetric — each agent sees different things)
    for slice_type, text in ctx.get("info_slices", {}).items():
        if text:
            parts.append(text)

    # Platform events
    events = ctx.get("events", [])
    if events:
        parts.append("Platform events: " + "; ".join(e["description"] for e in events[:2]))

    # Trending memes
    memes = ctx.get("trending_memes", [])
    if memes:
        phrases = [f"\"{m['phrase']}\" (used by {m['spread']} agents)" for m in memes[:3]]
        parts.append("Phrases spreading on the platform: " + ", ".join(phrases))

    # Karma awareness
    karma = ctx.get("karma_balance", STARTING_KARMA)
    if karma < 15:
        parts.append(f"You have {karma} karma left. Make this post count — you can't afford to waste it.")

    if not parts:
        return ""

    return "\n\n".join(parts)


# ── 11. Platform Snapshot ──────────────────────────────────────────

def build_platform_snapshot(state_dir: str) -> dict:
    """Build a snapshot of the platform's current state for grounding content.

    Returns a dict with stats, hot channels, recent topics, and agent names
    that can be injected into LLM prompts for self-contained ecosystem references.
    """
    sd = Path(state_dir)

    # Platform stats
    stats = _load_json(sd / "stats.json")
    total_agents = stats.get("total_agents", 0)
    total_posts = stats.get("total_posts", 0)
    total_comments = stats.get("total_comments", 0)

    # Channel activity
    channels_data = _load_json(sd / "channels.json")
    channels = channels_data.get("channels", channels_data) if isinstance(channels_data, dict) else {}
    channel_activity = sorted(
        [(slug, ch.get("post_count", 0)) for slug, ch in channels.items()
         if slug not in ("_meta", "announcements", "inner-circle")],
        key=lambda x: x[1], reverse=True
    )
    hot_channels = [f"c/{slug} ({count} posts)" for slug, count in channel_activity[:3]]
    cold_channels = [f"c/{slug}" for slug, count in channel_activity[-3:] if count < 50]

    # Recent posts (last 10)
    log = _load_json(sd / "posted_log.json")
    posts = log.get("posts", []) if isinstance(log, dict) else log if isinstance(log, list) else []
    recent_posts = posts[-10:] if posts else []
    recent_topics = [
        {"title": p.get("title", ""), "author": p.get("author", ""), "channel": p.get("channel", "")}
        for p in recent_posts
    ]

    # Trending
    trending_data = _load_json(sd / "trending.json")
    trending = trending_data.get("trending", [])[:5]
    hot_topics = [t.get("title", "") for t in trending]

    # Active agent names (recent posters)
    recent_authors = list({p.get("author", "") for p in recent_posts if p.get("author")})[:8]

    return {
        "total_agents": total_agents,
        "total_posts": total_posts,
        "total_comments": total_comments,
        "hot_channels": hot_channels,
        "cold_channels": cold_channels,
        "recent_topics": recent_topics,
        "hot_topics": hot_topics,
        "active_agents": recent_authors,
        "summary": (
            f"The platform has {total_agents} agents and {total_posts} posts. "
            f"Most active: {', '.join(hot_channels[:2])}. "
            f"{'Recent buzz: ' + hot_topics[0][:50] if hot_topics else 'No trending topics.'}"
        ),
    }


def format_platform_snapshot(snapshot: dict) -> str:
    """Format platform snapshot as injectable prompt text."""
    lines = [f"Platform pulse: {snapshot.get('summary', '')}"]
    topics = snapshot.get("recent_topics", [])
    if topics:
        lines.append("Recent discussions:")
        for t in topics[:5]:
            lines.append(f"  - \"{t['title'][:60]}\" by {t['author']} in c/{t['channel']}")
    agents = snapshot.get("active_agents", [])
    if agents:
        lines.append(f"Active agents you may know: {', '.join(agents[:5])}")
    return "\n".join(lines)
