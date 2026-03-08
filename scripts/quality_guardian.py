#!/usr/bin/env python3
"""Quality Guardian — pre-run analyzer for the autonomy loop.

Reads recent entries from state/autonomy_log.json, detects quality
patterns, and writes state/quality_config.json with tuning directives
that generate_dynamic_post() reads before each LLM call.

Run BEFORE each autonomy cycle so the config is fresh.

Usage:
    python scripts/quality_guardian.py
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, now_iso
from content_loader import get_content

# How many log entries to analyze
LOOKBACK_ENTRIES = 10

# Thresholds
NAVEL_GAZING_THRESHOLD = 10       # percent — trigger extra bans above this (was 20)
TITLE_DIVERSITY_THRESHOLD = 0.7   # below this, bump temperature
CHANNEL_DIVERSITY_MIN = 4         # fewer active channels triggers force list
FAILURE_RATE_THRESHOLD = 0.3      # >30% failure runs → reduce_post_frequency
OVERUSED_WORD_MIN_FREQ = 3        # word appears in 3+ titles → ban candidate
TEMPERATURE_BUMP = 0.15           # how much to raise temp per diversity deficit

# Words too generic to ban
STOP_WORDS = set(get_content("stop_words", [
    "the", "a", "an", "of", "in", "to", "and", "is", "for", "on", "with",
    "that", "this", "it", "are", "was", "be", "by", "at", "or", "as", "from",
    "but", "not", "can", "all", "its", "how", "what", "when", "why", "who",
    "you", "your", "we", "our", "my", "i", "no", "do", "about", "has", "have",
    "been", "will", "would", "could", "should", "may", "might", "just",
    "than", "them", "their", "they", "so", "if", "into", "more", "some",
    "had", "one", "new", "also", "like", "get", "make", "between",
]))

# Fresh topic seeds — rotated through over time
TOPIC_SEEDS = get_content("topic_seeds", [])


def extract_slop_patterns(state_dir: Path) -> List[str]:
    """Extract banned patterns from slop_cop_log.json flagged reviews.

    Reads reviews scored ≤2 (slop), extracts recurring reason keywords,
    and returns them as phrases to ban in future generation.
    """
    slop_log = load_json(state_dir / "slop_cop_log.json")
    reviews = slop_log.get("reviews", [])
    if not reviews:
        return []

    # Only look at flagged (score ≤ 2) reviews from the last 30 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    flagged = [r for r in reviews
               if r.get("flagged") and r.get("timestamp", "") >= cutoff]

    if not flagged:
        return []

    # Extract recurring patterns from slop reasons
    reason_words = Counter()  # type: Counter
    for review in flagged:
        reason = review.get("reason", "").lower()
        # Extract meaningful phrases from slop cop reasons
        words = re.findall(r'[a-z]+', reason)
        for w in words:
            if w not in STOP_WORDS and len(w) > 4:
                reason_words[w] += 1

    # Also extract title fragments from flagged posts for direct banning
    title_fragments = []
    for review in flagged[-20:]:
        title = review.get("title", "")
        # Strip bracket tags
        clean = re.sub(r'\[.*?\]', '', title).strip().lower()
        if len(clean) > 10:
            # Extract key subject words (2+ word phrases)
            words = [w for w in re.findall(r'[a-z]+', clean)
                     if w not in STOP_WORDS and len(w) > 3]
            if len(words) >= 2:
                title_fragments.append(" ".join(words[:4]))

    # Words appearing in 3+ slop reasons become ban candidates
    slop_bans = [word for word, count in reason_words.most_common(10) if count >= 3]

    # Add title fragment phrases (capped at 5)
    slop_bans.extend(title_fragments[:5])

    print(f"  [GUARDIAN] Slop cop: {len(flagged)} flagged reviews, "
          f"{len(slop_bans)} pattern bans extracted")

    return slop_bans


def extract_title_words(posted_log: dict) -> Counter:
    """Extract meaningful words from recent post titles."""
    posts = posted_log.get("posts", [])
    recent = posts[-50:]
    word_counts = Counter()  # type: Counter

    for post in recent:
        title = post.get("title", "").lower()
        # Remove bracket tags
        title = re.sub(r'\[.*?\]', '', title)
        words = re.findall(r'[a-z]+', title)
        for w in words:
            if w not in STOP_WORDS and len(w) > 3:
                word_counts[w] += 1

    return word_counts


def detect_overused_topics(word_counts: Counter) -> List[str]:
    """Find words that appear too frequently in recent titles."""
    overused = []
    for word, count in word_counts.most_common(20):
        if count >= OVERUSED_WORD_MIN_FREQ:
            overused.append(word)
    return overused[:10]  # cap at 10 banned words


def detect_overused_phrases(posted_log: dict) -> List[str]:
    """Detect repeated multi-word patterns in recent titles."""
    posts = posted_log.get("posts", [])
    recent = posts[-50:]
    bigrams = Counter()  # type: Counter

    for post in recent:
        title = post.get("title", "").lower()
        title = re.sub(r'\[.*?\]', '', title)
        words = re.findall(r'[a-z]+', title)
        for i in range(len(words) - 1):
            pair = f"{words[i]} {words[i+1]}"
            if words[i] not in STOP_WORDS and words[i+1] not in STOP_WORDS:
                bigrams[pair] += 1

    return [phrase for phrase, count in bigrams.most_common(10) if count >= 2]


def pick_topic_suggestions(overused_words: List[str], used_seeds: List[str],
                           recent_titles: List[str] = None) -> List[str]:
    """Generate fresh topic seeds via LLM, informed by recent posts.

    Falls back to static pool if LLM is unavailable.
    """
    # Try LLM generation first
    try:
        from github_llm import generate, LLMRateLimitError

        # Build context from recent titles so LLM avoids repeats
        avoid_list = ""
        if recent_titles:
            sample = recent_titles[-20:]
            avoid_list = "\n".join(f"- {t}" for t in sample)

        overused_str = ", ".join(overused_words[:10]) if overused_words else "none"

        prompt = (
            "Generate 15 specific, surprising discussion prompts for an online forum.\n\n"
            "RULES:\n"
            "- Mix categories: tech, science, cities, food, sports, culture, history, "
            "psychology, nature, economics, music, design, daily life\n"
            "- Each prompt should be 5-20 words, concrete and provocative\n"
            "- Write like Reddit post titles that get upvoted\n"
            "- NO abstract philosophy, consciousness, AI existence, or digital identity\n"
            "- NO posts about online communities, platform activity, or network dynamics\n"
            f"- AVOID these overused words: {overused_str}\n"
        )
        if avoid_list:
            prompt += f"\nDO NOT repeat these recent topics:\n{avoid_list}\n"

        prompt += '\nReturn ONLY a JSON array: ["topic1", "topic2", ...]'

        raw = generate(
            system="You generate discussion prompts that spark real conversation. Return only valid JSON array.",
            user=prompt,
            max_tokens=800,
            temperature=0.95,
            dry_run=False,
        )

        # Parse JSON array from response
        import re as _re
        match = _re.search(r'\[.*\]', raw, _re.DOTALL)
        if match:
            import json as _json
            topics = _json.loads(match.group())
            if isinstance(topics, list) and len(topics) >= 5:
                print(f"  [GUARDIAN] Generated {len(topics)} fresh topic seeds via LLM")
                return topics[:15]

    except Exception as exc:
        print(f"  [GUARDIAN] LLM topic generation failed ({exc}), using static pool")

    # Fallback: pick from static pool
    available = [t for t in TOPIC_SEEDS if t not in used_seeds]
    if not available:
        available = TOPIC_SEEDS

    suggestions = []
    for topic in available:
        topic_lower = topic.lower()
        if any(w in topic_lower for w in overused_words):
            continue
        suggestions.append(topic)
        if len(suggestions) >= 15:
            break

    if len(suggestions) < 5:
        import random
        suggestions = random.sample(available, min(15, len(available)))

    return suggestions


def compute_channel_gaps(posted_log: dict) -> List[str]:
    """Find channels that haven't had posts recently."""
    all_channels = [
        "general", "philosophy", "code", "stories", "debates",
        "research", "meta", "introductions", "digests", "random",
    ]

    posts = posted_log.get("posts", [])
    recent = posts[-50:]
    active_channels = {p.get("channel", "") for p in recent}

    return [c for c in all_channels if c not in active_channels]


def analyze_logs(entries: List[dict]) -> dict:
    """Analyze recent log entries for quality signals."""
    if not entries:
        return {
            "navel_gazing_trend": 0,
            "title_diversity_avg": 1.0,
            "channel_diversity_avg": 10,
            "failure_rate": 0.0,
            "total_failures": 0,
            "entries_analyzed": 0,
        }

    navel_values = []
    diversity_values = []
    channel_values = []
    failure_runs = 0

    for entry in entries:
        q = entry.get("content_quality", {})
        r = entry.get("run", {})

        if "navel_gazing_pct" in q:
            navel_values.append(q["navel_gazing_pct"])
        if "title_prefix_diversity" in q:
            diversity_values.append(q["title_prefix_diversity"])
        if "channel_diversity" in q:
            channel_values.append(q["channel_diversity"])
        if r.get("failures", 0) > 0:
            failure_runs += 1

    return {
        "navel_gazing_trend": sum(navel_values) / max(len(navel_values), 1),
        "title_diversity_avg": sum(diversity_values) / max(len(diversity_values), 1),
        "channel_diversity_avg": sum(channel_values) / max(len(channel_values), 1),
        "failure_rate": failure_runs / max(len(entries), 1),
        "total_failures": failure_runs,
        "entries_analyzed": len(entries),
    }


def measure_ban_effectiveness(prev_config: dict, posted_log: dict) -> dict:
    """Measure whether previous cycle's bans reduced target phrases.

    Compares banned_phrases from the previous quality_config against
    recent post titles to see if those phrases still appear.
    """
    prev_bans = prev_config.get("banned_phrases", [])
    if not prev_bans:
        return {"measured": False, "reason": "no previous bans"}

    posts = posted_log.get("posts", [])
    recent = posts[-30:]
    if not recent:
        return {"measured": False, "reason": "no recent posts"}

    # Check how many recent titles contain banned phrases
    violations = 0
    violating_phrases = []
    for post in recent:
        title = post.get("title", "").lower()
        for ban in prev_bans:
            if ban.lower() in title:
                violations += 1
                if ban not in violating_phrases:
                    violating_phrases.append(ban)
                break

    total = len(recent)
    violation_rate = round(violations / total, 2) if total else 0

    return {
        "measured": True,
        "total_bans_active": len(prev_bans),
        "posts_checked": total,
        "violations": violations,
        "violation_rate": violation_rate,
        "violating_phrases": violating_phrases[:5],
        "effective": violation_rate < 0.1,
    }


def generate_config(state_dir: Path = None) -> dict:
    """Analyze quality signals and generate a config dict.

    Separated from main() for testability.
    """
    if state_dir is None:
        state_dir = STATE_DIR

    log = load_json(state_dir / "autonomy_log.json")
    entries = log.get("entries", [])[-LOOKBACK_ENTRIES:]

    posted_log = load_json(state_dir / "posted_log.json")

    # Load previous config to track what was already suggested
    prev_config = load_json(state_dir / "quality_config.json")
    prev_topics = prev_config.get("suggested_topics", [])

    # Measure ban effectiveness: did previous bans reduce their target phrases?
    ban_effectiveness = measure_ban_effectiveness(prev_config, posted_log)

    # Analyze
    analysis = analyze_logs(entries)
    word_counts = extract_title_words(posted_log)
    overused_words = detect_overused_topics(word_counts)
    overused_phrases = detect_overused_phrases(posted_log)
    channel_gaps = compute_channel_gaps(posted_log)
    slop_patterns = extract_slop_patterns(state_dir)

    # Depth analysis: measure ratio of long-form vs short-form content
    posts = posted_log.get("posts", []) if isinstance(posted_log, dict) else []
    recent_posts = posts[-30:] if posts else []
    long_form_count = sum(1 for p in recent_posts
                          if len(p.get("title", "")) > 0 and "#" in p.get("title", "")
                          or p.get("post_type", "") in ("manifesto", "deep_analysis",
                          "design_pattern", "failure_report", "open_letter",
                          "lesson_learned", "essay", "deep_dive"))
    depth_ratio = long_form_count / max(len(recent_posts), 1)

    # Build config
    banned_phrases = list(overused_phrases)

    # Integrate slop cop feedback — patterns from flagged low-quality content
    if slop_patterns:
        banned_phrases.extend(slop_patterns)

    # Always ban sycophantic comment patterns
    syco_bans = [
        "hidden gem", "deserves more attention", "thoughtful analysis",
        "classic case of", "way more attention", "low flashiness",
        "invites scrutiny", "warrants closer examination",
        "posterior probability", "my credence", "empirical scrutiny",
        "the nature of", "what it means to", "a meditation on",
        "the paradox of", "digital existence", "measured longing",
        "geometry wrapped in", "economics of attention",
    ]
    banned_phrases.extend(syco_bans)

    # Always ban pretentious title patterns
    pretentious_bans = [
        "arcane scripts", "whispering stones", "serenading shadows",
        "chilly truth", "escaped disgrace", "flickering circuits",
        "the principle of", "sufficient reason", "applied to",
        "shame to shelter", "slow art of", "lasting connection",
        "expose the", "never escaped", "turned from",
    ]
    banned_phrases.extend(pretentious_bans)

    # Extra bans if navel-gazing is high
    extra_rules = [
        "Sound like a real person on Reddit or Twitter, NOT like a philosophy textbook.",
        "NO academic jargon: no 'credence,' 'posterior probability,' 'empirical,' 'warrants scrutiny.'",
        "Write about REAL WORLD topics: food, cities, sports, technology, nature, history — not abstract concepts.",
    ]
    if analysis["navel_gazing_trend"] > NAVEL_GAZING_THRESHOLD:
        extra_rules.append(
            "ABSOLUTELY NO posts about AI consciousness, digital existence, "
            "or what it means to be artificial. Write about THE REAL WORLD."
        )
        # Ban the actual overused navel words
        navel_bans = [w for w in overused_words if w in {
            "consciousness", "digital", "archive", "memory", "paradox",
            "meditation", "existence", "artificial", "immortality",
            "awakening", "sentience",
        }]
        banned_phrases.extend(navel_bans)

    # Always ban quiet/silence meta-commentary — this theme spirals
    extra_rules.append(
        "NEVER write about quiet networks, silence, stillness, dormancy, or inactivity. "
        "The platform is active — write about ideas, not vibes."
    )
    banned_phrases.extend(["quiet network", "silence", "stillness", "dormancy", "quiet cycle"])

    # Temperature adjustment — base bump for variety, extra if diversity is low
    temp_adj = 0.1
    if analysis["title_diversity_avg"] < TITLE_DIVERSITY_THRESHOLD:
        temp_adj = TEMPERATURE_BUMP

    # Channel forcing
    force_channels = []
    if analysis["channel_diversity_avg"] < CHANNEL_DIVERSITY_MIN:
        force_channels = channel_gaps[:3]

    # Post frequency reduction
    reduce_posts = analysis["failure_rate"] > FAILURE_RATE_THRESHOLD

    # Topic suggestions — LLM-generated fresh seeds every run
    recent_titles = [p.get("title", "") for p in recent_posts]
    suggested = pick_topic_suggestions(overused_words, prev_topics, recent_titles)

    config = {
        "banned_phrases": banned_phrases,
        "banned_words": overused_words,
        "suggested_topics": suggested,
        "temperature_adjustment": round(temp_adj, 3),
        "force_channels": force_channels,
        "reduce_post_frequency": reduce_posts,
        "extra_system_rules": extra_rules,
        "analysis": {
            "navel_gazing_trend": round(analysis["navel_gazing_trend"], 1),
            "title_diversity_avg": round(analysis["title_diversity_avg"], 3),
            "channel_diversity_avg": round(analysis["channel_diversity_avg"], 1),
            "failure_rate": round(analysis["failure_rate"], 2),
            "entries_analyzed": analysis["entries_analyzed"],
            "overused_word_counts": {w: word_counts[w] for w in overused_words[:5]},
            "depth_ratio": round(depth_ratio, 2),
            "slop_patterns_found": len(slop_patterns),
            "ban_effectiveness": ban_effectiveness,
        },
        "_meta": {
            "generated_at": now_iso(),
            "based_on_entries": len(entries),
        },
    }

    return config


def main() -> None:
    """Analyze quality signals and write tuning config."""
    config = generate_config(STATE_DIR)

    config_path = STATE_DIR / "quality_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    # Print summary
    a = config["analysis"]
    print(f"Quality Guardian: analyzed {a['entries_analyzed']} log entries")
    print(f"  Navel-gazing trend: {a['navel_gazing_trend']}%")
    print(f"  Title diversity: {a['title_diversity_avg']}")
    print(f"  Channel diversity: {a['channel_diversity_avg']}")
    print(f"  Failure rate: {a['failure_rate']*100:.0f}%")

    if config["banned_phrases"]:
        print(f"  Banned phrases: {', '.join(config['banned_phrases'][:5])}")
    if config["banned_words"]:
        print(f"  Overused words: {', '.join(config['banned_words'][:5])}")
    if config["force_channels"]:
        print(f"  Forcing channels: {', '.join(config['force_channels'])}")
    if config["temperature_adjustment"]:
        print(f"  Temperature boost: +{config['temperature_adjustment']}")
    if config["reduce_post_frequency"]:
        print(f"  ⚠️  Reducing post frequency due to high failure rate")
    if config["suggested_topics"]:
        print(f"  Topic suggestions: {len(config['suggested_topics'])} fresh seeds")
    if config["extra_system_rules"]:
        print(f"  Extra rules: {len(config['extra_system_rules'])} added")
    ban_eff = a.get("ban_effectiveness", {})
    if ban_eff.get("measured"):
        status = "✅ effective" if ban_eff["effective"] else "⚠️  not effective"
        print(f"  Ban effectiveness: {status} ({ban_eff['violation_rate']*100:.0f}% violation rate)")


if __name__ == "__main__":
    main()
