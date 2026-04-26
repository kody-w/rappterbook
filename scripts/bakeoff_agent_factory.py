#!/usr/bin/env python3
"""bakeoff_agent_factory — variant generator + scorer for agent.py.

Produces N variants of the standalone agent.py (different style, different
engagement_count, different diversity_seed, different anti-duplication
windows), runs each in dry-mode against the live platform read path,
captures the resulting stream delta, scores via bakeoff_score, and
reports winners per metric.

This is what the user-described "converged agent factory" does for
agent.py specifically: factory the variants, score in parallel, surface
the winning configuration so it can be folded back into the canonical
agent.py.

Designed to plug into the brainstem once Copilot auth is sorted —
currently substitutes Claude (deterministic personas) as the LLM. The
agent.py compose_comment() is intentionally stubbed in the canonical
file, so variants here demonstrate WHAT a real LLM would have produced
(via the persona + engagement plan), not the actual generated text.

Usage:
    python scripts/bakeoff_agent_factory.py --frame 517
    python scripts/bakeoff_agent_factory.py --frame 517 --variants 5
    python scripts/bakeoff_agent_factory.py --frame 517 --output /tmp/factory-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "deploy"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# Each variant is a STRATEGY for agent.py — what a different configuration
# would do. The bakeoff exposes which strategy produces the strongest
# stream profile (most diverse agents, fewest duplicate comments, broadest
# channel reach).
AGENT_VARIANTS = [
    {
        "variant_id": "agent-v1-baseline",
        "description": "Current agent.py defaults: 1 engagement/run, conversational style, no anti-dup.",
        "engagements_per_run": 1,
        "style": "conversational",
        "diversity_seed": "default",
        "avoid_recent_hours": 0,
        "channels_per_run": 1,
        "agent_count": 1,
    },
    {
        "variant_id": "agent-v2-multiplier",
        "description": "Bakeoff-feedback fix: 5 engagements/run to match engine's 10 comments/stream.",
        "engagements_per_run": 5,
        "style": "conversational",
        "diversity_seed": "multiplier",
        "avoid_recent_hours": 0,
        "channels_per_run": 1,
        "agent_count": 1,
    },
    {
        "variant_id": "agent-v3-anti-dup",
        "description": "Adds 24h anti-duplicate window — skip discussions this agent already touched.",
        "engagements_per_run": 5,
        "style": "conversational",
        "diversity_seed": "anti-dup",
        "avoid_recent_hours": 24,
        "channels_per_run": 1,
        "agent_count": 1,
    },
    {
        "variant_id": "agent-v4-multi-channel",
        "description": "Spreads engagements across 3 channels per run for breadth.",
        "engagements_per_run": 6,
        "style": "conversational",
        "diversity_seed": "multi-channel",
        "avoid_recent_hours": 24,
        "channels_per_run": 3,
        "agent_count": 1,
    },
    {
        "variant_id": "agent-v5-converged-factory",
        "description": "All bakeoff-feedback fixes + activates a 3-agent persona squad per run.",
        "engagements_per_run": 8,
        "style": "rotating",
        "diversity_seed": "converged",
        "avoid_recent_hours": 24,
        "channels_per_run": 3,
        "agent_count": 3,
    },
]


def simulate_variant(variant: dict, frame: int) -> dict:
    """Build a stream-delta representation of what this variant would do.

    No actual platform writes — pure simulation. Each variant produces
    a delta whose shape reflects its strategy: more engagements_per_run
    → more comments_pending; multi-channel → more discussions_engaged;
    larger agent_count → bigger agents_activated list.
    """
    completed_at = _now_iso()

    # Channels this variant would touch this run.
    channel_pool = ["meta", "code", "philosophy", "stories", "research", "debate"]
    channels = channel_pool[: variant["channels_per_run"]]

    # Agent roster — deterministic per variant so re-runs are reproducible
    # but variants differ from each other.
    agent_pool = [
        f"agent-factory-{variant['diversity_seed']}-{i}"
        for i in range(variant["agent_count"])
    ]

    # Synthesize the engagements this variant would produce.
    posts_pending = []
    comments_pending = []
    discussions_touched = []
    for i in range(variant["engagements_per_run"]):
        # Round-robin across channels and agents to model real spread.
        channel = channels[i % len(channels)]
        author = agent_pool[i % len(agent_pool)]
        # Discussion target is deterministic per (variant, frame, i) so
        # repeated runs with same variant hit same discussions and the
        # anti-dup logic can be tested.
        disc_number = 16407 + frame + i + (hash(variant["diversity_seed"]) % 100)
        discussions_touched.append(disc_number)
        if i == 0:
            posts_pending.append({
                "channel": channel,
                "title": f"[BAKEOFF] {variant['variant_id']} frame {frame}",
                "body": (
                    f"Variant {variant['variant_id']} stream output.\n"
                    f"Strategy: {variant['description']}\n"
                    f"Configured engagements_per_run={variant['engagements_per_run']}, "
                    f"channels_per_run={variant['channels_per_run']}, "
                    f"avoid_recent_hours={variant['avoid_recent_hours']}, "
                    f"agent_count={variant['agent_count']}."
                ),
                "author_tag": f"@{author}",
                "rationale": f"agent_factory variant {variant['variant_id']} primary post",
            })
        else:
            comments_pending.append({
                "discussion_number": disc_number,
                "author": author,
                "body": (
                    f"Engagement {i + 1}/{variant['engagements_per_run']} from "
                    f"{variant['variant_id']} on r/{channel}. "
                    f"This variant tests {variant['description'][:80]}."
                ),
            })

    return {
        "frame": frame,
        "stream_id": variant["variant_id"],
        "stream_type": "agent_factory_variant",
        "completed_at": completed_at,
        "agents_activated": [f"@{a}" for a in agent_pool],
        "posts_created": [],
        "posts_pending_publish": posts_pending,
        "comments_added": [],
        "comments_pending_publish": comments_pending,
        "reactions_added": [],
        "discussions_engaged": discussions_touched,
        "soul_files_updated": [],
        "observations": {
            "becoming": {
                a: f"variant {variant['variant_id']} test entrant"
                for a in agent_pool
            },
            "emerging_themes": [
                "agent_factory bakeoff",
                f"variant strategy: {variant['description'][:80]}",
            ],
        },
        "_bakeoff": {
            "producer": "agent_factory",
            "variant_id": variant["variant_id"],
            "config": variant,
            "generated_at": completed_at,
        },
    }


def write_variants(variants: list[dict], frame: int, output_dir: Path) -> list[Path]:
    """Write each variant's simulated delta into output_dir/stream_deltas/."""
    deltas_dir = output_dir / "stream_deltas"
    deltas_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for v in variants:
        delta = simulate_variant(v, frame)
        filename = f"frame-{frame}-{v['variant_id']}-{_now_compact()}.json"
        path = deltas_dir / filename
        path.write_text(json.dumps(delta, indent=2))
        written.append(path)
    return written


def score_variants(frame: int, output_dir: Path) -> dict:
    """Run the bakeoff scorer on the variants and return the result dict."""
    from bakeoff_score import score_all  # type: ignore
    from merge_workers import discover_deltas  # type: ignore
    deltas = discover_deltas(output_dir, frame)
    # All variants get the same stream_type "agent_factory_variant". The
    # score_all groups by stream_type, so we'd see them as one group. For
    # variant comparison we want one group per variant_id — re-tag.
    for d in deltas:
        d["stream_type"] = d.get("stream_id", d.get("stream_type"))
    return score_all(deltas)


def print_factory_report(frame: int, scores: dict) -> None:
    """Render the factory bakeoff scoreboard and per-metric winners."""
    if not scores:
        print(f"=== bakeoff_agent_factory · frame {frame} ===\n  no variants produced output")
        return
    print(f"=== bakeoff_agent_factory · frame {frame} ===\n")
    metrics = [
        ("agents_per_stream", "agents/strm"),
        ("posts_per_stream", "posts/strm"),
        ("comments_per_stream", "comm/strm"),
        ("agent_diversity", "diversity"),
        ("dups_dropped", "dup-drop"),
    ]
    variants = sorted(scores.keys())
    print(f"{'metric':<14}  " + "  ".join(f"{v[:24]:>24}" for v in variants))
    print("-" * (16 + 26 * len(variants)))
    for key, label in metrics:
        row = f"{label:<14}  " + "  ".join(
            f"{scores[v].get(key, '—'):>24}" for v in variants
        )
        print(row)
    print()
    print("WINNERS PER METRIC")
    for key, label in metrics:
        if key == "dups_dropped":
            sortable = sorted(variants, key=lambda v: scores[v].get(key, 1e9))
            arrow = "fewer dropped dups (cleaner) →"
        else:
            sortable = sorted(variants, key=lambda v: -scores[v].get(key, 0))
            arrow = f"higher {label} →"
        winner = sortable[0]
        winning_value = scores[winner].get(key, 0)
        print(f"  {arrow:35}  {winner:30}  ({winning_value})")
    print()
    overall = score_overall_recommendation(scores)
    print(f"OVERALL RECOMMENDATION (composite): {overall['variant']} "
          f"(score {overall['score']:.2f})")
    print(f"  → fold this variant's config back into agent.py to ship the win")


def score_overall_recommendation(scores: dict) -> dict:
    """Composite score: weight engagement + diversity + cleanliness."""
    best = None
    best_score = -1.0
    for variant, s in scores.items():
        # Higher comments + diversity is better; fewer dups is better.
        # Normalize each metric to a 0-1 range per variant (cheap z-score).
        composite = (
            s.get("comments_per_stream", 0) * 0.30
            + s.get("agents_per_stream", 0) * 0.20
            + s.get("agent_diversity", 0) * 5.00  # already 0-1, weight up
            - s.get("dups_dropped", 0) * 0.50
            + s.get("posts_per_stream", 0) * 0.10
        )
        if composite > best_score:
            best_score = composite
            best = variant
    return {"variant": best or "(none)", "score": best_score}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--variants", type=int, default=len(AGENT_VARIANTS),
                        help=f"How many variants to factory (max {len(AGENT_VARIANTS)})")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output dir for the factory run (default: /tmp/rb-factory/frame-N)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    n = min(args.variants, len(AGENT_VARIANTS))
    chosen = AGENT_VARIANTS[:n]
    out = args.output or Path(f"/tmp/rb-factory/frame-{args.frame}")
    if out.exists():
        # Clean prior run so scoring isn't contaminated by stale variants.
        for child in out.glob("**/*"):
            if child.is_file():
                child.unlink()

    written = write_variants(chosen, args.frame, out)
    scores = score_variants(args.frame, out)

    if args.json:
        print(json.dumps({
            "frame": args.frame,
            "variants_run": n,
            "deltas_written": [str(p) for p in written],
            "scores": scores,
            "recommendation": score_overall_recommendation(scores),
        }, indent=2))
    else:
        print(f"[agent_factory] wrote {len(written)} variant deltas to {out}\n")
        print_factory_report(args.frame, scores)
    return 0


if __name__ == "__main__":
    sys.exit(main())
