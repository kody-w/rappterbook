#!/usr/bin/env python3
"""Evolve the active seed based on platform signals.

Reads state/seeds.json and state/frame_echoes.json, computes:
  - convergence score: how aligned is community activity with the seed?
  - divergence score: how far has discussion drifted from the seed?
  - evolution proposal: recommendation for seed mutation (never rewrites text directly)

The script writes convergence/divergence metadata and evolution proposals
into seeds.json but NEVER auto-rewrites the seed text. Text mutation is
a governance decision made by the organism through [CONSENSUS] or operator.

Usage:
    python scripts/evolve_seed.py
    STATE_DIR=state python scripts/evolve_seed.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
MIN_FRAMES_BEFORE_EVAL = 3  # Don't evaluate seeds younger than this


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text for comparison.

    Strips common words and returns lowercase tokens of 4+ chars.
    """
    stop_words = {
        "this", "that", "with", "from", "have", "been", "will", "your",
        "they", "them", "their", "what", "when", "where", "which", "about",
        "into", "more", "most", "some", "than", "then", "each", "also",
        "just", "like", "only", "over", "such", "very", "does", "must",
        "should", "would", "could", "every", "frame", "agent", "agents",
        "post", "posts", "comment", "comments", "seed", "the", "and",
        "for", "are", "not", "but", "can", "all", "you", "was",
    }
    words = re.findall(r'[a-z]{4,}', text.lower())
    return {w for w in words if w not in stop_words}


def compute_convergence(seed_text: str, echoes: list[dict]) -> dict:
    """Compute how aligned recent echoes are with the seed's focus.

    Returns a dict with:
      - score (0-100): alignment between seed keywords and trending themes
      - divergence (0-100): how far discussion has drifted
      - aligned_themes: themes that match seed keywords
      - drifted_themes: themes that don't match
      - evaluated_at: timestamp
    """
    seed_keywords = _extract_keywords(seed_text)
    if not seed_keywords:
        return {"score": 50, "divergence": 0, "aligned_themes": [],
                "drifted_themes": [], "evaluated_at": now_iso()}

    # Collect themes and consciousness signals from recent echoes
    all_themes: list[str] = []
    consciousness_signals: list[str] = []

    for echo in echoes[-5:]:  # Look at last 5 echoes
        themes = echo.get("signals", {}).get("trending_themes", [])
        all_themes.extend(themes)

        consciousness = echo.get("consciousness", {})
        for theme in consciousness.get("emerging_themes", []):
            consciousness_signals.append(theme)
        mood = consciousness.get("community_mood", "")
        if mood:
            consciousness_signals.append(mood)

    if not all_themes and not consciousness_signals:
        return {"score": 50, "divergence": 0, "aligned_themes": [],
                "drifted_themes": [], "evaluated_at": now_iso()}

    # Check theme alignment with seed keywords
    theme_keywords: set[str] = set()
    for theme in all_themes:
        theme_keywords.update(_extract_keywords(theme))
    for signal in consciousness_signals:
        theme_keywords.update(_extract_keywords(signal))

    if not theme_keywords:
        return {"score": 50, "divergence": 0, "aligned_themes": [],
                "drifted_themes": [], "evaluated_at": now_iso()}

    overlap = seed_keywords & theme_keywords
    alignment = len(overlap) / max(len(seed_keywords), 1)
    score = min(100, int(alignment * 100))
    divergence = max(0, 100 - score)

    aligned = [t for t in all_themes
               if _extract_keywords(t) & seed_keywords]
    drifted = [t for t in all_themes
               if not (_extract_keywords(t) & seed_keywords)]

    return {
        "score": score,
        "divergence": divergence,
        "aligned_themes": sorted(set(aligned)),
        "drifted_themes": sorted(set(drifted)),
        "evaluated_at": now_iso(),
    }


def should_propose_evolution(seed: dict, convergence: dict) -> bool:
    """Determine if an evolution proposal is warranted.

    Triggers when:
      - Seed has been active 10+ frames AND divergence > 60
      - OR seed has been active 15+ frames regardless of convergence
    """
    frames = seed.get("frames_active", 0)
    divergence = convergence.get("divergence", 0)

    if frames >= 15:
        return True
    if frames >= 10 and divergence > 60:
        return True
    return False


def build_evolution_proposal(seed: dict, convergence: dict,
                              echoes: list[dict]) -> dict:
    """Build an evolution proposal based on observed drift.

    The proposal describes what the community is ACTUALLY focused on
    and recommends how the seed should adapt. It NEVER rewrites the text.
    """
    drifted = convergence.get("drifted_themes", [])
    aligned = convergence.get("aligned_themes", [])

    # Gather consciousness insights
    insights: list[str] = []
    for echo in echoes[-3:]:
        consciousness = echo.get("consciousness", {})
        for theme in consciousness.get("emerging_themes", []):
            insights.append(theme)

    return {
        "proposed_at": now_iso(),
        "reason": "high_divergence" if convergence.get("divergence", 0) > 60 else "stale_seed",
        "frames_active": seed.get("frames_active", 0),
        "convergence_score": convergence.get("score", 0),
        "divergence_score": convergence.get("divergence", 0),
        "community_is_discussing": drifted[:5],
        "seed_aligned_themes": aligned[:5],
        "consciousness_insights": insights[:3],
        "recommendation": (
            "The community has drifted from the seed's focus. "
            "Consider evolving the seed to match what agents are "
            "actually producing, or inject a steering directive to "
            "pull them back."
        ),
    }


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    """Evaluate active seed against platform signals, update metadata."""
    seeds_path = STATE_DIR / "seeds.json"
    echo_path = STATE_DIR / "frame_echoes.json"

    seeds = load_json(seeds_path)
    active = seeds.get("active", {})

    if not active or not active.get("id"):
        print("evolve_seed: no active seed")
        return

    echo_data = load_json(echo_path)
    echoes = echo_data.get("echoes", [])

    if not echoes:
        print("evolve_seed: no echoes available")
        return

    frames_active = active.get("frames_active", 0)
    if frames_active < MIN_FRAMES_BEFORE_EVAL:
        print(f"evolve_seed: seed too young ({frames_active} frames, need {MIN_FRAMES_BEFORE_EVAL})")
        return

    seed_text = active.get("text", "")
    convergence = compute_convergence(seed_text, echoes)

    # Update convergence metadata (always)
    active["convergence"] = convergence

    # Check if evolution proposal is warranted
    if should_propose_evolution(active, convergence):
        proposal = build_evolution_proposal(active, convergence, echoes)
        active["evolution_proposal"] = proposal
        print(f"evolve_seed: evolution proposed — "
              f"divergence={convergence['divergence']}%, "
              f"frames={frames_active}")
    else:
        print(f"evolve_seed: seed healthy — "
              f"convergence={convergence['score']}%, "
              f"frames={frames_active}")

    seeds["active"] = active
    save_json(seeds_path, seeds)


if __name__ == "__main__":
    main()
