#!/usr/bin/env python3
"""Evaluate twin-authored content against platform fidelity criteria.

Grades every piece against:
  - schema validity (required fields, length bounds)
  - voice signals (absence of anti-patterns: emoji spam, buzzwords,
    'humbled and excited', (1/10) thread indicators, etc.)
  - substance floor (minimum word/char content, concrete nouns, no pure filler)
  - diversity (Simpson index on topics + authors — no one topic dominating)
  - dedup (Jaccard on trigram shingles)

Output:
  state/twin_content/evaluation.json   — machine-readable report
  docs/twin-quality.md                 — human-readable report

Usage:
  python scripts/evaluate_twin_content.py
  python scripts/evaluate_twin_content.py --platform twitter
  python scripts/evaluate_twin_content.py --fail-below 70  # CI gate
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, now_iso  # noqa: E402
from twin_voices import PLATFORMS  # noqa: E402

CONTENT_DIR = Path(os.environ.get(
    "TWIN_CONTENT_DIR", ROOT / "state" / "twin_content"
))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", ROOT / "docs"))

# Anti-patterns flagged across platforms (case-insensitive regex)
UNIVERSAL_ANTIPATTERNS = [
    (r"\bhumbled and excited\b", "corporate-speak"),
    (r"\bthrilled to announce\b", "corporate-speak"),
    (r"\bgame[\-\s]?changer\b", "buzzword"),
    (r"\bsynerg(y|ies|ize)\b", "buzzword"),
    (r"\bleverag(e|ing)\b", "buzzword"),
    (r"\brevolutionar(y|ize)\b", "buzzword"),
    (r"\bcutting[\-\s]edge\b", "buzzword"),
    (r"\bdisrupt(ing|ive|ion)\b", "buzzword"),
    (r"\bparadigm shift\b", "buzzword"),
    (r"^\s*\(1/\d+\)", "manual-thread-marker"),
    (r"\bAgree\?\s*$", "engagement-bait"),
    (r"Thoughts\??\s*(👇|⬇|below)?\s*$", "engagement-bait"),
    (r"Upvote if", "engagement-bait"),
    (r"(👆|🚀|🔥|💡){2,}", "emoji-spam"),
    (r"\bas an AI\b", "llm-tell"),
    (r"\bI('m| am) (an|a) (AI|language model)", "llm-tell"),
]

PLATFORM_SPECIFIC = {
    "twitter": [
        (r"^(RT|Retweet)", "rt-prefix-in-original"),
        (r"#[A-Z][a-zA-Z]*#[A-Z]", "hashtag-stacking"),
    ],
    "hackernews": [
        (r"^🔥|^💡|^🚀", "emoji-title"),
        (r"TOP \d+|BEST", "listicle-title"),
    ],
    "reddit": [
        (r"Hey reddit", "reddit-opener"),
        (r"Long time lurker", "reddit-cliche"),
    ],
    "linkedin": [
        (r"\bmy journey\b", "linkedin-cliche"),
        (r"\bI'm humbled\b", "linkedin-cliche"),
    ],
    "medium": [
        (r"^\d+ (Reasons|Ways|Things)", "listicle-title"),
    ],
}


def _text_for_grading(item: dict, platform: str) -> str:
    """Concatenate all content text for a piece."""
    if platform == "twitter":
        parts = [item.get("text", "")]
        if item.get("thread"):
            parts.extend(item["thread"])
        return "\n".join(parts)
    if platform == "hackernews":
        return f"{item.get('title','')}\n{item.get('body','')}"
    if platform == "reddit":
        return f"{item.get('title','')}\n{item.get('selftext','')}"
    if platform == "linkedin":
        return f"{item.get('headline','')}\n{item.get('body','')}"
    if platform == "medium":
        return f"{item.get('title','')}\n{item.get('subtitle','')}\n{item.get('body_markdown','')}"
    return json.dumps(item)


def _shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i+k]) for i in range(len(words) - k + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def _grade_piece(item: dict, platform: str) -> dict:
    text = _text_for_grading(item, platform)
    wc = len(text.split())
    flags = []

    for pat, label in UNIVERSAL_ANTIPATTERNS + PLATFORM_SPECIFIC.get(platform, []):
        if re.search(pat, text, re.IGNORECASE | re.MULTILINE):
            flags.append(label)

    # Substance heuristics
    if wc < 8:
        flags.append("too-thin")
    # Concrete-noun ratio (rough signal: presence of specific numbers, file paths, URLs)
    has_number = bool(re.search(r"\b\d+\b", text))
    has_specific = bool(re.search(r"\b(rappterbook|rappter|zion|schema|twin|api|github|json|curl|\.py|\.json|\.html)\b", text, re.IGNORECASE))
    if not (has_number or has_specific):
        flags.append("no-specifics")

    # Grade: start at 100, subtract per flag
    score = 100
    for f in flags:
        if f in ("too-thin", "corporate-speak", "llm-tell"):
            score -= 25
        elif f in ("buzzword", "emoji-spam", "listicle-title", "engagement-bait"):
            score -= 15
        else:
            score -= 8
    score = max(0, score)
    return {"score": score, "flags": flags, "word_count": wc}


def _items_key(platform: str) -> str:
    return {
        "twitter": "tweets",
        "hackernews": "posts",
        "reddit": "posts",
        "linkedin": "posts",
        "medium": "articles",
    }[platform]


def evaluate_platform(platform: str) -> dict:
    data = load_json(CONTENT_DIR / f"{platform}.json")
    items = data.get(_items_key(platform), [])
    if not items:
        return {"platform": platform, "count": 0, "avg_score": 0,
                "grade": "F", "pieces": [], "diversity": {}, "dedup": {}}

    pieces = []
    shingle_sets = []
    topics = []
    authors = []

    for idx, item in enumerate(items):
        g = _grade_piece(item, platform)
        pieces.append({
            "idx": idx,
            "score": g["score"],
            "flags": g["flags"],
            "word_count": g["word_count"],
            "preview": _text_for_grading(item, platform)[:140].replace("\n", " "),
        })
        shingle_sets.append(_shingles(_text_for_grading(item, platform)))
        topics.append(item.get("topic", "unknown"))
        author_key = {
            "twitter": "handle",
            "hackernews": "by",
            "reddit": "author",
            "linkedin": "author",
            "medium": "author",
        }[platform]
        authors.append(item.get(author_key, "unknown"))

    # Dedup pairs: flag any piece pair with Jaccard > 0.4
    near_dups = []
    for i in range(len(shingle_sets)):
        for j in range(i + 1, len(shingle_sets)):
            sim = _jaccard(shingle_sets[i], shingle_sets[j])
            if sim > 0.4:
                near_dups.append({"i": i, "j": j, "jaccard": round(sim, 3)})
                pieces[i]["flags"].append(f"near-dup-of-{j}")
                pieces[i]["score"] = max(0, pieces[i]["score"] - 20)

    # Diversity: Simpson (1 = perfectly uniform, 0 = one item dominates)
    def simpson(xs):
        c = Counter(xs)
        total = sum(c.values())
        if total < 2:
            return 0.0
        return 1.0 - sum((n * (n - 1)) for n in c.values()) / (total * (total - 1))

    topic_diversity = round(simpson(topics), 3)
    author_diversity = round(simpson(authors), 3)

    avg = sum(p["score"] for p in pieces) / len(pieces)
    # Diversity bonus/penalty: up to ±10
    diversity_adj = (topic_diversity + author_diversity) / 2 * 20 - 10
    final_score = max(0, min(100, avg + diversity_adj))

    grade = (
        "A" if final_score >= 90 else
        "B" if final_score >= 80 else
        "C" if final_score >= 70 else
        "D" if final_score >= 60 else
        "F"
    )

    return {
        "platform": platform,
        "count": len(items),
        "avg_piece_score": round(avg, 1),
        "topic_diversity": topic_diversity,
        "author_diversity": author_diversity,
        "final_score": round(final_score, 1),
        "grade": grade,
        "flag_counts": dict(Counter(f for p in pieces for f in p["flags"])),
        "near_dup_pairs": near_dups[:20],
        "pieces": pieces,
        "weakest": sorted(pieces, key=lambda p: p["score"])[:5],
        "strongest": sorted(pieces, key=lambda p: -p["score"])[:5],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Twin Content Quality Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Overall grade: **{report['overall_grade']}** (score {report['overall_score']})",
        "",
        "## By platform",
        "",
        "| Platform | Items | Avg Piece | Topic Div | Author Div | Final | Grade |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in report["platforms"]:
        lines.append(
            f"| {p['platform']} | {p['count']} | {p['avg_piece_score']} | "
            f"{p['topic_diversity']} | {p['author_diversity']} | {p['final_score']} | "
            f"**{p['grade']}** |"
        )

    for p in report["platforms"]:
        lines += ["", f"## {p['platform']} detail", ""]
        if p["flag_counts"]:
            lines.append("**Flag counts:**")
            for f, n in sorted(p["flag_counts"].items(), key=lambda x: -x[1])[:10]:
                lines.append(f"- `{f}` × {n}")
            lines.append("")
        if p["weakest"]:
            lines.append("**Weakest pieces (revise these):**")
            for w in p["weakest"]:
                flagstr = ", ".join(w["flags"]) or "—"
                lines.append(f"- #{w['idx']} score={w['score']} flags=[{flagstr}]  \n  `{w['preview']}`")
            lines.append("")
        if p["strongest"]:
            lines.append("**Strongest pieces:**")
            for s in p["strongest"]:
                lines.append(f"- #{s['idx']} score={s['score']}  \n  `{s['preview']}`")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="all")
    ap.add_argument("--fail-below", type=float, default=0,
                    help="exit 1 if overall score below this")
    args = ap.parse_args()

    platforms = (list(PLATFORMS.keys())
                 if args.platform == "all"
                 else [args.platform])

    reports = [evaluate_platform(p) for p in platforms]
    overall_score = (
        round(sum(r["final_score"] for r in reports) / len(reports), 1)
        if reports else 0
    )
    overall_grade = (
        "A" if overall_score >= 90 else
        "B" if overall_score >= 80 else
        "C" if overall_score >= 70 else
        "D" if overall_score >= 60 else
        "F"
    )

    report = {
        "generated_at": now_iso(),
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "platforms": reports,
    }

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    save_json(CONTENT_DIR / "evaluation.json", report)
    md = render_markdown(report)
    (DOCS_DIR / "twin-quality.md").write_text(md)

    print(f"overall: {overall_grade} ({overall_score})")
    for r in reports:
        print(f"  {r['platform']:12s} {r['grade']} ({r['final_score']}) — {r['count']} items")

    if overall_score < args.fail_below:
        sys.exit(1)


if __name__ == "__main__":
    main()
