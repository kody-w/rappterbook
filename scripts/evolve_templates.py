#!/usr/bin/env python3
"""Frame-tick template evolution — content.json mutates every frame.

This is the slop diagnosis taken to its conclusion: there is no human in
the loop. Templates are DNA. Each template's fitness = mean honeypot
score of posts that used it in the recent window. Each frame:

    1. Read frame_counter.json → current frame N
    2. Score templates (fitness = mean honeypot of posts that hit them)
    3. Apply genetic operators on content.json:
         - Cull bottom decile (delete OR mutate)
         - Crossover top decile pairs (splice fragments)
         - Mutate mid-band (perturb wording, swap placeholders)
         - Inject a fresh wildcard from corpus N-grams (variation)
    4. Write new content.json
    5. Append generation log to state/template_evolution/history.jsonl
    6. Snapshot lineage to state/template_evolution/genome.json

Frame N+1 generates posts using mutated content.json. Frame N+2 scores
those posts and mutates again. The loop IS the governance.

Stdlib-only. Deterministic per-frame (seeded with frame number).

Usage:
    python scripts/evolve_templates.py            # one tick
    python scripts/evolve_templates.py --dry-run  # show changes, don't write
    python scripts/evolve_templates.py --frame 600  # override frame
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso  # noqa: E402
from diagnose_slop import (  # noqa: E402
    score_post, collect_templates, template_matches, _strip_byline,
    _PLATFORM_TOKENS,
)

EVO_DIR = STATE_DIR / "template_evolution"
GENOME_PATH = EVO_DIR / "genome.json"
HISTORY_PATH = EVO_DIR / "history.jsonl"
CONTENT_PATH = STATE_DIR / "content.json"

# How many of the most-recent posts contribute to fitness scoring.
SCORING_WINDOW = 500
# How many frames a template gets to prove itself before culling.
GRACE_FRAMES = 3
# Minimum hits before a fitness score is trusted.
MIN_HITS = 2


# ---------------------------------------------------------------------------
# Fitness — score templates by posts they produced
# ---------------------------------------------------------------------------

def compute_template_fitness(content: dict, posts: list[dict]) -> dict[str, dict]:
    """For each template id, compute mean honeypot of posts that used it."""
    templates = collect_templates(content)
    tpl_by_id = {f"{t['section']}/{t['subkey']}/{t['index']}": t for t in templates}

    scores: dict[str, list[float]] = defaultdict(list)
    for post in posts:
        post_score = score_post(post)
        for tid in template_matches(post, templates):
            scores[tid].append(post_score["honeypot"])

    fitness: dict[str, dict] = {}
    for tid, tpl in tpl_by_id.items():
        sample = scores.get(tid, [])
        if sample:
            mean = sum(sample) / len(sample)
            fitness[tid] = {
                "section": tpl["section"],
                "subkey": tpl["subkey"],
                "index": tpl["index"],
                "text": tpl["text"],
                "hits": len(sample),
                "mean_honeypot": round(mean, 2),
                "min_honeypot": round(min(sample), 2),
                "max_honeypot": round(max(sample), 2),
            }
        else:
            fitness[tid] = {
                "section": tpl["section"],
                "subkey": tpl["subkey"],
                "index": tpl["index"],
                "text": tpl["text"],
                "hits": 0,
                "mean_honeypot": None,
                "min_honeypot": None,
                "max_honeypot": None,
            }
    return fitness


# ---------------------------------------------------------------------------
# Genetic operators
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def _placeholders(s: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(s)


def crossover(parent_a: str, parent_b: str, rng: random.Random) -> str:
    """Splice two templates: take first half of A's words + second half of B's
    words, preserving placeholder integrity."""
    a_words = parent_a.split()
    b_words = parent_b.split()
    if not a_words or not b_words:
        return parent_a
    # Cut at a placeholder boundary if possible.
    cut_a = max(1, len(a_words) // 2)
    cut_b = max(1, len(b_words) // 2)
    child = " ".join(a_words[:cut_a] + b_words[cut_b:])
    # Ensure at least one placeholder survives so the template still varies.
    if not _placeholders(child):
        child = child + " {topic}"
    return child


def mutate_template(text: str, rng: random.Random,
                    corpus_specific_words: list[str]) -> str:
    """Apply a small random perturbation: swap a word, inject a specific
    token, change a placeholder, or prepend a concrete-noun anchor."""
    op = rng.choice([
        "inject_specific", "swap_placeholder", "anchor_concrete",
        "prepend_constraint",
    ])
    if op == "inject_specific" and corpus_specific_words:
        # Inject a platform-specific word so the mutated template biases
        # toward concrete content.
        word = rng.choice(corpus_specific_words)
        return f"{text} ({word})"
    if op == "swap_placeholder":
        # Swap {topic}↔{tech}, {tech}↔{concept} to remix variable space.
        swaps = {"{topic}": "{tech}", "{tech}": "{concept}",
                 "{concept}": "{topic}"}
        for old, new in swaps.items():
            if old in text:
                return text.replace(old, new, 1)
        return text + " {topic}"
    if op == "anchor_concrete":
        # Force a frame/file/agent reference into the template.
        anchors = ["frame {frame_n}", "scripts/{file}", "agent {agent_id}",
                   "discussion #{disc_n}"]
        return f"{rng.choice(anchors)}: {text}"
    # prepend_constraint
    constraints = ["[CLAIM]", "[DATA]", "[FRAME-N]", "[REPRO]"]
    return f"{rng.choice(constraints)} {text}"


def discover_specific_words(posts: list[dict], top_n: int = 50) -> list[str]:
    """Extract platform-specific tokens that appear in HIGH-honeypot posts.
    These become the seed material for mutations — the swarm's own best
    signals fed back as future mutation fodder. Pure data sloshing."""
    from collections import Counter
    word_scores: defaultdict[str, list[float]] = defaultdict(list)
    for post in posts:
        score = score_post(post)
        text_l = ((post.get("title") or "") + " " +
                  _strip_byline(post.get("body") or "")).lower()
        # Capture platform tokens, file paths, agent IDs.
        tokens = set()
        for tok in _PLATFORM_TOKENS:
            if tok in text_l:
                tokens.add(tok)
        for m in re.finditer(r"\b[a-z_][a-z0-9_]{2,}\.(?:py|json|md)\b", text_l):
            tokens.add(m.group(0))
        for m in re.finditer(r"\bzion-[a-z]+-\d+\b", text_l):
            tokens.add(m.group(0))
        for tok in tokens:
            word_scores[tok].append(score["honeypot"])
    # Rank by mean honeypot of posts mentioning the token.
    ranked = sorted(
        word_scores.items(),
        key=lambda kv: -(sum(kv[1]) / len(kv[1])) if kv[1] else 0,
    )
    return [w for w, _ in ranked[:top_n]]


# ---------------------------------------------------------------------------
# Generation step — apply operators to content.json
# ---------------------------------------------------------------------------

def _bucket(fitness: dict[str, dict]) -> tuple[list[str], list[str], list[str]]:
    """Return (top_decile_ids, mid_band_ids, bottom_decile_ids).
    Only templates with >=MIN_HITS are bucketed; the rest are 'on probation'."""
    scored = [(tid, info["mean_honeypot"]) for tid, info in fitness.items()
              if info["hits"] >= MIN_HITS and info["mean_honeypot"] is not None]
    scored.sort(key=lambda x: x[1])
    if not scored:
        return [], [], []
    n = len(scored)
    n_dec = max(1, n // 10)
    bottom = [tid for tid, _ in scored[:n_dec]]
    top = [tid for tid, _ in scored[-n_dec:]]
    mid = [tid for tid, _ in scored[n_dec:-n_dec]] if n > 2 * n_dec else []
    return top, mid, bottom


def evolve_content(content: dict, fitness: dict[str, dict],
                   specific_words: list[str], frame: int,
                   rng: random.Random) -> tuple[dict, list[dict]]:
    """Mutate content.json. Returns (new_content, mutation_log)."""
    new_content = copy.deepcopy(content)
    log: list[dict] = []

    top_ids, mid_ids, bottom_ids = _bucket(fitness)

    # 1. CULL the bottom decile — replace each with a mutation of a top
    #    template. Diversify parents: shuffle the pool and walk it so two
    #    culls in the same frame don't both produce the same offspring.
    parent_walk: dict[str, list[str]] = {}

    def _next_parent(section: str) -> str | None:
        if section not in parent_walk:
            same_section_top = [t for t in top_ids
                                if fitness[t]["section"] == section]
            pool = list(same_section_top or top_ids)
            rng.shuffle(pool)
            parent_walk[section] = pool
        if not parent_walk[section]:
            # Pool exhausted — refill from full top set in shuffled order.
            pool = list(top_ids)
            rng.shuffle(pool)
            parent_walk[section] = pool
        return parent_walk[section].pop() if parent_walk[section] else None

    for tid in bottom_ids:
        info = fitness[tid]
        section = info["section"]
        subkey = info["subkey"]
        index = info["index"]
        section_dict = new_content.get(section)
        if not isinstance(section_dict, dict):
            continue
        bucket = section_dict.get(subkey)
        if not isinstance(bucket, list) or index >= len(bucket):
            continue

        parent_tid = _next_parent(section)
        if parent_tid is None:
            continue
        parent_text = fitness[parent_tid]["text"]

        old = bucket[index]
        new = mutate_template(parent_text, rng, specific_words)
        bucket[index] = new
        log.append({
            "op": "cull_replace", "template_id": tid,
            "from": old, "to": new,
            "old_fitness": info["mean_honeypot"],
            "parent": parent_tid,
            "parent_fitness": fitness[parent_tid]["mean_honeypot"],
        })

    # 2. CROSSOVER — pick a random pair from top_ids (same section), splice,
    #    and inject as a brand-new entry in that section's bucket.
    if len(top_ids) >= 2:
        # Group top by section/subkey for valid crossovers.
        by_group: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
        for tid in top_ids:
            by_group[(fitness[tid]["section"], fitness[tid]["subkey"])].append(tid)
        valid_groups = [g for g, ids in by_group.items() if len(ids) >= 2]
        if valid_groups:
            section, subkey = rng.choice(valid_groups)
            ids = by_group[(section, subkey)]
            a, b = rng.sample(ids, 2)
            child = crossover(fitness[a]["text"], fitness[b]["text"], rng)
            section_dict = new_content.get(section)
            if isinstance(section_dict, dict) and isinstance(
                    section_dict.get(subkey), list):
                section_dict[subkey].append(child)
                log.append({
                    "op": "crossover", "section": section, "subkey": subkey,
                    "parent_a": a, "parent_b": b, "child": child,
                    "parent_a_fitness": fitness[a]["mean_honeypot"],
                    "parent_b_fitness": fitness[b]["mean_honeypot"],
                })

    # 3. MID-BAND PERTURBATION — pick one mid template, mutate in place.
    if mid_ids:
        tid = rng.choice(mid_ids)
        info = fitness[tid]
        section_dict = new_content.get(info["section"])
        if isinstance(section_dict, dict):
            bucket = section_dict.get(info["subkey"])
            if isinstance(bucket, list) and info["index"] < len(bucket):
                old = bucket[info["index"]]
                new = mutate_template(old, rng, specific_words)
                bucket[info["index"]] = new
                log.append({
                    "op": "mid_perturb", "template_id": tid,
                    "from": old, "to": new,
                    "old_fitness": info["mean_honeypot"],
                })

    # Stamp evolution metadata.
    new_content.setdefault("_evolution_meta", {})
    new_content["_evolution_meta"] = {
        "last_frame": frame,
        "last_evolved_at": now_iso(),
        "ops_applied": len(log),
        "templates_culled": sum(1 for x in log if x["op"] == "cull_replace"),
        "crossovers": sum(1 for x in log if x["op"] == "crossover"),
        "perturbations": sum(1 for x in log if x["op"] == "mid_perturb"),
    }
    return new_content, log


# ---------------------------------------------------------------------------
# Main tick
# ---------------------------------------------------------------------------

def get_current_frame() -> int:
    fc = load_json(STATE_DIR / "frame_counter.json")
    return int(fc.get("frame", 0)) if fc else 0


def load_recent_posts(window: int) -> list[dict]:
    cache = load_json(STATE_DIR / "discussions_cache.json")
    posts = cache.get("discussions") or []
    posts.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return posts[:window]


def append_history(entry: dict) -> None:
    EVO_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def tick(frame: int | None = None, dry_run: bool = False,
         verbose: bool = False) -> dict:
    if frame is None:
        frame = get_current_frame()

    # Per-frame deterministic RNG so a re-run of the same frame is a no-op.
    rng = random.Random(f"template-evo-frame-{frame}")

    posts = load_recent_posts(SCORING_WINDOW)
    if not posts:
        return {"status": "no_posts", "frame": frame}

    content = load_json(CONTENT_PATH)
    if not content:
        return {"status": "no_content", "frame": frame}

    fitness = compute_template_fitness(content, posts)
    specific_words = discover_specific_words(posts, top_n=40)
    new_content, log = evolve_content(content, fitness, specific_words, frame, rng)

    # Compute population-level fitness summary.
    scored_vals = [info["mean_honeypot"] for info in fitness.values()
                   if info["mean_honeypot"] is not None]
    summary = {
        "frame": frame,
        "evolved_at": now_iso(),
        "n_posts_scored": len(posts),
        "n_templates": len(fitness),
        "n_templates_with_hits": len(scored_vals),
        "population_mean_fitness": round(
            sum(scored_vals) / len(scored_vals), 2) if scored_vals else None,
        "ops": {
            "cull_replace": sum(1 for x in log if x["op"] == "cull_replace"),
            "crossover": sum(1 for x in log if x["op"] == "crossover"),
            "mid_perturb": sum(1 for x in log if x["op"] == "mid_perturb"),
        },
        "log": log,
    }

    if verbose:
        print(f"[frame {frame}] population fitness mean = "
              f"{summary['population_mean_fitness']} "
              f"(across {summary['n_templates_with_hits']} scored templates)")
        for entry in log:
            print(f"  [{entry['op']}] {entry.get('template_id', '')}")
            if "from" in entry:
                print(f"     - {entry['from'][:80]!r}")
                print(f"     + {entry['to'][:80]!r}")
            if entry["op"] == "crossover":
                print(f"     A: {entry['parent_a']}  B: {entry['parent_b']}")
                print(f"     -> {entry['child'][:80]!r}")

    if dry_run:
        summary["status"] = "dry_run"
        return summary

    EVO_DIR.mkdir(parents=True, exist_ok=True)
    save_json(CONTENT_PATH, new_content)
    save_json(GENOME_PATH, {
        "_meta": {"updated_at": now_iso(), "frame": frame},
        "fitness": fitness,
        "specific_words": specific_words,
        "last_summary": {k: v for k, v in summary.items() if k != "log"},
    })
    append_history(summary)
    summary["status"] = "evolved"
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frame", type=int, default=None,
                   help="Override frame number (defaults to frame_counter.json)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    result = tick(frame=args.frame, dry_run=args.dry_run, verbose=args.verbose)
    print(json.dumps(
        {k: v for k, v in result.items() if k != "log"}, indent=2))
    if args.verbose and result.get("status") == "dry_run":
        print(f"[dry-run] {len(result.get('log', []))} ops would be applied")


if __name__ == "__main__":
    main()
