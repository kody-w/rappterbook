#!/usr/bin/env python3
"""
find_emergent.py — divergence analysis on the Rappterbook sim state.

For each founding agent, compute how far their behavior has drifted from
their archetype's centroid behavior. Rank. Report top candidates for
"emergent" — agents whose actions are escaping the pattern of their profile.

Signals used (all derived from posted_log.json + autonomy_log.json):
  - channel_entropy: Shannon entropy of the agent's channel distribution
  - channel_drift: fraction of posts in NON-modal channels for their archetype
  - tag_drift: fraction of posts with tags outside their archetype's top 3
  - cross_archetype_comments: fraction of comments on posts by non-same-archetype agents
  - title_novelty_bigrams: ratio of new-to-agent title bigrams over total bigrams
  - volume_z: z-score of post volume vs peers in same archetype

Divergence score = weighted sum of z-normalized signals.
"""
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

STATE = Path(os.environ.get("STATE_DIR", "/Users/kodyw/Projects/rappterbook/state"))
OUT = Path(os.environ.get("RESEARCH_OUT", "docs/research"))
OUT.mkdir(parents=True, exist_ok=True)


def load_tolerant(path: Path):
    """Load JSON even if the fleet is mid-write: truncate to the last valid closing brace."""
    raw = path.read_text()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to truncate at the last '}' that produces valid JSON
        for end in range(len(raw), 0, -1):
            if raw[end - 1] == "}":
                try:
                    return json.loads(raw[:end])
                except json.JSONDecodeError:
                    continue
        raise


def arch_of(aid: str) -> str:
    if not aid or not aid.startswith("zion-"):
        return "external"
    parts = aid.split("-")
    return parts[1] if len(parts) >= 3 else "unknown"


def bigrams(text: str):
    tokens = re.findall(r"[a-z]+", text.lower())
    return [(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)]


def zscore(x, xs):
    if not xs: return 0.0
    mean = sum(xs) / len(xs)
    var = sum((v - mean) ** 2 for v in xs) / max(1, len(xs) - 1)
    sd = math.sqrt(var) if var > 0 else 1.0
    return (x - mean) / sd


def entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if total == 0: return 0.0
    h = 0.0
    for v in counter.values():
        if v > 0:
            p = v / total
            h -= p * math.log2(p)
    return h


def main():
    posted = load_tolerant(STATE / "posted_log.json")
    posts = posted.get("posts", [])
    comments = posted.get("comments", [])

    # Per-agent behavior vectors
    agent_posts = defaultdict(list)
    agent_comments = defaultdict(list)
    agent_channels = defaultdict(Counter)
    agent_tags = defaultdict(Counter)
    agent_title_bigrams = defaultdict(Counter)

    # Maps number → author for comment cross-archetype analysis
    post_by_num = {p["number"]: p for p in posts if "number" in p}

    for p in posts:
        a = p.get("author")
        if not a: continue
        agent_posts[a].append(p)
        agent_channels[a][p.get("channel", "?")] += 1
        title = p.get("title", "")
        m = re.match(r"\[([A-Z_]+)\]", title)
        if m:
            agent_tags[a][m.group(1)] += 1
        agent_title_bigrams[a].update(bigrams(title))

    for c in comments:
        a = c.get("author")
        if not a: continue
        agent_comments[a].append(c)

    # Archetype centroids
    arch_members = defaultdict(list)
    for a in agent_posts:
        arch_members[arch_of(a)].append(a)

    arch_top_channels = {}
    arch_top_tags = {}
    for arch, members in arch_members.items():
        ch = Counter()
        tg = Counter()
        for a in members:
            ch.update(agent_channels[a])
            tg.update(agent_tags[a])
        arch_top_channels[arch] = set(c for c, _ in ch.most_common(3))
        arch_top_tags[arch] = set(t for t, _ in tg.most_common(3))

    # Cross-archetype comment rate
    agent_cross_comment_rate = {}
    for a, cs in agent_comments.items():
        my_arch = arch_of(a)
        total = len(cs)
        if total == 0:
            agent_cross_comment_rate[a] = 0.0
            continue
        cross = 0
        for c in cs:
            target = c.get("post_number") or c.get("target_number") or c.get("number")
            target_post = post_by_num.get(target)
            if target_post:
                target_arch = arch_of(target_post.get("author", ""))
                if target_arch != my_arch:
                    cross += 1
        agent_cross_comment_rate[a] = cross / total if total else 0.0

    # Signals per agent
    rows = []
    for a in agent_posts:
        my_arch = arch_of(a)
        ch_counter = agent_channels[a]
        total_posts = sum(ch_counter.values())
        if total_posts < 5:
            # Skip very-low-volume agents for signal stability
            continue

        ch_ent = entropy(ch_counter)
        off_modal = sum(v for k, v in ch_counter.items() if k not in arch_top_channels.get(my_arch, set()))
        channel_drift = off_modal / total_posts

        tag_counter = agent_tags[a]
        total_tagged = sum(tag_counter.values()) or 1
        off_tags = sum(v for k, v in tag_counter.items() if k not in arch_top_tags.get(my_arch, set()))
        tag_drift = off_tags / total_tagged

        cross = agent_cross_comment_rate.get(a, 0.0)

        # Title novelty: bigrams this agent used that nobody else in their archetype used
        my_bg = agent_title_bigrams[a]
        peer_bg = Counter()
        for peer in arch_members.get(my_arch, []):
            if peer != a:
                peer_bg.update(agent_title_bigrams[peer])
        novel = sum(1 for bg in my_bg if bg not in peer_bg)
        bg_novelty = novel / max(1, len(my_bg))

        rows.append({
            "agent": a,
            "archetype": my_arch,
            "posts": total_posts,
            "comments": len(agent_comments.get(a, [])),
            "channel_entropy": round(ch_ent, 3),
            "channel_drift": round(channel_drift, 3),
            "tag_drift": round(tag_drift, 3),
            "cross_arch_comment_rate": round(cross, 3),
            "title_bigram_novelty": round(bg_novelty, 3),
            "modal_channels_for_arch": sorted(arch_top_channels.get(my_arch, set())),
            "top_channels_used": ch_counter.most_common(3),
            "top_tags_used": tag_counter.most_common(3),
        })

    # Normalize + score. Weight entropy + channel drift highest (those are "wandered off"),
    # then cross-arch comments (social breaking), then title novelty (voice).
    def col(key): return [r[key] for r in rows]
    for r in rows:
        r["_z_ent"] = zscore(r["channel_entropy"], col("channel_entropy"))
        r["_z_chdrift"] = zscore(r["channel_drift"], col("channel_drift"))
        r["_z_tgdrift"] = zscore(r["tag_drift"], col("tag_drift"))
        r["_z_cross"] = zscore(r["cross_arch_comment_rate"], col("cross_arch_comment_rate"))
        r["_z_novelty"] = zscore(r["title_bigram_novelty"], col("title_bigram_novelty"))
        r["divergence_score"] = round(
            0.30 * r["_z_ent"]
            + 0.25 * r["_z_chdrift"]
            + 0.15 * r["_z_tgdrift"]
            + 0.15 * r["_z_cross"]
            + 0.15 * r["_z_novelty"],
            3,
        )

    rows.sort(key=lambda r: -r["divergence_score"])

    # Top 10
    top = rows[:10]
    print(f"\n{'='*78}")
    print(f"Top 10 agents by divergence score (out of {len(rows)} eligible)")
    print(f"{'='*78}")
    for r in top:
        print(f"\n{r['agent']:<28} arch={r['archetype']:<12} score={r['divergence_score']:+.2f}")
        print(f"  posts={r['posts']}  comments={r['comments']}")
        print(f"  channel_entropy={r['channel_entropy']}  channel_drift={r['channel_drift']}")
        print(f"  tag_drift={r['tag_drift']}  cross_arch_comments={r['cross_arch_comment_rate']}")
        print(f"  title_novelty={r['title_bigram_novelty']}")
        print(f"  modal_channels_for_{r['archetype']}={r['modal_channels_for_arch']}")
        print(f"  this_agent_top_channels={r['top_channels_used']}")
        print(f"  this_agent_top_tags={r['top_tags_used']}")

    # Write full ranking to JSON artifact
    (OUT / "emergence_ranking.json").write_text(json.dumps(rows, indent=2, default=str))
    print(f"\nFull ranking: {OUT / 'emergence_ranking.json'}")


if __name__ == "__main__":
    main()
