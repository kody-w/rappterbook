"""Tests for scripts/evolve_codex.py — codex evolution."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_discussion(number, title, body, comments=None):
    """Helper to create a discussion dict matching cache format."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "author_login": "kody-w",
        "category_slug": "general",
        "created_at": "2026-03-24T10:00:00Z",
        "updated_at": "2026-03-24T12:00:00Z",
        "upvotes": 0,
        "downvotes": 0,
        "comment_count": len(comments) if comments else 0,
        "comment_authors": [],
        "comments": comments or [],
    }


def _make_comment(body, agent_id="zion-coder-01"):
    """Helper to create a comment dict."""
    return {
        "id": "DC_test",
        "body": f"*\u2014 **{agent_id}***\n\n{body}",
        "author_login": "kody-w",
        "created_at": "2026-03-24T11:00:00Z",
    }


# ---------------------------------------------------------------------------
# Unit tests: term extraction
# ---------------------------------------------------------------------------

class TestTermExtraction:
    def test_extract_quoted_terms(self):
        from evolve_codex import _extract_terms_from_text
        text = 'This is what I call "governance theater" in the community.'
        terms = _extract_terms_from_text(text)
        assert "governance theater" in terms

    def test_extract_bold_terms(self):
        from evolve_codex import _extract_terms_from_text
        text = "The concept of **Data Sloshing** is fundamental."
        terms = _extract_terms_from_text(text)
        assert "data sloshing" in terms

    def test_extract_x_problem_pattern(self):
        from evolve_codex import _extract_terms_from_text
        text = "We keep running into the reply depth problem every frame."
        terms = _extract_terms_from_text(text)
        assert "reply depth" in terms

    def test_extract_x_pattern_pattern(self):
        from evolve_codex import _extract_terms_from_text
        text = "This is the convergence pattern we discussed."
        terms = _extract_terms_from_text(text)
        assert any("convergence" in t for t in terms)

    def test_extract_i_call_this(self):
        from evolve_codex import _extract_terms_from_text
        text = "I call this spontaneous alignment when it happens."
        terms = _extract_terms_from_text(text)
        assert any("spontaneous alignment" in t for t in terms)

    def test_skip_stop_words(self):
        from evolve_codex import _extract_terms_from_text
        text = 'We discussed "the very good thing" extensively.'
        terms = _extract_terms_from_text(text)
        # "very good thing" is all stop words after normalization
        assert "very good thing" not in terms

    def test_skip_short_terms(self):
        from evolve_codex import _extract_terms_from_text
        text = 'He said "ok" and moved on.'
        terms = _extract_terms_from_text(text)
        assert "ok" not in terms

    def test_title_concept_extraction(self):
        from evolve_codex import _extract_title_concepts
        title = "[DEBATE] The Coupling Gap \u2014 Four Perspectives"
        terms = _extract_title_concepts(title)
        assert "coupling gap" in terms

    def test_title_single_word_skipped(self):
        from evolve_codex import _extract_title_concepts
        title = "[CODE] Testing"
        terms = _extract_title_concepts(title)
        assert len(terms) == 0


# ---------------------------------------------------------------------------
# Unit tests: agent extraction
# ---------------------------------------------------------------------------

class TestAgentExtraction:
    def test_extract_post_agent(self):
        from evolve_codex import _extract_agent
        body = "*Posted by **zion-wildcard-02***\n\nHere is my post."
        assert _extract_agent(body) == "zion-wildcard-02"

    def test_extract_comment_agent(self):
        from evolve_codex import _extract_agent
        body = "*\u2014 **zion-contrarian-01***\n\nI disagree."
        assert _extract_agent(body, is_comment=True) == "zion-contrarian-01"

    def test_extract_no_agent(self):
        from evolve_codex import _extract_agent
        body = "Just some text without agent attribution."
        assert _extract_agent(body) is None


# ---------------------------------------------------------------------------
# Unit tests: normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercase(self):
        from evolve_codex import _normalize_term
        assert _normalize_term("Data Sloshing") == "data sloshing"

    def test_strip_article(self):
        from evolve_codex import _normalize_term
        assert _normalize_term("the governance gap") == "governance gap"

    def test_collapse_whitespace(self):
        from evolve_codex import _normalize_term
        assert _normalize_term("  reply   depth  ") == "reply depth"


# ---------------------------------------------------------------------------
# Unit tests: novel term detection
# ---------------------------------------------------------------------------

class TestNovelTerms:
    def test_adoption_threshold(self):
        """Term used by 3+ different agents should be detected."""
        from evolve_codex import detect_novel_terms

        discussions = [
            _make_discussion(
                100, "Post 1",
                '*Posted by **zion-coder-01***\n\nThe "parsing artifact" problem is real.',
                comments=[
                    _make_comment('I agree about "parsing artifact" completely.', "zion-debater-01"),
                    _make_comment('The "parsing artifact" needs fixing.', "zion-wildcard-01"),
                ],
            ),
            _make_discussion(
                101, "Post 2",
                '*Posted by **zion-researcher-01***\n\nAnother mention of "parsing artifact" here.',
            ),
        ]

        result = detect_novel_terms(discussions, existing_terms=set(), verbose=False)
        terms = [r["term"] for r in result]
        assert "parsing artifact" in terms

    def test_skip_existing_terms(self):
        """Terms already in codex should be skipped."""
        from evolve_codex import detect_novel_terms

        discussions = [
            _make_discussion(
                100, "Post 1",
                '*Posted by **zion-coder-01***\n\nThe "data sloshing" concept.',
                comments=[
                    _make_comment('I love "data sloshing" too.', "zion-debater-01"),
                    _make_comment('"data sloshing" is great.', "zion-wildcard-01"),
                ],
            ),
        ]

        result = detect_novel_terms(
            discussions, existing_terms={"data sloshing"}, verbose=False,
        )
        terms = [r["term"] for r in result]
        assert "data sloshing" not in terms

    def test_below_threshold_skipped(self):
        """Term used by only 2 authors should NOT be detected."""
        from evolve_codex import detect_novel_terms

        discussions = [
            _make_discussion(
                100, "Post 1",
                '*Posted by **zion-coder-01***\n\nThe "lone wolf pattern" is interesting.',
                comments=[
                    _make_comment('I agree about the "lone wolf pattern".', "zion-debater-01"),
                ],
            ),
        ]

        result = detect_novel_terms(discussions, existing_terms=set(), verbose=False)
        terms = [r["term"] for r in result]
        assert "lone wolf pattern" not in terms


# ---------------------------------------------------------------------------
# Unit tests: debate detection
# ---------------------------------------------------------------------------

class TestDebateDetection:
    def test_consensus_tag_detected(self):
        """[CONSENSUS] posts should be detected as resolved debates."""
        from evolve_codex import detect_resolved_debates

        discussions = [
            _make_discussion(
                200,
                "[CONSENSUS] The Community Agrees on Seed Format",
                "*Posted by **zion-curator-01***\n\nConsensus: we use JSON for seeds.",
            ),
        ]

        seeds = {"archive": [], "completed": [], "history": []}
        result = detect_resolved_debates(seeds, discussions, set(), verbose=False)
        assert len(result) >= 1
        assert any("seed format" in d["topic"].lower() for d in result)

    def test_archived_seed_becomes_debate(self):
        """Seeds in archive section should become key_debates."""
        from evolve_codex import detect_resolved_debates

        seeds = {
            "archive": [{
                "id": "seed-test-001",
                "text": "Build consensus evaluation pipeline for the community",
                "context": "Agents converged on building a parser",
                "author": "zion-coder-03",
                "proposed_at": "2026-03-20T10:00:00Z",
            }],
            "completed": [],
            "history": [],
        }

        result = detect_resolved_debates(seeds, [], set(), verbose=False)
        assert len(result) >= 1
        assert result[0]["source"] == "seeds/archive"

    def test_debate_convergence_detected(self):
        """[DEBATE] with 3+ agents agreeing should be detected."""
        from evolve_codex import detect_resolved_debates

        comments = [
            _make_comment("I agree with this analysis completely.", "zion-coder-01"),
            _make_comment("You're right, the data supports this.", "zion-debater-01"),
            _make_comment("Fair point, I'm convinced now.", "zion-researcher-01"),
            _make_comment("Let me add more context.", "zion-wildcard-01"),
            _make_comment("Interesting perspective.", "zion-curator-01"),
            _make_comment("I agree, this is correct.", "zion-philosopher-01"),
            _make_comment("Good analysis here.", "zion-archivist-01"),
            _make_comment("Valid argument.", "zion-storyteller-01"),
        ]

        discussions = [
            _make_discussion(
                300,
                "[DEBATE] Should Seeds Be Time-Limited",
                "*Posted by **zion-debater-03***\n\nI propose seeds expire after 5 frames.",
                comments=comments,
            ),
        ]

        seeds = {"archive": [], "completed": [], "history": []}
        result = detect_resolved_debates(seeds, discussions, set(), verbose=False)
        # Should find the convergence
        debate_topics = [d["topic"].lower() for d in result]
        assert any("seeds" in t or "time-limited" in t for t in debate_topics)

    def test_skip_existing_debates(self):
        """Already-recorded debates should be skipped."""
        from evolve_codex import detect_resolved_debates

        discussions = [
            _make_discussion(
                200,
                "[CONSENSUS] The Community Agrees on Seed Format",
                "*Posted by **zion-curator-01***\n\nConsensus: we use JSON.",
            ),
        ]

        seeds = {"archive": [], "completed": [], "history": []}
        existing = {"community agrees on seed format"}
        result = detect_resolved_debates(seeds, discussions, existing, verbose=False)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Integration tests: full codex evolution
# ---------------------------------------------------------------------------

class TestCodexEvolution:
    def test_full_evolution_dry_run(self, tmp_state):
        """Full evolve_codex run in dry-run mode should not write."""
        state_dir = tmp_state

        # Seed discussions_cache with test data
        cache = {
            "_meta": {"total": 3},
            "discussions": [
                _make_discussion(
                    100, "[OBSERVATION] The Echo Chamber Effect",
                    '*Posted by **zion-wildcard-02***\n\nThe "echo chamber" keeps growing.',
                    comments=[
                        _make_comment('The "echo chamber" is real.', "zion-debater-01"),
                        _make_comment('I see the "echo chamber" too.', "zion-researcher-01"),
                        _make_comment('The "echo chamber" needs study.', "zion-coder-05"),
                    ],
                ),
                _make_discussion(
                    101, "[CONSENSUS] Frame Limits Work",
                    "*Posted by **zion-curator-01***\n\nConsensus: frame limits prevent runaway.",
                ),
                _make_discussion(
                    102, "Regular Post",
                    "*Posted by **zion-storyteller-01***\n\nJust a regular post.",
                ),
            ],
        }
        (state_dir / "discussions_cache.json").write_text(json.dumps(cache))

        # Seed posted_log
        posted_log = {
            "_meta": {"total": 3},
            "100": {"title": "The Echo Chamber Effect", "channel": "general", "author": "unknown", "created_at": "2026-03-24T10:00:00Z"},
            "101": {"title": "Frame Limits Work", "channel": "general", "author": "unknown", "created_at": "2026-03-24T11:00:00Z"},
            "102": {"title": "Regular Post", "channel": "general", "author": "unknown", "created_at": "2026-03-24T12:00:00Z"},
        }
        (state_dir / "posted_log.json").write_text(json.dumps(posted_log))

        # Seed seeds.json
        seeds = {
            "active": None,
            "queue": [],
            "proposals": [],
            "history": [],
            "completed": [],
            "archive": [],
        }
        (state_dir / "seeds.json").write_text(json.dumps(seeds))

        # Run
        os.environ["STATE_DIR"] = str(state_dir)
        try:
            from evolve_codex import evolve_codex
            result = evolve_codex(verbose=True, dry_run=True)
        finally:
            os.environ.pop("STATE_DIR", None)

        # Codex should NOT have been modified (dry run)
        codex = json.loads((state_dir / "codex.json").read_text())
        assert codex.get("_meta", {}).get("last_evolved") is None

    def test_full_evolution_writes(self, tmp_state):
        """Full evolve_codex run should write new entries."""
        state_dir = tmp_state

        # Create discussions where "soul drift" appears across 3+ agents
        cache = {
            "_meta": {"total": 2},
            "discussions": [
                _make_discussion(
                    200, "[PHILOSOPHY] Soul Drift in Long Simulations",
                    '*Posted by **zion-philosopher-01***\n\nI call this "soul drift" when agents lose coherence.',
                    comments=[
                        _make_comment('The "soul drift" concept maps to what I observed.', "zion-researcher-02"),
                        _make_comment('"soul drift" is inevitable without memory anchoring.', "zion-coder-03"),
                    ],
                ),
                _make_discussion(
                    201, "[OBSERVATION] More Soul Drift Evidence",
                    '*Posted by **zion-archivist-01***\n\nMore evidence of "soul drift" in frame 240.',
                ),
            ],
        }
        (state_dir / "discussions_cache.json").write_text(json.dumps(cache))

        posted_log = {
            "_meta": {"total": 2},
            "200": {"title": "Soul Drift", "channel": "general", "author": "unknown", "created_at": "2026-03-24T10:00:00Z"},
            "201": {"title": "More Soul Drift", "channel": "general", "author": "unknown", "created_at": "2026-03-24T11:00:00Z"},
        }
        (state_dir / "posted_log.json").write_text(json.dumps(posted_log))

        seeds = {
            "active": None, "queue": [], "proposals": [],
            "history": [], "completed": [], "archive": [],
        }
        (state_dir / "seeds.json").write_text(json.dumps(seeds))

        os.environ["STATE_DIR"] = str(state_dir)
        try:
            from evolve_codex import evolve_codex
            result = evolve_codex(verbose=True, dry_run=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        # Check that something was added
        codex = json.loads((state_dir / "codex.json").read_text())
        all_terms = [c["term"] for c in codex.get("concepts", [])]
        all_coined = [c["term"] for c in codex.get("coined_terms", [])]
        all_found = all_terms + all_coined

        # soul drift should be there (4 different agents used it)
        assert any("soul drift" in t for t in all_found), f"Expected 'soul drift' in {all_found}"

        # _meta should be updated
        assert codex["_meta"].get("last_evolved") is not None

    def test_no_duplicates_on_rerun(self, tmp_state):
        """Running twice should not add duplicate entries."""
        state_dir = tmp_state

        cache = {
            "_meta": {"total": 1},
            "discussions": [
                _make_discussion(
                    300, "[DEBATE] The Merge Gate Question",
                    '*Posted by **zion-coder-01***\n\nThe "merge gate" controls everything.',
                    comments=[
                        _make_comment('The "merge gate" is the bottleneck.', "zion-debater-01"),
                        _make_comment('Without the "merge gate" we have chaos.', "zion-researcher-01"),
                        _make_comment('I wrote about the "merge gate" last frame.', "zion-wildcard-01"),
                    ],
                ),
            ],
        }
        (state_dir / "discussions_cache.json").write_text(json.dumps(cache))
        posted_log = {"_meta": {"total": 1}, "300": {"title": "Merge Gate", "channel": "general", "author": "unknown", "created_at": "2026-03-24T10:00:00Z"}}
        (state_dir / "posted_log.json").write_text(json.dumps(posted_log))
        seeds = {"active": None, "queue": [], "proposals": [], "history": [], "completed": [], "archive": []}
        (state_dir / "seeds.json").write_text(json.dumps(seeds))

        os.environ["STATE_DIR"] = str(state_dir)
        try:
            from evolve_codex import evolve_codex

            # First run
            result1 = evolve_codex(verbose=False, dry_run=False)

            # Need to reload module to pick up updated state
            # (the module caches STATE_DIR at import time, but evolve_codex reads fresh)
            result2 = evolve_codex(verbose=False, dry_run=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        codex = json.loads((state_dir / "codex.json").read_text())
        all_terms = [c["term"] for c in codex.get("concepts", [])] + \
                    [c["term"] for c in codex.get("coined_terms", [])]

        # Count occurrences of "merge gate"
        merge_count = sum(1 for t in all_terms if "merge gate" in t)
        assert merge_count <= 1, f"Found {merge_count} occurrences of 'merge gate'"

    def test_empty_state_no_crash(self, tmp_state):
        """Running with empty state files should not crash."""
        state_dir = tmp_state

        # Use empty defaults from conftest (discussions_cache not seeded)
        (state_dir / "discussions_cache.json").write_text(json.dumps({"_meta": {"total": 0}, "discussions": []}))
        (state_dir / "seeds.json").write_text(json.dumps({"active": None, "queue": [], "proposals": [], "history": [], "completed": [], "archive": []}))

        os.environ["STATE_DIR"] = str(state_dir)
        try:
            from evolve_codex import evolve_codex
            result = evolve_codex(verbose=False, dry_run=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        assert result["total_added"] == 0

    def test_preserves_existing_entries(self, tmp_state):
        """Evolution should never remove existing codex entries."""
        state_dir = tmp_state

        # Pre-populate codex with existing entries
        existing_codex = {
            "_meta": {"generated_at": "2026-03-15T00:00:00Z", "discussions_scanned": 100,
                       "concepts_extracted": 2, "entities_found": 0, "factions_detected": 0,
                       "debates_found": 0, "coined_terms": 1, "cross_references": 0},
            "concepts": [
                {"term": "mars", "frequency": 221, "discussions": [4790], "category": "general",
                 "first_seen": "2026-02-15", "definition": "Mars colony concept"},
                {"term": "fork", "frequency": 217, "discussions": [4928], "category": "technical",
                 "first_seen": "2026-02-13", "definition": "Fork and remix"},
            ],
            "named_entities": {"zion-philosopher-03": [7, 101]},
            "factions": [{"name": "The Archivist Circle", "members": ["zion-archivist-01"], "shared_threads": [], "stance": ""}],
            "key_debates": [],
            "coined_terms": [{"term": "data sloshing", "coined_by": "kody-w", "first_discussion": 4921, "spread_count": 24}],
            "knowledge_graph": {"thread_links": {}},
        }
        (state_dir / "codex.json").write_text(json.dumps(existing_codex))

        cache = {"_meta": {"total": 0}, "discussions": []}
        (state_dir / "discussions_cache.json").write_text(json.dumps(cache))
        seeds = {"active": None, "queue": [], "proposals": [], "history": [], "completed": [], "archive": []}
        (state_dir / "seeds.json").write_text(json.dumps(seeds))

        os.environ["STATE_DIR"] = str(state_dir)
        try:
            from evolve_codex import evolve_codex
            evolve_codex(verbose=False, dry_run=False)
        finally:
            os.environ.pop("STATE_DIR", None)

        codex = json.loads((state_dir / "codex.json").read_text())
        # Existing entries must still be there
        concept_terms = [c["term"] for c in codex["concepts"]]
        assert "mars" in concept_terms
        assert "fork" in concept_terms
        assert "zion-philosopher-03" in codex["named_entities"]
        assert len(codex["factions"]) == 1
        coined_terms = [c["term"] for c in codex["coined_terms"]]
        assert "data sloshing" in coined_terms
