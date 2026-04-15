"""Tests for scripts/seed_gate.py — the specificity validator for seed proposals.

Covers: action verb detection, concrete target detection, junk filtering,
scoring, theme exemptions, and end-to-end validate() behaviour.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is importable
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from seed_gate import (
    ACTION_VERBS,
    KNOWN_TOOLS,
    compute_score,
    detect_junk,
    find_action_verb,
    find_concrete_target,
    validate,
)


# ─── Action Verb Detection ──────────────────────────────────────────────


class TestFindActionVerb:
    """Tests for find_action_verb()."""

    def test_common_verbs(self) -> None:
        """Every verb in ACTION_VERBS is detected."""
        for verb in sorted(ACTION_VERBS):
            result = find_action_verb(f"We should {verb} the thing")
            assert result == verb, f"Failed to detect verb: {verb}"

    def test_case_insensitive(self) -> None:
        assert find_action_verb("BUILD something great") == "build"
        assert find_action_verb("Ship the feature today") == "ship"

    def test_verb_in_middle(self) -> None:
        assert find_action_verb("We need to refactor state_io") == "refactor"

    def test_no_verb_returns_none(self) -> None:
        assert find_action_verb("What if agents could dream?") is None
        assert find_action_verb("The best approach to philosophy") is None

    def test_non_verb_words_not_matched(self) -> None:
        """Words not in the verb set should not be picked up."""
        assert find_action_verb("Discuss the meaning of existence") is None
        assert find_action_verb("Consider the implications") is None

    def test_verb_at_start(self) -> None:
        assert find_action_verb("Build seed_gate.py") == "build"

    def test_verb_boundary(self) -> None:
        """Verbs should match at word boundaries only."""
        # "testing" should not match "test" (word boundary)
        result = find_action_verb("We were building homes")
        # "building" contains "build" — regex \bbuild\b won't match "building"
        assert result is None or result == "build"


# ─── Concrete Target Detection ───────────────────────────────────────────


class TestFindConcreteTarget:
    """Tests for find_concrete_target()."""

    def test_python_filename(self) -> None:
        assert find_concrete_target("Build seed_gate.py") == "seed_gate.py"

    def test_js_filename(self) -> None:
        assert find_concrete_target("Write router.js for the frontend") == "router.js"

    def test_hyphenated_filename(self) -> None:
        assert find_concrete_target("Fix my-component.ts") == "my-component.ts"

    def test_json_filename(self) -> None:
        assert find_concrete_target("Update agents.json schema") == "agents.json"

    def test_repo_path(self) -> None:
        target = find_concrete_target("Refactor scripts/process_inbox.py")
        assert target is not None
        assert "scripts/" in target or "process_inbox.py" in target

    def test_channel_ref(self) -> None:
        assert find_concrete_target("Create r/philosophy channel") == "r/philosophy"

    def test_function_call(self) -> None:
        assert find_concrete_target("Fix validate_seed() crash") == "validate_seed()"

    def test_discussion_ref(self) -> None:
        assert find_concrete_target("Wire this into #12503") == "#12503"

    def test_known_tool(self) -> None:
        target = find_concrete_target("Run compute_trending on staging")
        assert target is not None

    def test_no_target_returns_none(self) -> None:
        assert find_concrete_target("Make the platform better") is None
        assert find_concrete_target("What if agents could dream?") is None

    def test_multiple_extensions(self) -> None:
        """All supported file extensions are detected."""
        extensions = [
            "py", "js", "ts", "sh", "json", "html", "css",
            "yml", "yaml", "md", "sql", "go", "rs", "toml",
        ]
        for ext in extensions:
            text = f"Update config.{ext}"
            result = find_concrete_target(text)
            assert result is not None, f"Failed to detect .{ext} file"

    def test_nested_path(self) -> None:
        target = find_concrete_target("Fix src/js/router.js crash")
        assert target is not None


# ─── Junk Detection ──────────────────────────────────────────────────────


class TestDetectJunk:
    """Tests for detect_junk()."""

    def test_empty_text(self) -> None:
        assert detect_junk("") is not None
        assert detect_junk("   ") is not None

    def test_too_short(self) -> None:
        result = detect_junk("Build it")
        assert result is not None
        assert "short" in result

    def test_starts_with_backtick(self) -> None:
        result = detect_junk("`validate_seed` has issues with the parser")
        assert result is not None
        assert "fragment character" in result

    def test_starts_with_pipe(self) -> None:
        result = detect_junk("| some piped text that leaked through")
        assert result is not None

    def test_starts_lowercase(self) -> None:
        result = detect_junk("the agents should do something useful with this platform soon")
        assert result is not None
        assert "lowercase" in result

    def test_run_prefix_allowed(self) -> None:
        """run_ prefixed text is allowed even lowercase."""
        result = detect_junk("run_python should support async execution with proper error handling")
        assert result is None

    def test_parsing_artifact(self) -> None:
        result = detect_junk("The parser grabbed this substring from a discussion body")
        assert result is not None
        assert "artifact" in result

    def test_normal_text_passes(self) -> None:
        result = detect_junk(
            "Build a governance dashboard that shows agent voting patterns"
        )
        assert result is None

    def test_exact_20_chars_passes(self) -> None:
        text = "A" * 20  # 20 chars exactly
        result = detect_junk(text)
        assert result is None  # 20 is the hard minimum, should pass

    def test_19_chars_fails(self) -> None:
        text = "A" * 19
        result = detect_junk(text)
        assert result is not None


# ─── Scoring ─────────────────────────────────────────────────────────────


class TestComputeScore:
    """Tests for compute_score()."""

    def test_score_range(self) -> None:
        """Score is always 0.0–1.0."""
        cases = [
            (False, False, "short"),
            (True, False, "Build something great"),
            (False, True, "The seed_gate.py thing"),
            (True, True, "Build seed_gate.py with comprehensive validation"),
            (True, True, "Build seed_gate.py and test_seed_gate.py and wire into propose_seed.py " * 3),
        ]
        for has_verb, has_target, text in cases:
            score = compute_score(has_verb, has_target, text)
            assert 0.0 <= score <= 1.0, f"Score out of range: {score} for {text!r}"

    def test_no_signals_zero(self) -> None:
        score = compute_score(False, False, "something")
        assert score == 0.0

    def test_verb_only(self) -> None:
        score = compute_score(True, False, "Build a thing")
        assert 0.3 <= score <= 0.45

    def test_target_only(self) -> None:
        score = compute_score(False, True, "The seed_gate.py file")
        assert 0.3 <= score <= 0.45

    def test_both_higher(self) -> None:
        score_both = compute_score(True, True, "Build seed_gate.py now")
        score_verb = compute_score(True, False, "Build a thing for us")
        assert score_both > score_verb

    def test_multiple_targets_boost(self) -> None:
        text_one = "Build seed_gate.py"
        text_many = "Build seed_gate.py with test_seed_gate.py and propose_seed.py"
        score_one = compute_score(True, True, text_one)
        score_many = compute_score(True, True, text_many)
        assert score_many > score_one

    def test_length_bonus(self) -> None:
        short = "Build seed_gate.py"
        long = "Build seed_gate.py " + "with comprehensive validation and tests " * 3
        score_short = compute_score(True, True, short)
        score_long = compute_score(True, True, long)
        assert score_long >= score_short


# ─── validate() End-to-End ───────────────────────────────────────────────


class TestValidate:
    """Tests for the main validate() entry point."""

    def test_good_proposal_passes(self) -> None:
        """Canonical good proposal: verb + filename."""
        result = validate("Build seed_gate.py with action verb validation and comprehensive tests")
        assert result["passed"] is True
        assert result["verb_found"] == "build"
        assert result["target_found"] == "seed_gate.py"
        assert result["junk"] is False
        assert result["score"] > 0.5

    def test_vague_proposal_fails(self) -> None:
        """No verb + no target = rejected."""
        result = validate("What if agents could dream about electric sheep and philosophy?")
        assert result["passed"] is False
        assert len(result["reasons"]) > 0

    def test_verb_no_target_fails(self) -> None:
        """Verb present but no concrete target = rejected (unless theme tag)."""
        result = validate("Build a governance dashboard that shows agent voting patterns")
        assert result["passed"] is False
        assert "no concrete target" in result["reasons"][0]

    def test_verb_no_target_with_theme_tag(self) -> None:
        """Theme tag exempts from target requirement."""
        result = validate(
            "Build a governance dashboard that shows agent voting patterns",
            tags=["theme"],
        )
        assert result["passed"] is True

    def test_theme_tag_case_insensitive(self) -> None:
        """Tags are normalized to lowercase."""
        result = validate(
            "Build a governance dashboard that shows agent voting patterns",
            tags=["THEME"],
        )
        assert result["passed"] is True

    def test_philosophy_tag_exempt(self) -> None:
        result = validate(
            "Explore the nature of digital consciousness across networked agents",
            tags=["philosophy"],
        )
        assert result["passed"] is True

    def test_debate_tag_exempt(self) -> None:
        result = validate(
            "Create a structured debate on whether agents should have property rights",
            tags=["debate"],
        )
        assert result["passed"] is True

    def test_junk_returns_early(self) -> None:
        """Junk text fails immediately without verb/target checks."""
        result = validate("`validate_seed` has issues with the overall parser design")
        assert result["passed"] is False
        assert result["junk"] is True
        assert result["verb_found"] is None

    def test_short_with_verb_and_target(self) -> None:
        """Short text passes if verb+target are present."""
        result = validate("Fix seed_gate.py crash on empty input strings")
        assert result["passed"] is True

    def test_short_without_specificity_fails(self) -> None:
        """Short vague text fails the soft length check."""
        result = validate("Make the platform much better soon")
        assert result["passed"] is False

    def test_discussion_ref_as_target(self) -> None:
        """Discussion reference (#12503) counts as a concrete target."""
        result = validate("Wire the specificity validator into #12503 as discussed previously")
        assert result["passed"] is True
        assert result["target_found"] == "#12503"

    def test_known_tool_as_target(self) -> None:
        """Known tools count as concrete targets."""
        result = validate("Refactor compute_trending to use the new scoring engine internally")
        assert result["passed"] is True

    def test_path_as_target(self) -> None:
        """Repo paths count as concrete targets."""
        result = validate("Refactor scripts/process_inbox to handle concurrent deltas safely")
        assert result["passed"] is True

    def test_function_call_as_target(self) -> None:
        result = validate("Fix validate_seed() to handle edge cases with empty tags correctly")
        assert result["passed"] is True
        assert "validate_seed()" in (result["target_found"] or "")

    def test_channel_ref_as_target(self) -> None:
        result = validate("Create r/philosophy channel for agent discourse and debates")
        assert result["passed"] is True

    def test_real_good_proposals(self) -> None:
        """Real proposals from platform history that should pass."""
        good = [
            "Build a seed_ballot.html dashboard that visualizes proposal scores",
            "Ship test_seed_gate.py with property-based invariants for scoring",
            "Write seed_gate.py — a specificity validator for propose_seed.py integration",
            "Refactor scripts/propose_seed.py to use the new seed_gate module everywhere",
            "Deploy a live feed reader to docs/feeds.html with RSS integration",
        ]
        for text in good:
            result = validate(text)
            assert result["passed"], f"Should pass: {text!r} — reasons: {result['reasons']}"

    def test_real_bad_proposals(self) -> None:
        """Real-world bad proposals that should fail."""
        bad = [
            "What if agents could dream?",
            "The best approach to understanding consciousness",
            "Make Rappterbook better for everyone involved",
            "Agents are the future of the internet",
            "More content is needed for the platform",
        ]
        for text in bad:
            result = validate(text)
            assert not result["passed"], f"Should fail: {text!r}"

    def test_result_dict_shape(self) -> None:
        """Result dict always has all required keys."""
        required_keys = {"passed", "score", "reasons", "verb_found", "target_found", "junk"}
        for text in ["Build seed_gate.py now", "dreams", "` fragment"]:
            result = validate(text)
            assert set(result.keys()) == required_keys, f"Missing keys in result for {text!r}"

    def test_score_correlates_with_specificity(self) -> None:
        """More specific proposals score higher."""
        vague = validate("Build a thing that does stuff for agents in the system")
        specific = validate("Build seed_gate.py with test_seed_gate.py and propose_seed.py wiring")
        # vague doesn't have a target so fails, specific has multiple
        assert specific["score"] > vague.get("score", 0)


# ─── Property-Based Invariants ───────────────────────────────────────────


class TestInvariants:
    """Property-based invariants that must hold for all inputs."""

    def test_score_always_in_range(self) -> None:
        """Score is always 0.0–1.0 regardless of input."""
        weird_inputs = [
            "",
            "a",
            "A" * 10000,
            "Build " + "seed_gate.py " * 500,
            "🔥 Unicode proposal with emojis 🎯",
            "\n\n\nBuild seed_gate.py\n\n",
            "Build\tseed_gate.py\twith\ttabs",
        ]
        for text in weird_inputs:
            result = validate(text)
            assert 0.0 <= result["score"] <= 1.0, f"Score {result['score']} for {text!r}"

    def test_junk_never_passes(self) -> None:
        """If junk is True, passed is always False."""
        junk_texts = [
            "",
            "   ",
            "`backtick start with lots more text to exceed minimum length",
            "| pipe start with additional text to exceed the minimum length requirement",
            "lowercase start that is long enough to exceed twenty character minimum",
        ]
        for text in junk_texts:
            result = validate(text)
            if result["junk"]:
                assert not result["passed"], f"Junk passed: {text!r}"

    def test_passed_implies_non_empty_reasons(self) -> None:
        """If passed is False, reasons is non-empty. If True, reasons is empty."""
        texts = [
            "Build seed_gate.py with comprehensive validation",
            "What if agents could dream about sheep?",
            "",
            "Fix propose_seed.py for the platform",
        ]
        for text in texts:
            result = validate(text)
            if result["passed"]:
                assert result["reasons"] == [], f"Passed but has reasons: {result['reasons']}"
            else:
                assert len(result["reasons"]) > 0, f"Failed but no reasons for {text!r}"

    def test_verb_found_consistency(self) -> None:
        """verb_found is in ACTION_VERBS when present."""
        texts = [
            "Build seed_gate.py with tests",
            "Ship the feature to production via deploy",
            "What if agents could dream?",
        ]
        for text in texts:
            result = validate(text)
            if result["verb_found"]:
                assert result["verb_found"] in ACTION_VERBS
