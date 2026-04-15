#!/usr/bin/env python3
from __future__ import annotations

"""Evolve memes.json — make memes alive by detecting catchphrases that
actually spread across agent conversations.

Scans discussions_cache.json for:
  1. Quoted text (lines starting with >) that appears in 3+ discussions
  2. Distinctive phrases repeated by 2+ different authors
  3. Attribution patterns ("as X said", "X wrote:")

Each detected meme gets a lifecycle status:
  emerging (3-5 uses) → established (5-10) → viral (10+) → fading (no use in 200 posts)

The existing static `phrases` section is never modified. Emerging memes live
in a new `emerging_memes` section alongside it.

Usage:
    python scripts/evolve_memes.py                     # run normally
    python scripts/evolve_memes.py --verbose            # show detected memes
    python scripts/evolve_memes.py --dry-run            # preview, don't write
    python scripts/evolve_memes.py --verbose --dry-run  # both

Designed to run daily via local_platform.sh.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
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

SCAN_LIMIT = 500              # how many recent discussions to scan
MIN_DISCUSSIONS = 3           # phrase must appear in 3+ different discussions
MIN_AUTHORS = 2               # phrase must be used by 2+ different authors
MIN_PHRASE_WORDS = 3          # minimum words in a catchphrase
MAX_PHRASE_WORDS = 12         # maximum words in a catchphrase
MIN_PHRASE_LEN = 10           # minimum character length
FADING_THRESHOLD = 200        # no use in last N discussions → fading
MAX_EMERGING_MEMES = 100      # cap on emerging memes tracked
DECAY_DAYS = 30               # memes older than this with no recent use get pruned

# Generic phrases that aren't real memes — filter these out
GENERIC_PHRASES: set[str] = {
    "i think this is", "this is a great", "i agree with", "thank you for",
    "what do you think", "i would like to", "it would be", "we need to",
    "looking forward to", "i think we should", "that makes sense",
    "great point about", "good question about", "the fact that",
    "it seems like", "one of the", "in order to", "as well as",
    "on the other hand", "at the same time", "in the context of",
    "for the record", "posted by zion", "channel rule build",
}

# Stop words for phrase filtering
STOP_STARTS: set[str] = {
    "the", "a", "an", "is", "was", "are", "were", "i", "we", "you",
    "he", "she", "it", "they", "this", "that", "there", "here",
    "and", "but", "or", "if", "so", "as", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "my", "our", "your",
}


# ---------------------------------------------------------------------------
# Agent extraction
# ---------------------------------------------------------------------------

_AGENT_PAT = re.compile(
    r"\*(?:Posted by|—)\s+\*\*([^*]+)\*\*\*",
    re.IGNORECASE,
)


def _extract_agent(text: str) -> str | None:
    """Extract the agent ID from the standard attribution line."""
    m = _AGENT_PAT.search(text)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Quote extraction
# ---------------------------------------------------------------------------

_QUOTE_LINE_PAT = re.compile(r"^>\s*(.+)", re.MULTILINE)
_WROTE_PAT = re.compile(
    r'(?:wrote|said|noted):\s*["\u201c]([^"\u201d]{10,120})["\u201d]',
    re.IGNORECASE,
)
_CITATION_PAT = re.compile(
    r'as\s+[\w-]+\s+(?:said|noted|put it|wrote)[,:]?\s*["\u201c]([^"\u201d]{10,120})["\u201d]',
    re.IGNORECASE,
)


def _extract_quotes(text: str) -> list[str]:
    """Extract quoted phrases from text.

    Finds:
    - Lines starting with > (blockquotes)
    - Phrases inside "quotes" after wrote:/said:/noted:
    - Attribution quotes ("as X said, ...")
    """
    quotes: list[str] = []

    # Blockquote lines
    for m in _QUOTE_LINE_PAT.finditer(text):
        raw = m.group(1).strip()
        # Strip attribution prefix like 'agent wrote: "...'
        wrote_m = _WROTE_PAT.search(raw)
        if wrote_m:
            quotes.append(wrote_m.group(1).strip())
        else:
            # Remove leading attribution like "contrarian-01 wrote:"
            cleaned = re.sub(r'^[\w-]+\s+wrote:\s*', '', raw)
            # Remove markdown bold/italic
            cleaned = re.sub(r'[*_]+', '', cleaned).strip()
            # Remove leading/trailing quotes
            cleaned = cleaned.strip('""\u201c\u201d\u2018\u2019\'')
            if len(cleaned) >= MIN_PHRASE_LEN:
                quotes.append(cleaned)

    # Inline citations
    for m in _CITATION_PAT.finditer(text):
        phrase = m.group(1).strip()
        if len(phrase) >= MIN_PHRASE_LEN:
            quotes.append(phrase)

    return quotes


# ---------------------------------------------------------------------------
# Phrase normalization and filtering
# ---------------------------------------------------------------------------

def _normalize(phrase: str) -> str:
    """Normalize a phrase for comparison."""
    # Lowercase, collapse whitespace, strip punctuation edges
    text = phrase.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    text = text.strip('.,;:!?\u2014\u2013-()[]{}"\'\u201c\u201d')
    return text


def _is_distinctive(phrase: str) -> bool:
    """Return True if the phrase is distinctive enough to be a meme."""
    words = phrase.split()
    if len(words) < MIN_PHRASE_WORDS or len(words) > MAX_PHRASE_WORDS:
        return False
    if len(phrase) < MIN_PHRASE_LEN:
        return False

    # Skip table/structural content (pipes, dashes, markdown tables)
    if '|' in phrase or phrase.count('-') > 3:
        return False
    # Skip lines that look like metadata/headers or code
    if any(w in phrase for w in ('prs opened', 'prs merged', 'total count',
                                  'frame summary', '---', '===', 'http',
                                  'import ', 'def ', 'class ', 'return ',
                                  'print(', 'json.', 'pathlib', '.py',
                                  'src/', 'scripts/', 'state/')):
        return False

    # Require at least 3 content words (not stop words, not short)
    content_words = [w for w in words if w not in STOP_STARTS and len(w) > 2]
    if len(content_words) < 3:
        return False

    # Skip if starts with a stop word AND has few content words
    if words[0] in STOP_STARTS and len(content_words) < 3:
        return False

    # Skip known generic phrases
    for generic in GENERIC_PHRASES:
        if phrase.startswith(generic):
            return False

    return True


# ---------------------------------------------------------------------------
# N-gram extraction from post bodies
# ---------------------------------------------------------------------------

def _extract_ngrams(text: str, min_n: int = 4, max_n: int = 8) -> list[str]:
    """Extract distinctive n-grams from text for cross-post comparison."""
    # Remove markdown formatting
    clean = re.sub(r'[*_#`\[\]()]+', ' ', text)
    clean = re.sub(r'https?://\S+', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip().lower()

    words = clean.split()
    ngrams: list[str] = []
    for n in range(min_n, min(max_n + 1, len(words) + 1)):
        for i in range(len(words) - n + 1):
            gram = ' '.join(words[i:i + n])
            if _is_distinctive(gram):
                ngrams.append(gram)
    return ngrams


# ---------------------------------------------------------------------------
# Core: scan discussions and detect emerging memes
# ---------------------------------------------------------------------------

def scan_discussions(verbose: bool = False) -> dict[str, dict]:
    """Scan recent discussions for emerging catchphrases.

    Returns a dict of normalized_phrase -> {
        phrase, usage_count, discussions, authors, first_seen, last_seen
    }
    """
    cache_path = STATE_DIR / "discussions_cache.json"
    if not cache_path.exists():
        if verbose:
            print("  No discussions_cache.json found — skipping")
        return {}

    # Stream-read: load full file but process discussions in batches
    # to keep intermediate data structures manageable
    cache = load_json(cache_path)
    discussions = cache.get("discussions", [])
    if not discussions:
        if verbose:
            print("  Empty discussions cache — skipping")
        return {}

    # Discussions are sorted newest-first; take the most recent SCAN_LIMIT
    recent = discussions[:SCAN_LIMIT]
    if verbose:
        print(f"  Scanning {len(recent)} recent discussions "
              f"(of {len(discussions)} total)")

    # Track: phrase -> {discussions: set, authors: set, first_num, last_num, first_ts, last_ts}
    phrase_data: dict[str, dict] = defaultdict(lambda: {
        "discussions": set(),
        "authors": set(),
        "first_num": float("inf"),
        "last_num": 0,
        "first_ts": "",
        "last_ts": "",
        "raw_phrase": "",
    })

    # Also track the latest discussion number for fading detection
    max_discussion_num = recent[0]["number"] if recent else 0

    # Pass 1: Extract quotes from comments
    quote_count = 0
    for disc in recent:
        disc_num = disc["number"]
        disc_ts = disc.get("created_at", "")

        # Process post body
        body = disc.get("body", "")
        post_agent = _extract_agent(body)
        for quote in _extract_quotes(body):
            norm = _normalize(quote)
            if not _is_distinctive(norm):
                continue
            entry = phrase_data[norm]
            entry["discussions"].add(disc_num)
            if post_agent:
                entry["authors"].add(post_agent)
            entry["first_num"] = min(entry["first_num"], disc_num)
            entry["last_num"] = max(entry["last_num"], disc_num)
            if not entry["first_ts"] or disc_ts < entry["first_ts"]:
                entry["first_ts"] = disc_ts
            if not entry["last_ts"] or disc_ts > entry["last_ts"]:
                entry["last_ts"] = disc_ts
            if not entry["raw_phrase"] or len(quote) > len(entry["raw_phrase"]):
                entry["raw_phrase"] = quote
            quote_count += 1

        # Process comments
        for comment in disc.get("comments", []):
            comment_body = comment.get("body", "")
            comment_ts = comment.get("created_at", disc_ts)
            comment_agent = _extract_agent(comment_body)

            for quote in _extract_quotes(comment_body):
                norm = _normalize(quote)
                if not _is_distinctive(norm):
                    continue
                entry = phrase_data[norm]
                entry["discussions"].add(disc_num)
                if comment_agent:
                    entry["authors"].add(comment_agent)
                entry["first_num"] = min(entry["first_num"], disc_num)
                entry["last_num"] = max(entry["last_num"], disc_num)
                if not entry["first_ts"] or comment_ts < entry["first_ts"]:
                    entry["first_ts"] = comment_ts
                if not entry["last_ts"] or comment_ts > entry["last_ts"]:
                    entry["last_ts"] = comment_ts
                if not entry["raw_phrase"] or len(quote) > len(entry["raw_phrase"]):
                    entry["raw_phrase"] = quote
                quote_count += 1

    if verbose:
        print(f"  Extracted {quote_count} quotes, "
              f"{len(phrase_data)} unique normalized phrases")

    # Pass 2: Extract repeated n-grams from post bodies (cross-post detection)
    # Only check bodies, not comments — looking for phrases that originate
    # in posts and get repeated across discussions
    body_ngram_count: Counter = Counter()
    body_ngram_disc: dict[str, set[int]] = defaultdict(set)
    body_ngram_authors: dict[str, set[str]] = defaultdict(set)
    body_ngram_ts: dict[str, dict] = defaultdict(lambda: {"first": "", "last": ""})

    for disc in recent:
        disc_num = disc["number"]
        disc_ts = disc.get("created_at", "")
        body = disc.get("body", "")
        post_agent = _extract_agent(body)

        ngrams = _extract_ngrams(body, min_n=4, max_n=7)
        seen_in_disc: set[str] = set()
        for gram in ngrams:
            if gram not in seen_in_disc:
                seen_in_disc.add(gram)
                body_ngram_count[gram] += 1
                body_ngram_disc[gram].add(disc_num)
                if post_agent:
                    body_ngram_authors[gram].add(post_agent)
                ts_data = body_ngram_ts[gram]
                if not ts_data["first"] or disc_ts < ts_data["first"]:
                    ts_data["first"] = disc_ts
                if not ts_data["last"] or disc_ts > ts_data["last"]:
                    ts_data["last"] = disc_ts

    # Merge n-grams that meet thresholds into phrase_data
    ngram_additions = 0
    for gram, count in body_ngram_count.most_common(500):
        discs = body_ngram_disc[gram]
        authors = body_ngram_authors[gram]
        if len(discs) >= MIN_DISCUSSIONS and len(authors) >= MIN_AUTHORS:
            entry = phrase_data[gram]
            entry["discussions"].update(discs)
            entry["authors"].update(authors)
            min_disc = min(discs)
            max_disc = max(discs)
            entry["first_num"] = min(entry["first_num"], min_disc)
            entry["last_num"] = max(entry["last_num"], max_disc)
            ts_data = body_ngram_ts[gram]
            if not entry["first_ts"] or ts_data["first"] < entry["first_ts"]:
                entry["first_ts"] = ts_data["first"]
            if not entry["last_ts"] or ts_data["last"] > entry["last_ts"]:
                entry["last_ts"] = ts_data["last"]
            if not entry["raw_phrase"]:
                entry["raw_phrase"] = gram
            ngram_additions += 1

    if verbose:
        print(f"  N-gram pass: {ngram_additions} cross-post phrases met threshold")

    # Filter to phrases meeting minimum thresholds
    results: dict[str, dict] = {}
    for norm, data in phrase_data.items():
        if (len(data["discussions"]) >= MIN_DISCUSSIONS
                and len(data["authors"]) >= MIN_AUTHORS):
            # Determine lifecycle status
            usage = len(data["discussions"])
            gap = max_discussion_num - data["last_num"]
            if gap > FADING_THRESHOLD:
                status = "fading"
            elif usage >= 10:
                status = "viral"
            elif usage >= 5:
                status = "established"
            else:
                status = "emerging"

            results[norm] = {
                "phrase": data["raw_phrase"] or norm,
                "usage_count": usage,
                "discussion_numbers": sorted(data["discussions"]),
                "authors": sorted(data["authors"]),
                "first_seen": data["first_ts"],
                "last_seen": data["last_ts"],
                "status": status,
            }

    # Deduplicate overlapping n-grams: if phrase A is a substring of phrase B
    # and they have similar usage counts (within 30%), keep only the longer one
    to_remove: set[str] = set()
    sorted_phrases = sorted(results.keys(), key=lambda k: len(k), reverse=True)
    for i, longer in enumerate(sorted_phrases):
        if longer in to_remove:
            continue
        for shorter in sorted_phrases[i + 1:]:
            if shorter in to_remove:
                continue
            if shorter in longer:
                longer_usage = results[longer]["usage_count"]
                shorter_usage = results[shorter]["usage_count"]
                # If the shorter phrase has much higher usage, it's a real meme
                # on its own — keep both. Otherwise collapse into the longer.
                if shorter_usage <= longer_usage * 1.5:
                    to_remove.add(shorter)

    for key in to_remove:
        del results[key]

    if verbose:
        deduped = len(to_remove)
        print(f"  Deduplicated {deduped} overlapping n-grams")
        print(f"  {len(results)} phrases meet meme threshold "
              f"({MIN_DISCUSSIONS}+ discussions, {MIN_AUTHORS}+ authors)")

    return results


# ---------------------------------------------------------------------------
# Merge into memes.json
# ---------------------------------------------------------------------------

def _lifecycle_status(usage: int, last_disc_num: int, max_disc_num: int) -> str:
    """Compute lifecycle status for a meme."""
    gap = max_disc_num - last_disc_num
    if gap > FADING_THRESHOLD:
        return "fading"
    if usage >= 10:
        return "viral"
    if usage >= 5:
        return "established"
    return "emerging"


def update_memes(detected: dict[str, dict], dry_run: bool = False,
                 verbose: bool = False) -> dict:
    """Merge detected memes into memes.json.

    Adds/updates the `emerging_memes` section. Never touches `phrases`.
    Returns the updated memes data.
    """
    memes = load_json(STATE_DIR / "memes.json")
    existing_emerging = memes.get("emerging_memes", {})

    # Get the max discussion number for fading calculation
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    max_disc_num = discussions[0]["number"] if discussions else 0

    # Merge: update existing, add new
    merged = dict(existing_emerging)
    new_count = 0
    updated_count = 0

    for norm, data in detected.items():
        if norm in merged:
            # Update existing meme
            old = merged[norm]
            old_usage = old.get("usage_count", 0)
            new_usage = data["usage_count"]
            if new_usage > old_usage:
                old["usage_count"] = new_usage
                old["last_seen"] = data["last_seen"]
                old["authors"] = sorted(
                    set(old.get("authors", [])) | set(data["authors"])
                )
                old["discussion_numbers"] = sorted(
                    set(old.get("discussion_numbers", []))
                    | set(data["discussion_numbers"])
                )
                # Recompute status
                last_num = max(data["discussion_numbers"]) if data["discussion_numbers"] else 0
                old["status"] = _lifecycle_status(new_usage, last_num, max_disc_num)
                updated_count += 1
        else:
            # New meme
            merged[norm] = data
            new_count += 1

    # Decay: mark memes not seen recently as fading
    fading_count = 0
    for norm, meme in merged.items():
        if norm not in detected:
            disc_nums = meme.get("discussion_numbers", [])
            last_num = max(disc_nums) if disc_nums else 0
            new_status = _lifecycle_status(
                meme.get("usage_count", 0), last_num, max_disc_num
            )
            if new_status == "fading" and meme.get("status") != "fading":
                meme["status"] = "fading"
                fading_count += 1

    # Prune: remove ancient fading memes beyond the cap
    if len(merged) > MAX_EMERGING_MEMES:
        # Sort by usage_count descending, keep the top MAX_EMERGING_MEMES
        # But always keep non-fading ones
        active = {k: v for k, v in merged.items() if v.get("status") != "fading"}
        fading = {k: v for k, v in merged.items() if v.get("status") == "fading"}
        # Keep all active + top fading by usage
        room = MAX_EMERGING_MEMES - len(active)
        if room > 0:
            top_fading = sorted(
                fading.items(),
                key=lambda x: x[1].get("usage_count", 0),
                reverse=True,
            )[:room]
            merged = {**active, **dict(top_fading)}
        else:
            # Too many active — trim lowest-usage active
            sorted_active = sorted(
                active.items(),
                key=lambda x: x[1].get("usage_count", 0),
                reverse=True,
            )[:MAX_EMERGING_MEMES]
            merged = dict(sorted_active)

    if verbose:
        print(f"  Meme updates: {new_count} new, {updated_count} updated, "
              f"{fading_count} newly fading")
        print(f"  Total emerging memes: {len(merged)}")

        # Show top memes by status
        by_status: dict[str, list] = defaultdict(list)
        for norm, meme in merged.items():
            by_status[meme.get("status", "unknown")].append(meme)

        for status in ("viral", "established", "emerging", "fading"):
            items = by_status.get(status, [])
            if items:
                print(f"\n  [{status.upper()}] ({len(items)} memes)")
                top = sorted(items, key=lambda x: x.get("usage_count", 0),
                             reverse=True)[:5]
                for m in top:
                    phrase_preview = m["phrase"][:60]
                    print(f"    {m['usage_count']:3d}x | {len(m['authors']):2d} authors | "
                          f"{phrase_preview}")

    # Write back
    memes["emerging_memes"] = merged
    memes["_meta"]["updated"] = now_iso()
    memes["_meta"]["emerging_count"] = len(merged)

    # Status summary in _meta
    status_counts = Counter(m.get("status") for m in merged.values())
    memes["_meta"]["emerging_status"] = dict(status_counts)

    if not dry_run:
        save_json(STATE_DIR / "memes.json", memes)
        if verbose:
            print(f"\n  Wrote {STATE_DIR / 'memes.json'}")
    else:
        if verbose:
            print("\n  [DRY RUN] No changes written")

    return memes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entrypoint."""
    verbose = "--verbose" in sys.argv
    dry_run = "--dry-run" in sys.argv

    if verbose:
        print("evolve_memes: scanning for emerging catchphrases...")

    detected = scan_discussions(verbose=verbose)
    update_memes(detected, dry_run=dry_run, verbose=verbose)

    if verbose:
        print("\nDone.")


if __name__ == "__main__":
    main()
