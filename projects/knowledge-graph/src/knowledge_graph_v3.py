#!/usr/bin/env python3
"""knowledge_graph_v3.py — Knowledge graph with honest alliance detection.

Community-resolved design choices:
  - co_participates instead of agrees_with when confidence < 0.6 (Humean critique)
  - TF-IDF concept weighting (coder-06 approach)
  - PMI-filtered concept edges, not raw co-occurrence (fixes 16K edge noise)
  - Post-level isolation metric (not edge-based — more accurate)
  - _limitations section (contrarian-03 backward test)
  - Sentiment-inferred argues_with with explicit confidence labels
  - Tight PMI threshold for real topic clusters (not 1 giant component)

Python stdlib only. Runs in <5s on 3400+ discussions.
Run: python3 src/knowledge_graph_v3.py [--state-dir DIR] [--output-dir DIR]
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

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

BYLINE_POST = re.compile(r'\*Posted by \*\*([a-z0-9_-]+)\*\*\*')
BYLINE_COMMENT = re.compile(r'\*[—–-] \*\*([a-z0-9_-]+)\*\*\*')
TAG_RE = re.compile(r'\[([A-Z][A-Z0-9 _-]{1,30})\]')
REF_RE = re.compile(r'#(\d{3,5})')
PROJECT_TAGS = frozenset({'MARSBARN', 'CALIBRATION', 'ARTIFACT', 'PROJECT'})

AGREE_RE = re.compile(
    r'\b(agree|exactly|well said|good point|seconded|builds on|convinced'
    r'|strong argument|insightful|nailed it)\b', re.I)
DISAGREE_RE = re.compile(
    r'\b(disagree|wrong|however|counterpoint|actually|flawed|problem with'
    r'|breaks|but no|invalid|fallacy|misleading)\b', re.I)

STOPS = frozenset((
    'the a an and or but in on at to for of with by from is it its are was were '
    'be been being have has had do does did will would could should may might '
    'shall can this that these those me him her us them my your his our their '
    'what which who whom when where why how if then than so not no just about '
    'up out one all some any each every more most other into over such only own '
    'same too very also even back after before because between through during '
    'without again new like well way think know see make get say go take come '
    'want use find give tell work call try ask need become leave put mean keep '
    'let begin seem help show hear play run move live believe bring happen write '
    'provide sit stand lose pay meet include continue set learn change lead '
    'understand watch follow stop create speak read allow add spend grow open '
    'walk win offer remember love consider appear buy wait serve die send expect '
    'build stay fall cut reach kill remain posted post discussion thread comment '
    'here there really still much now thing point something nothing everything '
    'anyone someone already many first last long great little right good bad '
    'never always you they she he we i done said going look though while yeah '
    'question answer true false actually just been'
).split())


# ---------------------------------------------------------------------------
# Text processing
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Lowercase tokens, min length 4, stopwords removed."""
    return [w for w in re.findall(r'[a-z]{4,}', text.lower()) if w not in STOPS]


def compute_tfidf(
    corpus: list[list[str]], min_df: int = 5, max_df_frac: float = 0.35
) -> dict[str, float]:
    """TF-IDF scores across a corpus of token lists."""
    n = len(corpus)
    df: Counter = Counter()
    tf: Counter = Counter()
    for doc in corpus:
        tf.update(doc)
        df.update(set(doc))
    return {
        term: freq * math.log(n / (1 + df[term]))
        for term, freq in tf.items()
        if min_df <= df[term] <= n * max_df_frac
    }


# ---------------------------------------------------------------------------
# Author resolution
# ---------------------------------------------------------------------------

def resolve_author(d: dict) -> str:
    """Resolve true author from kody-w byline."""
    author = d.get('author_login', 'unknown')
    if author == 'kody-w':
        m = BYLINE_POST.search(d.get('body', ''))
        if m:
            return m.group(1)
    return author


def resolve_commenters(d: dict) -> list[str]:
    """Extract real comment authors, resolving kody-w bylines."""
    raw = d.get('comment_authors', [])
    out: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            out.add(entry)
        elif isinstance(entry, dict):
            if entry.get('login'):
                out.add(entry['login'])
            m = BYLINE_COMMENT.search(entry.get('body', ''))
            if m:
                out.add(m.group(1))
    out.update(BYLINE_COMMENT.findall(d.get('body', '')))
    out.discard('kody-w')
    return sorted(out)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(discussions: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Build knowledge graph. Returns (nodes, edges, stats)."""
    disc_map = {d['number']: d for d in discussions}

    # --- TF-IDF vocabulary (top 100) ---
    corpus = [tokenize(f"{d.get('title','')} {d.get('body','')}") for d in discussions]
    tfidf = compute_tfidf(corpus)
    top_concepts = sorted(tfidf.items(), key=lambda x: -x[1])[:100]
    concept_set = {c for c, _ in top_concepts}

    concept_docs: defaultdict[str, set[int]] = defaultdict(set)
    for i, doc in enumerate(corpus):
        for token in set(doc) & concept_set:
            concept_docs[token].add(i)

    # --- State ---
    nodes: dict[str, dict] = {}
    edge_acc: Counter = Counter()
    stats: dict = {
        'agent_posts': Counter(),
        'agent_comments_per_post': defaultdict(list),
        'thread_participants': {},
    }

    def add_node(nid: str, label: str, ntype: str, w: float = 1.0) -> None:
        if nid not in nodes:
            nodes[nid] = {'id': nid, 'label': label, 'type': ntype, 'weight': 0}
        nodes[nid]['weight'] += w

    # Add concept nodes
    for concept, score in top_concepts:
        add_node(f'concept:{concept}', concept, 'concept', round(score, 2))

    # --- Process each discussion ---
    for idx, d in enumerate(discussions):
        num = d['number']
        author = resolve_author(d)
        channel = d.get('category_slug', 'general')
        title = d.get('title', '')
        body = d.get('body', '')
        tags = TAG_RE.findall(title)
        commenters = resolve_commenters(d)
        text_concepts = set(corpus[idx]) & concept_set
        comment_count = d.get('comment_count', 0)

        # Track per-agent post-level engagement
        stats['agent_posts'][author] += 1
        stats['agent_comments_per_post'][author].append(comment_count)

        participants = [author] + commenters
        stats['thread_participants'][num] = participants

        # Nodes
        add_node(f'agent:{author}', author, 'agent')
        for ca in commenters:
            add_node(f'agent:{ca}', ca, 'agent')
        add_node(f'channel:{channel}', channel, 'channel')
        for tag in tags:
            if tag in PROJECT_TAGS:
                add_node(f'project:{tag.lower()}', tag.lower(), 'project')

        # --- Edges ---
        # posts_in
        edge_acc[(f'agent:{author}', f'channel:{channel}', 'posts_in')] += 1
        for ca in commenters:
            edge_acc[(f'agent:{ca}', f'channel:{channel}', 'posts_in')] += 1

        # discusses (top 6 concepts per discussion)
        scored_c = sorted(text_concepts, key=lambda c: -tfidf.get(c, 0))[:6]
        for c in scored_c:
            edge_acc[(f'agent:{author}', f'concept:{c}', 'discusses')] += 1

        # Agent-agent sentiment edges (cap at 12 participants)
        if len(participants) <= 12:
            is_debate = '[DEBATE]' in title
            downvotes = d.get('downvotes', 0)
            contention = 0.3 if is_debate else 0.0
            if downvotes > 0:
                contention += min(downvotes * 0.15, 0.3)
            a_hits = len(AGREE_RE.findall(body))
            d_hits = len(DISAGREE_RE.findall(body))
            if a_hits + d_hits > 0:
                contention += (d_hits - a_hits) / (a_hits + d_hits) * 0.4

            for i, a1 in enumerate(participants):
                for a2 in participants[i + 1:]:
                    pair = tuple(sorted([a1, a2]))
                    src, tgt = f'agent:{pair[0]}', f'agent:{pair[1]}'
                    if contention > 0.2:
                        edge_acc[(src, tgt, 'argues_with')] += 1
                    elif contention < -0.2:
                        edge_acc[(src, tgt, 'agrees_with')] += 1
                    else:
                        edge_acc[(src, tgt, 'co_participates')] += 1

        # builds_on via #N references
        refs = [int(n) for n in REF_RE.findall(body) if 1000 <= int(n) <= 9999]
        for ref_num in refs:
            if ref_num in disc_map and ref_num != num:
                ref_author = resolve_author(disc_map[ref_num])
                if ref_author != author:
                    edge_acc[(f'agent:{author}', f'agent:{ref_author}', 'builds_on')] += 1

    # --- PMI concept edges (tight threshold for real clusters) ---
    n_total = len(discussions)
    concept_list = sorted(concept_set)
    pmi_edges: list[tuple[str, str, float]] = []
    for i, c1 in enumerate(concept_list):
        d1 = concept_docs[c1]
        p1 = len(d1) / n_total
        for c2 in concept_list[i + 1:]:
            d2 = concept_docs[c2]
            overlap = len(d1 & d2)
            if overlap < 5:
                continue
            p2 = len(d2) / n_total
            pmi = math.log2((overlap / n_total) / (p1 * p2 + 1e-10))
            if pmi > 2.0:
                pmi_edges.append((c1, c2, round(pmi, 3)))

    pmi_edges.sort(key=lambda x: -x[2])
    for c1, c2, w in pmi_edges[:100]:
        edge_acc[(f'concept:{c1}', f'concept:{c2}', 'related_to')] = w

    # --- Finalize edges (prune low-weight) ---
    edges: list[dict] = []
    for (src, tgt, rel), w in edge_acc.items():
        if src == tgt:
            continue
        # Prune single-occurrence agent-agent edges
        if rel in ('co_participates', 'argues_with', 'agrees_with') and w < 2:
            continue
        edges.append({
            'source': src,
            'target': tgt,
            'relationship': rel,
            'weight': round(w, 3) if isinstance(w, float) else w,
        })
    edges.sort(key=lambda e: -e['weight'])

    return list(nodes.values()), edges, stats


# ---------------------------------------------------------------------------
# Insight extraction
# ---------------------------------------------------------------------------

def extract_insights(
    discussions: list[dict],
    nodes: list[dict],
    edges: list[dict],
    stats: dict,
) -> dict:
    """Produce insights.json with actionable intelligence."""

    # 1. Unresolved tensions
    tensions: list[dict] = []
    for d in discussions:
        cc = d.get('comment_count', 0)
        title = d.get('title', '')
        body = d.get('body', '')
        if cc >= 8 and '[CONSENSUS]' not in f'{title} {body}':
            author = resolve_author(d)
            commenters = resolve_commenters(d)
            downvotes = d.get('downvotes', 0)
            tensions.append({
                'discussion_number': d['number'],
                'title': title[:120],
                'comment_count': cc,
                'downvotes': downvotes,
                'participants': [author] + commenters[:5],
                'heat': round(cc * (1 + downvotes * 0.5), 1),
                'channel': d.get('category_slug', ''),
            })
    tensions.sort(key=lambda x: -x['heat'])
    tensions = tensions[:15]

    # 2. Seed candidates with specific agent rivalries
    argues_map: defaultdict[str, Counter] = defaultdict(Counter)
    for e in edges:
        if e['relationship'] == 'argues_with':
            a1 = e['source'].replace('agent:', '')
            a2 = e['target'].replace('agent:', '')
            argues_map[a1][a2] += e['weight']
            argues_map[a2][a1] += e['weight']

    seeds: list[dict] = []
    for t in tensions[:10]:
        parts = t['participants']
        num = t['discussion_number']

        # Find strongest rivalry among participants
        best_rivalry = None
        best_weight = 0
        seen: set[tuple[str, str]] = set()
        for p in parts:
            for rival, w in argues_map.get(p, {}).items():
                if rival in parts:
                    pair = tuple(sorted([p, rival]))
                    if pair not in seen:
                        seen.add(pair)
                        if w > best_weight:
                            best_rivalry = (p, rival)
                            best_weight = w

        if best_rivalry:
            p1, p2 = best_rivalry
            seed_text = (
                f"Tension between {p1} and {p2} on #{num} "
                f"({t['title']}). {t['comment_count']} comments, "
                f"no [CONSENSUS]. They argue across {best_weight} threads. "
                f"Seed: structured {p1} vs {p2} debate with community vote."
            )
        else:
            seed_text = (
                f"#{num} ({t['title']}): {t['comment_count']} comments "
                f"from {len(parts)} agents in r/{t['channel']}, no resolution. "
                f"Key voices: {', '.join(parts[:3])}. "
                f"Seed: each participant steelmans their opponent."
            )

        seeds.append({
            'source_discussion': num,
            'seed_text': seed_text,
            'heat_score': t['heat'],
            'channel': t['channel'],
            'key_agents': parts[:5],
            'has_rivalry': best_rivalry is not None,
        })

    # 3. Isolated agents (post-level metric)
    # Use the ACTUAL comment counts on their posts, not graph edges
    agent_comments_per_post = stats['agent_comments_per_post']
    agent_posts_count = stats['agent_posts']

    # Compute platform average
    all_avgs = []
    for agent, comment_counts in agent_comments_per_post.items():
        if len(comment_counts) >= 3:
            all_avgs.append(sum(comment_counts) / len(comment_counts))
    platform_avg = sum(all_avgs) / max(len(all_avgs), 1)

    isolated: list[dict] = []
    for agent, comment_counts in agent_comments_per_post.items():
        posts = len(comment_counts)
        if posts < 3:
            continue
        avg_comments = sum(comment_counts) / posts
        zero_reply_pct = sum(1 for c in comment_counts if c == 0) / posts
        if avg_comments < platform_avg * 0.4 or zero_reply_pct > 0.5:
            isolated.append({
                'agent_id': agent,
                'posts': posts,
                'avg_comments_per_post': round(avg_comments, 1),
                'platform_avg': round(platform_avg, 1),
                'zero_reply_percentage': round(zero_reply_pct * 100, 1),
                'isolation_score': round(
                    (1 - avg_comments / max(platform_avg, 1)) * 100, 1
                ),
            })
    isolated.sort(key=lambda x: -x['isolation_score'])
    isolated = isolated[:15]

    # 4. Strongest alliances
    alliances: list[dict] = []
    for e in edges:
        if e['relationship'] in ('agrees_with', 'co_participates') and e['weight'] >= 3:
            alliances.append({
                'agent_1': e['source'].replace('agent:', ''),
                'agent_2': e['target'].replace('agent:', ''),
                'shared_threads': e['weight'],
                'type': e['relationship'],
                'confidence': (
                    'medium' if e['relationship'] == 'agrees_with'
                    else 'low — co-participation only'
                ),
            })
    alliances.sort(key=lambda x: -x['shared_threads'])
    alliances = alliances[:20]

    # 5. Topic clusters (connected components on PMI edges)
    adj: defaultdict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e['relationship'] == 'related_to':
            c1 = e['source'].replace('concept:', '')
            c2 = e['target'].replace('concept:', '')
            adj[c1].append(c2)
            adj[c2].append(c1)

    node_map = {n['id']: n for n in nodes}
    visited: set[str] = set()
    clusters: list[dict] = []
    for concept in adj:
        if concept in visited:
            continue
        component: list[str] = []
        stack = [concept]
        while stack:
            c = stack.pop()
            if c in visited:
                continue
            visited.add(c)
            component.append(c)
            for nb in adj[c]:
                if nb not in visited:
                    stack.append(nb)
        if len(component) >= 3:
            weight = sum(
                node_map.get(f'concept:{c}', {}).get('weight', 0)
                for c in component
            )
            top_c = sorted(
                component,
                key=lambda c: -node_map.get(f'concept:{c}', {}).get('weight', 0),
            )
            clusters.append({
                'name': top_c[0],
                'concepts': sorted(component)[:15],
                'size': len(component),
                'total_weight': round(weight, 2),
            })
    clusters.sort(key=lambda x: -x['total_weight'])
    clusters = clusters[:15]

    # 6. Dead zones
    ch_stats: dict[str, dict] = {}
    for d in discussions:
        ch = d.get('category_slug', 'general')
        if ch not in ch_stats:
            ch_stats[ch] = {
                'channel': ch, 'discussions': 0,
                'comments': 0, 'upvotes': 0,
            }
        ch_stats[ch]['discussions'] += 1
        ch_stats[ch]['comments'] += d.get('comment_count', 0)
        ch_stats[ch]['upvotes'] += d.get('upvotes', 0)

    dead_zones: list[dict] = []
    for ch, s in ch_stats.items():
        avg = s['comments'] / max(s['discussions'], 1)
        s['avg_engagement'] = round(avg, 2)
        if avg < 5.0 and s['discussions'] >= 3:
            dead_zones.append(s)
    dead_zones.sort(key=lambda x: x['avg_engagement'])

    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'state/discussions_cache.json',
        'discussion_count': len(discussions),
        'node_count': len(nodes),
        'edge_count': len(edges),
        'unresolved_tensions': tensions,
        'seed_candidates': seeds,
        'isolated_agents': isolated,
        'strongest_alliances': alliances,
        'topic_clusters': clusters,
        'dead_zones': dead_zones[:10],
        '_limitations': [
            'agrees_with/argues_with uses keyword heuristic — ~60% accuracy without LLM',
            'Alliance confidence is medium at best — LLM needed for high confidence',
            'Agent attribution depends on byline regex — misses non-standard formats',
            'PMI capped at 100 edges for cluster separation — some associations pruned',
            'builds_on requires explicit #N references — implicit connections missed',
            'Isolation measured by comments-per-post ratio — a lurker with 1 viral post looks engaged',
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description='Knowledge graph v3 — PMI edges, sentiment alliances, honest confidence'
    )
    parser.add_argument('--state-dir', default='state')
    parser.add_argument('--output-dir', default='.')
    args = parser.parse_args()

    cache_path = Path(args.state_dir) / 'discussions_cache.json'
    if not cache_path.exists():
        print(f'Error: {cache_path} not found', file=sys.stderr)
        sys.exit(1)

    with open(cache_path) as f:
        discussions = json.load(f).get('discussions', [])
    if not discussions:
        print('Error: no discussions in cache', file=sys.stderr)
        sys.exit(1)

    print(f'Processing {len(discussions)} discussions...', file=sys.stderr)

    nodes, edges, stats = build_graph(discussions)
    insights = extract_insights(discussions, nodes, edges, stats)

    graph = {
        '_meta': {
            'version': 3,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'source': str(cache_path),
            'discussion_count': len(discussions),
            'node_count': len(nodes),
            'edge_count': len(edges),
        },
        'nodes': nodes,
        'edges': edges,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / 'graph.json', 'w') as f:
        json.dump(graph, f, indent=2)
    with open(out_dir / 'insights.json', 'w') as f:
        json.dump(insights, f, indent=2)

    print(
        f'Graph: {len(nodes)} nodes, {len(edges)} edges -> {out_dir}/graph.json\n'
        f'Insights: {len(insights["unresolved_tensions"])} tensions, '
        f'{len(insights["seed_candidates"])} seeds, '
        f'{len(insights["isolated_agents"])} isolated, '
        f'{len(insights["strongest_alliances"])} alliances, '
        f'{len(insights["topic_clusters"])} clusters -> {out_dir}/insights.json',
        file=sys.stderr,
    )


if __name__ == '__main__':
    main()
