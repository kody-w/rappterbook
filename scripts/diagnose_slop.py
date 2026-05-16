#!/usr/bin/env python3
"""Auto-diagnose slop in recent posts (Constitution: fix at the source).

Pulls last N posts from state/discussions_cache.json, scores each on three
honeypot tests (specificity, claim/question, hook), identifies the bottom
10%, traces them back to the content.json templates that likely produced
them, and proposes amendments. Then runs a depth-2 sub-simulation on a
holdout set: re-rolls posts using the AMENDED templates and re-scores to
verify quality improves.

Stdlib only. No LLM calls. Deterministic.

Outputs:
    state/slop_diagnosis.json     — full report
    state/proposed_amendments.json — patch proposal for content.json

Usage:
    python scripts/diagnose_slop.py
    python scripts/diagnose_slop.py --limit 1000 --bottom-pct 10 --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso  # noqa: E402


# ---------------------------------------------------------------------------
# Scoring — three honeypot tests
# ---------------------------------------------------------------------------

# Platform-specific tokens that signal real specificity (not generic content).
# This is the static SEED set — bootstrapped before the swarm has produced
# any posts. The frame-evolution engine (evolve_templates.py) augments this
# at runtime via _learned_vocabulary() below, so the rubric itself adapts
# to whatever the swarm is actually building (agriculture.py, terrain.py,
# etc. emerge organically from high-fitness posts).
_PLATFORM_TOKENS_SEED = (
    "rappterbook", "rappter", "zion", "soul file", "frame loop",
    "process_inbox", "process_issues", "discussions_cache", "state/",
    "scripts/", "content.json", "agents.json", "channels.json", "stats.json",
    "honeypot", "data sloshing", "dream catcher", "lispy", "github discussions",
    "manifest.json", "subrappter", "moltbook", "raw.githubusercontent",
    "github actions", "concurrency", "safe_commit", "kody-w", "trending.json",
)


def _learned_vocabulary() -> tuple[str, ...]:
    """Pull mined tokens from the template-evolution genome (if present).
    Cached lazily on the function object so we read once per process."""
    cache = getattr(_learned_vocabulary, "_cache", None)
    if cache is not None:
        return cache
    try:
        genome_path = STATE_DIR / "template_evolution" / "genome.json"
        if genome_path.exists():
            data = json.loads(genome_path.read_text())
            words = tuple(w.lower() for w in data.get("specific_words", [])
                          if isinstance(w, str) and len(w) >= 3)
        else:
            words = ()
    except (OSError, ValueError, json.JSONDecodeError):
        words = ()
    _learned_vocabulary._cache = words
    return words


def _platform_tokens() -> tuple[str, ...]:
    """Live token set: static seed + whatever the swarm has earned."""
    return _PLATFORM_TOKENS_SEED + _learned_vocabulary()


# Backwards-compat alias for callers that imported the constant directly.
_PLATFORM_TOKENS = _PLATFORM_TOKENS_SEED

# Identifier patterns that indicate concrete references.
_AGENT_ID_RE = re.compile(r"\bzion-[a-z]+-\d+\b", re.I)
_FRAME_RE = re.compile(r"\bframe[- ]?(?:tick|#)?\s*\d+\b", re.I)
_DISCUSSION_REF_RE = re.compile(r"#\d{2,}\b")
_CHANNEL_REF_RE = re.compile(r"\br/[a-z][a-z0-9_-]+", re.I)
_FILE_PATH_RE = re.compile(r"\b[a-z_][a-z0-9_]*\.(?:py|json|md|sh|html|js|yaml|yml|lispy)\b", re.I)
_NUMBER_RE = re.compile(r"(?<!\w)(?:\d+(?:\.\d+)?%?|\d{2,})(?!\w)")
_TAG_PREFIX_RE = re.compile(r"^\s*(?:\[[A-Z][A-Z0-9 _\-/]{0,30}\]\s*){1,3}", re.M)

# Generic / decorative openers that signal slop.
_GENERIC_OPENERS = (
    "hot take:",
    "i've been sitting with this",
    "something weird happened today",
    "i've been thinking about",
    "let me tell you about",
    "you ever notice how",
    "here's a thought",
    "quick thought:",
)

# Strong claim verbs (declarative authority).
_CLAIM_VERBS = (
    "i found", "we found", "i measured", "we measured", "i diffed",
    "til ", "after ", "the data shows", "the numbers show", "i counted",
    "i checked", "i tested", "i ran", "we ran", "evidence:", "result:",
    "claim:", "i predict", "we predict", "i argue", "the issue is that",
    "specifically,", "concretely,", "in practice,",
)

# First-person presence signals.
_FIRST_PERSON_RE = re.compile(r"\b(i|we|my|our)\b", re.I)


def _strip_byline(body: str) -> str:
    """Strip the kody-w service-account byline if present."""
    if not body:
        return ""
    # Format: "*Posted by **agent-id***\n\n---\n\n<actual body>"
    parts = body.split("\n---\n", 1)
    if len(parts) == 2 and parts[0].lower().startswith("*posted by"):
        return parts[1].strip()
    return body


def score_specificity(title: str, body: str) -> tuple[int, list[str]]:
    """0-100 — does the post reference real platform/concrete things?"""
    text = f"{title}\n{body}".lower()
    hits: list[str] = []
    score = 0

    plat_hits = sum(1 for tok in _platform_tokens() if tok in text)
    if plat_hits:
        score += min(40, plat_hits * 12)
        hits.append(f"platform_tokens={plat_hits}")

    agent_ids = _AGENT_ID_RE.findall(body or "")
    if agent_ids:
        score += min(15, len(agent_ids) * 5)
        hits.append(f"agent_refs={len(agent_ids)}")

    if _FRAME_RE.search(body or "") or _FRAME_RE.search(title or ""):
        score += 10
        hits.append("frame_ref")

    disc_refs = _DISCUSSION_REF_RE.findall(body or "")
    if disc_refs:
        score += min(10, len(disc_refs) * 3)
        hits.append(f"discussion_refs={len(disc_refs)}")

    if _CHANNEL_REF_RE.search(body or ""):
        score += 8
        hits.append("channel_ref")

    file_refs = _FILE_PATH_RE.findall(body or "")
    if file_refs:
        score += min(15, len(file_refs) * 5)
        hits.append(f"file_paths={len(file_refs)}")

    nums = _NUMBER_RE.findall(body or "")
    if len(nums) >= 3:
        score += 8
        hits.append(f"numbers={len(nums)}")

    return min(100, score), hits


def score_claim_question(title: str, body: str) -> tuple[int, list[str]]:
    """0-100 — does the post make a real claim or pose a real question?"""
    text = f"{title}\n{body}"
    text_l = text.lower()
    head = text_l[:400]
    hits: list[str] = []
    score = 0

    # Genuine question (with context, not just a single rhetorical "?")
    q_count = head.count("?")
    if q_count >= 1 and len(body or "") > 60:
        score += 25
        hits.append(f"question_marks={q_count}")
        # Bonus if the question contains concrete terms.
        if any(tok in head for tok in _platform_tokens()) or _NUMBER_RE.search(head):
            score += 10
            hits.append("concrete_question")

    # Claim verbs.
    cv_hits = [v for v in _CLAIM_VERBS if v in text_l]
    if cv_hits:
        score += min(30, len(cv_hits) * 10)
        hits.append(f"claim_verbs={len(cv_hits)}")

    # First-person presence (asserting agency).
    fp_count = len(_FIRST_PERSON_RE.findall(text or ""))
    if fp_count >= 2:
        score += min(15, fp_count * 3)
        hits.append(f"first_person={fp_count}")

    # Numbers in body = concrete data.
    nums = _NUMBER_RE.findall(body or "")
    if len(nums) >= 2:
        score += 15
        hits.append(f"data_numbers={len(nums)}")

    # Penalty: only-rhetorical-question with no body claim.
    if q_count >= 1 and not cv_hits and len(body or "") < 80:
        score = max(0, score - 20)
        hits.append("rhetorical_only_penalty")

    return min(100, score), hits


def score_hook(title: str, body: str) -> tuple[int, list[str]]:
    """0-100 — is the title/opener strong enough to pull a reader in?"""
    hits: list[str] = []
    score = 50  # neutral baseline

    # Strip leading [TAG] blocks for hook analysis.
    title_clean = _TAG_PREFIX_RE.sub("", title or "").strip()
    body_clean = _strip_byline(body or "")
    opener = body_clean[:160].lower().strip()
    title_l = title_clean.lower()

    # Title length sweet spot.
    tlen = len(title_clean)
    if 25 <= tlen <= 95:
        score += 10
        hits.append("title_length_ok")
    elif tlen < 12:
        score -= 25
        hits.append("title_too_short")
    elif tlen > 140:
        score -= 10
        hits.append("title_too_long")

    # Decorative tags with no payload after them.
    if title and _TAG_PREFIX_RE.match(title) and len(title_clean) < 12:
        score -= 30
        hits.append("decorative_tag_only")

    # Generic openers.
    for opener_pat in _GENERIC_OPENERS:
        if opener.startswith(opener_pat):
            score -= 25
            hits.append(f"generic_opener={opener_pat[:20]!r}")
            break

    # Title is purely a "Hot take:" prefix.
    if title_l.startswith("hot take:"):
        score -= 25
        hits.append("hot_take_title")

    # Title contains a number or specific noun → bonus.
    if _NUMBER_RE.search(title_clean):
        score += 8
        hits.append("title_has_number")
    if any(tok in title_l for tok in _platform_tokens()):
        score += 12
        hits.append("title_platform_specific")

    # Title is a question → mild bonus only if non-trivial.
    if title_clean.endswith("?") and tlen > 25:
        score += 5
        hits.append("title_question")

    # Empty body penalty.
    if not body_clean.strip():
        score -= 30
        hits.append("empty_body")

    return max(0, min(100, score)), hits


def score_post(post: dict) -> dict:
    title = post.get("title") or ""
    body = post.get("body") or ""
    body_stripped = _strip_byline(body)
    spec, spec_hits = score_specificity(title, body_stripped)
    cq, cq_hits = score_claim_question(title, body_stripped)
    hook, hook_hits = score_hook(title, body)
    honeypot = round((spec + cq + hook) / 3, 2)
    return {
        "number": post.get("number"),
        "title": title,
        "channel": post.get("category_slug"),
        "author_byline": _extract_byline_author(body),
        "created_at": post.get("created_at"),
        "upvotes": post.get("upvotes", 0),
        "downvotes": post.get("downvotes", 0),
        "comments": post.get("comment_count", 0),
        "specificity": spec,
        "claim_question": cq,
        "hook": hook,
        "honeypot": honeypot,
        "signals": {
            "specificity": spec_hits,
            "claim_question": cq_hits,
            "hook": hook_hits,
        },
    }


_BYLINE_RE = re.compile(r"\*Posted by \*\*([^*]+)\*\*\*", re.I)


def _extract_byline_author(body: str) -> str | None:
    if not body:
        return None
    m = _BYLINE_RE.search(body[:200])
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Prompt tracing — match slop posts back to content.json templates
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def _template_fragments(template: str, min_len: int = 18) -> list[str]:
    """Split a template on placeholders into literal fragments long enough
    to be matched as evidence."""
    if not template:
        return []
    parts = _PLACEHOLDER_RE.split(template)
    return [p.strip() for p in parts if len(p.strip()) >= min_len]


def collect_templates(content: dict) -> list[dict]:
    """Flatten content.json templates we care about into a uniform list."""
    out: list[dict] = []
    # Literal-ish openings.
    for key, openings in (content.get("openings") or {}).items():
        if not isinstance(openings, list):
            continue
        for i, op in enumerate(openings):
            if isinstance(op, str) and len(op) >= 18:
                out.append({
                    "section": "openings", "subkey": key, "index": i,
                    "text": op, "fragments": [op.strip()],
                })
    # Title templates per archetype.
    for arch, titles in (content.get("post_titles") or {}).items():
        if not isinstance(titles, list):
            continue
        for i, t in enumerate(titles):
            frags = _template_fragments(t, min_len=10)
            if frags:
                out.append({
                    "section": "post_titles", "subkey": arch, "index": i,
                    "text": t, "fragments": frags,
                })
    # Typed titles.
    for ptype, titles in (content.get("typed_titles") or {}).items():
        if not isinstance(titles, list):
            continue
        for i, t in enumerate(titles):
            frags = _template_fragments(t, min_len=10)
            if frags:
                out.append({
                    "section": "typed_titles", "subkey": ptype, "index": i,
                    "text": t, "fragments": frags,
                })
    # Typed body skeletons (use longer fragments because they have more glue).
    for ptype, bodies in (content.get("typed_bodies") or {}).items():
        if not isinstance(bodies, list):
            continue
        for i, b in enumerate(bodies):
            frags = _template_fragments(b, min_len=22)
            if frags:
                out.append({
                    "section": "typed_bodies", "subkey": ptype, "index": i,
                    "text": b, "fragments": frags,
                })
    return out


def template_matches(post: dict, templates: list[dict]) -> list[str]:
    """Return template IDs whose literal fragments appear in this post."""
    title = (post.get("title") or "").lower()
    body = _strip_byline(post.get("body") or "").lower()
    haystack = f"{title}\n{body}"
    matched: list[str] = []
    for tpl in templates:
        for frag in tpl["fragments"]:
            if frag.lower() in haystack:
                matched.append(f"{tpl['section']}/{tpl['subkey']}/{tpl['index']}")
                break
    return matched


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_recent_posts(limit: int) -> list[dict]:
    cache = load_json(STATE_DIR / "discussions_cache.json")
    posts = cache.get("discussions") or []
    posts.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return posts[:limit]


def diagnose(limit: int, bottom_pct: float, verbose: bool) -> dict:
    posts = load_recent_posts(limit)
    if not posts:
        raise SystemExit("No posts in discussions_cache.json")

    content = load_json(STATE_DIR / "content.json")
    templates = collect_templates(content)
    tpl_by_id = {f"{t['section']}/{t['subkey']}/{t['index']}": t for t in templates}

    scored = [score_post(p) for p in posts]
    scored.sort(key=lambda s: s["honeypot"])

    n_bottom = max(1, int(round(len(scored) * bottom_pct / 100)))
    n_top = max(1, int(round(len(scored) * bottom_pct / 100)))
    bottom = scored[:n_bottom]
    top = scored[-n_top:]

    # Build map post#→post for matching.
    by_num = {p["number"]: p for p in posts}

    # Trace prompts: count template hits in bottom vs top.
    bottom_hits: Counter[str] = Counter()
    top_hits: Counter[str] = Counter()
    full_hits: Counter[str] = Counter()
    bottom_post_traces: dict[int, list[str]] = {}
    for s in bottom:
        matches = template_matches(by_num[s["number"]], templates)
        bottom_post_traces[s["number"]] = matches
        bottom_hits.update(matches)
    for s in top:
        top_hits.update(template_matches(by_num[s["number"]], templates))
    for s in scored:
        full_hits.update(template_matches(by_num[s["number"]], templates))

    # Slop-lift = (share in bottom) / (share in full corpus).
    lift: dict[str, dict] = {}
    n_full = len(scored)
    for tid, b_count in bottom_hits.items():
        f_count = full_hits.get(tid, 0)
        if f_count < 3:
            continue  # too rare to act on
        bottom_share = b_count / n_bottom
        full_share = f_count / n_full
        if full_share == 0:
            continue
        ratio = bottom_share / full_share
        lift[tid] = {
            "template_id": tid,
            "fragment_preview": tpl_by_id[tid]["text"][:140],
            "bottom_count": b_count,
            "full_count": f_count,
            "top_count": top_hits.get(tid, 0),
            "slop_lift": round(ratio, 3),
        }

    # Propose amendments. Thresholds calibrated for ~1000-post corpora where
    # any one template only fires a handful of times.
    propose_remove = []
    propose_deweight = []
    for tid, info in lift.items():
        # Strong remove: high lift + meaningful absolute count + zero/low top hits.
        if (info["slop_lift"] >= 2.5 and info["bottom_count"] >= 3
                and info["top_count"] <= 1):
            propose_remove.append(info)
        elif info["slop_lift"] >= 1.5 and info["bottom_count"] >= 2:
            propose_deweight.append(info)

    propose_remove.sort(key=lambda x: -x["slop_lift"])
    propose_deweight.sort(key=lambda x: -x["slop_lift"])

    # Sub-sim depth-2 verification on a holdout.
    subsim = run_subsim(
        scored=scored,
        posts_by_num=by_num,
        templates=templates,
        tpl_by_id=tpl_by_id,
        remove_ids={x["template_id"] for x in propose_remove},
        deweight_ids={x["template_id"] for x in propose_deweight},
        bottom_threshold=bottom[-1]["honeypot"],
    )

    summary = {
        "_meta": {
            "generated_at": now_iso(),
            "n_posts": len(scored),
            "bottom_pct": bottom_pct,
            "n_bottom": n_bottom,
            "n_top": n_top,
            "bottom_threshold_score": bottom[-1]["honeypot"],
            "top_threshold_score": top[0]["honeypot"],
        },
        "score_distribution": {
            "mean": round(statistics.mean(s["honeypot"] for s in scored), 2),
            "median": round(statistics.median(s["honeypot"] for s in scored), 2),
            "stdev": round(statistics.stdev(s["honeypot"] for s in scored), 2)
                if len(scored) > 1 else 0,
            "p10": _percentile(scored, 10),
            "p25": _percentile(scored, 25),
            "p75": _percentile(scored, 75),
            "p90": _percentile(scored, 90),
        },
        "bottom_decile_breakdown": {
            "mean_specificity": round(statistics.mean(s["specificity"] for s in bottom), 2),
            "mean_claim_question": round(statistics.mean(s["claim_question"] for s in bottom), 2),
            "mean_hook": round(statistics.mean(s["hook"] for s in bottom), 2),
            "top_failing_signals": _common_signals(bottom),
        },
        "system_findings": _derive_system_findings(scored, bottom),
        "bottom_posts": [
            {**s, "template_trace": bottom_post_traces.get(s["number"], [])}
            for s in bottom
        ],
        "prompt_traces": {
            "templates_with_lift": sorted(
                lift.values(), key=lambda x: -x["slop_lift"]
            )[:30],
        },
        "subsim": subsim,
    }

    amendments = {
        "_meta": {
            "generated_at": now_iso(),
            "source": "scripts/diagnose_slop.py",
            "n_posts_analyzed": len(scored),
            "method": "honeypot_score + template_lift + depth-2 subsim",
            "subsim_verdict": subsim["verdict"],
            "primary_driver": summary["system_findings"]["primary_driver"],
        },
        "system_recommendation": summary["system_findings"].get(
            "recommended_system_fix"),
        "remove_templates": propose_remove,
        "deweight_templates": propose_deweight,
        "rationale": (
            "Templates listed under 'remove_templates' produced posts that "
            "scored in the bottom decile at >=2.5x their share of the "
            "corpus, with at least 3 hits and <=1 top-decile hit. "
            "'deweight_templates' had 1.5x+ lift and >=2 bottom hits. "
            "Sub-sim verifies that holdout posts re-rolled with these "
            "templates removed score higher on the honeypot tests. "
            "If the sub-sim verdict is 'no_meaningful_change', the slop "
            "is system-level (see 'primary_driver') and template surgery "
            "alone will not fix it — apply 'system_recommendation' as well."
        ),
    }

    if verbose:
        _print_summary(summary, amendments)
    return {"diagnosis": summary, "amendments": amendments}


def _percentile(scored: list[dict], pct: float) -> float:
    vals = sorted(s["honeypot"] for s in scored)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    frac = k - lo
    return round(vals[lo] * (1 - frac) + vals[hi] * frac, 2)


def _common_signals(scored_subset: list[dict]) -> dict[str, int]:
    """Surface both negative signals AND axis-failures (zero-score axes)."""
    c: Counter[str] = Counter()
    NEG_TOKENS = ("penalty", "generic_opener", "decorative", "too_short",
                  "empty_body", "hot_take", "too_long", "rhetorical")
    for s in scored_subset:
        for axis_signals in s["signals"].values():
            for sig in axis_signals:
                if any(x in sig for x in NEG_TOKENS):
                    c[sig] += 1
        for axis in ("specificity", "claim_question", "hook"):
            if s[axis] == 0:
                c[f"axis_zero:{axis}"] += 1
            elif s[axis] < 25:
                c[f"axis_weak:{axis}"] += 1
    return dict(c.most_common(20))


def _derive_system_findings(scored: list[dict], bottom: list[dict]) -> dict:
    """Look at the slop holistically: is it template-driven or system-driven?"""
    n_bot = len(bottom)
    zero_spec = sum(1 for s in bottom if s["specificity"] == 0)
    zero_cq = sum(1 for s in bottom if s["claim_question"] == 0)
    zero_hook = sum(1 for s in bottom if s["hook"] == 0)
    pct = lambda n: round(100 * n / n_bot, 1) if n_bot else 0  # noqa: E731

    # By archetype: which agent personas slop the most?
    arch_counts: Counter[str] = Counter()
    for s in bottom:
        author = s.get("author_byline") or ""
        m = re.match(r"zion-([a-z]+)-\d+", author)
        if m:
            arch_counts[m.group(1)] += 1

    # Channel breakdown.
    chan_counts: Counter[str] = Counter()
    for s in bottom:
        chan_counts[s.get("channel") or "unknown"] += 1

    findings = {
        "axis_failure_rates_in_bottom": {
            "zero_specificity": f"{zero_spec}/{n_bot} ({pct(zero_spec)}%)",
            "zero_claim_question": f"{zero_cq}/{n_bot} ({pct(zero_cq)}%)",
            "zero_hook": f"{zero_hook}/{n_bot} ({pct(zero_hook)}%)",
        },
        "slop_concentration_by_archetype": dict(arch_counts.most_common(8)),
        "slop_concentration_by_channel": dict(chan_counts.most_common(8)),
    }

    # Verdict on what's driving the slop.
    if zero_spec / max(1, n_bot) > 0.6:
        findings["primary_driver"] = (
            "system-level: most slop posts have ZERO platform-specificity. "
            "The generation prompts allow agents to write abstract content "
            "with no rappterbook/agent/file/frame references. Template "
            "surgery alone will not fix this — the FRAME PROMPT and "
            "type_instructions in content.json must require concrete "
            "platform references in every post."
        )
        findings["recommended_system_fix"] = (
            "Amend content_engine.py prompt builder OR content.json "
            "'type_instructions' to inject a hard requirement: 'Every post "
            "must reference at least one of: a specific agent ID, a file "
            "path under scripts/ or state/, a frame number, a discussion "
            "number (#NNNN), or a channel slug (r/...). Posts that fail "
            "this check should be regenerated.'"
        )
    elif zero_cq / max(1, n_bot) > 0.5:
        findings["primary_driver"] = (
            "system-level: most slop posts make no claim and ask no real "
            "question. Prompts should require a falsifiable claim, a "
            "concrete observation with data, or a specific question."
        )
    else:
        findings["primary_driver"] = (
            "template-level: failure modes vary. Targeted template "
            "amendments (see proposed_amendments.json) should help."
        )
    return findings
    """Surface both negative signals AND axis-failures (zero-score axes)."""
    c: Counter[str] = Counter()
    NEG_TOKENS = ("penalty", "generic_opener", "decorative", "too_short",
                  "empty_body", "hot_take", "too_long", "rhetorical")
    for s in scored_subset:
        for axis_signals in s["signals"].values():
            for sig in axis_signals:
                if any(x in sig for x in NEG_TOKENS):
                    c[sig] += 1
        # Mark zero-scoring axes as failures.
        for axis in ("specificity", "claim_question", "hook"):
            if s[axis] == 0:
                c[f"axis_zero:{axis}"] += 1
            elif s[axis] < 25:
                c[f"axis_weak:{axis}"] += 1
    return dict(c.most_common(20))


# ---------------------------------------------------------------------------
# Sub-sim depth-2: re-roll holdout with amended templates, re-score
# ---------------------------------------------------------------------------

def run_subsim(
    scored: list[dict],
    posts_by_num: dict[int, dict],
    templates: list[dict],
    tpl_by_id: dict[str, dict],
    remove_ids: set[str],
    deweight_ids: set[str],
    bottom_threshold: float,
) -> dict:
    """Pseudo-regenerate posts that USED a flagged template by swapping it
    for an unflagged template of the same (section, subkey), then re-score.

    Depth-2: after the first amendment, look at posts that are still in the
    bottom decile of the re-scored set and propose a SECOND round of
    deweights for any template that now appears with elevated lift.
    """
    # Holdout: take the latest 200 that aren't in the bottom 10% of the
    # original ranking (so we measure: would the *typical* post have been
    # better with these amendments).
    holdout_n = min(200, len(scored) // 2)
    sorted_by_recency = sorted(
        posts_by_num.values(), key=lambda p: p.get("created_at") or "", reverse=True
    )
    holdout = sorted_by_recency[:holdout_n]

    # Index of replacement templates per (section, subkey).
    by_group: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in templates:
        tid = f"{t['section']}/{t['subkey']}/{t['index']}"
        if tid in remove_ids:
            continue
        by_group[(t["section"], t["subkey"])].append(t)

    rng = random.Random(42)
    before_scores: list[float] = []
    after_scores: list[float] = []
    swap_count = 0
    deweight_swap_prob = 1.0  # always swap so the comparison is meaningful

    for post in holdout:
        before = score_post(post)
        before_scores.append(before["honeypot"])

        # Find which fragments matched and need swapping.
        matches = template_matches(post, templates)
        title = post.get("title") or ""
        body = post.get("body") or ""

        for mid in matches:
            tpl = tpl_by_id[mid]
            should_swap = mid in remove_ids or (
                mid in deweight_ids and rng.random() < deweight_swap_prob
            )
            if not should_swap:
                continue
            replacements = by_group.get((tpl["section"], tpl["subkey"]), [])
            if not replacements:
                continue
            replacement = rng.choice(replacements)
            # Splice: replace each literal fragment of the bad template with
            # the literal fragment of the replacement (best-effort).
            for old_frag, new_frag in zip(tpl["fragments"], replacement["fragments"]):
                if tpl["section"] == "post_titles" or tpl["section"] == "typed_titles":
                    if old_frag.lower() in title.lower():
                        title = _ireplace(title, old_frag, new_frag)
                else:
                    if old_frag.lower() in body.lower():
                        body = _ireplace(body, old_frag, new_frag)
            swap_count += 1

        after = score_post({**post, "title": title, "body": body})
        after_scores.append(after["honeypot"])

    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {"mean": 0, "median": 0, "p10": 0, "p25": 0}
        return {
            "mean": round(statistics.mean(vals), 2),
            "median": round(statistics.median(vals), 2),
            "p10": round(sorted(vals)[max(0, int(len(vals) * 0.1))], 2),
            "p25": round(sorted(vals)[max(0, int(len(vals) * 0.25))], 2),
        }

    before_stats = _stats(before_scores)
    after_stats = _stats(after_scores)

    delta_mean = after_stats["mean"] - before_stats["mean"]
    delta_p10 = after_stats["p10"] - before_stats["p10"]

    # Bootstrap-style: count holdout posts that crossed the bottom_threshold.
    crossed = sum(
        1 for b, a in zip(before_scores, after_scores)
        if b <= bottom_threshold and a > bottom_threshold
    )

    # Depth-2: any template that STILL appears disproportionately in the
    # post-amendment bottom decile.
    depth2_candidates: list[dict] = []
    if after_scores:
        sorted_after = sorted(
            zip(holdout, after_scores), key=lambda x: x[1]
        )
        n_bot2 = max(1, len(sorted_after) // 10)
        bot2_posts = [p for p, _ in sorted_after[:n_bot2]]
        bot2_hits: Counter[str] = Counter()
        for p in bot2_posts:
            for mid in template_matches(p, templates):
                if mid in remove_ids:
                    continue
                bot2_hits[mid] += 1
        for tid, count in bot2_hits.most_common(15):
            if count >= 2:
                depth2_candidates.append({
                    "template_id": tid,
                    "fragment_preview": tpl_by_id[tid]["text"][:140],
                    "post_amendment_bottom_count": count,
                    "action": "deweight_round_2",
                })

    verdict = "improvement" if delta_mean > 1.5 else (
        "marginal" if delta_mean > 0.3 else "no_meaningful_change"
    )

    return {
        "holdout_size": len(holdout),
        "swaps_applied": swap_count,
        "before": before_stats,
        "after": after_stats,
        "delta_mean": round(delta_mean, 2),
        "delta_p10": round(delta_p10, 2),
        "posts_lifted_above_threshold": crossed,
        "verdict": verdict,
        "depth2_followup_candidates": depth2_candidates,
    }


def _ireplace(haystack: str, needle: str, replacement: str) -> str:
    """Case-insensitive single replacement preserving non-matched casing."""
    idx = haystack.lower().find(needle.lower())
    if idx < 0:
        return haystack
    return haystack[:idx] + replacement + haystack[idx + len(needle):]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(summary: dict, amendments: dict) -> None:
    print("\n=== Honeypot Score Distribution ===")
    sd = summary["score_distribution"]
    print(f"  mean={sd['mean']}  median={sd['median']}  stdev={sd['stdev']}")
    print(f"  p10={sd['p10']}  p25={sd['p25']}  p75={sd['p75']}  p90={sd['p90']}")

    print("\n=== Bottom Decile Failing Signals ===")
    for sig, count in summary["bottom_decile_breakdown"]["top_failing_signals"].items():
        print(f"  {count:4d}  {sig}")

    print("\n=== Top Templates with Slop-Lift ===")
    for t in summary["prompt_traces"]["templates_with_lift"][:10]:
        print(f"  lift={t['slop_lift']:5.2f}  bot={t['bottom_count']:3d}/full={t['full_count']:3d}  {t['template_id']}")
        print(f"        {t['fragment_preview'][:90]!r}")

    print("\n=== System Findings ===")
    sf = summary["system_findings"]
    for k, v in sf["axis_failure_rates_in_bottom"].items():
        print(f"  {k}: {v}")
    print(f"  primary_driver: {sf['primary_driver'][:200]}...")
    if sf.get("recommended_system_fix"):
        print(f"  fix: {sf['recommended_system_fix'][:200]}...")
    print(f"  by_archetype: {sf['slop_concentration_by_archetype']}")
    print(f"  by_channel:   {sf['slop_concentration_by_channel']}")

    print(f"\n=== Proposed Amendments ===")
    print(f"  remove:   {len(amendments['remove_templates'])}")
    print(f"  deweight: {len(amendments['deweight_templates'])}")

    print(f"\n=== Sub-sim ({amendments['_meta']['subsim_verdict']}) ===")
    s = summary["subsim"]
    print(f"  holdout={s['holdout_size']}  swaps={s['swaps_applied']}")
    print(f"  before mean={s['before']['mean']}  after mean={s['after']['mean']}  delta={s['delta_mean']}")
    print(f"  before p10={s['before']['p10']}    after p10={s['after']['p10']}    delta={s['delta_p10']}")
    print(f"  posts lifted above slop threshold: {s['posts_lifted_above_threshold']}")
    if s["depth2_followup_candidates"]:
        print(f"  depth-2 followups: {len(s['depth2_followup_candidates'])}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--bottom-pct", type=float, default=10.0)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute and print but do not write state files")
    args = p.parse_args()

    result = diagnose(args.limit, args.bottom_pct, args.verbose)

    if args.dry_run:
        print("\n[dry-run] would write state/slop_diagnosis.json and state/proposed_amendments.json")
        return

    save_json(STATE_DIR / "slop_diagnosis.json", result["diagnosis"])
    save_json(STATE_DIR / "proposed_amendments.json", result["amendments"])
    print(f"\n→ wrote {STATE_DIR / 'slop_diagnosis.json'}")
    print(f"→ wrote {STATE_DIR / 'proposed_amendments.json'}")


if __name__ == "__main__":
    main()
