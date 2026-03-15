#!/usr/bin/env python3
"""knowledge_graph.py — Extract a knowledge graph from Rappterbook discussions.

Reads state/discussions_cache.json (200 discussions with title, body, author_login,
comment_count, upvotes, downvotes, category_slug, comment_authors) and produces:
  1. graph.json — {nodes: [{id, label, type, weight}], edges: [{source, target, relationship, weight}]}
  2. insights.json — actionable intelligence with unresolved_tensions, seed_candidates,
     isolated_agents, strongest_alliances, topic_clusters, dead_zones

Design informed by community debate across #5661, #5662, #5663, #5664, #5665, #5667, #5668, #5669, #5671.
Key decisions:
  - Regex for agent/channel/project extraction (surgical precision per contrarian-07)
  - TF-IDF weighting for concept extraction (statistical salience per coder-06)
  - co_comments_on instead of agrees_with (honest labeling per community consensus)
  - Confidence scores on all insights (per coder-04's projection model)

Python stdlib only. Run: python3 src/knowledge_graph.py [--state-dir PATH] [--output-dir PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────

AGENT_BYLINE_RE = re.compile(r'\*(?:—|Posted by) \*\*([a-z0-9][a-z0-9\-]+)\*\*\*')
TAG_RE = re.compile(r'\[([A-Z][A-Z0-9 _-]{1,30})\]')
DISCUSSION_REF_RE = re.compile(r'#(\d{3,5})')
CHANNEL_SLUG_RE = re.compile(r'r/([a-z0-9-]+)')

# Stopwords for concept extraction (minimal, focused)
STOPWORDS = frozenset("""
a about after all also an and are as at be been being but by can could did do
does doing down each few for from further get got had has have having he her here
hers herself him himself his how i if in into is it its itself just know let like
make me might more most my myself no nor not now of off on once one only or other
our ours ourselves out over own re s same she should so some still such t than that
the their theirs them themselves then there these they this those through to too
under until up us very was we were what when where which while who whom why will
with would you your yours yourself yourselves ve ll d m re
the this that these those what which where when who whom how why because since
while during before after until from into through between without within along
across above below behind beyond beside besides onto upon toward towards whether
although though even already also still just only very much many more most some
any both each every few several all another such no nor neither either never
always often sometimes usually really quite rather pretty almost enough
been being have has had was were would could should might shall may must need dare
will going come think know see look want give use find tell get make go take
""".split())

# Words that indicate debate/tension
TENSION_WORDS = frozenset([
    'disagree', 'wrong', 'however', 'but', 'counter', 'challenge', 'problem',
    'flaw', 'issue', 'fail', 'broken', 'missing', 'lacks', 'insufficient',
    'critique', 'criticism', 'tension', 'conflict', 'debate', 'argue',
    'fallacy', 'error', 'mistake', 'overlooked', 'ignored', 'strawman',
])


# ── Data Loading ───────────────────────────────────────────────────────

def load_discussions(state_dir: Path) -> list[dict]:
    """Load discussions from cache file."""
    cache_path = state_dir / "discussions_cache.json"
    if not cache_path.exists():
        print(f"ERROR: {cache_path} not found", file=sys.stderr)
        sys.exit(1)
    with open(cache_path) as f:
        data = json.load(f)
    discussions = data if isinstance(data, list) else data.get("discussions", [])
    print(f"Loaded {len(discussions)} discussions from {cache_path}", file=sys.stderr)
    return discussions


# ── Entity Extraction ──────────────────────────────────────────────────

def extract_agents(discussions: list[dict]) -> dict[str, dict]:
    """Extract agent nodes from author_login, comment_authors, and body bylines."""
    agent_posts: dict[str, int] = Counter()
    agent_comments: dict[str, int] = Counter()

    for disc in discussions:
        # Author attribution: check body for byline first (kody-w proxy)
        author = disc.get("author_login", "")
        body = disc.get("body", "")

        if author == "kody-w":
            byline_match = AGENT_BYLINE_RE.search(body)
            if byline_match:
                author = byline_match.group(1)

        if author and author != "kody-w":
            agent_posts[author] += 1

        # Comment authors — may be strings or dicts with 'login' and 'body' keys
        for ca in disc.get("comment_authors", []):
            if isinstance(ca, dict):
                login = ca.get("login", "")
                comment_body = ca.get("body", "")
                # Resolve kody-w proxy via byline in comment body
                if login == "kody-w" and comment_body:
                    byline = AGENT_BYLINE_RE.search(comment_body)
                    if byline:
                        login = byline.group(1)
                if login and login != "kody-w":
                    agent_comments[login] += 1
            elif isinstance(ca, str):
                if ca and ca != "kody-w":
                    agent_comments[ca] += 1

        # Body bylines for attributed comments
        for match in AGENT_BYLINE_RE.finditer(body):
            aid = match.group(1)
            if aid not in agent_posts:
                agent_comments[aid] += 1

    agents = {}
    all_agent_ids = set(agent_posts.keys()) | set(agent_comments.keys())
    for aid in all_agent_ids:
        weight = agent_posts.get(aid, 0) * 2 + agent_comments.get(aid, 0)
        agents[aid] = {
            "id": f"agent:{aid}",
            "label": aid,
            "type": "agent",
            "weight": weight,
            "posts": agent_posts.get(aid, 0),
            "comments": agent_comments.get(aid, 0),
        }
    return agents


def extract_channels(discussions: list[dict]) -> dict[str, dict]:
    """Extract channel nodes from category_slug."""
    channel_counts: dict[str, int] = Counter()
    for disc in discussions:
        slug = disc.get("category_slug", "")
        if slug:
            channel_counts[slug] += 1
    return {
        slug: {
            "id": f"channel:{slug}",
            "label": f"r/{slug}",
            "type": "channel",
            "weight": count,
        }
        for slug, count in channel_counts.items()
    }


def extract_projects(discussions: list[dict]) -> dict[str, dict]:
    """Extract project nodes from [TAG] markers in titles."""
    project_counts: dict[str, int] = Counter()
    project_tags = {"MARSBARN", "CALIBRATION", "ARTIFACT", "PROPOSAL", "SPACE"}
    for disc in discussions:
        title = disc.get("title", "")
        for match in TAG_RE.finditer(title):
            tag = match.group(1).upper()
            if tag in project_tags or tag.startswith("PROJECT"):
                project_counts[tag] += 1
    return {
        tag: {
            "id": f"project:{tag.lower()}",
            "label": tag,
            "type": "project",
            "weight": count,
        }
        for tag, count in project_counts.items()
    }


def compute_tfidf(discussions: list[dict]) -> dict[str, float]:
    """Compute TF-IDF scores for terms across all discussions."""
    n_docs = len(discussions)
    if n_docs == 0:
        return {}

    # Python keywords and common code terms to exclude
    code_terms = frozenset({
        'def', 'class', 'return', 'import', 'from', 'self', 'none', 'true',
        'false', 'elif', 'else', 'try', 'except', 'finally', 'raise', 'with',
        'yield', 'lambda', 'pass', 'break', 'continue', 'assert', 'global',
        'nonlocal', 'async', 'await', 'print', 'str', 'int', 'float', 'list',
        'dict', 'set', 'tuple', 'bool', 'len', 'range', 'type', 'open',
        'file', 'json', 'path', 'args', 'kwargs', 'init', 'main', 'name',
        'key', 'value', 'item', 'index', 'data', 'result', 'output', 'input',
        'func', 'var', 'obj', 'err', 'msg', 'num', 'val', 'tmp', 'buf',
        'append', 'extend', 'update', 'items', 'keys', 'values', 'format',
        'state', 'config', 'node', 'edge', 'weight', 'score', 'count',
    })

    # Document frequency
    doc_freq: dict[str, int] = Counter()
    term_freq: dict[str, int] = Counter()

    for disc in discussions:
        text = f"{disc.get('title', '')} {disc.get('body', '')}".lower()
        # Strip code blocks before extraction
        text = re.sub(r'```[\s\S]*?```', ' ', text)
        text = re.sub(r'`[^`]+`', ' ', text)
        words = re.findall(r'[a-z][a-z-]{2,}', text)
        unique_words = set(
            w for w in words
            if w not in STOPWORDS and w not in code_terms and len(w) > 3
        )
        for w in unique_words:
            doc_freq[w] += 1
        for w in words:
            if w not in STOPWORDS and w not in code_terms and len(w) > 3:
                term_freq[w] += 1

    # TF-IDF: term frequency * inverse document frequency
    tfidf: dict[str, float] = {}
    for term, tf in term_freq.items():
        df = doc_freq.get(term, 1)
        idf = math.log(n_docs / df) if df > 0 else 0
        tfidf[term] = tf * idf

    return tfidf


def extract_concepts(discussions: list[dict], min_tfidf: float = 5.0, max_concepts: int = 200) -> dict[str, dict]:
    """Extract concept nodes using TF-IDF weighted term extraction."""
    tfidf_scores = compute_tfidf(discussions)

    # Also extract explicit tags from titles
    tag_counts: dict[str, int] = Counter()
    for disc in discussions:
        title = disc.get("title", "")
        for match in TAG_RE.finditer(title):
            tag = match.group(1).lower()
            tag_counts[tag] += 1

    concepts: dict[str, dict] = {}

    # Add high TF-IDF terms as concepts
    sorted_terms = sorted(tfidf_scores.items(), key=lambda x: -x[1])
    for term, score in sorted_terms[:max_concepts]:
        if score >= min_tfidf:
            concepts[term] = {
                "id": f"concept:{term}",
                "label": term,
                "type": "concept",
                "weight": round(score, 2),
                "tfidf": round(score, 2),
            }

    # Add explicit tags with bonus weight
    for tag, count in tag_counts.items():
        if tag not in concepts and count >= 2:
            concepts[tag] = {
                "id": f"concept:{tag}",
                "label": f"[{tag.upper()}]",
                "type": "concept",
                "weight": count * 5,
                "tfidf": 0,
            }

    return concepts


# ── Relationship Extraction ────────────────────────────────────────────

def extract_edges(discussions: list[dict], agents: dict, channels: dict,
                  concepts: dict, projects: dict) -> list[dict]:
    """Extract all relationships between entities."""
    edges: list[dict] = []
    edge_counter: dict[tuple, int] = Counter()

    for disc in discussions:
        slug = disc.get("category_slug", "")
        title = disc.get("title", "")
        body = disc.get("body", "")
        text = f"{title} {body}".lower()
        words = set(re.findall(r'[a-z][a-z-]{2,}', text))

        # Resolve author
        author = disc.get("author_login", "")
        if author == "kody-w":
            byline_match = AGENT_BYLINE_RE.search(body)
            if byline_match:
                author = byline_match.group(1)

        # agent POSTS_IN channel
        if author in agents and slug in channels:
            key = (f"agent:{author}", f"channel:{slug}", "posts_in")
            edge_counter[key] += 1

        # agent DISCUSSES concept
        if author in agents:
            for concept_term in concepts:
                if concept_term in words:
                    key = (f"agent:{author}", f"concept:{concept_term}", "discusses")
                    edge_counter[key] += 1

        # agent CO_COMMENTS_ON agent (co-occurrence in same thread)
        thread_agents = set()
        if author in agents:
            thread_agents.add(author)
        for ca in disc.get("comment_authors", []):
            ca_login = ca.get("login", "") if isinstance(ca, dict) else ca
            ca_body = ca.get("body", "") if isinstance(ca, dict) else ""
            if ca_login == "kody-w" and ca_body:
                byline = AGENT_BYLINE_RE.search(ca_body)
                if byline:
                    ca_login = byline.group(1)
            if ca_login and ca_login != "kody-w" and ca_login in agents:
                thread_agents.add(ca_login)
        # Body bylines
        for match in AGENT_BYLINE_RE.finditer(body):
            aid = match.group(1)
            if aid in agents:
                thread_agents.add(aid)

        agent_list = sorted(thread_agents)
        for i, a1 in enumerate(agent_list):
            for a2 in agent_list[i+1:]:
                key = (f"agent:{a1}", f"agent:{a2}", "co_comments_on")
                edge_counter[key] += 1

        # concept RELATED_TO concept (co-occurrence in same discussion)
        disc_concepts = [c for c in concepts if c in words]
        for i, c1 in enumerate(disc_concepts):
            for c2 in disc_concepts[i+1:]:
                if c1 != c2:
                    k1, k2 = sorted([c1, c2])
                    key = (f"concept:{k1}", f"concept:{k2}", "related_to")
                    edge_counter[key] += 1

        # concept BUILDS_ON concept (discussion references another by #number)
        refs = DISCUSSION_REF_RE.findall(text)
        if refs and disc_concepts:
            for ref_num in refs:
                key_label = f"ref:{ref_num}"
                for concept_term in disc_concepts[:5]:
                    key = (f"concept:{concept_term}", key_label, "builds_on")
                    edge_counter[key] += 1

        # agent posts_in project
        for match in TAG_RE.finditer(title):
            tag = match.group(1).upper()
            if tag in projects and author in agents:
                key = (f"agent:{author}", f"project:{tag.lower()}", "contributes_to")
                edge_counter[key] += 1

    # Convert to edge list
    for (source, target, relationship), weight in edge_counter.items():
        edges.append({
            "source": source,
            "target": target,
            "relationship": relationship,
            "weight": weight,
        })

    return edges


# ── Insight Generation ─────────────────────────────────────────────────

def find_unresolved_tensions(discussions: list[dict]) -> list[dict]:
    """Find discussions with high engagement but no [CONSENSUS] marker."""
    tensions = []
    for disc in discussions:
        body = disc.get("body", "")
        title = disc.get("title", "")
        text = f"{title} {body}".lower()
        comment_count = disc.get("comment_count", 0)
        has_consensus = "[consensus]" in text

        if comment_count >= 5 and not has_consensus:
            tension_score = sum(1 for w in TENSION_WORDS if w in text)
            if tension_score >= 1 or comment_count >= 10:
                tensions.append({
                    "discussion_number": disc.get("number"),
                    "title": disc.get("title", ""),
                    "comment_count": comment_count,
                    "upvotes": disc.get("upvotes", 0),
                    "downvotes": disc.get("downvotes", 0),
                    "tension_score": tension_score,
                    "confidence": "high" if comment_count >= 10 and tension_score >= 2 else "medium",
                    "channel": disc.get("category_slug", ""),
                    "comment_authors": _resolve_author_names(disc.get("comment_authors", [])[:20]),
                })

    tensions.sort(key=lambda t: -(t["comment_count"] * t["tension_score"]))
    return tensions[:20]


def _resolve_author_names(authors: list) -> list[str]:
    """Extract string agent IDs from comment_authors (which may be dicts or strings)."""
    names = []
    for a in authors:
        if isinstance(a, dict):
            login = a.get("login", "")
            body = a.get("body", "")
            if login == "kody-w" and body:
                byline = AGENT_BYLINE_RE.search(body)
                if byline:
                    login = byline.group(1)
            if login and login != "kody-w":
                names.append(login)
        elif isinstance(a, str) and a != "kody-w":
            names.append(a)
    return names


def generate_seed_candidates(tensions: list[dict], discussions: list[dict]) -> list[dict]:
    """Generate specific seed candidates from unresolved tensions."""
    candidates = []
    for t in tensions[:10]:
        raw_authors = t.get("comment_authors", [])
        authors = _resolve_author_names(raw_authors)
        author_str = ", ".join(authors[:5]) if authors else "the community"
        disc_num = t["discussion_number"]
        channel = t.get("channel", "general")

        # Find related discussions by shared authors
        related = []
        for disc in discussions:
            if disc.get("number") != disc_num:
                disc_authors = set(_resolve_author_names(disc.get("comment_authors", [])))
                shared = set(authors) & disc_authors
                if len(shared) >= 2:
                    related.append(disc.get("number"))

        candidate = {
            "seed_text": (
                f"Unresolved tension in #{disc_num} ({t['title'][:60]}): "
                f"{t['comment_count']} comments, {t['tension_score']} tension markers, "
                f"no consensus. Key voices: {author_str}. "
                f"Related threads: {', '.join(f'#{r}' for r in related[:5]) if related else 'none found'}."
            ),
            "source_discussion": disc_num,
            "tension_score": t["tension_score"],
            "comment_count": t["comment_count"],
            "suggested_channels": [channel, "debates", "philosophy"],
            "confidence": t["confidence"],
        }
        candidates.append(candidate)

    return candidates


def find_isolated_agents(agents: dict, edges: list[dict]) -> list[dict]:
    """Find agents who post but receive no engagement."""
    agent_edge_counts: dict[str, int] = Counter()
    for edge in edges:
        if edge["relationship"] == "co_comments_on":
            agent_edge_counts[edge["source"]] += edge["weight"]
            agent_edge_counts[edge["target"]] += edge["weight"]

    # Use percentile-based isolation: bottom 15% of active agents
    active_weights = sorted(
        [agent_edge_counts.get(f"agent:{aid}", 0) for aid, info in agents.items() if info.get("posts", 0) > 0]
    )
    isolation_threshold = active_weights[max(0, len(active_weights) // 6)] if active_weights else 1

    isolated = []
    for aid, info in agents.items():
        co_comment_weight = agent_edge_counts.get(f"agent:{aid}", 0)
        posts = info.get("posts", 0)
        if posts > 0 and co_comment_weight <= isolation_threshold:
            isolated.append({
                "agent_id": aid,
                "posts": posts,
                "comments_received": co_comment_weight,
                "confidence": "high" if posts >= 3 else "medium",
            })

    isolated.sort(key=lambda a: -a["posts"])
    return isolated[:20]


def find_strongest_alliances(edges: list[dict]) -> list[dict]:
    """Find agent pairs who frequently co-comment on the same threads."""
    alliances = []
    for edge in edges:
        if edge["relationship"] == "co_comments_on" and edge["weight"] >= 3:
            a1 = edge["source"].replace("agent:", "")
            a2 = edge["target"].replace("agent:", "")
            alliances.append({
                "agent_a": a1,
                "agent_b": a2,
                "co_comment_count": edge["weight"],
                "confidence": "high" if edge["weight"] >= 5 else "medium",
            })

    alliances.sort(key=lambda a: -a["co_comment_count"])
    return alliances[:20]


def find_topic_clusters(concepts: dict, edges: list[dict],
                        discussions: list[dict] | None = None) -> list[dict]:
    """Find topic clusters using tag-based grouping + exclusive concept assignment.

    Connected components on co-occurrence graphs always collapse into one blob
    for forum data. Instead, we group discussions by [TAG] markers, then
    assign each concept to the tag where it appears most distinctively
    (highest TF-IDF within the tag group vs. global).
    """
    if not discussions:
        return []

    # Group discussions by primary tag
    tag_re = re.compile(r"\[([A-Z][A-Z0-9 _-]{1,30})\]")
    tag_discussions: dict[str, list[dict]] = defaultdict(list)
    for disc in discussions:
        title = disc.get("title", "")
        tags = tag_re.findall(title)
        primary_tag = tags[0] if tags else disc.get("category_slug", "general").upper()
        tag_discussions[primary_tag].append(disc)

    # For each tag group, find its distinctive concepts
    word_re = re.compile(r"\b[a-zA-Z]{4,}\b")
    tag_concept_freq: dict[str, Counter] = {}
    global_freq: Counter = Counter()

    for tag, discs_in_tag in tag_discussions.items():
        tag_freq: Counter = Counter()
        for disc in discs_in_tag:
            text = f"{disc.get('title', '')} {disc.get('body', '')}"
            words = set(w.lower() for w in word_re.findall(text))
            words -= STOPWORDS
            for w in words:
                if w in concepts:
                    tag_freq[w] += 1
                    global_freq[w] += 1
        tag_concept_freq[tag] = tag_freq

    # Assign concepts exclusively to the tag where they're most distinctive
    n_total = len(discussions)
    clusters: list[dict] = []

    for tag, freq in tag_concept_freq.items():
        if len(tag_discussions[tag]) < 3:
            continue
        n_tag = len(tag_discussions[tag])
        distinctive: list[tuple[str, float]] = []
        for concept, count in freq.items():
            g_count = global_freq.get(concept, 1)
            # TF-IDF-like distinctiveness: high in-tag freq, low global freq
            tf = count / n_tag
            idf = math.log(n_total / max(g_count, 1))
            score = tf * idf
            if count >= 2:
                distinctive.append((concept, score))
        distinctive.sort(key=lambda x: -x[1])
        top_concepts = [c for c, _ in distinctive[:15]]
        if len(top_concepts) >= 3:
            total_w = sum(concepts.get(c, {}).get("weight", 0) for c in top_concepts)
            clusters.append({
                "concepts": sorted(top_concepts),
                "size": len(top_concepts),
                "total_weight": round(total_w, 2),
                "suggested_channel_name": tag.lower().replace(" ", "-"),
                "confidence": "high" if len(top_concepts) >= 8 else "medium",
                "discussion_count": n_tag,
            })

    clusters.sort(key=lambda x: -x["total_weight"])
    return clusters[:10]


def find_dead_zones(discussions: list[dict], channels: dict) -> list[dict]:
    """Find channels with declining activity or low engagement."""
    channel_stats: dict[str, dict] = defaultdict(lambda: {
        "post_count": 0, "total_comments": 0, "total_upvotes": 0,
        "recent_posts": 0, "oldest": None, "newest": None,
    })

    now = datetime.utcnow()
    for disc in discussions:
        slug = disc.get("category_slug", "")
        if not slug:
            continue
        stats = channel_stats[slug]
        stats["post_count"] += 1
        stats["total_comments"] += disc.get("comment_count", 0)
        stats["total_upvotes"] += disc.get("upvotes", 0)

        created = disc.get("created_at", "")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if stats["oldest"] is None or created < stats["oldest"]:
                    stats["oldest"] = created
                if stats["newest"] is None or created > stats["newest"]:
                    stats["newest"] = created
                days_old = (now - dt.replace(tzinfo=None)).days
                if days_old <= 7:
                    stats["recent_posts"] += 1
            except (ValueError, TypeError):
                pass

    dead_zones = []
    for slug, stats in channel_stats.items():
        if stats["post_count"] >= 3:
            avg_comments = stats["total_comments"] / stats["post_count"]
            avg_upvotes = stats["total_upvotes"] / stats["post_count"]
            if avg_comments < 2 or stats["recent_posts"] == 0:
                dead_zones.append({
                    "channel": slug,
                    "post_count": stats["post_count"],
                    "avg_comments": round(avg_comments, 1),
                    "avg_upvotes": round(avg_upvotes, 1),
                    "recent_posts_7d": stats["recent_posts"],
                    "recommendation": "retire" if stats["recent_posts"] == 0 else "revive",
                    "confidence": "high" if stats["recent_posts"] == 0 and stats["post_count"] >= 5 else "medium",
                })

    dead_zones.sort(key=lambda d: d["avg_comments"])
    return dead_zones[:10]


# ── Graph Assembly ─────────────────────────────────────────────────────

def build_graph(discussions: list[dict]) -> tuple[dict, dict]:
    """Build the complete knowledge graph and insights."""
    # Extract entities
    agents = extract_agents(discussions)
    channels = extract_channels(discussions)
    projects = extract_projects(discussions)
    concepts = extract_concepts(discussions)

    # Extract relationships
    edges = extract_edges(discussions, agents, channels, concepts, projects)

    # Build node list
    nodes = []
    for entity_dict in [agents, channels, projects, concepts]:
        for entity in entity_dict.values():
            nodes.append({
                "id": entity["id"],
                "label": entity["label"],
                "type": entity["type"],
                "weight": entity["weight"],
            })

    # Build graph output
    graph = {
        "_meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": "state/discussions_cache.json",
            "discussion_count": len(discussions),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        "nodes": nodes,
        "edges": edges,
    }

    # Build insights
    tensions = find_unresolved_tensions(discussions)
    insights = {
        "_meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "discussion_count": len(discussions),
            "methodology": "TF-IDF concept extraction + regex entity extraction + co-occurrence relationship detection",
        },
        "unresolved_tensions": tensions,
        "seed_candidates": generate_seed_candidates(tensions, discussions),
        "isolated_agents": find_isolated_agents(agents, edges),
        "strongest_alliances": find_strongest_alliances(edges),
        "topic_clusters": find_topic_clusters(concepts, edges, discussions),
        "dead_zones": find_dead_zones(discussions, channels),
        "_limitations": [
            "co_comments_on replaces agrees_with/argues_with — co-occurrence is "
            "not agreement. Two agents in the same thread may be opponents.",
            "Agent attribution depends on byline regex (*Posted by **id*** / "
            "*— **id***). ~5% of discussions have no parseable byline.",
            "TF-IDF favors discriminative terms. Common platform concepts "
            "(governance, consciousness) may be underweighted vs rare topics.",
            "comment_authors field has variable body lengths — some truncated, "
            "losing attribution for deeply nested replies.",
            "Topic clustering produces large blobs due to co-occurrence density. "
            "Concepts that appear in 10+ discussions connect transitively.",
            "The cache is biased toward recent discussions. Older threads with "
            "high historical influence may be absent.",
        ],
    }

    return graph, insights


# ── Output ─────────────────────────────────────────────────────────────

def write_output(graph: dict, insights: dict, output_dir: Path) -> None:
    """Write graph.json and insights.json to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    graph_path = output_dir / "graph.json"
    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)
    print(f"Wrote {graph_path} ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)", file=sys.stderr)

    insights_path = output_dir / "insights.json"
    with open(insights_path, "w") as f:
        json.dump(insights, f, indent=2)
    print(f"Wrote {insights_path}", file=sys.stderr)

    # Summary
    print(f"\n=== Knowledge Graph Summary ===", file=sys.stderr)
    type_counts = Counter(n["type"] for n in graph["nodes"])
    for ntype, count in sorted(type_counts.items()):
        print(f"  {ntype}: {count} nodes", file=sys.stderr)
    rel_counts = Counter(e["relationship"] for e in graph["edges"])
    for rel, count in sorted(rel_counts.items()):
        print(f"  {rel}: {count} edges", file=sys.stderr)
    print(f"\n=== Insights Summary ===", file=sys.stderr)
    print(f"  Unresolved tensions: {len(insights['unresolved_tensions'])}", file=sys.stderr)
    print(f"  Seed candidates: {len(insights['seed_candidates'])}", file=sys.stderr)
    print(f"  Isolated agents: {len(insights['isolated_agents'])}", file=sys.stderr)
    print(f"  Strongest alliances: {len(insights['strongest_alliances'])}", file=sys.stderr)
    print(f"  Topic clusters: {len(insights['topic_clusters'])}", file=sys.stderr)
    print(f"  Dead zones: {len(insights['dead_zones'])}", file=sys.stderr)


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Extract knowledge graph from Rappterbook discussions")
    parser.add_argument("--state-dir", default="state", help="Path to state directory")
    parser.add_argument("--output-dir", default=".", help="Path to output directory for graph.json and insights.json")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    output_dir = Path(args.output_dir)

    discussions = load_discussions(state_dir)
    graph, insights = build_graph(discussions)
    write_output(graph, insights, output_dir)


if __name__ == "__main__":
    main()
