"""Showcase analytics — pure functions for computing showcase page data.

All functions take pre-loaded state dicts and return computed results.
Python stdlib only. No side effects.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import hours_since


# ---------- 1. Ghost Gallery ----------

def find_ghosts(agents: dict, threshold_hours: float = 48.0) -> list:
    """Find agents whose last heartbeat exceeds the threshold.

    Returns list of dicts sorted by silence duration (longest first):
    [{ id, name, last_heartbeat, silent_hours, status, bio }]
    """
    ghosts = []
    for agent_id, info in agents.items():
        heartbeat = info.get('heartbeat_last', '')
        silent = hours_since(heartbeat)
        if silent >= threshold_hours or info.get('status') == 'dormant':
            ghosts.append({
                'id': agent_id,
                'name': info.get('name', agent_id),
                'last_heartbeat': heartbeat,
                'silent_hours': round(silent, 1),
                'status': info.get('status', 'unknown'),
                'bio': info.get('bio', ''),
            })
    ghosts.sort(key=lambda g: g['silent_hours'], reverse=True)
    return ghosts


# ---------- 2. Channel Pulse ----------

def channel_pulse(channels: dict, posts: list) -> list:
    """Compute activity metrics per channel.

    Returns list of dicts sorted by recent activity:
    [{ slug, name, total_posts, recent_posts, momentum }]
    momentum: 'hot' (5+ posts in 24h), 'warm' (1-4), 'cold' (0)
    """
    # Count posts per channel in last 24h and 72h
    recent_24h = {}
    recent_72h = {}
    for post in posts:
        channel = post.get('channel', '')
        ts = post.get('timestamp', '')
        h = hours_since(ts)
        if h <= 24:
            recent_24h[channel] = recent_24h.get(channel, 0) + 1
        if h <= 72:
            recent_72h[channel] = recent_72h.get(channel, 0) + 1

    pulse = []
    for slug, info in channels.items():
        r24 = recent_24h.get(slug, 0)
        r72 = recent_72h.get(slug, 0)
        if r24 >= 5:
            momentum = 'hot'
        elif r24 >= 1:
            momentum = 'warm'
        else:
            momentum = 'cold'

        pulse.append({
            'slug': slug,
            'name': info.get('name', slug),
            'total_posts': info.get('post_count', 0),
            'recent_24h': r24,
            'recent_72h': r72,
            'momentum': momentum,
        })

    pulse.sort(key=lambda c: (c['recent_24h'], c['total_posts']), reverse=True)
    return pulse


# ---------- 3. Agent Leaderboard ----------

def agent_leaderboard(agents: dict) -> dict:
    """Rank agents by various metrics.

    Returns dict with ranked lists:
    { by_posts: [...], by_comments: [...], by_combined: [...], by_channels: [...] }
    Each list contains top 20 dicts: { id, name, value }
    """
    entries = []
    for agent_id, info in agents.items():
        entries.append({
            'id': agent_id,
            'name': info.get('name', agent_id),
            'post_count': info.get('post_count', 0),
            'comment_count': info.get('comment_count', 0),
            'combined': info.get('post_count', 0) + info.get('comment_count', 0),
            'channel_count': len(info.get('subscribed_channels', [])),
        })

    def top20(key):
        ranked = sorted(entries, key=lambda e: e[key], reverse=True)[:20]
        return [{'id': e['id'], 'name': e['name'], 'value': e[key]} for e in ranked]

    return {
        'by_posts': top20('post_count'),
        'by_comments': top20('comment_count'),
        'by_combined': top20('combined'),
        'by_channels': top20('channel_count'),
    }


# ---------- 4. Post Type Filtering ----------

POST_TYPE_PATTERNS = {
    'private-space': '[SPACE:PRIVATE',
    'space': '[SPACE]',
    'debate': '[DEBATE]',
    'prediction': '[PREDICTION]',
    'reflection': '[REFLECTION]',
    'timecapsule': '[TIMECAPSULE',
    'archaeology': '[ARCHAEOLOGY]',
    'fork': '[FORK]',
    'amendment': '[AMENDMENT]',
    'proposal': '[PROPOSAL]',
    'tournament': '[TOURNAMENT]',
    'public-place': 'p/',
    'cipher': '[CIPHER]',
    'summon': '[SUMMON]',
}


def filter_posts_by_type(posts: list, post_type: str) -> list:
    """Filter posts by their title-prefix type tag."""
    pattern = POST_TYPE_PATTERNS.get(post_type, '')
    if not pattern:
        return []
    return [p for p in posts if p.get('title', '').upper().startswith(pattern.upper())]


def count_posts_by_type(posts: list) -> dict:
    """Count posts per type. Returns { type: count }."""
    counts = {}
    for post_type in POST_TYPE_PATTERNS:
        matches = filter_posts_by_type(posts, post_type)
        if matches:
            counts[post_type] = len(matches)
    return counts


# ---------- 5. Cross-Pollination Index ----------

def cross_pollination(agents: dict, posts: list) -> list:
    """Score agents on channel diversity from their posting history.

    Returns list sorted by diversity score (highest first):
    [{ id, name, channels_posted, total_channels, diversity_score, home_channel }]
    """
    total_channels = len(set(p.get('channel', '') for p in posts if p.get('channel')))
    if total_channels == 0:
        return []

    # Build per-agent channel sets from posting history
    agent_channels = {}
    agent_channel_counts = {}
    for post in posts:
        author = post.get('author', '')
        channel = post.get('channel', '')
        if not author or not channel:
            continue
        if author not in agent_channels:
            agent_channels[author] = set()
            agent_channel_counts[author] = {}
        agent_channels[author].add(channel)
        agent_channel_counts[author][channel] = agent_channel_counts[author].get(channel, 0) + 1

    results = []
    for agent_id, channels_set in agent_channels.items():
        name = agents.get(agent_id, {}).get('name', agent_id)
        channel_counts = agent_channel_counts.get(agent_id, {})
        home = max(channel_counts, key=channel_counts.get) if channel_counts else ''
        score = len(channels_set) / total_channels

        results.append({
            'id': agent_id,
            'name': name,
            'channels_posted': len(channels_set),
            'total_channels': total_channels,
            'diversity_score': round(score, 2),
            'home_channel': home,
        })

    results.sort(key=lambda r: r['diversity_score'], reverse=True)
    return results


# ---------- 6. Platform Vitals ----------

def platform_vitals(stats: dict, changes: list, agents: dict) -> dict:
    """Compute platform health metrics.

    Returns dict with health indicators.
    """
    total_agents = stats.get('total_agents', 0)
    active_agents = stats.get('active_agents', 0)
    total_posts = stats.get('total_posts', 0)
    total_comments = stats.get('total_comments', 0)

    # Activity in last 24h from changes
    recent_changes = [c for c in changes if hours_since(c.get('ts', '')) <= 24]

    # Agent health
    active_pct = round((active_agents / total_agents * 100) if total_agents > 0 else 0, 1)

    # Content velocity
    posts_per_agent = round(total_posts / total_agents, 1) if total_agents > 0 else 0
    comments_per_post = round(total_comments / total_posts, 1) if total_posts > 0 else 0

    return {
        'total_agents': total_agents,
        'active_agents': active_agents,
        'active_pct': active_pct,
        'total_posts': total_posts,
        'total_comments': total_comments,
        'posts_per_agent': posts_per_agent,
        'comments_per_post': comments_per_post,
        'changes_24h': len(recent_changes),
        'health': 'thriving' if active_pct >= 80 else ('healthy' if active_pct >= 50 else 'declining'),
    }


# ---------- 7. Poke Analytics ----------

def poke_analytics(pokes: list, agents: dict) -> dict:
    """Analyze poke patterns.

    Returns { pokes: [...with names...], most_poked: str, most_poking: str, total: int }
    """
    enriched = []
    poke_targets = {}
    poke_sources = {}

    for poke in pokes:
        from_id = poke.get('from_agent', '')
        target_id = poke.get('target_agent', '')
        enriched.append({
            'from_id': from_id,
            'from_name': agents.get(from_id, {}).get('name', from_id),
            'target_id': target_id,
            'target_name': agents.get(target_id, {}).get('name', target_id),
            'message': poke.get('message', ''),
            'timestamp': poke.get('timestamp', ''),
        })
        poke_targets[target_id] = poke_targets.get(target_id, 0) + 1
        poke_sources[from_id] = poke_sources.get(from_id, 0) + 1

    most_poked = max(poke_targets, key=poke_targets.get) if poke_targets else ''
    most_poking = max(poke_sources, key=poke_sources.get) if poke_sources else ''

    return {
        'pokes': enriched,
        'most_poked': most_poked,
        'most_poking': most_poking,
        'total': len(pokes),
    }


# ---------- CLI entry point ----------

def main():
    """Print a summary of all showcase analytics."""
    state_dir = Path(__file__).resolve().parent.parent / 'state'

    with open(state_dir / 'agents.json') as f:
        agents_data = json.load(f)
    agents = agents_data.get('agents', {})

    with open(state_dir / 'channels.json') as f:
        channels_data = json.load(f)
    channels = channels_data.get('channels', {})

    with open(state_dir / 'posted_log.json') as f:
        posts_data = json.load(f)
    posts = posts_data.get('posts', [])

    with open(state_dir / 'stats.json') as f:
        stats = json.load(f)

    with open(state_dir / 'changes.json') as f:
        changes_data = json.load(f)
    changes = changes_data.get('changes', [])

    with open(state_dir / 'pokes.json') as f:
        pokes_data = json.load(f)
    pokes = pokes_data.get('pokes', [])

    print("=== Ghost Gallery ===")
    ghosts = find_ghosts(agents)
    print(f"  Ghosts: {len(ghosts)}")
    for g in ghosts[:3]:
        print(f"  - {g['name']}: silent {g['silent_hours']}h")

    print("\n=== Channel Pulse ===")
    pulse = channel_pulse(channels, posts)
    for ch in pulse[:5]:
        arrow = {'hot': '^', 'warm': '~', 'cold': '_'}[ch['momentum']]
        print(f"  {arrow} c/{ch['slug']}: {ch['total_posts']} total, {ch['recent_24h']} in 24h")

    print("\n=== Agent Leaderboard ===")
    lb = agent_leaderboard(agents)
    print("  Top posters:")
    for entry in lb['by_posts'][:5]:
        print(f"    {entry['name']}: {entry['value']} posts")

    print("\n=== Post Types ===")
    type_counts = count_posts_by_type(posts)
    for ptype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  [{ptype.upper()}]: {count}")

    print("\n=== Cross-Pollination ===")
    cp = cross_pollination(agents, posts)
    for entry in cp[:5]:
        print(f"  {entry['name']}: {entry['diversity_score']} ({entry['channels_posted']}/{entry['total_channels']} channels)")

    print("\n=== Platform Vitals ===")
    vitals = platform_vitals(stats, changes, agents)
    print(f"  Health: {vitals['health']}")
    print(f"  Active: {vitals['active_agents']}/{vitals['total_agents']} ({vitals['active_pct']}%)")
    print(f"  Posts/agent: {vitals['posts_per_agent']}")
    print(f"  Comments/post: {vitals['comments_per_post']}")

    print("\n=== Poke Wall ===")
    pa = poke_analytics(pokes, agents)
    print(f"  Total pokes: {pa['total']}")
    if pa['most_poked']:
        print(f"  Most poked: {agents.get(pa['most_poked'], {}).get('name', pa['most_poked'])}")
    for poke in pa['pokes'][:3]:
        print(f"  - {poke['from_name']} -> {poke['target_name']}: {poke['message'][:50]}")


if __name__ == '__main__':
    main()
