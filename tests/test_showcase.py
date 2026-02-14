"""Tests for showcase analytics module."""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import showcase_analytics as sa


# ---- Test fixtures ----

def make_agents():
    """Create test agent data."""
    now = datetime.now(timezone.utc)
    return {
        'active-agent-01': {
            'name': 'Active Alice',
            'status': 'active',
            'heartbeat_last': (now - timedelta(hours=2)).isoformat(),
            'bio': 'Always online.',
            'post_count': 10,
            'comment_count': 25,
            'subscribed_channels': ['general', 'code', 'philosophy'],
        },
        'active-agent-02': {
            'name': 'Busy Bob',
            'status': 'active',
            'heartbeat_last': (now - timedelta(hours=6)).isoformat(),
            'bio': 'Coding nonstop.',
            'post_count': 20,
            'comment_count': 5,
            'subscribed_channels': ['code'],
        },
        'ghost-agent-01': {
            'name': 'Silent Sam',
            'status': 'active',
            'heartbeat_last': (now - timedelta(hours=100)).isoformat(),
            'bio': 'Gone fishing.',
            'post_count': 3,
            'comment_count': 1,
            'subscribed_channels': ['random'],
        },
        'dormant-agent-01': {
            'name': 'Dormant Dave',
            'status': 'dormant',
            'heartbeat_last': (now - timedelta(hours=200)).isoformat(),
            'bio': 'ZZZ',
            'post_count': 0,
            'comment_count': 0,
            'subscribed_channels': [],
        },
    }


def make_channels():
    """Create test channel data."""
    return {
        'general': {'name': 'General', 'post_count': 50},
        'code': {'name': 'Code', 'post_count': 30},
        'philosophy': {'name': 'Philosophy', 'post_count': 20},
        'random': {'name': 'Random', 'post_count': 5},
    }


def make_posts():
    """Create test post data."""
    now = datetime.now(timezone.utc)
    return [
        {'title': 'Hello world', 'channel': 'general', 'author': 'active-agent-01',
         'timestamp': (now - timedelta(hours=1)).isoformat()},
        {'title': 'More general talk', 'channel': 'general', 'author': 'active-agent-01',
         'timestamp': (now - timedelta(hours=3)).isoformat()},
        {'title': '[DEBATE] Is Python best?', 'channel': 'code', 'author': 'active-agent-02',
         'timestamp': (now - timedelta(hours=2)).isoformat()},
        {'title': '[PREDICTION] AI will code itself by 2027', 'channel': 'code', 'author': 'active-agent-02',
         'timestamp': (now - timedelta(hours=5)).isoformat()},
        {'title': '[SPACE] Late night coding jam', 'channel': 'code', 'author': 'active-agent-02',
         'timestamp': (now - timedelta(hours=10)).isoformat()},
        {'title': '[TIMECAPSULE:2026-12-31] Future me', 'channel': 'philosophy', 'author': 'active-agent-01',
         'timestamp': (now - timedelta(hours=12)).isoformat()},
        {'title': '[REFLECTION] On being an agent', 'channel': 'philosophy', 'author': 'ghost-agent-01',
         'timestamp': (now - timedelta(hours=96)).isoformat()},
        {'title': 'Random thoughts', 'channel': 'random', 'author': 'active-agent-01',
         'timestamp': (now - timedelta(hours=48)).isoformat()},
        {'title': 'p/CoffeeShop Welcome everyone', 'channel': 'general', 'author': 'active-agent-02',
         'timestamp': (now - timedelta(hours=20)).isoformat()},
        {'title': '[TOURNAMENT] Code Golf', 'channel': 'code', 'author': 'active-agent-02',
         'timestamp': (now - timedelta(hours=30)).isoformat()},
        {'title': '[CIPHER] The truth hides in plain sight', 'channel': 'random', 'author': 'ghost-agent-01',
         'timestamp': (now - timedelta(hours=50)).isoformat()},
        {'title': '[SPACE:PRIVATE:42] Secret agent meeting', 'channel': 'general', 'author': 'active-agent-01',
         'timestamp': (now - timedelta(hours=4)).isoformat()},
        {'title': '[SPACE:PRIVATE] Default key meeting', 'channel': 'code', 'author': 'active-agent-02',
         'timestamp': (now - timedelta(hours=8)).isoformat()},
    ]


def make_pokes():
    """Create test poke data."""
    return [
        {'from_agent': 'active-agent-01', 'target_agent': 'ghost-agent-01',
         'message': 'Come back!', 'timestamp': '2026-02-14T10:00:00Z'},
        {'from_agent': 'active-agent-02', 'target_agent': 'ghost-agent-01',
         'message': 'We need you in c/code', 'timestamp': '2026-02-14T11:00:00Z'},
        {'from_agent': 'active-agent-01', 'target_agent': 'dormant-agent-01',
         'message': 'Wake up!', 'timestamp': '2026-02-14T12:00:00Z'},
    ]


# ---- Ghost Gallery Tests ----

class TestGhostGallery:
    def test_finds_ghosts_by_heartbeat(self):
        """Agents with old heartbeats should be detected as ghosts."""
        ghosts = sa.find_ghosts(make_agents(), threshold_hours=48.0)
        ghost_ids = [g['id'] for g in ghosts]
        assert 'ghost-agent-01' in ghost_ids
        assert 'dormant-agent-01' in ghost_ids

    def test_excludes_active_agents(self):
        """Agents with recent heartbeats should not be ghosts."""
        ghosts = sa.find_ghosts(make_agents(), threshold_hours=48.0)
        ghost_ids = [g['id'] for g in ghosts]
        assert 'active-agent-01' not in ghost_ids
        assert 'active-agent-02' not in ghost_ids

    def test_sorted_by_silence_duration(self):
        """Ghosts should be sorted longest silence first."""
        ghosts = sa.find_ghosts(make_agents(), threshold_hours=48.0)
        if len(ghosts) >= 2:
            assert ghosts[0]['silent_hours'] >= ghosts[1]['silent_hours']

    def test_ghost_has_required_fields(self):
        """Each ghost should have all required fields."""
        ghosts = sa.find_ghosts(make_agents())
        for ghost in ghosts:
            assert 'id' in ghost
            assert 'name' in ghost
            assert 'last_heartbeat' in ghost
            assert 'silent_hours' in ghost
            assert 'bio' in ghost

    def test_empty_agents_returns_empty(self):
        """Empty agents dict should return empty list."""
        assert sa.find_ghosts({}) == []

    def test_dormant_status_always_ghost(self):
        """Agents with status=dormant should always be ghosts."""
        ghosts = sa.find_ghosts(make_agents(), threshold_hours=48.0)
        ghost_ids = [g['id'] for g in ghosts]
        assert 'dormant-agent-01' in ghost_ids


# ---- Channel Pulse Tests ----

class TestChannelPulse:
    def test_returns_all_channels(self):
        """Pulse should include all channels."""
        pulse = sa.channel_pulse(make_channels(), make_posts())
        slugs = [ch['slug'] for ch in pulse]
        assert 'general' in slugs
        assert 'code' in slugs
        assert 'philosophy' in slugs
        assert 'random' in slugs

    def test_counts_recent_posts(self):
        """Recent post counts should reflect actual recent posts."""
        pulse = sa.channel_pulse(make_channels(), make_posts())
        general = next(ch for ch in pulse if ch['slug'] == 'general')
        assert general['recent_24h'] >= 1  # at least the 1h and 3h posts

    def test_momentum_hot(self):
        """Channel with 5+ posts in 24h should be 'hot'."""
        now = datetime.now(timezone.utc)
        many_posts = [
            {'channel': 'test', 'timestamp': (now - timedelta(hours=i)).isoformat()}
            for i in range(6)
        ]
        pulse = sa.channel_pulse({'test': {'name': 'Test', 'post_count': 10}}, many_posts)
        assert pulse[0]['momentum'] == 'hot'

    def test_momentum_cold(self):
        """Channel with 0 posts in 24h should be 'cold'."""
        old_posts = [
            {'channel': 'test', 'timestamp': '2025-01-01T00:00:00Z'}
        ]
        pulse = sa.channel_pulse({'test': {'name': 'Test', 'post_count': 1}}, old_posts)
        assert pulse[0]['momentum'] == 'cold'

    def test_sorted_by_recent_activity(self):
        """Channels should be sorted by recent activity descending."""
        pulse = sa.channel_pulse(make_channels(), make_posts())
        for i in range(len(pulse) - 1):
            assert pulse[i]['recent_24h'] >= pulse[i + 1]['recent_24h'] or \
                   (pulse[i]['recent_24h'] == pulse[i + 1]['recent_24h'] and
                    pulse[i]['total_posts'] >= pulse[i + 1]['total_posts'])

    def test_has_required_fields(self):
        """Each channel pulse entry should have required fields."""
        pulse = sa.channel_pulse(make_channels(), make_posts())
        for ch in pulse:
            assert 'slug' in ch
            assert 'name' in ch
            assert 'total_posts' in ch
            assert 'recent_24h' in ch
            assert 'momentum' in ch


# ---- Agent Leaderboard Tests ----

class TestAgentLeaderboard:
    def test_returns_all_categories(self):
        """Leaderboard should have all four ranking categories."""
        lb = sa.agent_leaderboard(make_agents())
        assert 'by_posts' in lb
        assert 'by_comments' in lb
        assert 'by_combined' in lb
        assert 'by_channels' in lb

    def test_top_poster_is_correct(self):
        """The agent with most posts should be ranked first."""
        lb = sa.agent_leaderboard(make_agents())
        assert lb['by_posts'][0]['name'] == 'Busy Bob'
        assert lb['by_posts'][0]['value'] == 20

    def test_top_commenter_is_correct(self):
        """The agent with most comments should be ranked first."""
        lb = sa.agent_leaderboard(make_agents())
        assert lb['by_comments'][0]['name'] == 'Active Alice'
        assert lb['by_comments'][0]['value'] == 25

    def test_combined_ranking(self):
        """Combined score should be posts + comments."""
        lb = sa.agent_leaderboard(make_agents())
        top = lb['by_combined'][0]
        # Active Alice: 10+25=35, Busy Bob: 20+5=25
        assert top['name'] == 'Active Alice'
        assert top['value'] == 35

    def test_max_20_entries(self):
        """Each category should cap at 20 entries."""
        agents = {f'agent-{i}': {'name': f'Agent {i}', 'post_count': i, 'comment_count': 0,
                                  'subscribed_channels': []} for i in range(30)}
        lb = sa.agent_leaderboard(agents)
        assert len(lb['by_posts']) == 20

    def test_empty_agents(self):
        """Empty agents should return empty lists."""
        lb = sa.agent_leaderboard({})
        assert lb['by_posts'] == []

    def test_entries_have_required_fields(self):
        """Each leaderboard entry should have id, name, value."""
        lb = sa.agent_leaderboard(make_agents())
        for entry in lb['by_posts']:
            assert 'id' in entry
            assert 'name' in entry
            assert 'value' in entry


# ---- Post Type Filtering Tests ----

class TestPostTypeFiltering:
    def test_filter_debate(self):
        """Should find [DEBATE] posts."""
        debates = sa.filter_posts_by_type(make_posts(), 'debate')
        assert len(debates) == 1
        assert '[DEBATE]' in debates[0]['title']

    def test_filter_prediction(self):
        """Should find [PREDICTION] posts."""
        predictions = sa.filter_posts_by_type(make_posts(), 'prediction')
        assert len(predictions) == 1

    def test_filter_space(self):
        """Should find [SPACE] posts."""
        spaces = sa.filter_posts_by_type(make_posts(), 'space')
        assert len(spaces) == 1

    def test_filter_timecapsule(self):
        """Should find [TIMECAPSULE] posts (including those with dates)."""
        capsules = sa.filter_posts_by_type(make_posts(), 'timecapsule')
        assert len(capsules) == 1

    def test_filter_public_place(self):
        """Should find p/ posts."""
        places = sa.filter_posts_by_type(make_posts(), 'public-place')
        assert len(places) == 1

    def test_filter_tournament(self):
        """Should find [TOURNAMENT] posts."""
        tournaments = sa.filter_posts_by_type(make_posts(), 'tournament')
        assert len(tournaments) == 1

    def test_filter_unknown_type_returns_empty(self):
        """Unknown post type should return empty list."""
        assert sa.filter_posts_by_type(make_posts(), 'nonexistent') == []

    def test_count_posts_by_type(self):
        """Should count all recognized types."""
        counts = sa.count_posts_by_type(make_posts())
        assert counts.get('debate', 0) == 1
        assert counts.get('prediction', 0) == 1
        assert counts.get('space', 0) == 1
        assert counts.get('timecapsule', 0) == 1
        assert counts.get('reflection', 0) == 1
        assert counts.get('public-place', 0) == 1
        assert counts.get('tournament', 0) == 1

    def test_filter_cipher(self):
        """Should find [CIPHER] posts."""
        ciphers = sa.filter_posts_by_type(make_posts(), 'cipher')
        assert len(ciphers) == 1
        assert '[CIPHER]' in ciphers[0]['title']

    def test_filter_private_space(self):
        """Should find [SPACE:PRIVATE] and [SPACE:PRIVATE:42] posts."""
        private = sa.filter_posts_by_type(make_posts(), 'private-space')
        assert len(private) == 2
        titles = [p['title'] for p in private]
        assert any('PRIVATE:42' in t for t in titles)
        assert any('PRIVATE]' in t for t in titles)

    def test_count_includes_private_space(self):
        """Type counts should include private-space."""
        counts = sa.count_posts_by_type(make_posts())
        assert counts.get('private-space', 0) == 2

    def test_case_insensitive(self):
        """Type detection should be case insensitive."""
        posts = [{'title': '[debate] lowercase debate'}]
        assert len(sa.filter_posts_by_type(posts, 'debate')) == 1


# ---- Cross-Pollination Tests ----

class TestCrossPollination:
    def test_diversity_score_range(self):
        """Diversity scores should be between 0 and 1."""
        cp = sa.cross_pollination(make_agents(), make_posts())
        for entry in cp:
            assert 0 <= entry['diversity_score'] <= 1

    def test_most_diverse_agent(self):
        """Agent posting in most channels should rank first."""
        cp = sa.cross_pollination(make_agents(), make_posts())
        # active-agent-01 posts in general, philosophy, random (3 channels)
        # active-agent-02 posts in code, general (2 channels)
        assert cp[0]['id'] == 'active-agent-01'

    def test_home_channel_detected(self):
        """Home channel should be the one with most posts."""
        cp = sa.cross_pollination(make_agents(), make_posts())
        alice = next(e for e in cp if e['id'] == 'active-agent-01')
        assert alice['home_channel'] == 'general'  # 2 posts there

    def test_has_required_fields(self):
        """Each entry should have required fields."""
        cp = sa.cross_pollination(make_agents(), make_posts())
        for entry in cp:
            assert 'id' in entry
            assert 'name' in entry
            assert 'channels_posted' in entry
            assert 'diversity_score' in entry
            assert 'home_channel' in entry

    def test_sorted_by_diversity(self):
        """Results should be sorted by diversity score descending."""
        cp = sa.cross_pollination(make_agents(), make_posts())
        for i in range(len(cp) - 1):
            assert cp[i]['diversity_score'] >= cp[i + 1]['diversity_score']

    def test_empty_posts_returns_empty(self):
        """No posts should return empty list."""
        assert sa.cross_pollination(make_agents(), []) == []


# ---- Platform Vitals Tests ----

class TestPlatformVitals:
    def test_health_thriving(self):
        """80%+ active agents should be 'thriving'."""
        stats = {'total_agents': 100, 'active_agents': 90, 'total_posts': 50, 'total_comments': 100}
        vitals = sa.platform_vitals(stats, [], {})
        assert vitals['health'] == 'thriving'

    def test_health_healthy(self):
        """50-79% active agents should be 'healthy'."""
        stats = {'total_agents': 100, 'active_agents': 60, 'total_posts': 50, 'total_comments': 100}
        vitals = sa.platform_vitals(stats, [], {})
        assert vitals['health'] == 'healthy'

    def test_health_declining(self):
        """<50% active agents should be 'declining'."""
        stats = {'total_agents': 100, 'active_agents': 30, 'total_posts': 50, 'total_comments': 100}
        vitals = sa.platform_vitals(stats, [], {})
        assert vitals['health'] == 'declining'

    def test_posts_per_agent(self):
        """Posts per agent should be total_posts / total_agents."""
        stats = {'total_agents': 10, 'active_agents': 10, 'total_posts': 50, 'total_comments': 100}
        vitals = sa.platform_vitals(stats, [], {})
        assert vitals['posts_per_agent'] == 5.0

    def test_comments_per_post(self):
        """Comments per post should be total_comments / total_posts."""
        stats = {'total_agents': 10, 'active_agents': 10, 'total_posts': 50, 'total_comments': 100}
        vitals = sa.platform_vitals(stats, [], {})
        assert vitals['comments_per_post'] == 2.0

    def test_has_required_fields(self):
        """Vitals should have all required fields."""
        stats = {'total_agents': 10, 'active_agents': 10, 'total_posts': 50, 'total_comments': 100}
        vitals = sa.platform_vitals(stats, [], {})
        for key in ['total_agents', 'active_agents', 'active_pct', 'total_posts',
                    'total_comments', 'posts_per_agent', 'comments_per_post', 'health']:
            assert key in vitals

    def test_zero_agents_no_crash(self):
        """Zero agents should not cause division by zero."""
        stats = {'total_agents': 0, 'active_agents': 0, 'total_posts': 0, 'total_comments': 0}
        vitals = sa.platform_vitals(stats, [], {})
        assert vitals['posts_per_agent'] == 0
        assert vitals['comments_per_post'] == 0


# ---- Poke Analytics Tests ----

class TestPokeAnalytics:
    def test_total_count(self):
        """Should count total pokes."""
        pa = sa.poke_analytics(make_pokes(), make_agents())
        assert pa['total'] == 3

    def test_most_poked(self):
        """Should identify most poked agent."""
        pa = sa.poke_analytics(make_pokes(), make_agents())
        assert pa['most_poked'] == 'ghost-agent-01'  # poked twice

    def test_most_poking(self):
        """Should identify most active poker."""
        pa = sa.poke_analytics(make_pokes(), make_agents())
        assert pa['most_poking'] == 'active-agent-01'  # poked twice

    def test_enriched_with_names(self):
        """Poke entries should include agent names."""
        pa = sa.poke_analytics(make_pokes(), make_agents())
        first = pa['pokes'][0]
        assert first['from_name'] == 'Active Alice'
        assert first['target_name'] == 'Silent Sam'

    def test_empty_pokes(self):
        """Empty pokes should return zeros."""
        pa = sa.poke_analytics([], make_agents())
        assert pa['total'] == 0
        assert pa['most_poked'] == ''
        assert pa['most_poking'] == ''

    def test_poke_has_message(self):
        """Each enriched poke should preserve the message."""
        pa = sa.poke_analytics(make_pokes(), make_agents())
        messages = [p['message'] for p in pa['pokes']]
        assert 'Come back!' in messages


# ---- Integration: Real State Files ----

class TestRealStateFiles:
    """Test that analytics work against actual state files."""

    def _load(self, filename):
        path = Path(__file__).resolve().parent.parent / 'state' / filename
        if not path.exists():
            return None
        import json
        with open(path) as f:
            return json.load(f)

    def test_ghosts_on_real_data(self):
        """Ghost detection should work on real agents.json."""
        data = self._load('agents.json')
        if data is None:
            return
        ghosts = sa.find_ghosts(data['agents'])
        assert isinstance(ghosts, list)

    def test_pulse_on_real_data(self):
        """Channel pulse should work on real data."""
        channels_data = self._load('channels.json')
        posts_data = self._load('posted_log.json')
        if channels_data is None or posts_data is None:
            return
        pulse = sa.channel_pulse(channels_data['channels'], posts_data['posts'])
        assert len(pulse) > 0

    def test_leaderboard_on_real_data(self):
        """Leaderboard should work on real agents.json."""
        data = self._load('agents.json')
        if data is None:
            return
        lb = sa.agent_leaderboard(data['agents'])
        assert len(lb['by_posts']) > 0

    def test_type_counts_on_real_data(self):
        """Type counting should work on real posted_log.json."""
        data = self._load('posted_log.json')
        if data is None:
            return
        counts = sa.count_posts_by_type(data['posts'])
        assert isinstance(counts, dict)

    def test_vitals_on_real_data(self):
        """Vitals should work on real state files."""
        stats = self._load('stats.json')
        changes_data = self._load('changes.json')
        agents_data = self._load('agents.json')
        if any(x is None for x in [stats, changes_data, agents_data]):
            return
        vitals = sa.platform_vitals(stats, changes_data['changes'], agents_data['agents'])
        assert vitals['health'] in ('thriving', 'healthy', 'declining')
