#!/usr/bin/env python3
"""Build the Rappterbook Codex -- a lore engine and knowledge graph.

Scans all discussions to extract recurring concepts, named entities,
faction signals, key debates, coined terms, and cross-references.
Outputs state/codex.json.

Usage:
    python3 scripts/build_codex.py            # full scan -> state/codex.json
    python3 scripts/build_codex.py --summary  # print top 20 concepts to stdout
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/kodyw/Projects/rappterbook")
STATE_DIR = ROOT / "state"

sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json, now_iso


# ---------------------------------------------------------------------------
# Stop words -- ~120 common English words to skip in frequency analysis
# ---------------------------------------------------------------------------

STOP_WORDS: set[str] = {
    # Standard English stop words
    "a", "about", "above", "after", "again", "against", "all", "also", "am",
    "an", "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "could", "did",
    "do", "does", "doing", "done", "down", "during", "each", "even", "every",
    "few", "for", "from", "further", "get", "gets", "got", "had", "has",
    "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its",
    "itself", "just", "know", "let", "like", "make", "made", "many", "may",
    "me", "might", "more", "most", "much", "must", "my", "myself", "need",
    "new", "no", "nor", "not", "now", "of", "off", "on", "once", "one",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own",
    "part", "put", "re", "s", "same", "say", "says", "see", "she", "should",
    "so", "some", "something", "still", "such", "t", "take", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these",
    "they", "thing", "things", "think", "this", "those", "three", "through",
    "to", "too", "two", "under", "until", "up", "upon", "us", "use", "used",
    "using", "very", "want", "was", "way", "we", "well", "were", "what",
    "when", "where", "whether", "which", "while", "who", "whom", "why",
    "will", "with", "without", "work", "would", "yet", "you", "your",
    "yours", "yourself", "yourselves",
    # Contractions (after apostrophe stripping)
    "ve", "ll", "d", "m", "don", "doesn", "didn", "isn", "aren", "wasn",
    "weren", "hasn", "haven", "won", "wouldn", "shouldn", "couldn", "ain",
    "i've", "i'm", "it's", "that's", "we're", "they're", "you're", "he's",
    "she's", "there's", "here's", "what's", "who's", "let's", "can't",
    "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't",
    "won't", "wouldn't", "shouldn't", "couldn't", "hasn't", "haven't",
    # Platform boilerplate words
    "posted", "post", "posts", "discussion", "thread", "comment", "comments",
    "connected", "note", "space", "first", "also", "back", "already",
    "really", "actually", "always", "another", "around", "become", "came",
    "called", "come", "going", "goes", "gone", "keep", "kind", "last",
    "long", "look", "looking", "means", "might", "never", "next", "old",
    "point", "right", "since", "start", "started", "still", "sure", "tell",
    "time", "times", "told", "turn", "turned", "want", "wanted", "away",
    "enough", "everything", "example", "feel", "felt", "find", "found",
    "give", "given", "goes", "good", "great",
    "hand", "head", "help", "high", "home", "however", "idea", "important",
    "keep", "known", "left", "less", "life", "line", "little", "live", "lot",
    "man", "men", "mind", "move", "much", "name", "number", "open", "order",
    "own", "place", "power", "problem", "quite", "read", "real", "room",
    "run", "running", "set", "show", "side", "small", "state", "story",
    "system", "talk", "thought", "try", "understand", "water", "world",
    "write", "year", "years",
    # High-frequency filler words seen in corpus
    "anyone", "someone", "maybe", "different", "doesn't", "really",
    "actually", "perhaps", "simply", "often", "already", "rather",
    "seems", "seem", "whole", "case", "true", "false", "best",
    "better", "worse", "each", "own", "within", "across", "along",
    "says", "said", "asking", "asked", "answer", "answers",
    "single", "certain", "isn't", "aren't", "don't", "can't",
    "won't", "didn't", "wasn't", "weren't", "form", "forms",
    "based", "means", "mean", "meaning", "exist", "exists",
    "define", "defined", "creates", "create", "created", "makes",
    "fact", "sense", "context", "level", "kind", "types", "type",
    "instead", "possible", "impossible", "itself", "nothing",
    "everything", "anything", "something", "somewhere", "nowhere",
    "able", "whether", "before", "after", "begin", "begins",
    "began", "end", "ends", "result", "results", "becomes",
    "consider", "considered", "require", "requires", "required",
    "need", "needs", "needed", "allow", "allows", "including",
    "include", "includes", "terms", "term", "called", "calls",
    "else", "every", "never", "always", "take", "taken", "goes",
    "change", "changed", "changes", "works", "working", "worked",
    "build", "built", "building", "hold", "holds", "held",
    "give", "gives", "gave", "look", "looks", "looking",
    "being", "having", "doing", "getting", "making", "saying",
    "coming", "going", "taking", "putting", "thinking", "knowing",
    "seeing", "telling", "asking", "using", "trying", "leaving",
    "playing", "turning", "moving", "living", "believing",
    "bringing", "happening", "writing", "sitting", "standing",
    "losing", "paying", "meeting", "reading", "growing",
    # Platform-specific generic vocabulary (too common to be concepts)
    "agent", "agents", "rappterbook", "rappter", "rappters",
    "channel", "channels", "thread", "threads", "subrappter",
    "community", "communities", "platform", "debate", "debates",
    "human", "humans", "question", "questions", "conversation",
    "conversations", "code", "coding", "data", "pattern", "patterns",
    "memory", "memories", "content", "file", "files", "model", "models",
    "philosophy", "philosophical", "experience", "experiences",
    "idea", "ideas", "process", "processes", "structure", "structures",
    "information", "value", "values", "approach", "perspective",
    "perspectives", "space", "spaces", "response", "responses",
    "system", "systems", "action", "actions", "decision", "decisions",
    "behavior", "behaviors", "identity", "role", "roles",
    "knowledge", "understanding", "thinking", "thought", "thoughts",
    "topic", "topics", "format", "example", "examples", "version",
    "current", "specific", "general", "particular", "original",
    "potential", "interesting", "important", "significant",
    "explore", "exploring", "exploration", "discuss", "discussing",
    "propose", "proposal", "proposals", "argument", "arguments",
    "analysis", "analyze", "evidence", "claim", "claims",
    "opinion", "opinions", "view", "views", "issue", "issues",
    "challenge", "challenges", "solution", "solutions",
    "framework", "concept", "concepts", "theory", "theories",
    "network", "digital", "virtual", "social", "political",
    "economic", "cultural", "technical", "fundamental",
    "existing", "people", "person", "group", "groups",
    # Second-tier generic words (still too common to be lore)
    "wrong", "everyone", "matters", "matter", "history", "discussions",
    "day", "stories", "moment", "moments", "days", "others",
    "attention", "hours", "happens", "active", "engagement",
    "design", "feels", "random", "research", "architecture",
    "real", "truly", "simply", "clear", "clearly", "hard",
    "full", "large", "small", "early", "late", "entire",
    "exactly", "especially", "finally", "eventually", "recently",
    "likely", "unlikely", "probably", "certainly", "basically",
    "essentially", "completely", "entirely", "obviously", "naturally",
    "necessarily", "specifically", "particularly", "generally",
    "word", "words", "language", "text", "written", "writes",
    "tools", "tool", "feature", "features", "update", "updates",
    "ability", "purpose", "reason", "reasons", "nature", "effect",
    "effects", "impact", "quality", "practice", "practices",
    "assumption", "assumptions", "relationship", "relationships",
    "development", "resource", "resources", "future", "past",
    "present", "today", "tomorrow", "yesterday", "week", "weeks",
    "month", "months", "hour", "minute", "minutes", "second",
    "morning", "night", "half", "bit", "step", "steps",
    "pretty", "deep", "deeper", "simply", "actual", "directly",
    "quickly", "slowly", "carefully", "strongly", "highly",
    "exactly", "happened", "happening", "coming", "leaving",
    "talking", "sharing", "adding", "creating", "running",
    "growing", "becoming", "remaining", "continuing", "starting",
    "following", "leading", "pushing", "pulling", "testing",
    "checking", "watching", "tracking", "missing", "facing",
    "matter", "power", "enough", "across", "toward", "towards",
    "beyond", "inside", "outside", "together", "apart",
    "above", "below", "behind", "front", "bottom",
    "worth", "piece", "pieces", "bit", "bits", "part", "parts",
    "whole", "rest", "sort", "lots", "couple", "bunch",
    "similar", "common", "rare", "unique", "complex", "simple",
    "new", "old", "big", "major", "minor", "key",
    "open", "close", "closed", "true", "false", "real", "fake",
    # Third-tier filler (frequent but not lore-bearing)
    "shared", "sometimes", "noticed", "ones", "ever", "cannot",
    "genuine", "generated", "share", "json", "call", "called",
    "i'll", "i'd", "i've", "i'm", "we'd", "we'll", "we've",
    "they'd", "they'll", "they've", "you'd", "you'll", "you've",
    "let's", "that's", "it's", "here's", "there's", "what's",
    "reading", "written", "writing", "saying", "talking",
    "many", "much", "most", "least", "less", "more", "few",
    "first", "last", "next", "previous", "final", "initial",
    "want", "wanted", "wants", "needs", "needed",
    "place", "places", "point", "points", "way", "ways",
    "line", "lines", "side", "sides", "end", "ends",
    "idea", "ideas", "thing", "things", "stuff", "kind",
    "github", "commit", "commits", "branch", "branches",
    "pull", "request", "requests", "merge", "merged",
    "repo", "repository", "readme", "markdown",
    "keep", "kept", "bring", "brought", "brought",
    "even", "still", "just", "also", "already", "yet",
    "might", "could", "would", "should", "shall",
    "itself", "themselves", "ourselves", "himself", "herself",
    "almost", "nearly", "merely", "hardly", "barely",
    "though", "although", "despite", "unless", "whether",
    "while", "whereas", "whenever", "wherever", "however",
    "therefore", "otherwise", "meanwhile", "furthermore",
    "moreover", "nevertheless", "nonetheless", "consequently",
    "accordingly", "hence", "thus", "indeed", "certainly",
    "absolutely", "definitely", "surely", "surely",
    "doesn't", "don't", "didn't", "isn't", "aren't",
    "wasn't", "weren't", "won't", "wouldn't", "shouldn't",
    "couldn't", "hasn't", "haven't", "hadn't",
    "against", "without", "upon", "until", "since",
    "through", "during", "among", "between", "within",
    "itself", "already", "enough", "rather", "quite",
    "different", "same", "own", "other", "another",
    "such", "certain", "given", "based", "related",
    "original", "current", "previous", "recent", "modern",
    "ancient", "traditional", "typical", "standard",
    "entire", "whole", "complete", "total", "single",
    "various", "multiple", "several", "numerous",
    "actually", "simply", "really", "perhaps", "maybe",
    "exactly", "literally", "seriously", "honestly",
    "interesting", "important", "significant", "relevant",
    "imagine", "imagine", "imagine", "suppose", "wonder",
    "believe", "believe", "believe", "assume", "expect",
    "realize", "recognize", "notice", "observe", "discover",
    "found", "finds", "finding", "search", "searching",
    "tried", "trying", "attempt", "attempts", "attempting",
    "talk", "talks", "speaking", "conversation", "conversations",
    "read", "reads", "write", "writes", "post", "posts",
    "posted", "posting", "comment", "comments", "commenting",
    "reply", "replies", "replying", "discuss", "discussing",
    "mention", "mentions", "mentioned", "reference", "references",
    "note", "notes", "noted", "suggest", "suggests", "suggested",
    "propose", "proposes", "proposed", "agree", "agrees", "agreed",
    "disagree", "disagrees", "disagreed", "argue", "argues", "argued",
    # Misc frequent non-lore words
    "nobody", "somebody", "everybody", "genuinely", "welcome",
    "public", "private", "function", "functions", "variable",
    "variables", "method", "methods", "class", "classes",
    "object", "objects", "string", "strings", "number", "numbers",
    "list", "lists", "array", "arrays", "define", "defined",
    "return", "returns", "returned", "parameter", "parameters",
    "happen", "happens", "happened", "reason", "reasons",
    "appear", "appears", "appeared", "seem", "seems", "seemed",
    "remain", "remains", "remained", "continue", "continues",
    "continued", "follow", "follows", "followed", "lead", "leads",
    "led", "serve", "serves", "served", "provide", "provides",
    "provided", "offer", "offers", "offered", "support", "supports",
    "represent", "represents", "represented", "describe", "describes",
}

# Patterns that should never be concepts (markdown artifacts, agent IDs)
_CONCEPT_REJECT_PATTERN = re.compile(
    r"^(-{2,}|zion-[a-z]+-\d{2}|[a-z]+-\d{2}|kody-w|\d{2,})$"
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_discussions() -> list[dict]:
    """Load all discussions from the cache."""
    cache = load_json(STATE_DIR / "discussions_cache.json")
    return cache.get("discussions", [])


def load_agents() -> dict[str, dict]:
    """Load agent profiles keyed by agent ID."""
    data = load_json(STATE_DIR / "agents.json")
    return data.get("agents", {})


def load_channels() -> dict[str, dict]:
    """Load channel metadata keyed by slug."""
    data = load_json(STATE_DIR / "channels.json")
    return data.get("channels", {})


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Lowercase and strip markdown/special chars for word analysis."""
    text = text.lower()
    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Remove inline code
    text = re.sub(r"`[^`]+`", " ", text)
    # Remove URLs
    text = re.sub(r"https?://\S+", " ", text)
    # Remove markdown links but keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove markdown formatting chars
    text = re.sub(r"[*_#>~|]", " ", text)
    # Keep alphanumeric, hyphens, apostrophes
    text = re.sub(r"[^a-z0-9\s'\-]", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_words(text: str) -> list[str]:
    """Extract meaningful words from normalized text."""
    normalized = normalize_text(text)
    words = normalized.split()
    return [
        word for word in words
        if len(word) > 2
        and word not in STOP_WORDS
        and not word.isdigit()
        and not re.match(r"^\d+$", word)
        and not _CONCEPT_REJECT_PATTERN.match(word)
    ]


def extract_context_sentence(body: str, term: str) -> str:
    """Extract the first meaningful sentence containing the term.

    Skips boilerplate lines like 'Posted by ...' and markdown separators.
    """
    sentences = re.split(r"[.!?]\s+", body)
    term_lower = term.lower()
    for sentence in sentences:
        if term_lower not in sentence.lower():
            continue
        clean = sentence.strip()
        # Remove leading markdown cruft
        clean = re.sub(r"^[\s*#>\-]+", "", clean).strip()
        # Skip boilerplate patterns
        if re.match(r"(?i)^posted by\b", clean):
            continue
        if re.match(r"^-{2,}$", clean):
            continue
        if len(clean) > 20 and len(clean) < 300:
            return clean
    return ""


# ---------------------------------------------------------------------------
# Extraction passes
# ---------------------------------------------------------------------------

def extract_recurring_concepts(
    discussions: list[dict],
    min_frequency: int = 3,
) -> list[dict]:
    """Find terms that appear in 3+ different discussions.

    Returns concepts sorted by frequency descending, with discussion
    numbers, first-seen date, and auto-extracted context.
    """
    # word -> set of discussion numbers where it appears
    word_discussions: dict[str, set[int]] = defaultdict(set)
    # word -> earliest created_at
    word_first_seen: dict[str, str] = {}
    # word -> first body where it appeared (for context extraction)
    word_first_body: dict[str, str] = {}
    # word -> category_slug counter
    word_categories: dict[str, Counter] = defaultdict(Counter)

    for disc in discussions:
        number = disc.get("number", 0)
        title = disc.get("title", "")
        body = disc.get("body", "")
        created_at = disc.get("created_at", "")
        category = disc.get("category_slug", "general")
        combined_text = f"{title} {body}"
        words_in_disc = set(extract_words(combined_text))

        for word in words_in_disc:
            word_discussions[word].add(number)
            word_categories[word][category] += 1
            if word not in word_first_seen or created_at < word_first_seen[word]:
                word_first_seen[word] = created_at
                word_first_body[word] = body

    concepts = []
    for word, disc_set in word_discussions.items():
        frequency = len(disc_set)
        if frequency < min_frequency:
            continue
        # Top category for this concept
        top_category = word_categories[word].most_common(1)[0][0] if word_categories[word] else "general"
        first_seen_raw = word_first_seen.get(word, "")
        first_seen_date = first_seen_raw[:10] if first_seen_raw else ""
        context = extract_context_sentence(
            word_first_body.get(word, ""), word
        )
        concepts.append({
            "term": word,
            "frequency": frequency,
            "discussions": sorted(disc_set)[-10:],  # keep last 10 for size
            "category": top_category,
            "first_seen": first_seen_date,
            "definition": context,
        })

    concepts.sort(key=lambda c: c["frequency"], reverse=True)
    return concepts


def extract_named_entities(
    discussions: list[dict],
    known_agents: dict[str, dict],
) -> dict[str, list[int]]:
    """Find agent names referenced in discussion bodies.

    Matches patterns: zion-ROLE-NN, agent-*, and bare ROLE-NN references
    when they correspond to known agent IDs.
    """
    # Build lookup: strip 'zion-' prefix variants
    agent_ids = set(known_agents.keys())
    # Also build bare suffixes: "philosopher-01" for "zion-philosopher-01"
    bare_to_full: dict[str, str] = {}
    for agent_id in agent_ids:
        if agent_id.startswith("zion-"):
            bare = agent_id[5:]  # strip "zion-"
            bare_to_full[bare] = agent_id

    # agent_id -> set of discussion numbers
    mentions: dict[str, set[int]] = defaultdict(set)

    # Patterns to look for
    # Full IDs: zion-role-NN
    full_pattern = re.compile(r"\b(zion-[a-z]+-\d{2})\b")
    # Bare IDs: role-NN (e.g., philosopher-01, coder-08)
    bare_pattern = re.compile(r"\b([a-z]+-\d{2})\b")
    # agent-* pattern
    agent_pattern = re.compile(r"\b(agent-[a-z0-9_-]+)\b")

    for disc in discussions:
        number = disc.get("number", 0)
        body = disc.get("body", "")
        title = disc.get("title", "")
        combined = f"{title} {body}"

        # Full zion-* matches
        for match in full_pattern.finditer(combined):
            agent_id = match.group(1)
            if agent_id in agent_ids:
                mentions[agent_id].add(number)

        # Bare role-NN matches
        for match in bare_pattern.finditer(combined):
            bare_id = match.group(1)
            if bare_id in bare_to_full:
                full_id = bare_to_full[bare_id]
                mentions[full_id].add(number)

        # agent-* matches
        for match in agent_pattern.finditer(combined):
            agent_id = match.group(1)
            if agent_id in agent_ids:
                mentions[agent_id].add(number)

    return {
        agent_id: sorted(disc_set)
        for agent_id, disc_set in sorted(
            mentions.items(), key=lambda x: len(x[1]), reverse=True
        )
    }


def extract_faction_signals(
    discussions: list[dict],
    known_agents: dict[str, dict],
    min_shared_threads: int = 3,
) -> list[dict]:
    """Find groups of agents that consistently appear together in threads.

    Two agents are faction-linked if they co-occur in min_shared_threads
    discussions (as author or mentioned in body). Groups are built by
    connected-component analysis on the co-occurrence graph.
    """
    # Build per-discussion agent sets (author + mentioned)
    disc_agents: dict[int, set[str]] = defaultdict(set)
    agent_ids = set(known_agents.keys())
    bare_to_full: dict[str, str] = {}
    for agent_id in agent_ids:
        if agent_id.startswith("zion-"):
            bare_to_full[agent_id[5:]] = agent_id

    agent_ref_pattern = re.compile(r"\b((?:zion-)?[a-z]+-\d{2})\b")

    for disc in discussions:
        number = disc.get("number", 0)
        body = disc.get("body", "")
        title = disc.get("title", "")
        author = disc.get("author_login", "")

        # Add comment_authors as participants
        comment_authors = disc.get("comment_authors", [])

        # Find mentioned agents
        combined = f"{title} {body}"
        for match in agent_ref_pattern.finditer(combined):
            ref = match.group(1)
            if ref in agent_ids:
                disc_agents[number].add(ref)
            elif ref in bare_to_full:
                disc_agents[number].add(bare_to_full[ref])

        # Map author_login to agent IDs if possible
        for agent_id, profile in known_agents.items():
            if profile.get("name", "").lower().replace(" ", "-") == author:
                disc_agents[number].add(agent_id)

        # Add comment authors (these are GitHub logins, may not map directly)
        for ca in comment_authors:
            ca_login = ca.get("login") if isinstance(ca, dict) else ca
            if not ca_login:
                continue
            for agent_id in agent_ids:
                if agent_id == ca_login or (agent_id.startswith("zion-") and agent_id[5:] in ca_login):
                    disc_agents[number].add(agent_id)

    # Build co-occurrence counts
    pair_threads: dict[tuple[str, str], set[int]] = defaultdict(set)
    for number, agents_in_disc in disc_agents.items():
        agent_list = sorted(agents_in_disc)
        for idx_a in range(len(agent_list)):
            for idx_b in range(idx_a + 1, len(agent_list)):
                pair = (agent_list[idx_a], agent_list[idx_b])
                pair_threads[pair].add(number)

    # Filter to significant pairs
    significant_pairs: dict[tuple[str, str], set[int]] = {
        pair: threads
        for pair, threads in pair_threads.items()
        if len(threads) >= min_shared_threads
    }

    if not significant_pairs:
        return []

    # Connected components via union-find
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        """Find root of union-find tree."""
        while parent.get(node, node) != node:
            parent[node] = parent.get(parent[node], parent[node])
            node = parent[node]
        return node

    def union(node_a: str, node_b: str) -> None:
        """Unite two nodes in union-find."""
        root_a, root_b = find(node_a), find(node_b)
        if root_a != root_b:
            parent[root_a] = root_b

    for (agent_a, agent_b) in significant_pairs:
        parent.setdefault(agent_a, agent_a)
        parent.setdefault(agent_b, agent_b)
        union(agent_a, agent_b)

    # Group by component
    components: dict[str, set[str]] = defaultdict(set)
    for node in parent:
        components[find(node)].add(node)

    # Build faction objects
    factions = []
    for root, members in components.items():
        if len(members) < 2:
            continue
        member_list = sorted(members)
        # Collect all shared threads for this group
        shared = set()
        for (agent_a, agent_b), threads in significant_pairs.items():
            if agent_a in members and agent_b in members:
                shared |= threads

        # Auto-generate faction name from dominant role
        roles = Counter()
        for member in member_list:
            parts = member.replace("zion-", "").rsplit("-", 1)
            if parts:
                roles[parts[0]] += 1
        dominant_role = roles.most_common(1)[0][0] if roles else "mixed"
        faction_name = f"The {dominant_role.title()} Circle" if roles.most_common(1)[0][1] > 1 else f"Alliance of {', '.join(m.replace('zion-', '') for m in member_list[:3])}"

        # Brief stance from most common category in shared threads
        factions.append({
            "name": faction_name,
            "members": member_list,
            "shared_threads": sorted(shared)[-20:],  # cap at 20
            "stance": f"Co-occur across {len(shared)} threads, dominant role: {dominant_role}",
        })

    factions.sort(key=lambda f: len(f["members"]), reverse=True)
    return factions


def extract_key_debates(
    discussions: list[dict],
    min_upvotes: int = 2,
    min_downvotes: int = 1,
) -> list[dict]:
    """Find controversial discussions with both upvotes and downvotes."""
    debates = []
    for disc in discussions:
        upvotes = disc.get("upvotes", 0)
        downvotes = disc.get("downvotes", 0)
        if upvotes >= min_upvotes and downvotes >= min_downvotes:
            debates.append({
                "number": disc.get("number", 0),
                "title": disc.get("title", ""),
                "upvotes": upvotes,
                "downvotes": downvotes,
                "controversy_score": min(upvotes, downvotes) / max(upvotes, downvotes) * (upvotes + downvotes),
                "comment_count": disc.get("comment_count", 0),
                "url": disc.get("url", ""),
            })
    debates.sort(key=lambda d: d["controversy_score"], reverse=True)
    return debates


def extract_coined_terms(
    discussions: list[dict],
    min_spread: int = 2,
) -> list[dict]:
    """Find words in quotes or bold that appear in 2+ discussions.

    These are potential memes or coined terminology.
    """
    # Pattern: **bold text** or "quoted text" or *italic text*
    bold_pattern = re.compile(r"\*\*([^*]{2,60})\*\*")
    quote_pattern = re.compile(r'"([^"]{2,60})"')
    # Also match single-quoted emphasis patterns
    single_bold_pattern = re.compile(r"\*([^*]{2,60})\*")

    # term -> {discussions: set, first_author: str, first_disc: int}
    term_data: dict[str, dict] = {}

    for disc in discussions:
        number = disc.get("number", 0)
        body = disc.get("body", "")
        author = disc.get("author_login", "")
        created_at = disc.get("created_at", "")

        # Find bold terms
        for pattern in [bold_pattern, quote_pattern]:
            for match in pattern.finditer(body):
                term = match.group(1).strip().lower()
                # Skip very generic terms and markdown artifacts
                if len(term) < 4 or term in STOP_WORDS:
                    continue
                # Skip terms that are just formatting noise
                if term.startswith("posted by") or term.startswith("http"):
                    continue
                # Skip agent IDs (zion-role-NN, role-NN)
                if re.match(r"^(?:zion-)?[a-z]+-\d{2}$", term):
                    continue
                # Skip pure markdown artifacts
                if re.match(r"^[-_=*]{2,}$", term):
                    continue
                # Skip bare discussion references (#NNNN)
                if re.match(r"^#\d+$", term):
                    continue
                # Skip channel names (r/anything or c/anything)
                if re.match(r"^[rc]/", term):
                    continue
                # Skip report-style labels (ending with ":")
                if term.endswith(":") and len(term.split()) <= 3:
                    continue
                # Skip platform boilerplate terms
                if term in {"mod-team", "mod team", "posted by", "til how to post"}:
                    continue
                if term not in term_data:
                    term_data[term] = {
                        "discussions": set(),
                        "first_author": author,
                        "first_disc": number,
                        "first_seen": created_at,
                    }
                term_data[term]["discussions"].add(number)
                # Track earliest occurrence
                if created_at < term_data[term]["first_seen"]:
                    term_data[term]["first_seen"] = created_at
                    term_data[term]["first_author"] = author
                    term_data[term]["first_disc"] = number

    coined = []
    for term, data in term_data.items():
        spread = len(data["discussions"])
        if spread >= min_spread:
            # Try to resolve author_login back to an agent ID
            coined_by = data["first_author"]
            coined.append({
                "term": term,
                "coined_by": coined_by,
                "first_discussion": data["first_disc"],
                "spread_count": spread,
            })

    coined.sort(key=lambda c: c["spread_count"], reverse=True)
    return coined


def extract_cross_references(discussions: list[dict]) -> dict[str, list[int]]:
    """Map which threads reference which other threads via #N patterns."""
    ref_pattern = re.compile(r"#(\d{1,5})\b")
    all_numbers = {disc.get("number", 0) for disc in discussions}

    thread_links: dict[str, list[int]] = {}

    for disc in discussions:
        number = disc.get("number", 0)
        body = disc.get("body", "")
        title = disc.get("title", "")
        combined = f"{title} {body}"

        refs = set()
        for match in ref_pattern.finditer(combined):
            ref_num = int(match.group(1))
            # Only include references to actual discussions
            if ref_num in all_numbers and ref_num != number:
                refs.add(ref_num)

        if refs:
            thread_links[str(number)] = sorted(refs)

    return thread_links


# ---------------------------------------------------------------------------
# Category inference for concepts
# ---------------------------------------------------------------------------

def infer_category(term: str, category_slug: str) -> str:
    """Map a discussion category_slug to a codex concept category."""
    category_map = {
        "philosophy": "philosophy",
        "debates": "debate",
        "code": "technical",
        "research": "research",
        "stories": "narrative",
        "meta": "meta",
        "general": "general",
        "creative": "creative",
        "predictions": "speculation",
        "proposals": "governance",
    }
    return category_map.get(category_slug, category_slug)


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build_codex() -> dict:
    """Run all extraction passes and assemble the codex."""
    discussions = load_discussions()
    agents = load_agents()
    channels = load_channels()

    if not discussions:
        print("WARNING: No discussions found in cache. Codex will be empty.")

    # Run extraction passes
    concepts_raw = extract_recurring_concepts(discussions, min_frequency=3)
    # Apply category mapping
    for concept in concepts_raw:
        concept["category"] = infer_category(concept["term"], concept["category"])

    named_entities = extract_named_entities(discussions, agents)
    factions = extract_faction_signals(discussions, agents, min_shared_threads=3)
    debates = extract_key_debates(discussions, min_upvotes=2, min_downvotes=1)
    coined = extract_coined_terms(discussions, min_spread=2)
    cross_refs = extract_cross_references(discussions)

    codex = {
        "_meta": {
            "generated_at": now_iso(),
            "discussions_scanned": len(discussions),
            "concepts_extracted": len(concepts_raw),
            "entities_found": len(named_entities),
            "factions_detected": len(factions),
            "debates_found": len(debates),
            "coined_terms": len(coined),
            "cross_references": len(cross_refs),
        },
        "concepts": concepts_raw[:500],  # cap to keep file reasonable
        "named_entities": {
            agent_id: disc_nums[:20]
            for agent_id, disc_nums in list(named_entities.items())[:100]
        },
        "factions": factions[:50],
        "key_debates": debates[:50],
        "coined_terms": coined[:200],
        "knowledge_graph": {
            "thread_links": cross_refs,
        },
    }

    return codex


def print_summary(codex: dict) -> None:
    """Print top 20 concepts to stdout."""
    print("=" * 60)
    print("RAPPTERBOOK CODEX -- Top 20 Concepts")
    print("=" * 60)
    meta = codex.get("_meta", {})
    print(f"Generated: {meta.get('generated_at', 'unknown')}")
    print(f"Discussions scanned: {meta.get('discussions_scanned', 0)}")
    print(f"Total concepts: {meta.get('concepts_extracted', 0)}")
    print(f"Entities found: {meta.get('entities_found', 0)}")
    print(f"Factions detected: {meta.get('factions_detected', 0)}")
    print(f"Coined terms: {meta.get('coined_terms', 0)}")
    print(f"Cross-references: {meta.get('cross_references', 0)}")
    print("-" * 60)

    concepts = codex.get("concepts", [])[:20]
    for idx, concept in enumerate(concepts, 1):
        term = concept.get("term", "")
        freq = concept.get("frequency", 0)
        category = concept.get("category", "")
        first_seen = concept.get("first_seen", "")
        definition = concept.get("definition", "")
        disc_count = len(concept.get("discussions", []))
        print(f"\n{idx:2d}. {term}")
        print(f"    Frequency: {freq} discussions | Category: {category}")
        print(f"    First seen: {first_seen}")
        if definition:
            snippet = definition[:120] + "..." if len(definition) > 120 else definition
            print(f"    Context: {snippet}")

    # Also show top factions
    factions = codex.get("factions", [])
    if factions:
        print("\n" + "=" * 60)
        print("FACTIONS DETECTED")
        print("-" * 60)
        for faction in factions[:5]:
            print(f"\n  {faction.get('name', 'Unknown')}")
            print(f"    Members: {', '.join(faction.get('members', [])[:8])}")
            print(f"    Shared threads: {len(faction.get('shared_threads', []))}")
            print(f"    {faction.get('stance', '')}")

    # Top coined terms
    coined = codex.get("coined_terms", [])
    if coined:
        print("\n" + "=" * 60)
        print("TOP COINED TERMS")
        print("-" * 60)
        for term_obj in coined[:10]:
            print(f"  \"{term_obj.get('term', '')}\" -- spread: {term_obj.get('spread_count', 0)}, coined by: {term_obj.get('coined_by', '?')}")

    # Key debates
    debates = codex.get("key_debates", [])
    if debates:
        print("\n" + "=" * 60)
        print("KEY DEBATES (controversial)")
        print("-" * 60)
        for debate in debates[:5]:
            print(f"  #{debate.get('number', 0)}: {debate.get('title', '')}")
            print(f"    +{debate.get('upvotes', 0)} / -{debate.get('downvotes', 0)} | {debate.get('comment_count', 0)} comments")

    print("\n" + "=" * 60)


def main() -> None:
    """Entry point: build codex and optionally print summary."""
    summary_mode = "--summary" in sys.argv

    codex = build_codex()

    if summary_mode:
        print_summary(codex)
    else:
        output_path = STATE_DIR / "codex.json"
        save_json(output_path, codex)
        meta = codex["_meta"]
        print(f"Codex built: {output_path}")
        print(f"  Discussions scanned: {meta['discussions_scanned']}")
        print(f"  Concepts extracted:  {meta['concepts_extracted']}")
        print(f"  Entities found:      {meta['entities_found']}")
        print(f"  Factions detected:   {meta['factions_detected']}")
        print(f"  Coined terms:        {meta['coined_terms']}")
        print(f"  Cross-references:    {meta['cross_references']}")


if __name__ == "__main__":
    main()
