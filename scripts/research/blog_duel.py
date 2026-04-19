#!/usr/bin/env python3
"""
blog_duel.py — mechanical comparator for two candidate blog posts on the same topic.

Usage:
    python blog_duel.py <mine_dir> <agent_dir> [--out report.json]

Produces a comparison report on 7 mechanical dimensions per post-pair:
  - word_count            (target range: 900-1500)
  - avg_sentence_length   (shorter = punchier)
  - sentence_length_std   (varied = better rhythm)
  - concreteness_ratio    (ratio of sentences with numbers / proper nouns / code)
  - mdash_density         (per 1000 words; Kody's voice signature)
  - bullet_ratio          (fraction of lines that are bullets; lower = more prose)
  - internal_link_count   (links to /blog/<slug>)
  - opener_specificity    (0-3; 0=generic, 3=specific incident/date/number)
  - closer_lands          (0-3; 0=summary/fluff, 3=pivot/punch/imperative)

Voice and idea-density are not fully mechanical — the comparator emits
concrete signals and a recommended next step (mine / agent / merge), but the
final call is left to a human (or LLM) reader.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
from pathlib import Path


def parse_frontmatter(content: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not m:
        return {}, content
    fm_text, body = m.group(1), m.group(2)
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def word_count(body: str) -> int:
    return len(re.findall(r"\b\w+\b", body))


def sentences(body: str) -> list[str]:
    # Strip code blocks + YAML frontmatter leftovers
    cleaned = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    cleaned = re.sub(r"\n#{1,6}\s.*?\n", "\n", cleaned)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", cleaned)
    return [p.strip() for p in parts if len(p.strip()) > 15]


def avg_and_std_sentence_length(body: str) -> tuple[float, float]:
    sents = sentences(body)
    if not sents:
        return 0.0, 0.0
    lengths = [len(s.split()) for s in sents]
    if len(lengths) < 2:
        return float(lengths[0]), 0.0
    return statistics.mean(lengths), statistics.stdev(lengths)


def concreteness_ratio(body: str) -> float:
    """Fraction of sentences containing numbers, proper nouns, or code."""
    sents = sentences(body)
    if not sents:
        return 0.0
    concrete = 0
    for s in sents:
        has_number = bool(re.search(r"\b\d+\b", s))
        has_proper = bool(re.search(r"[A-Z]{2,}|\b[A-Z][a-z]+[A-Z]", s))
        has_code = "`" in s
        if has_number or has_proper or has_code:
            concrete += 1
    return concrete / len(sents)


def mdash_density(body: str) -> float:
    """M-dashes per 1000 words. Kody's voice uses these."""
    count = body.count("—")
    wc = max(1, word_count(body))
    return (count / wc) * 1000


def bullet_ratio(body: str) -> float:
    lines = [ln for ln in body.split("\n") if ln.strip()]
    if not lines:
        return 0.0
    bullet_lines = sum(1 for ln in lines if ln.strip().startswith(("- ", "* ", "1. ", "2. ", "3. ")))
    return bullet_lines / len(lines)


def internal_link_count(body: str) -> int:
    # Markdown links where href is a slug-looking word (no protocol)
    return len(re.findall(r"\]\(([a-z][a-z0-9-]+)\)", body))


def opener_specificity(body: str) -> int:
    """Score the first paragraph 0-3 for specificity.
    0 = generic/abstract opener
    1 = mild specificity (terms of art but no data)
    2 = specific entity + fact
    3 = specific incident with time/date/data
    """
    # First substantive paragraph (after any h1 or blank lines)
    lines = body.strip().split("\n")
    first_para = []
    for line in lines:
        line = line.strip()
        if line.startswith("#") or not line:
            if first_para:
                break
            continue
        first_para.append(line)
        if len(" ".join(first_para)) > 300:
            break
    text = " ".join(first_para)
    if not text:
        return 0
    has_date = bool(re.search(r"\b20\d{2}\b|frame\s*\d+|\d{2}:\d{2}|UTC", text))
    has_number = bool(re.search(r"\b\d+\b", text))
    has_specific_entity = bool(re.search(r"\bzion-[a-z]+-\d+\b|Rappterbook|Amendment\s+[IVX]+|\.rapp\.egg|kodyTwinAI", text))
    score = 0
    if has_number:
        score += 1
    if has_specific_entity:
        score += 1
    if has_date:
        score += 1
    return min(score, 3)


def closer_lands(body: str) -> int:
    """Score the last paragraph 0-3 for landing force.
    0 = summary/fluff/filler
    1 = summary with a minor pivot
    2 = imperative or punchline
    3 = imperative + specific action or memorable line
    """
    # Strip the Related section
    stripped = re.sub(r"---\s*\n\*\*Related:\*\*.*$", "", body, flags=re.DOTALL | re.MULTILINE)
    paras = [p.strip() for p in stripped.strip().split("\n\n") if p.strip()]
    if not paras:
        return 0
    last = paras[-1]
    score = 0
    # Imperative or short punch
    sents_last = sentences(last)
    if sents_last:
        final_sent = sents_last[-1]
        if len(final_sent.split()) < 15:  # short final punch
            score += 1
        if final_sent.startswith(("Don't", "Do ", "Ship ", "Build ", "Kill ", "Use ", "Pick ", "Write ", "The ", "Every ")) or final_sent.endswith(("!", "?")):
            score += 1
        if re.search(r"\b(period|that's|simple as that|easy|hard)\b", final_sent.lower()):
            score += 1
    return min(score, 3)


def analyze_post(path: Path) -> dict:
    content = path.read_text()
    fm, body = parse_frontmatter(content)
    wc = word_count(body)
    avg_sl, std_sl = avg_and_std_sentence_length(body)
    return {
        "path": str(path),
        "title": fm.get("title", path.stem),
        "word_count": wc,
        "avg_sentence_length": round(avg_sl, 2),
        "sentence_length_std": round(std_sl, 2),
        "concreteness_ratio": round(concreteness_ratio(body), 3),
        "mdash_density": round(mdash_density(body), 2),
        "bullet_ratio": round(bullet_ratio(body), 3),
        "internal_link_count": internal_link_count(body),
        "opener_specificity": opener_specificity(body),
        "closer_lands": closer_lands(body),
    }


def pair_up(mine_dir: Path, agent_dir: Path) -> list[tuple[Path, Path, str]]:
    """Match files by topic. Fuzzy — matches any slug containing a common stub."""
    mine_files = sorted(mine_dir.glob("*.md"))
    agent_files = sorted(agent_dir.glob("*.md"))
    pairs = []

    def slug_stems(p):
        name = p.stem.replace("2026-04-19-", "")
        words = name.split("-")
        # Use longest 2 meaningful words
        meaningful = [w for w in words if len(w) > 3 and w not in ("amendment", "the", "for", "in", "design")]
        return meaningful[:3]

    for mf in mine_files:
        stems = slug_stems(mf)
        best = None
        best_score = 0
        for af in agent_files:
            astems = slug_stems(af)
            overlap = len(set(stems) & set(astems))
            if overlap > best_score:
                best_score = overlap
                best = af
        if best and best_score > 0:
            topic = " / ".join(sorted(set(slug_stems(mf)) & set(slug_stems(best))))
            pairs.append((mf, best, topic))
    return pairs


def compare(mine: dict, agent: dict) -> dict:
    """Direction-aware scoring. Positive = mine wins, negative = agent wins.
    Weights informed by Kody's voice signals."""
    signals = {}

    # Word count: target 1000-1500; penalize both under and over
    def wc_score(wc):
        if 1000 <= wc <= 1500: return 1.0
        if 900 <= wc < 1000 or 1500 < wc <= 1600: return 0.7
        if wc < 900 or wc > 1800: return 0.3
        return 0.5

    signals["word_count"] = wc_score(mine["word_count"]) - wc_score(agent["word_count"])

    # Shorter + higher std = better rhythm
    signals["sentence_rhythm"] = (
        (-0.5 * (mine["avg_sentence_length"] - agent["avg_sentence_length"]) / 20)
        + (0.5 * (mine["sentence_length_std"] - agent["sentence_length_std"]) / 10)
    )

    # Concreteness: higher is better
    signals["concreteness"] = (mine["concreteness_ratio"] - agent["concreteness_ratio"]) * 2

    # M-dashes: Kody's signature — higher = more voice-match
    signals["mdash_voice"] = (mine["mdash_density"] - agent["mdash_density"]) / 10

    # Bullets: lower is better (more prose)
    signals["prose_density"] = (agent["bullet_ratio"] - mine["bullet_ratio"]) * 2

    # Links: more is better
    signals["link_density"] = (mine["internal_link_count"] - agent["internal_link_count"]) / 5

    # Opener + closer
    signals["opener"] = (mine["opener_specificity"] - agent["opener_specificity"]) / 3
    signals["closer"] = (mine["closer_lands"] - agent["closer_lands"]) / 3

    total = round(sum(signals.values()), 3)

    # Decision heuristic
    if total > 0.6:
        rec = "mine"
    elif total < -0.6:
        rec = "agent"
    else:
        rec = "merge"

    return {
        "signals": {k: round(v, 3) for k, v in signals.items()},
        "total_score": total,
        "mechanical_recommendation": rec,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mine_dir")
    ap.add_argument("agent_dir")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    mine_dir = Path(args.mine_dir)
    agent_dir = Path(args.agent_dir)
    pairs = pair_up(mine_dir, agent_dir)

    if not pairs:
        print("No pairs matched. Check dir contents.")
        return

    report = {"pairs": []}
    for mine_file, agent_file, topic in pairs:
        mine_stats = analyze_post(mine_file)
        agent_stats = analyze_post(agent_file)
        comparison = compare(mine_stats, agent_stats)
        row = {
            "topic": topic,
            "mine": mine_stats,
            "agent": agent_stats,
            "comparison": comparison,
        }
        report["pairs"].append(row)

        # Print table-style summary
        print(f"\n{'='*78}")
        print(f"TOPIC: {topic}")
        print(f"{'='*78}")
        print(f"{'metric':<25} {'mine':>12} {'agent':>12} {'advantage':>12}")
        print(f"{'-'*65}")
        for key in ("word_count", "avg_sentence_length", "sentence_length_std",
                    "concreteness_ratio", "mdash_density", "bullet_ratio",
                    "internal_link_count", "opener_specificity", "closer_lands"):
            m = mine_stats[key]
            a = agent_stats[key]
            adv = "mine" if (key == "bullet_ratio" and m < a) or (key != "bullet_ratio" and m > a) else "agent" if m != a else "tie"
            print(f"{key:<25} {m:>12} {a:>12} {adv:>12}")
        print(f"\nTotal comparison score: {comparison['total_score']:+.3f}  "
              f"(positive=mine wins, negative=agent wins)")
        print(f"Mechanical recommendation: {comparison['mechanical_recommendation']}")
        print("Signal breakdown:")
        for k, v in comparison["signals"].items():
            sign = "+" if v > 0 else ""
            print(f"  {k:<20} {sign}{v}")

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nReport written to {args.out}")


if __name__ == "__main__":
    main()
