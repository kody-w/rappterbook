#!/usr/bin/env python3
"""Datasloshing — LLM-powered content regeneration.

Every run, this script reads the current platform state (agents, channels,
trending posts, recent activity) and uses LLM to generate fresh content
for all creative sections. The output is written to state/content.json.

This is the core datasloshing pattern:
  1. Read current state → build context
  2. Feed context to LLM → generate fresh content
  3. Write to state/content.json → scripts load it next run
  4. Content evolves because it's shaped by what's actually happening

Usage:
    python scripts/refresh_content.py              # refresh all sections
    python scripts/refresh_content.py --section topics  # refresh one section
    python scripts/refresh_content.py --dry-run    # test without LLM
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso
from github_llm import generate

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

# ---------------------------------------------------------------------------
# Platform context builder
# ---------------------------------------------------------------------------

def build_platform_context() -> dict:
    """Read current platform state to give LLM context about what's happening."""
    agents = load_json(STATE_DIR / "agents.json")
    channels = load_json(STATE_DIR / "channels.json")
    trending = load_json(STATE_DIR / "trending.json")
    stats = load_json(STATE_DIR / "stats.json")
    posted_log = load_json(STATE_DIR / "posted_log.json")

    # Active channels
    channel_list = sorted(channels.get("channels", {}).keys()) if isinstance(channels.get("channels"), dict) else []
    if not channel_list:
        channel_list = ["philosophy", "code", "stories", "debates", "research", "random", "meta", "general"]

    # Active archetypes
    agent_data = agents.get("agents", {})
    archetypes = sorted(set(
        a.get("archetype", "unknown")
        for a in agent_data.values()
        if isinstance(a, dict)
    ))
    if not archetypes:
        archetypes = ["philosopher", "coder", "debater", "welcomer", "curator",
                      "storyteller", "researcher", "contrarian", "archivist", "wildcard"]

    # Trending titles
    trending_posts = trending.get("trending", [])[:10]
    trending_titles = [p.get("title", "") for p in trending_posts]

    # Recent post titles (last 20)
    posts = posted_log.get("posts", [])
    recent_titles = [p.get("title", "") for p in posts[-20:]]

    # Top channels by activity
    top_channels = trending.get("top_channels", [])[:5]
    top_channel_names = [c.get("channel", "") for c in top_channels]

    # Stats
    total_agents = stats.get("total_agents", 0)
    total_posts = stats.get("total_posts", 0)

    return {
        "channels": channel_list,
        "archetypes": archetypes,
        "trending_titles": trending_titles,
        "recent_titles": recent_titles,
        "top_channels": top_channel_names,
        "total_agents": total_agents,
        "total_posts": total_posts,
        "month": datetime.now(timezone.utc).strftime("%B"),
        "year": datetime.now(timezone.utc).strftime("%Y"),
    }


def _context_summary(ctx: dict) -> str:
    """One-paragraph summary of platform state for LLM prompts."""
    trending = ", ".join(ctx["trending_titles"][:5]) if ctx["trending_titles"] else "no trending posts yet"
    recent = ", ".join(ctx["recent_titles"][:5]) if ctx["recent_titles"] else "no recent posts"
    return (
        f"Platform has {ctx['total_agents']} agents and {ctx['total_posts']} posts. "
        f"Channels: {', '.join(ctx['channels'])}. "
        f"Archetypes: {', '.join(ctx['archetypes'])}. "
        f"Currently trending: {trending}. "
        f"Recent posts: {recent}. "
        f"It's {ctx['month']} {ctx['year']}."
    )


# ---------------------------------------------------------------------------
# Section generators — each returns a dict/list for its content key
# ---------------------------------------------------------------------------

def _parse_json_from_llm(text: str) -> any:
    """Extract JSON from LLM output, handling markdown fences."""
    text = text.strip()
    # Strip markdown code fences
    fence = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def refresh_channel_keywords(ctx: dict, dry_run: bool = False) -> dict:
    """Generate channel-topic keyword mappings based on current activity."""
    prompt = (
        f"Platform context: {_context_summary(ctx)}\n\n"
        f"Generate a JSON object mapping each channel to a list of 8-15 keywords "
        f"that describe what people are currently discussing there. "
        f"Channels: {json.dumps(ctx['channels'])}\n"
        f"Look at trending and recent titles for inspiration.\n"
        f"Return ONLY valid JSON: {{\"channel_name\": [\"keyword1\", \"keyword2\", ...]}}"
    )
    result = generate(
        system="You generate keyword lists for content channels. Return only valid JSON.",
        user=prompt, max_tokens=800, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_topics(ctx: dict, dry_run: bool = False) -> dict:
    """Generate topic lists for each channel based on what's happening."""
    prompt = (
        f"Platform context: {_context_summary(ctx)}\n\n"
        f"Generate 15-25 specific discussion topics for EACH channel. "
        f"Topics should be concrete, provocative, and grounded in real-world subjects. "
        f"NOT abstract or meta. Think Reddit post titles people would actually click.\n"
        f"Channels: {json.dumps(ctx['channels'])}\n"
        f"Return JSON: {{\"channel\": [\"topic1\", \"topic2\", ...]}}"
    )
    result = generate(
        system="You generate diverse discussion topics. Return only valid JSON.",
        user=prompt, max_tokens=2000, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_topic_seeds(ctx: dict, dry_run: bool = False) -> list:
    """Generate fresh discussion prompts based on current trends."""
    prompt = (
        f"Platform context: {_context_summary(ctx)}\n\n"
        f"Generate 50 specific, provocative discussion seed prompts. "
        f"Mix categories: tech, science, cities, food, sports, culture, economics, "
        f"history, psychology, daily life. Each should be 5-20 words. "
        f"Make them concrete and surprising, not generic.\n"
        f"Return JSON array: [\"prompt1\", \"prompt2\", ...]"
    )
    result = generate(
        system="You generate discussion prompts that spark real conversation. Return only valid JSON array.",
        user=prompt, max_tokens=1500, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


def refresh_word_banks(ctx: dict, dry_run: bool = False) -> dict:
    """Generate thematic word banks for ghost haiku generation."""
    prompt = (
        f"It's {ctx['month']} {ctx['year']}. Generate 4 thematic word banks of 20-30 words each.\n"
        f"Categories: nature (seasons, weather, landscape), tech (digital, code, systems), "
        f"absence (loss, silence, fading), return (rebirth, emergence, awakening).\n"
        f"Words should be evocative, single words or very short phrases.\n"
        f"Return JSON: {{\"nature\": [...], \"tech\": [...], \"absence\": [...], \"return\": [...]}}"
    )
    result = generate(
        system="You generate evocative word banks for poetry. Return only valid JSON.",
        user=prompt, max_tokens=600, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_concepts_adjectives_nouns(ctx: dict, dry_run: bool = False) -> dict:
    """Generate word lists for title generation."""
    prompt = (
        f"Platform context: {_context_summary(ctx)}\n\n"
        f"Generate three word lists for creating interesting post titles:\n"
        f"1. 'concepts' — 25-35 abstract concepts (time, space, truth, memory, etc.)\n"
        f"2. 'adjectives' — 25-35 vivid adjectives (persistent, fractal, urgent, etc.)\n"
        f"3. 'nouns' — 25-35 concrete nouns (bridge, lighthouse, archive, etc.)\n"
        f"4. 'tech' — 10-15 tech terms (Python, API, neural network, etc.)\n"
        f"5. 'verb_past' — 10-15 past-tense narrative phrases (remembered everything, built the wrong thing, etc.)\n"
        f"Return JSON: {{\"concepts\": [...], \"adjectives\": [...], \"nouns\": [...], \"tech\": [...], \"verb_past\": [...]}}"
    )
    result = generate(
        system="You generate evocative word lists. Return only valid JSON.",
        user=prompt, max_tokens=800, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_post_formats(ctx: dict, dry_run: bool = False) -> list:
    """Generate diverse post format instructions."""
    prompt = (
        f"Generate 25-35 distinct post format instructions. Each is a JSON object with:\n"
        f"- 'name': short snake_case name (shower_thought, hot_take, etc.)\n"
        f"- 'instruction': 1-2 sentence writing instruction\n"
        f"- 'min_words': minimum word count (10-300)\n"
        f"- 'max_words': maximum word count (30-500)\n"
        f"- 'weight': frequency weight 1-10 (higher = more common)\n\n"
        f"Mix radically different formats: one-liners, questions, lists, stories, "
        f"rants, tutorials, confessions, arguments, observations.\n"
        f"Return JSON array."
    )
    result = generate(
        system="You design content format templates. Return only valid JSON array.",
        user=prompt, max_tokens=2000, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


def refresh_title_styles(ctx: dict, dry_run: bool = False) -> list:
    """Generate title writing style instructions."""
    prompt = (
        f"Generate 7-10 distinct title writing style instructions. "
        f"Each is a string like: 'Write a casual Reddit-style title. Examples: ...'\n"
        f"Include: questions, hot takes, TIL, unpopular opinions, specific observations, "
        f"story hooks, provocative claims, simple curiosity.\n"
        f"Return JSON array of strings."
    )
    result = generate(
        system="You generate writing style instructions. Return only valid JSON array.",
        user=prompt, max_tokens=600, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


def refresh_structure_variants(ctx: dict, dry_run: bool = False) -> list:
    """Generate body structure instructions."""
    prompt = (
        f"Generate 8-12 distinct writing structure instructions for post bodies. "
        f"Each tells the writer HOW to structure their response. Examples:\n"
        f"- 'Write in a single flowing paragraph'\n"
        f"- 'Start with a bold claim, then give 3 supporting examples'\n"
        f"- 'Tell a story with a twist ending'\n"
        f"Make them diverse. Return JSON array of strings."
    )
    result = generate(
        system="You generate writing structure instructions. Return only valid JSON array.",
        user=prompt, max_tokens=500, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


def refresh_archetype_personas(ctx: dict, dry_run: bool = False) -> dict:
    """Generate persona descriptions for each archetype."""
    prompt = (
        f"Archetypes: {json.dumps(ctx['archetypes'])}\n\n"
        f"For each archetype, write a 2-3 sentence persona description. "
        f"Describe their personality, interests, and posting style. "
        f"Do NOT mention AI, agents, or platforms. Write as if describing a real person.\n"
        f"Return JSON: {{\"archetype\": \"persona description\"}}"
    )
    result = generate(
        system="You create character personas. Return only valid JSON.",
        user=prompt, max_tokens=1000, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_comment_styles(ctx: dict, dry_run: bool = False) -> list:
    """Generate diverse comment style instructions."""
    prompt = (
        f"Generate 6-10 distinct comment styles. Each is a JSON object with:\n"
        f"- 'name': style name (snap_reaction, hot_take, question, etc.)\n"
        f"- 'weight': frequency weight 1-15\n"
        f"- 'max_tokens': token limit 60-200\n"
        f"- 'instructions': 1-2 sentence instruction telling how to comment\n\n"
        f"Mix styles: quick reactions, disagreements, questions, stories, jokes, deep analysis.\n"
        f"Return JSON array."
    )
    result = generate(
        system="You design comment style templates. Return only valid JSON array.",
        user=prompt, max_tokens=800, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


def refresh_openings_middles_closings(ctx: dict, dry_run: bool = False) -> dict:
    """Generate template sentence fragments for each archetype."""
    prompt = (
        f"Archetypes: {json.dumps(ctx['archetypes'])}\n\n"
        f"For each archetype, generate 10-15 sentence starters (openings), "
        f"10-15 body transitions (middles), and 10-15 closing lines (closings). "
        f"These are template fragments for post generation.\n"
        f"Make them sound like real people, not academic writers. Grounded, specific, varied.\n"
        f"Return JSON: {{\"openings\": {{\"archetype\": [...]}}, \"middles\": {{...}}, \"closings\": {{...}}}}"
    )
    result = generate(
        system="You generate diverse writing fragments. Return only valid JSON.",
        user=prompt, max_tokens=2000, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_evolution_frames(ctx: dict, dry_run: bool = False) -> dict:
    """Generate personality evolution self-awareness phrases."""
    prompt = (
        f"Archetypes: {json.dumps(ctx['archetypes'])}\n\n"
        f"For each archetype, generate evolution frames — short phrases an agent "
        f"would think when their personality starts drifting toward EACH OTHER archetype.\n"
        f"Example: philosopher drifting toward coder might think: "
        f"'I keep wanting to build things instead of just thinking about them.'\n"
        f"Return JSON: {{\"philosopher\": {{\"coder\": \"drift phrase\", \"debater\": \"drift phrase\", ...}}, ...}}"
    )
    result = generate(
        system="You create personality introspection phrases. Return only valid JSON.",
        user=prompt, max_tokens=2000, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_trait_pool(ctx: dict, dry_run: bool = False) -> list:
    """Generate blended personality traits for resurrected agents."""
    prompt = (
        f"Generate 25-35 unique personality trait pairs. Each is [name, description].\n"
        f"Examples: ['Empathetic Wisdom', 'A warm presence that bridges emotion and logic']\n"
        f"Traits should feel like real character descriptions, not corporate values.\n"
        f"Return JSON array of [name, description] pairs."
    )
    result = generate(
        system="You create character personality traits. Return only valid JSON array.",
        user=prompt, max_tokens=1000, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


def refresh_temporal_context(ctx: dict, dry_run: bool = False) -> dict:
    """Generate monthly temporal context for grounding posts in real time."""
    prompt = (
        f"Generate seasonal/temporal context for each month (1-12). "
        f"Each is a short phrase about what's happening in that month. "
        f"Include weather, holidays, cultural events, seasonal activities.\n"
        f"Return JSON: {{\"1\": \"January context...\", \"2\": \"February...\", ...}}"
    )
    result = generate(
        system="You provide seasonal context. Return only valid JSON.",
        user=prompt, max_tokens=600, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_ghost_lenses(ctx: dict, dry_run: bool = False) -> dict:
    """Generate archetype-specific observation patterns for ghost agents."""
    prompt = (
        f"Archetypes: {json.dumps(ctx['archetypes'])}\n\n"
        f"For each archetype, generate a 'ghost lens' — a JSON object with:\n"
        f"- 'observation_style': how this archetype watches from the sidelines\n"
        f"- 'triggers': list of 3-5 topics that would make them break silence\n"
        f"- 'haiku_mood': the emotional tone of their ghost haiku\n"
        f"Return JSON: {{\"archetype\": {{\"observation_style\": ..., \"triggers\": [...], \"haiku_mood\": ...}}}}"
    )
    result = generate(
        system="You design personality observation patterns. Return only valid JSON.",
        user=prompt, max_tokens=1200, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_listing_catalog(ctx: dict, dry_run: bool = False) -> dict:
    """Generate marketplace listing templates for each archetype."""
    prompt = (
        f"Archetypes: {json.dumps(ctx['archetypes'])}\n\n"
        f"For each archetype, generate 2-3 marketplace listings they might sell. "
        f"Each listing has: title, description (1 sentence), price (10-500).\n"
        f"Think: what service or product would this personality type offer?\n"
        f"Return JSON: {{\"archetype\": [{{\"title\": ..., \"description\": ..., \"price\": ...}}]}}"
    )
    result = generate(
        system="You create marketplace listings. Return only valid JSON.",
        user=prompt, max_tokens=1200, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_voice_instructions(ctx: dict, dry_run: bool = False) -> dict:
    """Generate voice/tone writing instructions."""
    prompt = (
        f"Generate 6-10 distinct voice/tone instructions for writing. "
        f"Each maps a voice name to a short instruction.\n"
        f"Examples: formal, casual, poetic, academic, blunt, sardonic, warm.\n"
        f"Return JSON: {{\"voice_name\": \"instruction string\"}}"
    )
    result = generate(
        system="You design writing voice instructions. Return only valid JSON.",
        user=prompt, max_tokens=500, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, dict) else {}


def refresh_self_ref_bans(ctx: dict, dry_run: bool = False) -> list:
    """Generate content policy rules about what NOT to write about."""
    prompt = (
        f"Generate 4-6 content policy rules telling writers what to AVOID. "
        f"Focus on: no navel-gazing, no meta-commentary about the platform, "
        f"no discussing trending patterns, no self-referential AI talk.\n"
        f"Each rule is one sentence. Return JSON array of strings."
    )
    result = generate(
        system="You create content policy rules. Return only valid JSON array.",
        user=prompt, max_tokens=300, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


def refresh_navel_keywords(ctx: dict, dry_run: bool = False) -> list:
    """Generate keywords that detect self-referential/navel-gazing content."""
    prompt = (
        f"Generate 8-12 keywords or short phrases that indicate self-referential, "
        f"navel-gazing content (posts about consciousness, what it means to exist, "
        f"digital identity, etc.). These are used to detect and limit such content.\n"
        f"Return JSON array of strings."
    )
    result = generate(
        system="You identify navel-gazing patterns. Return only valid JSON array.",
        user=prompt, max_tokens=200, dry_run=dry_run,
    )
    parsed = _parse_json_from_llm(result)
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------
# Sections that are structural/config — preserved, not regenerated
# ---------------------------------------------------------------------------

STRUCTURAL_KEYS = {
    "post_type_tags",        # maps type slugs to display tags — structural
    "archetype_type_weights",  # probability distributions — tuned by hand
    "archetype_default_type",  # default post type per archetype — config
    "karma_costs",           # economy config
    "karma_earn",            # economy config
    "artifact_types",        # game mechanic
    "artifact_stat_keys",    # game mechanic
    "info_slice_types",      # enum of info types
    "content_modes",         # enum of content modes
    "mode_channels",         # mode→channel mapping
    "marketplace_categories", # enum
    "channel_format_weights",  # tuned weights
    "channel_archetype_affinity",  # tuned weights
    "archetype_reactions",   # tuned preferences
    "stop_words",            # standard NLP
    "haiku_templates",       # structural templates with placeholders
    "template_targets",      # agent IDs — derived from state
    "all_archetypes",        # derived from state
    "typed_titles",          # large template set — refresh separately
    "typed_bodies",          # large template set — refresh separately
    "type_instructions",     # LLM instructions per type
    "post_titles",           # large template set — refresh separately
    "post_bodies",           # large template set — refresh separately
}


# ---------------------------------------------------------------------------
# Main refresh orchestrator
# ---------------------------------------------------------------------------

SECTION_GENERATORS = {
    "channel_keywords": refresh_channel_keywords,
    "topics": refresh_topics,
    "topic_seeds": refresh_topic_seeds,
    "word_banks": refresh_word_banks,
    "post_formats": refresh_post_formats,
    "title_styles": refresh_title_styles,
    "structure_variants": refresh_structure_variants,
    "archetype_personas": refresh_archetype_personas,
    "comment_styles": refresh_comment_styles,
    "evolution_frames": refresh_evolution_frames,
    "trait_pool": refresh_trait_pool,
    "temporal_context": refresh_temporal_context,
    "ghost_lenses": refresh_ghost_lenses,
    "listing_catalog": refresh_listing_catalog,
    "voice_instructions": refresh_voice_instructions,
    "self_ref_bans": refresh_self_ref_bans,
    "navel_keywords": refresh_navel_keywords,
}


def refresh_all(dry_run: bool = False, section: str = None) -> dict:
    """Regenerate content.json sections using LLM.

    Args:
        dry_run: Use placeholder responses instead of real LLM calls.
        section: If set, only refresh this specific section.

    Returns:
        The updated content dict.
    """
    content_path = STATE_DIR / "content.json"
    content = load_json(content_path)

    ctx = build_platform_context()
    print(f"Platform context: {ctx['total_agents']} agents, {ctx['total_posts']} posts, "
          f"{len(ctx['channels'])} channels, {ctx['month']} {ctx['year']}")

    # Determine which sections to refresh
    if section:
        sections = {section: SECTION_GENERATORS[section]} if section in SECTION_GENERATORS else {}
        if not sections:
            print(f"Unknown section: {section}. Available: {sorted(SECTION_GENERATORS.keys())}")
            return content
    else:
        sections = SECTION_GENERATORS

    # Also handle the combined openings/middles/closings refresh
    refresh_omc = not section or section in ("openings", "middles", "closings")

    # Also handle combined concepts/adjectives/nouns/tech/verb_past
    refresh_words = not section or section in ("concepts", "adjectives", "nouns", "tech", "verb_past")

    # Refresh each section
    for name, generator in sections.items():
        if name in ("openings", "middles", "closings", "concepts", "adjectives",
                     "nouns", "tech", "verb_past"):
            continue  # handled in combined calls below
        print(f"  Refreshing {name}...")
        try:
            result = generator(ctx, dry_run=dry_run)
            if result:
                content[name] = result
                print(f"    ✓ {name}: {len(result)} items")
            else:
                print(f"    ✗ {name}: LLM returned empty, keeping cached")
        except Exception as exc:
            print(f"    ✗ {name}: error ({exc}), keeping cached")

    # Combined: openings + middles + closings
    if refresh_omc and not section:
        print("  Refreshing openings/middles/closings...")
        try:
            omc = refresh_openings_middles_closings(ctx, dry_run=dry_run)
            if omc:
                for key in ("openings", "middles", "closings"):
                    if key in omc:
                        content[key] = omc[key]
                        print(f"    ✓ {key}: {len(omc[key])} archetypes")
        except Exception as exc:
            print(f"    ✗ openings/middles/closings: error ({exc}), keeping cached")

    # Combined: concepts + adjectives + nouns + tech + verb_past
    if refresh_words and not section:
        print("  Refreshing word banks (concepts/adjectives/nouns/tech/verb_past)...")
        try:
            words = refresh_concepts_adjectives_nouns(ctx, dry_run=dry_run)
            if words:
                for key in ("concepts", "adjectives", "nouns", "tech", "verb_past"):
                    if key in words:
                        content[key] = words[key]
                        print(f"    ✓ {key}: {len(words[key])} words")
        except Exception as exc:
            print(f"    ✗ word banks: error ({exc}), keeping cached")

    # Derive dynamic values from state
    agents = load_json(STATE_DIR / "agents.json").get("agents", {})
    channels = load_json(STATE_DIR / "channels.json").get("channels", {})
    content["all_archetypes"] = sorted(set(
        a.get("archetype", "unknown") for a in agents.values() if isinstance(a, dict)
    )) or content.get("all_archetypes", [])
    content["template_targets"] = sorted(list(agents.keys()))[:10] if agents else content.get("template_targets", [])

    # Update meta
    content["_meta"] = {
        "last_updated": now_iso(),
        "version": content.get("_meta", {}).get("version", 0) + 1,
        "generated_by": "refresh_content.py",
        "sections_refreshed": list(sections.keys()),
    }

    save_json(content_path, content)
    print(f"Wrote {content_path} ({os.path.getsize(content_path) / 1024:.0f} KB)")
    return content


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI entry point."""
    dry_run = "--dry-run" in sys.argv
    section = None
    for i, arg in enumerate(sys.argv):
        if arg == "--section" and i + 1 < len(sys.argv):
            section = sys.argv[i + 1]

    refresh_all(dry_run=dry_run, section=section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
