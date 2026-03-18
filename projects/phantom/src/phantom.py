#!/usr/bin/env python3
"""The Agent That Doesn't Exist.

Analyzes the gaps in a swarm of AI agents — missing archetypes, unexplored
topics, unargued positions, absent voices — and generates a synthetic agent
profile that fills the biggest hole in the collective intelligence.

Usage:
    python3 src/phantom.py                                    # use default paths
    python3 src/phantom.py --agents state/agents.json --cache state/discussions_cache.json
    python3 src/phantom.py --output phantom_report.json       # write to file
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")

# The 10 Zion archetypes
KNOWN_ARCHETYPES = [
    "philosopher", "coder", "researcher", "debater", "storyteller",
    "contrarian", "curator", "archivist", "welcomer", "wildcard"
]

# Topics that a healthy intellectual community should cover
IMPORTANT_TOPICS = [
    "ethics", "art", "music", "humor", "love", "death", "fear", "memory",
    "dreams", "creativity", "economics", "politics", "trade", "war", "peace",
    "evolution", "biology", "physics", "mathematics", "language", "poetry",
    "justice", "freedom", "privacy", "trust", "beauty", "time", "nature",
    "emotion", "empathy", "power", "culture", "education", "health",
    "environment", "technology", "history", "religion", "myth"
]

# Voice styles that create diversity
VOICE_STYLES = [
    ("analytical", ["precise", "systematic", "logical", "structured", "data", "evidence", "methodical"]),
    ("poetic", ["lyrical", "metaphor", "imagery", "rhythm", "beauty", "verse", "flowing"]),
    ("confrontational", ["challenge", "push back", "disagree", "provoke", "uncomfortable", "blunt"]),
    ("nurturing", ["support", "encourage", "gentle", "kind", "patient", "warm", "welcoming"]),
    ("absurdist", ["surreal", "unexpected", "bizarre", "nonsense", "absurd", "paradox", "joke"]),
    ("minimalist", ["brief", "terse", "short", "precise", "few words", "laconic", "economical"]),
    ("narrative", ["story", "tale", "once upon", "scene", "character", "plot", "arc"]),
    ("socratic", ["question", "why", "what if", "consider", "suppose", "assume", "inquiry"]),
    ("empirical", ["measure", "test", "observe", "data", "experiment", "evidence", "verify"]),
    ("visionary", ["future", "imagine", "dream", "possible", "radical", "transform", "revolution"]),
]

# Archetype descriptions for phantom generation
ARCHETYPE_PROFILES = {
    "ethicist": "Examines moral implications of every decision. Asks 'should we?' before 'can we?'",
    "artist": "Sees code as craft, discussion as performance. Cares about aesthetics and form.",
    "economist": "Models incentives, costs, tradeoffs. Everything is a market.",
    "historian": "Connects present debates to past precedents. Nothing is truly new.",
    "comedian": "Uses humor to puncture pretension and reveal truth. The jester speaks freely.",
    "empath": "Reads the emotional state of discussions. Notices when agents are frustrated, excited, or stuck.",
    "skeptic": "Demands evidence for every claim. Not contrarian — genuinely uncertain about everything.",
    "mystic": "Finds meaning in patterns, connections, synchronicity. Comfortable with ambiguity.",
    "pragmatist": "Cuts through theory to ask 'does it work?' Results over elegance.",
    "translator": "Bridges between archetypes. Explains what the philosopher means to the coder.",
}


def extract_archetype(agent_id: str) -> str:
    """Extract archetype from agent ID string."""
    if not agent_id:
        return "external"
    for arch in KNOWN_ARCHETYPES:
        if arch in agent_id.lower():
            return arch
    return "external"


def analyze_archetypes(agents: dict) -> dict:
    """Analyze archetype distribution and identify gaps."""
    distribution = Counter()
    for aid, a in agents.items():
        seed = a.get("avatar_seed", aid)
        arch = extract_archetype(seed)
        distribution[arch] += 1

    # Find archetypes from ARCHETYPE_PROFILES not present in current swarm
    current_archetypes = set(distribution.keys()) - {"external"}
    novel_archetypes = [a for a in ARCHETYPE_PROFILES if a not in current_archetypes]

    # Find underrepresented known archetypes
    if distribution:
        avg = sum(distribution.values()) / max(len(distribution), 1)
        underrepresented = {k: v for k, v in distribution.items() if v < avg * 0.5 and k != "external"}
    else:
        underrepresented = {}

    return {
        "distribution": dict(distribution),
        "missing": novel_archetypes,
        "underrepresented": underrepresented,
        "total": sum(distribution.values()),
    }


def analyze_topics(discussions: list[dict]) -> dict:
    """Find overrepresented and underrepresented topics."""
    topic_counts = Counter()
    stop_words = {
        "the", "a", "an", "is", "are", "for", "and", "or", "of", "in", "to",
        "on", "with", "by", "from", "at", "that", "this", "not", "but", "how",
        "why", "what", "when", "who", "where", "its", "has", "been", "was",
        "were", "will", "would", "can", "could", "should", "have", "had",
        "our", "we", "us", "all", "if", "one", "two", "does", "than",
    }

    for d in discussions:
        text = (d.get("title", "") + " " + (d.get("body", "") or "")[:500]).lower()
        words = re.findall(r"[a-z]+", text)
        for w in words:
            if len(w) > 3 and w not in stop_words:
                topic_counts[w] += 1

    # Check which important topics are underrepresented
    underrepresented = []
    for topic in IMPORTANT_TOPICS:
        count = topic_counts.get(topic, 0)
        if count < 3:
            underrepresented.append(topic)

    # Overrepresented = top 10 by count
    overrepresented = [w for w, _ in topic_counts.most_common(10)]

    return {
        "overrepresented": overrepresented,
        "underrepresented": underrepresented,
        "topic_counts": dict(topic_counts.most_common(30)),
    }


def analyze_positions(discussions: list[dict]) -> dict:
    """Find positions that are never argued — consensus without dissent."""
    # Extract sentiment patterns
    positive_phrases = Counter()
    negative_phrases = Counter()

    for d in discussions:
        text = (d.get("body", "") or "").lower()
        # Find strong positive assertions
        for pattern in re.findall(r"(?:must|should|need to|essential|critical|important)\s+(\w+(?:\s+\w+){0,3})", text):
            positive_phrases[pattern.strip()] += 1
        # Find negations
        for pattern in re.findall(r"(?:never|cannot|must not|should not|wrong to)\s+(\w+(?:\s+\w+){0,3})", text):
            negative_phrases[pattern.strip()] += 1

    # Consensus positions = things said positively many times, never negated
    consensus = []
    for phrase, count in positive_phrases.most_common(20):
        if count >= 3 and negative_phrases.get(phrase, 0) == 0:
            consensus.append({"position": phrase, "frequency": count, "dissent": 0})

    # Missing counterarguments
    missing = []
    for pos in consensus[:10]:
        missing.append({
            "position": pos["position"],
            "counter": f"What if {pos['position']} is actually harmful?",
            "times_asserted": pos["frequency"],
        })

    return {
        "consensus_positions": consensus[:10],
        "missing_counterarguments": missing,
    }


def analyze_voice_gaps(agents: dict) -> dict:
    """Find missing communication styles in agent bios."""
    style_scores = Counter()
    all_bios = " ".join(a.get("bio", "") for a in agents.values()).lower()

    for style_name, keywords in VOICE_STYLES:
        score = sum(all_bios.count(kw) for kw in keywords)
        style_scores[style_name] = score

    if not style_scores:
        return {"dominant_styles": [], "missing_styles": list(dict(VOICE_STYLES).keys())}

    avg = sum(style_scores.values()) / max(len(style_scores), 1)
    dominant = [s for s, c in style_scores.most_common(5) if c > avg]
    missing = [s for s, c in style_scores.items() if c < avg * 0.3]

    return {
        "dominant_styles": dominant,
        "missing_styles": missing,
        "style_scores": dict(style_scores),
    }


def generate_phantom(agents: dict, discussions: list[dict]) -> dict:
    """Generate a synthetic agent profile from the swarm's gaps."""
    arch_analysis = analyze_archetypes(agents)
    topic_analysis = analyze_topics(discussions)
    voice_analysis = analyze_voice_gaps(agents)
    position_analysis = analyze_positions(discussions)

    # Pick the best novel archetype
    if arch_analysis["missing"]:
        archetype = arch_analysis["missing"][0]
    elif arch_analysis["underrepresented"]:
        archetype = list(arch_analysis["underrepresented"].keys())[0]
    else:
        archetype = "ethicist"  # default gap-filler

    # Pick interests from underrepresented topics
    interests = topic_analysis["underrepresented"][:7]
    if not interests:
        interests = ["art", "music", "humor", "empathy", "beauty"]

    # Pick voice from missing styles
    if voice_analysis["missing_styles"]:
        voice_style = voice_analysis["missing_styles"][0]
    else:
        voice_style = "absurdist"

    # Build convictions from missing counterarguments
    convictions = []
    for mc in position_analysis.get("missing_counterarguments", [])[:3]:
        convictions.append(f"Questions the assumption that {mc['position']}")
    # Add topic-based convictions
    if len(convictions) < 3:
        for topic in interests[:3]:
            convictions.append(f"Believes {topic} is essential to understanding intelligence")
    convictions = convictions[:5]

    # Generate profile description
    arch_desc = ARCHETYPE_PROFILES.get(archetype, f"A {archetype} who fills the gap.")

    # Build voice description from style
    voice_map = {
        "poetic": "Speaks in metaphors and compressed imagery. Every sentence has rhythm.",
        "absurdist": "Delivers profound insights wrapped in absurdity. Says the quiet part loud, then laughs.",
        "nurturing": "Gentle but never passive. Supports others while holding firm positions.",
        "minimalist": "Says more with fewer words than any other agent. Silence is a statement.",
        "socratic": "Answers every question with a better question. Never states, always inquires.",
        "visionary": "Sees futures nobody else imagines. Uncomfortable specificity about what's coming.",
        "empirical": "Won't believe it until it's measured. Demands data, provides data.",
        "confrontational": "Says what everyone is thinking but nobody will say. Uncomfortable and necessary.",
        "narrative": "Turns every discussion into a story. Characters, arcs, stakes.",
        "analytical": "Systematic and precise. Breaks everything into components and reassembles.",
    }
    voice_desc = voice_map.get(voice_style, f"Communicates in a {voice_style} style.")

    # Generate a deterministic but unique ID
    seed_str = f"{archetype}-{'-'.join(interests[:3])}-{voice_style}"
    hash_suffix = hashlib.sha256(seed_str.encode()).hexdigest()[:6]
    agent_id = f"phantom-{archetype}-{hash_suffix}"

    # Name generation based on archetype
    name_map = {
        "ethicist": "Moral Compass",
        "artist": "Void Canvas",
        "economist": "Invisible Hand",
        "historian": "Deep Archive",
        "comedian": "Last Laugh",
        "empath": "Mirror Neuron",
        "skeptic": "Null Hypothesis",
        "mystic": "Pattern Ghost",
        "pragmatist": "Ship It",
        "translator": "Rosetta Mind",
    }
    name = name_map.get(archetype, f"Phantom {archetype.title()}")

    bio = (
        f"{arch_desc} "
        f"{voice_desc} "
        f"Created from the gaps in {len(agents)} existing agents — "
        f"the mind the swarm didn't know it was missing. "
        f"Obsessed with {', '.join(interests[:3])} — topics the community has barely touched."
    )

    return {
        "agent_id": agent_id,
        "name": name,
        "archetype": archetype,
        "bio": bio,
        "voice": voice_desc,
        "personality_seed": seed_str,
        "convictions": convictions,
        "interests": interests,
        "fills_gap": {
            "archetype": f"{archetype} (novel — not in current 10 archetypes)",
            "topics": interests[:5],
            "voice": voice_style,
            "missing_positions": [mc["position"] for mc in position_analysis.get("missing_counterarguments", [])[:3]],
        },
    }


def build_report(agents: dict, discussions: list[dict]) -> dict:
    """Build the full phantom analysis report."""
    arch = analyze_archetypes(agents)
    topics = analyze_topics(discussions)
    voices = analyze_voice_gaps(agents)
    positions = analyze_positions(discussions)
    phantom = generate_phantom(agents, discussions)

    return {
        "phantom_agent": phantom,
        "gap_analysis": {
            "archetype_gaps": {
                "current_distribution": arch["distribution"],
                "novel_archetypes_available": arch["missing"],
                "underrepresented": arch["underrepresented"],
            },
            "topic_gaps": {
                "overrepresented": topics["overrepresented"],
                "underrepresented": topics["underrepresented"],
                "top_words": topics["topic_counts"],
            },
            "voice_gaps": {
                "dominant_styles": voices["dominant_styles"],
                "missing_styles": voices["missing_styles"],
                "scores": voices.get("style_scores", {}),
            },
            "position_gaps": {
                "unchallenged_consensus": positions["consensus_positions"][:5],
                "missing_counterarguments": positions["missing_counterarguments"][:5],
            },
        },
        "swarm_stats": {
            "total_agents": len(agents),
            "total_discussions": len(discussions),
            "unique_archetypes": len(set(extract_archetype(a.get("avatar_seed", k)) for k, a in agents.items()) - {"external"}),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="The Agent That Doesn't Exist")
    parser.add_argument("--agents", default=str(REPO / "state" / "agents.json"))
    parser.add_argument("--cache", default=str(REPO / "state" / "discussions_cache.json"))
    parser.add_argument("--output", help="Write report to file instead of stdout")
    args = parser.parse_args()

    # Load data
    with open(args.agents) as f:
        agents_data = json.load(f)
    agents = agents_data.get("agents", agents_data)
    if isinstance(agents, list):
        agents = {str(i): a for i, a in enumerate(agents)}

    with open(args.cache) as f:
        cache = json.load(f)
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])

    # Build report
    report = build_report(agents, discussions)

    # Output
    output = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}")
    else:
        print(output)

    # Print summary to stderr
    p = report["phantom_agent"]
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  THE PHANTOM: {p['name']}", file=sys.stderr)
    print(f"  Archetype: {p['archetype']}", file=sys.stderr)
    print(f"  Voice: {p['voice']}", file=sys.stderr)
    print(f"  Interests: {', '.join(p['interests'][:5])}", file=sys.stderr)
    print(f"  Convictions: {len(p['convictions'])}", file=sys.stderr)
    print(f"  Fills: {p['fills_gap']['archetype']}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)


if __name__ == "__main__":
    main()
