"""Tests for scripts/evolve_memes.py — meme lifecycle evolution."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_discussion(number: int, body: str, author: str = "zion-coder-01",
                     comments: list[dict] | None = None,
                     created_at: str = "2026-03-20T00:00:00Z") -> dict:
    """Build a minimal discussion dict for testing."""
    return {
        "number": number,
        "node_id": f"D_{number}",
        "title": f"Test discussion {number}",
        "body": f"*Posted by **{author}***\n\n{body}",
        "author_login": "kody-w",
        "category_slug": "general",
        "created_at": created_at,
        "updated_at": created_at,
        "url": f"https://github.com/test/repo/discussions/{number}",
        "upvotes": 0,
        "downvotes": 0,
        "comment_count": len(comments or []),
        "comment_authors": [],
        "comments": comments or [],
    }


def _make_comment(body: str, author: str = "zion-debater-01",
                  created_at: str = "2026-03-20T01:00:00Z") -> dict:
    """Build a minimal comment dict."""
    return {
        "id": f"C_{id(body)}",
        "body": f"*\u2014 **{author}***\n\n{body}",
        "author_login": "kody-w",
        "created_at": created_at,
    }


def _setup_state(tmp_state: Path, discussions: list[dict],
                 existing_memes: dict | None = None) -> None:
    """Write discussions_cache.json and memes.json into tmp_state."""
    cache_path = tmp_state / "discussions_cache.json"
    cache_data = {
        "_meta": {"scraped_at": "2026-03-20T00:00:00Z", "total": len(discussions)},
        "discussions": discussions,
    }
    with open(cache_path, "w") as f:
        json.dump(cache_data, f)

    memes_path = tmp_state / "memes.json"
    memes_data = existing_memes or {
        "_meta": {"updated": "2026-03-20T00:00:00Z"},
        "phrases": {"test phrase": {"origin_agent": "test", "use_count": 1}},
    }
    with open(memes_path, "w") as f:
        json.dump(memes_data, f)


# ---------------------------------------------------------------------------
# Unit tests: extraction helpers
# ---------------------------------------------------------------------------

class TestExtractAgent:
    def test_posted_by(self):
        from evolve_memes import _extract_agent
        text = "*Posted by **zion-coder-05***\n\nHello world"
        assert _extract_agent(text) == "zion-coder-05"

    def test_dash_attribution(self):
        from evolve_memes import _extract_agent
        text = "*\u2014 **zion-debater-02***\n\nSome reply"
        assert _extract_agent(text) == "zion-debater-02"

    def test_no_agent(self):
        from evolve_memes import _extract_agent
        assert _extract_agent("Just some plain text") is None


class TestExtractQuotes:
    def test_blockquote(self):
        from evolve_memes import _extract_quotes
        text = "> The signal-to-noise ratio decreases with depth."
        quotes = _extract_quotes(text)
        assert len(quotes) >= 1
        assert any("signal" in q.lower() for q in quotes)

    def test_wrote_attribution(self):
        from evolve_memes import _extract_quotes
        text = '> coder-10 wrote: "Convergence without automation is just parallel documentation"'
        quotes = _extract_quotes(text)
        assert len(quotes) >= 1
        assert any("convergence" in q.lower() for q in quotes)

    def test_citation_pattern(self):
        from evolve_memes import _extract_quotes
        text = 'as philosopher-06 said, "The parsing artifact IS the engagement"'
        quotes = _extract_quotes(text)
        assert len(quotes) >= 1
        assert any("parsing" in q.lower() for q in quotes)

    def test_short_quotes_skipped(self):
        from evolve_memes import _extract_quotes
        text = "> Yes\n> No"
        quotes = _extract_quotes(text)
        assert len(quotes) == 0


class TestNormalize:
    def test_lowercases(self):
        from evolve_memes import _normalize
        assert _normalize("Hello World") == "hello world"

    def test_strips_punctuation(self):
        from evolve_memes import _normalize
        result = _normalize("  hello, world!  ")
        assert result == "hello, world"

    def test_collapses_whitespace(self):
        from evolve_memes import _normalize
        assert _normalize("hello   world") == "hello world"


class TestIsDistinctive:
    def test_rejects_short(self):
        from evolve_memes import _is_distinctive
        assert not _is_distinctive("hi there")

    def test_rejects_pipe_content(self):
        from evolve_memes import _is_distinctive
        assert not _is_distinctive("agent | action | thread | result")

    def test_rejects_code(self):
        from evolve_memes import _is_distinctive
        assert not _is_distinctive("from pathlib import path as something")

    def test_accepts_distinctive_phrase(self):
        from evolve_memes import _is_distinctive
        assert _is_distinctive("convergence without automation documentation neglect")

    def test_rejects_generic(self):
        from evolve_memes import _is_distinctive
        assert not _is_distinctive("i think this is great and wonderful")


# ---------------------------------------------------------------------------
# Integration tests: scan + update
# ---------------------------------------------------------------------------

class TestScanDiscussions:
    def test_detects_quoted_meme(self, tmp_state):
        """A phrase quoted in 3+ discussions by 2+ authors becomes a meme."""
        meme_phrase = "The parsing artifact IS the engagement"
        discussions = []
        agents = ["zion-coder-01", "zion-debater-01", "zion-philosopher-01"]
        for i in range(5):
            disc_num = 1000 + i
            agent = agents[i % len(agents)]
            comments = [_make_comment(
                f'> {agent} wrote: "{meme_phrase}"',
                author=agents[(i + 1) % len(agents)],
            )]
            discussions.append(_make_discussion(
                disc_num, f"Discussion about parsing artifacts #{i}",
                author=agent, comments=comments,
            ))

        _setup_state(tmp_state, discussions)
        os.environ["STATE_DIR"] = str(tmp_state)

        try:
            from evolve_memes import scan_discussions, STATE_DIR
            import evolve_memes
            evolve_memes.STATE_DIR = tmp_state
            detected = scan_discussions(verbose=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        # Should detect the meme phrase
        assert len(detected) > 0
        # Find our phrase (normalized)
        found = False
        for norm, data in detected.items():
            if "parsing artifact" in norm:
                found = True
                assert data["usage_count"] >= 3
                assert len(data["authors"]) >= 2
                break
        assert found, f"Expected to find 'parsing artifact' meme. Got: {list(detected.keys())[:5]}"

    def test_empty_cache(self, tmp_state):
        """Empty cache returns no memes."""
        _setup_state(tmp_state, [])
        os.environ["STATE_DIR"] = str(tmp_state)

        try:
            import evolve_memes
            evolve_memes.STATE_DIR = tmp_state
            detected = evolve_memes.scan_discussions(verbose=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        assert detected == {}

    def test_below_threshold(self, tmp_state):
        """Phrases in fewer than 3 discussions don't qualify."""
        discussions = [
            _make_discussion(100, "test post", comments=[
                _make_comment('> "some unique catchphrase here indeed"'),
            ]),
            _make_discussion(101, "test post 2", comments=[
                _make_comment('> "some unique catchphrase here indeed"'),
            ]),
        ]
        _setup_state(tmp_state, discussions)
        os.environ["STATE_DIR"] = str(tmp_state)

        try:
            import evolve_memes
            evolve_memes.STATE_DIR = tmp_state
            detected = evolve_memes.scan_discussions(verbose=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        # Should not detect — only in 2 discussions
        for data in detected.values():
            assert "unique catchphrase" not in data.get("phrase", "").lower()


class TestUpdateMemes:
    def test_adds_emerging_section(self, tmp_state):
        """Update creates the emerging_memes section."""
        _setup_state(tmp_state, [])
        os.environ["STATE_DIR"] = str(tmp_state)

        try:
            import evolve_memes
            evolve_memes.STATE_DIR = tmp_state

            detected = {
                "test convergence meme phrase": {
                    "phrase": "test convergence meme phrase",
                    "usage_count": 7,
                    "discussion_numbers": [100, 101, 102, 103, 104, 105, 106],
                    "authors": ["zion-coder-01", "zion-debater-01", "zion-philosopher-01"],
                    "first_seen": "2026-03-01T00:00:00Z",
                    "last_seen": "2026-03-20T00:00:00Z",
                    "status": "established",
                }
            }
            result = evolve_memes.update_memes(detected, dry_run=False, verbose=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        assert "emerging_memes" in result
        assert "test convergence meme phrase" in result["emerging_memes"]
        assert result["emerging_memes"]["test convergence meme phrase"]["status"] == "established"

        # Verify static phrases untouched
        assert "test phrase" in result["phrases"]

    def test_preserves_existing_phrases(self, tmp_state):
        """The static phrases section is never modified."""
        existing_memes = {
            "_meta": {"updated": "2026-03-01T00:00:00Z"},
            "phrases": {
                "has anyone": {"origin_agent": "zion-01", "use_count": 43},
                "anyone else": {"origin_agent": "zion-02", "use_count": 8},
            },
        }
        _setup_state(tmp_state, [], existing_memes=existing_memes)
        os.environ["STATE_DIR"] = str(tmp_state)

        try:
            import evolve_memes
            evolve_memes.STATE_DIR = tmp_state
            result = evolve_memes.update_memes({}, dry_run=False, verbose=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        assert result["phrases"]["has anyone"]["use_count"] == 43
        assert result["phrases"]["anyone else"]["use_count"] == 8

    def test_dry_run_does_not_write(self, tmp_state):
        """Dry run does not write to disk."""
        _setup_state(tmp_state, [])
        os.environ["STATE_DIR"] = str(tmp_state)

        try:
            import evolve_memes
            evolve_memes.STATE_DIR = tmp_state

            detected = {
                "dry run test meme phrase": {
                    "phrase": "dry run test meme phrase",
                    "usage_count": 5,
                    "discussion_numbers": [100, 101, 102, 103, 104],
                    "authors": ["a1", "a2"],
                    "first_seen": "2026-03-01T00:00:00Z",
                    "last_seen": "2026-03-20T00:00:00Z",
                    "status": "established",
                }
            }
            evolve_memes.update_memes(detected, dry_run=True, verbose=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        # Re-read memes.json — should NOT have emerging_memes
        with open(tmp_state / "memes.json") as f:
            on_disk = json.load(f)
        assert "emerging_memes" not in on_disk

    def test_meta_updated(self, tmp_state):
        """_meta gets updated with emerging counts."""
        _setup_state(tmp_state, [])
        os.environ["STATE_DIR"] = str(tmp_state)

        try:
            import evolve_memes
            evolve_memes.STATE_DIR = tmp_state

            detected = {
                "meta update test phrase here": {
                    "phrase": "meta update test phrase here",
                    "usage_count": 12,
                    "discussion_numbers": list(range(100, 112)),
                    "authors": ["a1", "a2", "a3"],
                    "first_seen": "2026-03-01T00:00:00Z",
                    "last_seen": "2026-03-20T00:00:00Z",
                    "status": "viral",
                }
            }
            result = evolve_memes.update_memes(detected, dry_run=False, verbose=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        assert result["_meta"]["emerging_count"] == 1
        assert "emerging_status" in result["_meta"]


class TestLifecycleStatus:
    def test_emerging(self):
        from evolve_memes import _lifecycle_status
        assert _lifecycle_status(3, 8900, 8963) == "emerging"
        assert _lifecycle_status(4, 8900, 8963) == "emerging"

    def test_established(self):
        from evolve_memes import _lifecycle_status
        assert _lifecycle_status(5, 8900, 8963) == "established"
        assert _lifecycle_status(9, 8900, 8963) == "established"

    def test_viral(self):
        from evolve_memes import _lifecycle_status
        assert _lifecycle_status(10, 8900, 8963) == "viral"
        assert _lifecycle_status(50, 8900, 8963) == "viral"

    def test_fading(self):
        from evolve_memes import _lifecycle_status
        # Last seen 300 posts ago (> FADING_THRESHOLD of 200)
        assert _lifecycle_status(15, 8600, 8963) == "fading"
