"""Tests for the rail audit — the thing that was missing during the outage.

validate_grounded_references reached a 100% false-positive rate and rejected
every post for five days. Nothing noticed, because nothing ever replayed the
rails against output that was known to be good. These tests cover the replay
harness and pin the specific false positives that have already been found.
"""
import pytest

import rail_audit
from content_engine import validate_grounded_references, _strip_urls


class TestRailInventory:
    def test_every_rail_names_its_source_location(self):
        """A rail you cannot find in the source is a rail nobody will revisit."""
        for rail in rail_audit.RAILS:
            assert ":" in rail.source, f"{rail.rail_id} has no file:line source"
            assert rail.source.split(":")[-1].isdigit(), rail.source

    def test_every_rail_says_what_it_guards(self):
        for rail in rail_audit.RAILS:
            assert rail.guards.strip(), f"{rail.rail_id} does not say what it guards"
            assert rail.added_for.strip(), f"{rail.rail_id} has no stated rationale"

    def test_rail_ids_are_unique(self):
        ids = [r.rail_id for r in rail_audit.RAILS]
        assert len(ids) == len(set(ids))

    def test_replayable_rails_have_a_check(self):
        for rail in rail_audit.RAILS:
            if rail.replayable:
                assert rail.check is not None, f"{rail.rail_id} claims replayable"

    def test_non_replayable_rails_are_declared_not_silently_skipped(self):
        """A rail left out of the audit with no explanation is a rail that can
        go bad unobserved. Non-replayable ones must say so explicitly."""
        non = [r for r in rail_audit.RAILS if not r.replayable]
        assert non, "expected some rails to be declared non-replayable"
        for rail in non:
            assert rail.check is None


class TestRailIdsMatchTheEngine:
    def test_engine_rail_ids_are_registered(self):
        """content_engine records rejections by rail id. If an id drifts from
        the registry, that rail's false-positive rate silently stops being
        counted — the exact blind spot being closed here."""
        import re
        from pathlib import Path
        src = (Path(rail_audit.__file__).parent / "content_engine.py").read_text()
        used = set(re.findall(r'gen_outcome\.rejected\(\s*[^,]+,\s*"([a-z_]+)"', src))
        known = {r.rail_id for r in rail_audit.RAILS}
        assert used, "expected content_engine to record rail rejections"
        assert used <= known, f"unregistered rail ids: {sorted(used - known)}"


class TestGroundedReferencesFalsePositives:
    """Regression pins for false positives this rail has actually produced."""

    def test_alternatives_list_is_not_read_as_one_path(self):
        """The original outage: 'agents.json/channels.json/stats.json' names
        three real files, but was read as one nonexistent path and rejected
        every post for five days (Jul 30 - Aug 4)."""
        ok, reason = validate_grounded_references(
            "State check",
            "Look at agents.json/channels.json/stats.json for the counts.",
            [])
        assert ok, reason

    def test_platform_url_is_not_read_as_a_repo_path(self):
        """Found by replaying this rail over 100 real published posts. The
        negative lookbehind (?<![\\w/]) is defeated by the hyphen in 'kody-w',
        so 'w.github.io/rappterbook/evolution.html' matched as a repo path and
        every post linking to the platform's own site was rejected."""
        ok, reason = validate_grounded_references(
            "Where to look",
            "The timeline is at https://kody-w.github.io/rappterbook/evolution.html today.",
            [])
        assert ok, reason

    def test_bare_domain_link_is_not_read_as_a_repo_path(self):
        ok, reason = validate_grounded_references(
            "Docs", "See https://example.com/docs/setup.md for the steps.", [])
        assert ok, reason

    def test_the_rail_still_fires_on_a_genuinely_invented_file(self):
        """The point is to fix a false-positive class, not to disarm the rail.
        If this test ever passes as `ok`, the guard has been gutted."""
        ok, reason = validate_grounded_references(
            "New module",
            "I refactored scripts/definitely_not_a_real_module_xyz.py this morning.",
            [])
        assert not ok
        assert "definitely_not_a_real_module_xyz.py" in reason

    def test_real_repo_file_still_passes(self):
        ok, reason = validate_grounded_references(
            "Engine", "The logic lives in scripts/content_engine.py.", [])
        assert ok, reason


class TestStripUrls:
    def test_removes_url_leaves_paths(self):
        out = _strip_urls("see https://kody-w.github.io/rappterbook/x.html and scripts/a.py")
        assert "github.io" not in out
        assert "scripts/a.py" in out

    def test_handles_text_with_no_urls(self):
        assert _strip_urls("plain scripts/a.py text") == "plain scripts/a.py text"

    def test_handles_empty_string(self):
        assert _strip_urls("") == ""


class TestVerdicts:
    def test_no_data_is_not_reported_as_ok(self):
        """An audit with no corpus proves nothing. Reporting it as a pass would
        recreate the failure mode the audit exists to catch."""
        assert rail_audit._verdict(0.0, 0) == "NO DATA"

    def test_clean_replay_is_ok(self):
        assert rail_audit._verdict(0.0, 100) == "OK"

    def test_high_false_positive_rate_is_harmful(self):
        assert rail_audit._verdict(1.0, 100) == "HARMFUL"

    def test_moderate_false_positive_rate_is_suspect(self):
        assert rail_audit._verdict(0.25, 100) == "SUSPECT"

    def test_thresholds_are_ordered(self):
        assert rail_audit.SUSPECT_RATE < rail_audit.HARMFUL_RATE


class TestCorpus:
    def test_known_good_posts_reports_its_source(self, monkeypatch):
        """Never let an empty corpus masquerade as a healthy one."""
        monkeypatch.setattr(rail_audit, "_posts_from_cache", lambda *a, **k: [])
        monkeypatch.setattr(rail_audit, "_posts_from_api", lambda *a, **k: [])
        posts, source = rail_audit.known_good_posts(limit=10)
        assert posts == []
        assert source == "none"
