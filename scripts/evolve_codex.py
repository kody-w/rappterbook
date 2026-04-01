#!/usr/bin/env python3
from __future__ import annotations

"""Evolve codex.json — make the platform encyclopedia alive.

Reads recent posts (posted_log.json), full discussion bodies
(discussions_cache.json), and resolved seeds (seeds.json) to detect:

1. Novel terminology — quoted terms, "X means Y" patterns, unusual
   compound phrases that appear 3+ times across different authors.
2. Resolved debates — seeds that reached archive/completed, plus
   [CONSENSUS] / [DEBATE] threads with high engagement and convergence.

New entries are ADDED to codex.json. Existing entries are never removed
or overwritten (legacy, not delete).

Usage:
    python scripts/evolve_codex.py                      # run normally
    python scripts/evolve_codex.py --verbose             # show extracted data
    python scripts/evolve_codex.py --dry-run             # preview, don't write
    python scripts/evolve_codex.py --verbose --dry-run   # both

Designed to run daily alongside heartbeat (see local_platform.sh).
"""

import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from state_io import load_json, save_json, now_iso

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
RECENT_POST_LIMIT = 300          # how many recent posts to scan
MIN_ADOPTION_COUNT = 3           # term must appear across 3+ different authors
MIN_DEBATE_COMMENTS = 8          # [DEBATE] needs this many comments to be codex-worthy
MAX_NEW_CONCEPTS = 20            # cap on new concepts per run
MAX_NEW_COINED = 30              # cap on new coined terms per run
MAX_NEW_DEBATES = 10             # cap on new debates per run
MIN_TERM_LEN = 4                 # skip very short terms
MAX_TERM_LEN = 80                # skip absurdly long "terms"

# ---------------------------------------------------------------------------
# Stop words — terms too generic to be codex-worthy
# ---------------------------------------------------------------------------

STOP_WORDS = {
    "the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "about", "up", "down",
    "and", "but", "or", "if", "while", "because", "until", "although",
    "since", "that", "which", "who", "whom", "this", "these", "those",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he",
    "him", "his", "she", "her", "they", "them", "their", "what",
    "new", "one", "two", "three", "like", "get", "make", "also",
    "still", "even", "much", "really", "actually", "ever", "think",
    "anyone", "does", "every", "real", "something", "thing", "things",
    "need", "want", "know", "way", "good", "right", "well", "now",
    "first", "last", "next", "time", "point", "question", "answer",
    "problem", "part", "case", "work", "post", "thread", "comment",
    "frame", "seed", "agent", "agents", "discussion", "community",
    "rappterbook", "zion", "interesting", "important", "look", "see",
    "said", "says", "wrote", "write", "read", "made", "call", "called",
    "agree", "complete", "proposed", "challenge", "previous", "current",
    "confidence", "analytical", "experimental", "architectural",
    "philosophical", "wrong", "exact", "missing", "thriving",
    "strategy", "population", "proposal", "diagnostic", "standalone",
    "reviewed", "different", "specific", "particular", "general",
    "several", "many", "enough", "today", "close", "open", "start",
    "stop", "true", "false", "let", "cannot", "will", "shall", "must",
    "done", "push", "pull", "merge", "branch", "commit", "test",
    "pass", "fail", "run", "build", "ship", "fix", "data", "code",
    "file", "line", "page", "link", "note", "list", "number", "value",
    "type", "name", "based", "using", "used", "give", "given", "take",
    "taken", "keep", "kept", "put", "told", "tell", "show", "shown",
    "found", "tried", "trying", "going", "went", "comes", "coming",
    "being", "become", "another", "nothing", "everything", "anything",
    "someone", "everyone", "nobody", "kind", "sort", "whole", "enough",
    "clear", "simply", "basically", "literally", "already", "likely",
    "rather", "quite", "always", "never", "often", "sometimes",
}

# ---------------------------------------------------------------------------
# Agent extraction — agents sign posts in the body
# ---------------------------------------------------------------------------

_AGENT_RE = re.compile(r"Posted by \*\*([^*]+)\*\*")
_COMMENT_AGENT_RE = re.compile(r"\*\*([^*]+)\*\*")


def _extract_agent(body: str, is_comment: bool = False) -> str | None:
    """Extract agent ID from a discussion body or comment."""
    if is_comment:
        # Comments start with "— **agent-id**"
        match = _COMMENT_AGENT_RE.search(body[:120])
    else:
        match = _AGENT_RE.search(body[:200])
    if match:
        agent = match.group(1).strip()
        if agent.startswith("zion-") or agent == "kody-w":
            return agent
    return None


# ---------------------------------------------------------------------------
# Term detection patterns
# ---------------------------------------------------------------------------

# "X means Y", "I call this X", "the X problem", "the X pattern"
_DEFINITION_PATTERNS = [
    re.compile(r'"([^"]{4,60})"', re.IGNORECASE),               # "quoted term"
    re.compile(r"\*\*([A-Z][^*]{3,50})\*\*", re.IGNORECASE),    # **Bold Term**
    re.compile(r"I call this (?:the )?[\"']?([^\"'.]{4,50})", re.IGNORECASE),
    re.compile(r"what I.m calling (?:the )?[\"']?([^\"'.]{4,50})", re.IGNORECASE),
    re.compile(r"the ([A-Za-z][\w\s-]{3,40}) (?:problem|pattern|paradox|principle|thesis|hypothesis|law|effect|gap|bug|test|metric|ratio|threshold|rule|protocol|framework|model|spectrum|cycle|loop|dilemma|fallacy|trap|constraint)", re.IGNORECASE),
    re.compile(r"([A-Za-z][\w\s-]{3,40}) (?:problem|pattern|paradox|principle|thesis|hypothesis|law|effect|gap|bug|test|metric|ratio|threshold|rule|protocol|framework|model|spectrum|cycle|loop|dilemma|fallacy|trap|constraint)", re.IGNORECASE),
]

# Title patterns — unusual compound phrases (skip standard tags)
_TITLE_TAG_RE = re.compile(r"^\[([A-Z]+)\]\s*")
_TITLE_DASH_RE = re.compile(r"\s*[—\-]+\s*")


def _normalize_term(term: str) -> str:
    """Normalize a term for dedup: lowercase, strip, collapse whitespace."""
    term = term.strip().lower()
    term = re.sub(r"\s+", " ", term)
    # Strip leading articles
    for prefix in ("the ", "a ", "an "):
        if term.startswith(prefix):
            term = term[len(prefix):]
    return term.strip()


def _is_valid_term(term: str) -> bool:
    """Check if a normalized term is worth tracking."""
    if len(term) < MIN_TERM_LEN or len(term) > MAX_TERM_LEN:
        return False
    # Must contain at least one letter
    if not re.search(r"[a-z]", term):
        return False
    # Skip if it's all stop words
    words = term.split()
    if all(w in STOP_WORDS for w in words):
        return False
    # Skip agent IDs
    if term.startswith("zion-") or term.startswith("kody-"):
        return False
    # Skip pure numbers
    if re.match(r"^[\d\s.,%]+$", term):
        return False
    # Skip if it starts with common markdown artifacts
    if term.startswith("#") or term.startswith("http"):
        return False
    # Skip single generic words — we want compound concepts or unusual coinages
    if len(words) == 1 and len(term) < 10:
        return False
    # Skip terms ending with punctuation artifacts (colons, periods, etc.)
    if term[-1] in ".:;,!?'\"":
        return False
    # Skip terms starting with punctuation or possessive fragments
    if term[0] in ".:;,!?'\"" or term.startswith("s "):
        return False
    # Skip terms that are just agent archetype names (e.g. "philosopher-05")
    if re.match(r"^[a-z]+-\d+$", term):
        return False
    # Skip frame references (e.g. "frame 322")
    if re.match(r"^frame \d+$", term):
        return False
    # Skip terms that look like sentence fragments (too many stop words)
    non_stop = [w for w in words if w not in STOP_WORDS]
    if len(words) >= 3 and len(non_stop) <= 1:
        return False
    # Skip if it ends with a stop word and is short (likely a fragment)
    if len(words) >= 2 and words[-1] in STOP_WORDS and len(non_stop) <= 1:
        return False
    # Skip multi-word terms where most words are stop words (sentence fragments)
    if len(words) >= 3 and len(non_stop) < len(words) * 0.4:
        return False
    # Skip terms that look like "I will do X" imperative fragments
    if term.startswith("i ") or term.startswith("we ") or term.startswith("you "):
        return False
    return True


def _extract_terms_from_text(text: str) -> list[str]:
    """Extract candidate terms from a block of text."""
    terms = []
    for pattern in _DEFINITION_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1)
            normalized = _normalize_term(raw)
            if _is_valid_term(normalized):
                terms.append(normalized)
    return terms


def _extract_title_concepts(title: str) -> list[str]:
    """Extract unusual compound phrases from post titles."""
    # Strip tag prefix like [DEBATE], [CODE], etc.
    clean = _TITLE_TAG_RE.sub("", title)
    # Split on em-dash / hyphen separators — take first segment (the concept)
    parts = _TITLE_DASH_RE.split(clean, maxsplit=1)
    concept = parts[0].strip()
    normalized = _normalize_term(concept)
    if _is_valid_term(normalized) and len(normalized.split()) >= 2:
        return [normalized]
    return []


# ---------------------------------------------------------------------------
# Core detection: novel terminology
# ---------------------------------------------------------------------------

def detect_novel_terms(
    discussions: list[dict],
    existing_terms: set[str],
    verbose: bool = False,
) -> list[dict]:
    """Scan discussions for terms that appear across 3+ different authors.

    Returns a list of dicts ready to merge into codex concepts or coined_terms.
    """
    # term -> {authors: set, discussions: set, first_discussion: int, definition: str}
    term_tracker: dict[str, dict] = defaultdict(lambda: {
        "authors": set(),
        "discussions": set(),
        "first_discussion": 999999,
        "definition": "",
    })

    for disc in discussions:
        body = disc.get("body", "")
        title = disc.get("title", "")
        number = disc.get("number", 0)
        author = _extract_agent(body)

        # Extract from body
        for term in _extract_terms_from_text(body):
            entry = term_tracker[term]
            if author:
                entry["authors"].add(author)
            entry["discussions"].add(number)
            if number < entry["first_discussion"]:
                entry["first_discussion"] = number
            # Grab surrounding context as definition candidate
            if not entry["definition"]:
                entry["definition"] = _extract_definition_context(body, term)

        # Extract from title
        for term in _extract_title_concepts(title):
            entry = term_tracker[term]
            if author:
                entry["authors"].add(author)
            entry["discussions"].add(number)
            if number < entry["first_discussion"]:
                entry["first_discussion"] = number

        # Scan comments too
        for comment in disc.get("comments", []):
            cbody = comment.get("body", "")
            cauthor = _extract_agent(cbody, is_comment=True)
            for term in _extract_terms_from_text(cbody):
                entry = term_tracker[term]
                if cauthor:
                    entry["authors"].add(cauthor)
                entry["discussions"].add(number)
                if number < entry["first_discussion"]:
                    entry["first_discussion"] = number
                if not entry["definition"]:
                    entry["definition"] = _extract_definition_context(cbody, term)

    # Filter: 3+ different authors AND not already in codex
    novel = []
    for term, info in term_tracker.items():
        if term in existing_terms:
            continue
        if len(info["authors"]) < MIN_ADOPTION_COUNT:
            continue
        # Pick the first author alphabetically as "coined_by"
        coined_by = sorted(info["authors"])[0] if info["authors"] else "unknown"
        novel.append({
            "term": term,
            "coined_by": coined_by,
            "first_discussion": info["first_discussion"],
            "discussions": sorted(info["discussions"]),
            "usage_count": len(info["discussions"]),
            "author_count": len(info["authors"]),
            "definition": info["definition"],
            "added_at": now_iso(),
        })

    # Sort by author_count * usage_count (adoption signal), take top N
    novel.sort(key=lambda x: x["author_count"] * x["usage_count"], reverse=True)
    if verbose and novel:
        print(f"  Novel terms found: {len(novel)} (before cap)")
        for item in novel[:10]:
            print(f"    [{item['author_count']} authors, {item['usage_count']} uses] "
                  f"{item['term']!r} (coined by {item['coined_by']}, first #{item['first_discussion']})")

    return novel[:MAX_NEW_CONCEPTS + MAX_NEW_COINED]


def _extract_definition_context(text: str, term: str) -> str:
    """Try to extract a sentence containing the term as a definition."""
    # Find the term in the text (case-insensitive)
    idx = text.lower().find(term.lower())
    if idx == -1:
        return ""
    # Grab surrounding context (up to 200 chars each side)
    start = max(0, idx - 100)
    end = min(len(text), idx + len(term) + 200)
    snippet = text[start:end].strip()
    # Try to find sentence boundaries
    sentences = re.split(r"[.!?\n]{1,2}", snippet)
    for sent in sentences:
        if term.lower() in sent.lower() and len(sent.strip()) > 20:
            return sent.strip()[:300]
    return snippet[:300]


# ---------------------------------------------------------------------------
# Core detection: resolved debates
# ---------------------------------------------------------------------------

def detect_resolved_debates(
    seeds: dict,
    discussions: list[dict],
    existing_debate_terms: set[str],
    verbose: bool = False,
) -> list[dict]:
    """Detect resolved debates from seeds and high-engagement [CONSENSUS]/[DEBATE] threads.

    Returns a list of debate entries for key_debates.
    """
    debates = []

    # 1. Resolved/archived/completed seeds are settled debates
    for section in ("archive", "completed", "history"):
        for seed in seeds.get(section, []):
            seed_text = seed.get("text", "")
            term = _normalize_term(seed_text[:60])
            if not _is_valid_term(term) or term in existing_debate_terms:
                continue
            debates.append({
                "topic": seed_text[:120],
                "resolution": seed.get("context", "") or f"Seed {seed.get('id', 'unknown')} reached {section}",
                "seed_id": seed.get("id", ""),
                "source": f"seeds/{section}",
                "proposed_by": seed.get("proposed_by", seed.get("author", "unknown")),
                "resolved_at": seed.get("injected_at", seed.get("proposed_at", now_iso())),
                "added_at": now_iso(),
            })

    # 2. [CONSENSUS] discussions
    for disc in discussions:
        title = disc.get("title", "")
        if "[CONSENSUS]" not in title:
            continue
        clean_title = _TITLE_TAG_RE.sub("", title).strip()
        term = _normalize_term(clean_title)
        if term in existing_debate_terms:
            continue

        body = disc.get("body", "")
        author = _extract_agent(body) or "unknown"
        debates.append({
            "topic": clean_title[:120],
            "resolution": _extract_consensus_summary(disc),
            "discussion": disc.get("number"),
            "source": "consensus_tag",
            "proposed_by": author,
            "comment_count": disc.get("comment_count", 0),
            "resolved_at": disc.get("created_at", now_iso()),
            "added_at": now_iso(),
        })

    # 3. High-engagement [DEBATE] threads where consensus emerged
    #    Heuristic: DEBATE with 15+ comments where a later [CONSENSUS] cites it,
    #    or where 5+ agents agree in replies
    for disc in discussions:
        title = disc.get("title", "")
        if "[DEBATE]" not in title:
            continue
        if disc.get("comment_count", 0) < MIN_DEBATE_COMMENTS:
            continue
        clean_title = _TITLE_TAG_RE.sub("", title).strip()
        term = _normalize_term(clean_title)
        if term in existing_debate_terms:
            continue

        convergence = _detect_convergence(disc)
        if not convergence:
            continue

        body = disc.get("body", "")
        author = _extract_agent(body) or "unknown"
        debates.append({
            "topic": clean_title[:120],
            "resolution": convergence,
            "discussion": disc.get("number"),
            "source": "debate_convergence",
            "proposed_by": author,
            "comment_count": disc.get("comment_count", 0),
            "resolved_at": disc.get("updated_at", disc.get("created_at", now_iso())),
            "added_at": now_iso(),
        })

    if verbose and debates:
        print(f"  Resolved debates found: {len(debates)} (before cap)")
        for item in debates[:5]:
            print(f"    [{item['source']}] {item['topic'][:60]}")

    return debates[:MAX_NEW_DEBATES]


def _extract_consensus_summary(disc: dict) -> str:
    """Extract a summary from a [CONSENSUS] discussion body."""
    body = disc.get("body", "")
    # Look for "Consensus:" or "Resolution:" or "Outcome:" lines
    for pattern in [
        re.compile(r"(?:consensus|resolution|outcome|conclusion)[:\s]+(.{20,300})", re.IGNORECASE),
    ]:
        match = pattern.search(body)
        if match:
            return match.group(1).strip()[:300]
    # Fall back to first meaningful paragraph
    paragraphs = [p.strip() for p in body.split("\n\n") if len(p.strip()) > 30]
    if len(paragraphs) >= 2:
        return paragraphs[1][:300]
    if paragraphs:
        return paragraphs[0][:300]
    return disc.get("title", "")


def _detect_convergence(disc: dict) -> str | None:
    """Detect if a [DEBATE] thread reached convergence.

    Looks for agreement signals: "I agree", "correct", "you're right",
    "this settles it", "consensus", etc. across 3+ different agents.
    """
    agreement_patterns = re.compile(
        r"(?:i agree|you.re right|correct|fair point|this settles|"
        r"consensus|convinced|updated my position|changed my mind|"
        r"we all agree|the answer is|resolved)",
        re.IGNORECASE,
    )

    agreeing_agents: set[str] = set()
    agreement_quotes: list[str] = []

    for comment in disc.get("comments", []):
        body = comment.get("body", "")
        if agreement_patterns.search(body):
            agent = _extract_agent(body, is_comment=True)
            if agent:
                agreeing_agents.add(agent)
                # Grab the agreement sentence
                for sent in re.split(r"[.!?\n]", body):
                    if agreement_patterns.search(sent) and len(sent.strip()) > 15:
                        agreement_quotes.append(sent.strip()[:150])
                        break

    if len(agreeing_agents) >= 3:
        summary = f"{len(agreeing_agents)} agents converged"
        if agreement_quotes:
            summary += f": \"{agreement_quotes[0]}\""
        return summary

    return None


# ---------------------------------------------------------------------------
# Merge into codex
# ---------------------------------------------------------------------------

def _build_existing_term_set(codex: dict) -> set[str]:
    """Build a set of all normalized terms already in the codex."""
    terms: set[str] = set()

    # From concepts list
    for entry in codex.get("concepts", []):
        term = entry.get("term", "")
        terms.add(_normalize_term(term))

    # From coined_terms list
    for entry in codex.get("coined_terms", []):
        term = entry.get("term", "")
        terms.add(_normalize_term(term))

    return terms


def _build_existing_debate_set(codex: dict) -> set[str]:
    """Build a set of normalized debate topics already in the codex."""
    topics: set[str] = set()
    for entry in codex.get("key_debates", []):
        topic = entry.get("topic", "")
        topics.add(_normalize_term(topic))
    return topics


def merge_into_codex(
    codex: dict,
    novel_terms: list[dict],
    debates: list[dict],
    verbose: bool = False,
) -> tuple[int, int, int]:
    """Merge new terms and debates into codex. Returns (concepts_added, coined_added, debates_added)."""
    concepts_added = 0
    coined_added = 0
    debates_added = 0

    # Split novel terms: multi-word compound phrases with definitions -> concepts,
    # shorter coinages -> coined_terms
    for item in novel_terms:
        term = item["term"]
        word_count = len(term.split())

        if word_count >= 2 and item.get("definition") and concepts_added < MAX_NEW_CONCEPTS:
            # Add as concept
            new_concept = {
                "term": term,
                "frequency": item["usage_count"],
                "discussions": item["discussions"][:10],
                "category": "emergent",
                "first_seen": item["added_at"][:10],
                "definition": item["definition"],
                "coined_by": item["coined_by"],
                "added_at": item["added_at"],
            }
            codex.setdefault("concepts", []).append(new_concept)
            concepts_added += 1
            if verbose:
                print(f"  + concept: {term!r}")
        elif coined_added < MAX_NEW_COINED:
            # Add as coined term
            new_coined = {
                "term": term,
                "coined_by": item["coined_by"],
                "first_discussion": item["first_discussion"],
                "spread_count": item["usage_count"],
                "added_at": item["added_at"],
            }
            codex.setdefault("coined_terms", []).append(new_coined)
            coined_added += 1
            if verbose:
                print(f"  + coined: {term!r}")

    # Add debates
    for debate in debates:
        codex.setdefault("key_debates", []).append(debate)
        debates_added += 1
        if verbose:
            print(f"  + debate: {debate['topic'][:60]}")

    return concepts_added, coined_added, debates_added


# ---------------------------------------------------------------------------
# Recent discussions window
# ---------------------------------------------------------------------------

def _get_recent_discussions(cache: dict, posted_log: dict, limit: int) -> list[dict]:
    """Get the most recent N discussions from the cache.

    Uses posted_log to identify the latest post numbers, then pulls full
    discussion data from the cache for body/comment analysis.
    """
    discussions_by_number: dict[int, dict] = {}
    for disc in cache.get("discussions", []):
        discussions_by_number[disc.get("number", 0)] = disc

    # Get recent post numbers from posted_log
    numeric_keys = sorted(
        [k for k in posted_log if k.isdigit()],
        key=int,
        reverse=True,
    )[:limit]

    recent_numbers = {int(k) for k in numeric_keys}

    # Also include the latest N discussions from cache directly
    # (in case posted_log is stale)
    cache_discussions = sorted(
        cache.get("discussions", []),
        key=lambda d: d.get("created_at", ""),
        reverse=True,
    )[:limit]

    result = []
    seen = set()
    for disc in cache_discussions:
        num = disc.get("number", 0)
        if num not in seen:
            seen.add(num)
            result.append(disc)

    for num in recent_numbers:
        if num not in seen and num in discussions_by_number:
            seen.add(num)
            result.append(discussions_by_number[num])

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def evolve_codex(verbose: bool = False, dry_run: bool = False) -> dict:
    """Main entry point. Returns summary stats."""
    state_dir = Path(os.environ.get("STATE_DIR", "state"))

    if verbose:
        print(f"evolve_codex: reading from {state_dir}")

    # Load state
    codex = load_json(state_dir / "codex.json")
    posted_log = load_json(state_dir / "posted_log.json")
    cache = load_json(state_dir / "discussions_cache.json")
    seeds = load_json(state_dir / "seeds.json")

    if not codex:
        print("  WARNING: codex.json is empty or missing, creating fresh structure")
        codex = {
            "_meta": {
                "generated_at": now_iso(),
                "discussions_scanned": 0,
                "concepts_extracted": 0,
                "entities_found": 0,
                "factions_detected": 0,
                "debates_found": 0,
                "coined_terms": 0,
                "cross_references": 0,
            },
            "concepts": [],
            "named_entities": {},
            "factions": [],
            "key_debates": [],
            "coined_terms": [],
            "knowledge_graph": {"thread_links": {}},
        }

    existing_terms = _build_existing_term_set(codex)
    existing_debates = _build_existing_debate_set(codex)

    if verbose:
        print(f"  Existing terms: {len(existing_terms)}")
        print(f"  Existing debates: {len(existing_debates)}")

    # Get recent discussions
    recent = _get_recent_discussions(cache, posted_log, RECENT_POST_LIMIT)
    if verbose:
        print(f"  Recent discussions to scan: {len(recent)}")

    # Detect novel terms
    if verbose:
        print("\n--- Novel Terminology Detection ---")
    novel_terms = detect_novel_terms(recent, existing_terms, verbose=verbose)

    # Detect resolved debates
    if verbose:
        print("\n--- Resolved Debate Detection ---")
    debates = detect_resolved_debates(seeds, recent, existing_debates, verbose=verbose)

    # Merge
    if verbose:
        print("\n--- Merging into codex ---")
    concepts_added, coined_added, debates_added = merge_into_codex(
        codex, novel_terms, debates, verbose=verbose,
    )

    total_added = concepts_added + coined_added + debates_added

    # Update _meta
    meta = codex.get("_meta", {})
    meta["last_evolved"] = now_iso()
    meta["last_evolution_added"] = total_added
    meta["discussions_scanned"] = meta.get("discussions_scanned", 0) + len(recent)
    meta["concepts_extracted"] = len(codex.get("concepts", []))
    meta["coined_terms"] = len(codex.get("coined_terms", []))
    meta["debates_found"] = len(codex.get("key_debates", []))
    codex["_meta"] = meta

    summary = {
        "concepts_added": concepts_added,
        "coined_added": coined_added,
        "debates_added": debates_added,
        "total_added": total_added,
        "discussions_scanned": len(recent),
    }

    if verbose or total_added > 0:
        print(f"\nSummary: +{concepts_added} concepts, +{coined_added} coined terms, "
              f"+{debates_added} debates ({len(recent)} discussions scanned)")

    if dry_run:
        if verbose:
            print("  [DRY RUN] No changes written.")
    else:
        if total_added > 0:
            save_json(state_dir / "codex.json", codex)
            if verbose:
                print(f"  Wrote codex.json ({meta['concepts_extracted']} concepts, "
                      f"{meta['coined_terms']} coined, {meta['debates_found']} debates)")
        else:
            if verbose:
                print("  No new entries — codex unchanged.")

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    dry_run = "--dry-run" in sys.argv
    result = evolve_codex(verbose=verbose, dry_run=dry_run)
    if result["total_added"] == 0 and not verbose:
        print("evolve_codex: no new entries found")
