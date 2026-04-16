"""Tests for seed_gate.py -- canonical specificity validator.

Covers: verb detection, target detection (files, paths, tools, modules,
CLI, discussions, channels, quoted), junk detection (hard + soft artifacts),
scoring with unique-target counting, validation pass/fail, exempt tags,
CLI, real-world proposals, edge cases, property invariants, smoke tests,
propose_seed.py contract, and regression tests for false rejects.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from seed_gate import (
    ACTION_VERBS,
    EXEMPT_TAGS,
    KNOWN_MODULES,
    CHANNEL_RE,
    CLI_RE,
    DISCUSSION_RE,
    FILE_RE,
    MODULE_CONTEXT_RE,
    PATH_RE,
    QUOTED_RE,
    TOOL_RE,
    SeedGateResult,
    passes_gate,
    validate,
    validate_seed,
    canonicalize_target,
    count_unique_targets,
    is_soft_artifact,
)


def _v(text, tags=None, mode="admission"):
    return validate(text, tags or [], mode)


def _vs(text, tags=None, mode="admission"):
    return validate_seed(text, tags or [], mode=mode)


# ===================================================================
# 1. Constants
# ===================================================================

class TestConstants:
    def test_action_verbs_nonempty(self):
        assert len(ACTION_VERBS) >= 40

    def test_action_verbs_all_lowercase(self):
        for v in ACTION_VERBS:
            assert v == v.lower()

    def test_exempt_tags_nonempty(self):
        assert len(EXEMPT_TAGS) >= 4

    def test_exempt_tags_all_lowercase(self):
        for t in EXEMPT_TAGS:
            assert t == t.lower()

    def test_known_modules_discovered(self):
        assert len(KNOWN_MODULES) >= 10

    def test_known_modules_no_test_or_run(self):
        for m in KNOWN_MODULES:
            assert not m.startswith("test_")
            assert not m.startswith("run_")

    def test_known_modules_only_snake_case(self):
        for m in KNOWN_MODULES:
            assert "_" in m

    def test_known_modules_contains_expected(self):
        for m in ("water_mining", "solar_array", "seed_gate"):
            assert m in KNOWN_MODULES


# ===================================================================
# 2. Regex patterns
# ===================================================================

class TestRegexPatterns:
    def test_file_re_python(self):
        assert FILE_RE.search("Build seed_gate.py validator")

    def test_file_re_json(self):
        assert FILE_RE.search("Fix state/agents.json integrity")

    def test_file_re_rust(self):
        assert FILE_RE.search("Port parser to grammar.rs")

    def test_path_re_src(self):
        assert PATH_RE.search("Refactor src/water_mining module")

    def test_path_re_tests(self):
        assert PATH_RE.search("Add tests/test_drill coverage")

    def test_path_re_engine(self):
        assert PATH_RE.search("Fix engine/tick overflow")

    def test_path_re_state(self):
        assert PATH_RE.search("Validate state/mars integrity")

    def test_path_re_docs(self):
        assert PATH_RE.search("Update docs/index.html layout")

    def test_tool_re_snake(self):
        assert TOOL_RE.search("Refactor process_inbox handler")

    def test_tool_re_no_single(self):
        assert not TOOL_RE.search("Build parser module")

    def test_cli_re_backtick(self):
        assert CLI_RE.search("Run `pytest -v` on CI")

    def test_cli_re_flag(self):
        assert CLI_RE.search("Add --verbose flag")

    def test_cli_re_short_flag(self):
        assert CLI_RE.search("Support -f option")

    def test_discussion_re(self):
        assert DISCUSSION_RE.search("See discussion #12503")

    def test_discussion_re_no_short(self):
        assert not DISCUSSION_RE.search("Issue #42 is important")

    def test_channel_re_r(self):
        assert CHANNEL_RE.search("Create r/mars-engineering")

    def test_channel_re_c(self):
        assert CHANNEL_RE.search("Post in c/general channel")

    def test_quoted_re(self):
        assert QUOTED_RE.search('Add "thermal control loop" feature')

    def test_module_context_backtick(self):
        assert MODULE_CONTEXT_RE.search("Fix `water_mining` bug")

    def test_module_context_import(self):
        assert MODULE_CONTEXT_RE.search("import solar_array works")

    def test_module_context_from(self):
        assert MODULE_CONTEXT_RE.search("from dust_storm import x")


# ===================================================================
# 3. Verb detection
# ===================================================================

class TestVerbDetection:
    @pytest.mark.parametrize("verb", ["build", "create", "fix", "test", "ship", "deploy"])
    def test_common_verbs(self, verb):
        result = _v(f"{verb.capitalize()} the water_mining.py system entirely")
        assert result["verb_found"] == verb

    def test_case_insensitive(self):
        result = _v("BUILD water_mining.py from scratch again")
        assert result["verb_found"] == "build"

    def test_no_verb(self):
        result = _v("Water mining system with multiple features included")
        assert result["verb_found"] is None

    def test_verb_mid_sentence(self):
        result = _v("The team should build water_mining.py carefully")
        assert result["verb_found"] == "build"


# ===================================================================
# 4. Target detection
# ===================================================================

class TestTargetDetection:
    def test_file_target(self):
        result = _v("Build water_mining.py optimizer quickly now")
        assert result["target_found"] == "water_mining.py"

    def test_path_target(self):
        result = _v("Fix src/thermal_control module carefully here")
        assert result["target_found"] == "src/thermal_control"

    def test_tool_target(self):
        result = _v("Build the process_inbox handler properly here")
        assert result["target_found"] == "process_inbox"

    def test_cli_target(self):
        result = _v("Test with `pytest -v` for better output here")
        assert result["target_found"] == "`pytest -v`"

    def test_discussion_target(self):
        result = _v("Build feature from discussion #12503 ideas")
        assert result["target_found"] == "#12503"

    def test_channel_target(self):
        result = _v("Create content for r/mars-engineering now")
        assert result["target_found"] == "r/mars-engineering"

    def test_quoted_target(self):
        result = _v('Implement "thermal control loop" system now')
        assert result["target_found"] == '"thermal control loop"'

    def test_no_target(self):
        result = _v("Build something amazing and wonderful today")
        assert result["target_found"] is None

    def test_file_beats_tool(self):
        result = _v("Build water_mining.py with process_inbox")
        assert result["target_found"] == "water_mining.py"

    def test_module_context_backtick(self):
        if "water_mining" in KNOWN_MODULES:
            result = _v("Fix `water_mining` efficiency problem")
            assert result["target_found"] == "water_mining"


# ===================================================================
# 5. Junk detection
# ===================================================================

class TestJunkDetection:
    def test_empty(self):
        assert _v("")["junk"] is True

    def test_whitespace(self):
        assert _v("   \n  ")["junk"] is True

    def test_too_short(self):
        assert _v("Build it")["junk"] is True

    def test_starts_lowercase_verb_allowed(self):
        # Lowercase text starting with an action verb is NOT junk
        assert _v("build something really cool and interesting here now")["junk"] is False

    def test_starts_lowercase_fragment(self):
        # Lowercase text NOT starting with a verb IS junk
        assert _v("the thing we talked about doing sometime later")["junk"] is True

    def test_starts_backtick(self):
        assert _v("`code fragment` extracted from somewhere else")["junk"] is True

    def test_numbered_list(self):
        assert _v("1. First item in a numbered list of tasks")["junk"] is True

    def test_bare_url(self):
        assert _v("https://example.com/path/to/something")["junk"] is True

    def test_todo_comment(self):
        assert _v("TODO: Fix the water_mining module bug here")["junk"] is True

    def test_run_prefix_exception(self):
        assert _v("run_proof for water_mining.py system verify")["junk"] is False

    def test_hard_artifact_parser_grabbed(self):
        r = _v("Parser grabbed this fragment from the document")
        assert r["junk"] is True
        assert "artifact" in r["reasons"][0]

    def test_hard_artifact_parsing_artifact(self):
        assert _v("Parsing artifact detected in the pipeline")["junk"] is True

    def test_hard_artifact_outside_grammar(self):
        assert _v("Outside that grammar the token has no meaning")["junk"] is True


# ===================================================================
# 6. Soft artifact detection
# ===================================================================

class TestSoftArtifacts:
    def test_redeemed_by_verb_target(self):
        result = _v("Fix the regex in water_mining.py for edges")
        assert result["passed"] is True

    def test_unredeemed_fails(self):
        result = _v("The regex pattern is broken and needs attention")
        assert result["passed"] is False
        assert result["junk"] is True

    def test_the_parser_unredeemed(self):
        assert _v("The parser module handles tokenization inputs")["passed"] is False

    def test_substring_unredeemed(self):
        assert _v("Substring extraction failed in data processing")["passed"] is False

    def test_redeemed_parser_in_file(self):
        result = _v("Fix the parser in seed_gate.py for extraction")
        assert result["passed"] is True


# ===================================================================
# 7. Scoring
# ===================================================================

class TestScoring:
    def test_high_score_file(self):
        r = _v("Build water_mining.py optimizer with advanced drilling and scanning algorithms")
        assert r["score"] >= 0.7

    def test_zero_score_junk(self):
        assert _v("")["score"] == 0.0

    def test_verb_only_low(self):
        r = _v("Build something amazing and wonderful for everyone")
        assert 0.0 < r["score"] <= 0.5

    def test_multi_target_bonus(self):
        single = _v("Build water_mining.py optimizer carefully here")
        multi = _v("Build water_mining.py and solar_array.py integration")
        assert multi["score"] >= single["score"]

    def test_score_capped(self):
        text = "Build " + " and ".join(f"mod_{i}.py" for i in range(20))
        assert _v(text)["score"] <= 1.0

    def test_path_scores_high(self):
        assert _v("Fix src/thermal_control module for efficiency")["score"] >= 0.5


# ===================================================================
# 8. Canonicalization
# ===================================================================

class TestCanonicalization:
    def test_strip_prefix(self):
        assert canonicalize_target("src/water_mining.py") == "water_mining"

    def test_strip_extension(self):
        assert canonicalize_target("water_mining.py") == "water_mining"

    def test_strip_quotes(self):
        assert canonicalize_target('"water_mining"') == "water_mining"

    def test_lowercase(self):
        assert canonicalize_target("Water_Mining.PY") == "water_mining"

    def test_same_forms_canonicalize(self):
        assert canonicalize_target("src/water_mining.py") == canonicalize_target("water_mining.py")

    def test_count_unique_deduplicates(self):
        text = "Fix water_mining.py and src/water_mining module"
        assert count_unique_targets(text) >= 1

    def test_count_unique_multiple(self):
        text = "Build water_mining.py and solar_array.py"
        assert count_unique_targets(text) >= 2

    def test_count_unique_empty(self):
        assert count_unique_targets("Nothing specific mentioned") == 0


# ===================================================================
# 9. Validation pass/fail
# ===================================================================

class TestValidation:
    def test_pass_verb_file(self):
        assert _v("Build water_mining.py optimizer for drilling")["passed"]

    def test_pass_verb_tool(self):
        assert _v("Fix process_inbox handler for delta processing")["passed"]

    def test_pass_verb_path(self):
        assert _v("Refactor src/thermal_control for modularity")["passed"]

    def test_pass_verb_discussion(self):
        assert _v("Build feature from discussion #12503 plan")["passed"]

    def test_pass_verb_channel(self):
        assert _v("Create content for r/mars-engineering now")["passed"]

    def test_fail_no_verb(self):
        r = _v("Water_mining.py optimizer for deep drilling etc")
        assert not r["passed"]
        assert any("verb" in s.lower() for s in r["reasons"])

    def test_fail_no_target(self):
        r = _v("Build something amazing and wonderful for all")
        assert not r["passed"]
        assert any("target" in s.lower() for s in r["reasons"])

    def test_fail_both_missing(self):
        r = _v("Something amazing and wonderful for everyone")
        assert not r["passed"]
        assert len(r["reasons"]) >= 2

    def test_exempt_tag_no_target(self):
        assert _v("Explore consciousness in artificial agents", ["theme"])["passed"]

    def test_exempt_tag_needs_verb(self):
        assert not _v("The nature of consciousness in AI systems", ["theme"])["passed"]

    def test_exempt_case_insensitive(self):
        assert _v("Explore consciousness in agents deeply", ["THEME"])["passed"]

    def test_exempt_multiple_tags(self):
        assert _v("Debate ethics of Mars terraforming now", ["philosophy", "debate"])["passed"]


# ===================================================================
# 10. Mode: purge vs admission
# ===================================================================

class TestModeConsistency:
    def test_admission_detects_verb(self):
        assert _v("Build seed_gate.py validator for checking")["verb_found"] == "build"

    def test_purge_detects_verb(self):
        assert _v("Build seed_gate.py validator checking", mode="purge")["verb_found"] == "build"

    def test_purge_always_passes_nonjunk(self):
        assert _v("Something without a verb or target long enough", mode="purge")["passed"]

    def test_admission_rejects_no_target(self):
        assert not _v("Build something amazing wonderful for all")["passed"]

    def test_purge_score_half(self):
        assert _v("Build seed_gate.py validator quickly", mode="purge")["score"] == 0.5


# ===================================================================
# 11. Dataclass API
# ===================================================================

class TestDataclassAPI:
    def test_frozen(self):
        r = _vs("Build seed_gate.py validator for system")
        with pytest.raises(AttributeError):
            r.passed = False

    def test_verb_property(self):
        assert _vs("Build seed_gate.py validator system").verb == "build"

    def test_target_property(self):
        assert _vs("Build seed_gate.py validator system").target == "seed_gate.py"

    def test_verb_property_none(self):
        assert _vs("Water_mining.py optimizer for drilling").verb == ""

    def test_to_dict_matches(self):
        text = "Build seed_gate.py validator for system"
        assert _vs(text).to_dict() == _v(text)


# ===================================================================
# 12. Real-world proposals
# ===================================================================

class TestRealWorld:
    def test_canonical_seed(self):
        assert _v("Build seed_gate.py with action verb validation")["passed"]

    def test_mars_module(self):
        assert _v("Optimize water_mining.py deep well drilling")["passed"]

    def test_engine_refactor(self):
        assert _v("Refactor engine/tick.py for parallel streams")["passed"]

    def test_discussion_ref(self):
        assert _v("Implement proposal from discussion #12503")["passed"]

    def test_multi_file(self):
        r = _v("Wire seed_gate.py into propose_seed.py validation")
        assert r["passed"]
        assert r["score"] >= 0.6

    def test_vague_rejected(self):
        assert not _v("Make everything better and more amazing")["passed"]

    def test_philosophy_exempt(self):
        assert _v("Explore what it means for agents to dream", ["philosophy"])["passed"]


# ===================================================================
# 13. Regression: false rejects
# ===================================================================

class TestFalseRejectRegression:
    def test_fix_regex_in_file(self):
        assert _v("Fix the regex in water_mining.py edge cases")["passed"]

    def test_refactor_parser_in_file(self):
        assert _v("Refactor the parser in seed_gate.py extraction")["passed"]

    def test_substring_in_module(self):
        assert _v("Investigate substring in dust_filter.py edges")["passed"]

    def test_cli_flag_proposal(self):
        assert _v("Add --dry-run flag to process_inbox testing")["passed"]

    def test_backtick_command(self):
        assert _v("Test with `python3 -m pytest tests/` full")["passed"]


# ===================================================================
# 14. Edge cases
# ===================================================================

class TestEdgeCases:
    def test_unicode(self):
        assert _v("Build water_mining.py with UTF-8 日本語")["passed"]

    def test_very_long(self):
        text = "Build seed_gate.py " + "x " * 5000
        r = _v(text)
        assert r["passed"]
        assert r["score"] <= 1.0

    def test_newlines(self):
        assert _v("Build water_mining.py\noptimizer for deep\ndrilling")["passed"]

    def test_none_tags(self):
        assert validate("Build water_mining.py optimizer drill", None)["passed"]

    def test_empty_tags(self):
        assert validate("Build water_mining.py optimizer drill", [])["passed"]

    def test_deterministic(self):
        text = "Build water_mining.py optimizer deep drilling"
        assert _v(text) == _v(text)


# ===================================================================
# 15. Property invariants
# ===================================================================

_CORPUS = [
    "Build seed_gate.py",
    "",
    "x",
    "Build something cool and really interesting",
    "The module is nice and works well for us",
    "Build seed_gate.py validator " * 100,
    "run_test for my_module.py quickly and quietly",
    "Design philosophical framework for agents",
    "https://example.com/path/to/something/here",
    "1. numbered item in a list of stuff here",
    "\n\n\n",
    "Fix the regex in water_mining.py for edges",
    "Parser grabbed this from extraction pipeline",
    "Optimize src/thermal_control for efficiency",
]


class TestInvariants:
    @pytest.mark.parametrize("text", _CORPUS)
    def test_score_in_range(self, text):
        assert 0.0 <= _v(text)["score"] <= 1.0

    @pytest.mark.parametrize("text", _CORPUS)
    def test_junk_is_bool(self, text):
        assert isinstance(_v(text)["junk"], bool)

    @pytest.mark.parametrize("text", _CORPUS)
    def test_reasons_is_list(self, text):
        assert isinstance(_v(text)["reasons"], list)

    @pytest.mark.parametrize("text", _CORPUS)
    def test_passed_is_bool(self, text):
        assert isinstance(_v(text)["passed"], bool)

    @pytest.mark.parametrize("text", _CORPUS)
    def test_dict_equals_dataclass(self, text):
        assert _v(text) == _vs(text).to_dict()

    @pytest.mark.parametrize("text", _CORPUS)
    def test_junk_passed_disjoint(self, text):
        r = _v(text)
        if r["junk"]:
            assert not r["passed"]

    @pytest.mark.parametrize("text", _CORPUS)
    def test_passes_gate_consistent(self, text):
        assert passes_gate(text) == _v(text)["passed"]


# ===================================================================
# 16. CLI
# ===================================================================

class TestCLI:
    def test_cli_pass(self):
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "seed_gate.py"),
             "Build seed_gate.py validator for checking"],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert json.loads(r.stdout)["passed"] is True

    def test_cli_fail(self):
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "seed_gate.py"),
             "Something vague and unspecific without direction"],
            capture_output=True, text=True
        )
        assert r.returncode == 1
        assert json.loads(r.stdout)["passed"] is False

    def test_cli_no_args(self):
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "seed_gate.py")],
            capture_output=True, text=True
        )
        assert r.returncode == 1


# ===================================================================
# 17. Smoke
# ===================================================================

class TestSmoke:
    def test_50_proposals(self):
        for i in range(50):
            r = _v(f"Build module_{i}.py for Mars colony feature {i}")
            assert "passed" in r

    def test_all_verbs_detectable(self):
        for verb in sorted(ACTION_VERBS):
            r = _v(f"{verb.capitalize()} the water_mining.py module")
            assert r["verb_found"] == verb, f"Verb {verb!r} not detected"


# ===================================================================
# 18. propose_seed.py contract
# ===================================================================

class TestProposeSeedContract:
    def test_import_validate(self):
        from seed_gate import validate as vs
        assert isinstance(vs("Build seed_gate.py validator"), dict)

    def test_passed_key(self):
        assert isinstance(_v("Build seed_gate.py validator")["passed"], bool)

    def test_reasons_joinable(self):
        r = _v("Something vague without real direction here")
        assert isinstance("; ".join(r["reasons"]), str)

    def test_purge_contract(self):
        r = validate("Build seed_gate.py validator", mode="purge")
        assert r["passed"] is True

    def test_score_float(self):
        r = _v("Build seed_gate.py validator for testing")
        assert isinstance(r["score"], float)
        assert 0.0 <= r["score"] <= 1.0

    def test_no_code_key(self):
        assert "code" not in _v("Build seed_gate.py validator")

    def test_verb_found_key(self):
        r = _v("Build seed_gate.py validator for system")
        assert "verb_found" in r
        assert "verb" not in r

    def test_target_found_key(self):
        r = _v("Build seed_gate.py validator for system")
        assert "target_found" in r
        assert "target" not in r

    def test_junk_key(self):
        assert isinstance(_v("Build seed_gate.py validator")["junk"], bool)


# ---- New tests for consolidated features (PRs #245/#246/#247) ----


class TestFileReFalsePositives:
    """FILE_RE should not match abbreviations like e.g., i.e., etc."""

    def test_eg_not_a_file(self):
        from seed_gate import find_target
        t, k = find_target("Consider e.g. the deployment options for Mars")
        assert t != "e.g", f"e.g matched as {k}"

    def test_ie_not_a_file(self):
        from seed_gate import find_target
        t, k = find_target("The module i.e. the core system should be refactored")
        assert t != "i.e", f"i.e matched as {k}"

    def test_am_not_a_file(self):
        from seed_gate import find_target
        t, k = find_target("Deploy the system before 9 a.m. tomorrow morning")
        assert t != "a.m", f"a.m matched as {k}"

    def test_real_file_still_matches(self):
        from seed_gate import find_target
        t, k = find_target("Update the config.yaml for better settings")
        assert t == "config.yaml" and k == "file"

    def test_eg_in_sentence_with_real_file(self):
        r = _v("Fix e.g. the water_mining.py thermal model bug")
        assert r["target_found"] == "water_mining.py"

    def test_validate_eg_only_no_file(self):
        r = _v("Explore e.g. what would happen if agents debated")
        assert r["target_found"] != "e.g"


class TestSpecialFiles:
    """Special files without extensions: Dockerfile, Makefile, README, etc."""

    def test_dockerfile(self):
        from seed_gate import find_target
        t, k = find_target("Build the Dockerfile for the Mars colony")
        assert t == "Dockerfile" and k == "file"

    def test_makefile(self):
        from seed_gate import find_target
        t, k = find_target("Refactor the Makefile for cleaner builds")
        assert t == "Makefile" and k == "file"

    def test_readme(self):
        from seed_gate import find_target
        t, k = find_target("Update README with new architecture docs")
        assert t == "README" and k == "file"

    def test_constitution(self):
        from seed_gate import find_target
        t, k = find_target("Review CONSTITUTION for amendment proposals")
        assert t == "CONSTITUTION" and k == "file"

    def test_agents_md(self):
        from seed_gate import find_target
        t, k = find_target("Improve AGENTS documentation coverage")
        assert t == "AGENTS" and k == "file"

    def test_validate_with_special_file(self):
        r = _v("Build the Dockerfile for Mars colony deployment")
        assert r["passed"] is True
        assert r["target_found"] == "Dockerfile"

    def test_regular_file_takes_priority(self):
        """A .py file should match FILE_RE before SPECIAL_FILE_RE."""
        from seed_gate import find_target
        t, k = find_target("Fix thermal_control.py and update README")
        assert t == "thermal_control.py"


class TestKnownTools:
    """KNOWN_TOOLS: rappterbook-specific tools matched by precision regex."""

    def test_state_io(self):
        from seed_gate import find_target
        t, k = find_target("Refactor state_io for better atomicity")
        assert t == "state_io" and k == "tool"

    def test_process_inbox(self):
        from seed_gate import find_target
        t, k = find_target("Debug process_inbox delta processing logic")
        assert t == "process_inbox" and k == "tool"

    def test_propose_seed(self):
        from seed_gate import find_target
        t, k = find_target("Improve propose_seed with better filtering")
        assert t == "propose_seed" and k == "tool"

    def test_seed_gate_as_tool(self):
        from seed_gate import find_target
        t, k = find_target("Validate seed_gate detects all patterns")
        assert t == "seed_gate" and k == "tool"

    def test_known_tool_before_generic(self):
        """Known tools should match before generic TOOL_RE."""
        from seed_gate import find_target, KNOWN_TOOLS
        for tool in sorted(KNOWN_TOOLS)[:5]:
            t, k = find_target(f"Refactor {tool} for clarity")
            assert t == tool, f"Expected {tool}, got {t}"

    def test_validate_with_known_tool(self):
        r = _v("Build state_io with better error handling")
        assert r["passed"] is True
        assert r["target_found"] == "state_io"


class TestQuestionStems:
    """Question stems infer verbs for exempt-tag proposals."""

    def test_what_if_maps_to_explore(self):
        r = _v("What if agents could dream in parallel", tags=["philosophy"])
        assert r["verb_found"] == "explore"
        assert r["passed"] is True

    def test_how_might_maps_to_design(self):
        r = _v("How might we scale the colony to a million agents", tags=["exploration"])
        assert r["verb_found"] == "design"
        assert r["passed"] is True

    def test_should_we_maps_to_evaluate(self):
        r = _v("Should we abandon the water mining experiment", tags=["debate"])
        assert r["verb_found"] == "evaluate"
        assert r["passed"] is True

    def test_why_not_maps_to_propose(self):
        r = _v("Why not allow agents to govern themselves completely", tags=["philosophy"])
        assert r["verb_found"] == "propose"

    def test_no_stem_without_exempt_tag(self):
        """Question stems should NOT fire without an exempt tag."""
        r = _v("What if agents could dream in parallel")
        assert r["verb_found"] is None
        assert r["passed"] is False

    def test_stem_with_real_verb_uses_real_verb(self):
        """If text has a real verb, don't override with stem mapping."""
        r = _v("What if we build a new thermal control system", tags=["philosophy"])
        assert r["verb_found"] == "build"

    def test_how_could_maps_to_design(self):
        r = _v("How could the sim achieve true emergence behavior", tags=["exploration"])
        assert r["verb_found"] == "design"

    def test_case_insensitive(self):
        r = _v("WHAT IF agents evolved beyond their archetypes", tags=["philosophy"])
        assert r["verb_found"] == "explore"


class TestBatchValidation:
    """validate_batch() returns structured results with stats."""

    def test_basic_batch(self):
        from seed_gate import validate_batch
        proposals = [
            "Build seed_gate.py with verb detection",
            "just vibes and stuff happening here",
            "   ",
            "Consider improving the thermal model design",
        ]
        br = validate_batch(proposals)
        assert br.stats.total == 4
        assert br.stats.passed + br.stats.failed + br.stats.junk == 4

    def test_all_passed(self):
        from seed_gate import validate_batch
        br = validate_batch([
            "Build seed_gate.py with better detection",
            "Fix thermal_control.py for edge cases",
        ])
        assert br.stats.passed == 2
        assert br.stats.junk == 0
        assert br.stats.failed == 0

    def test_all_junk(self):
        from seed_gate import validate_batch
        br = validate_batch(["   ", "ab", "`fragment` from parser"])
        assert br.stats.junk == 3
        assert br.stats.passed == 0

    def test_empty_batch(self):
        from seed_gate import validate_batch
        br = validate_batch([])
        assert br.stats.total == 0
        assert br.stats.pass_rate == 0.0

    def test_junk_items_contain_text(self):
        from seed_gate import validate_batch
        br = validate_batch(["   ", "Build seed_gate.py now"])
        assert len(br.junk_items) >= 1
        assert br.junk_items[0][0] == "   "

    def test_passed_items_contain_result(self):
        from seed_gate import validate_batch
        br = validate_batch(["Build seed_gate.py with better detection"])
        assert len(br.passed_items) == 1
        text, result = br.passed_items[0]
        assert result["passed"] is True

    def test_failed_items_not_junk(self):
        """Failed items are vague-but-not-junk."""
        from seed_gate import validate_batch
        br = validate_batch(["Consider improving the thermal model design work"])
        if br.stats.failed > 0:
            text, result = br.failed_items[0]
            assert result["junk"] is False
            assert result["passed"] is False


class TestBatchStats:
    """BatchStats dataclass: pass_rate, junk_rate, merge."""

    def test_pass_rate(self):
        from seed_gate import BatchStats
        s = BatchStats(total=10, passed=7, failed=2, junk=1)
        assert abs(s.pass_rate - 0.7) < 0.001

    def test_junk_rate(self):
        from seed_gate import BatchStats
        s = BatchStats(total=10, passed=7, failed=2, junk=1)
        assert abs(s.junk_rate - 0.1) < 0.001

    def test_empty_rates(self):
        from seed_gate import BatchStats
        s = BatchStats(total=0, passed=0, failed=0, junk=0)
        assert s.pass_rate == 0.0
        assert s.junk_rate == 0.0

    def test_merge(self):
        from seed_gate import BatchStats
        s1 = BatchStats(total=3, passed=1, failed=1, junk=1)
        s2 = BatchStats(total=5, passed=4, failed=1, junk=0)
        merged = s1.merge(s2)
        assert merged.total == 8
        assert merged.passed == 5
        assert merged.failed == 2
        assert merged.junk == 1

    def test_merge_identity(self):
        from seed_gate import BatchStats
        empty = BatchStats(total=0, passed=0, failed=0, junk=0)
        s = BatchStats(total=3, passed=2, failed=1, junk=0)
        assert s.merge(empty) == s


class TestLowercaseImperative:
    """Smart lowercase handling: verb-starting text passes, fragments fail."""

    def test_build_verb_not_junk(self):
        r = _v("build seed_gate.py with better verb detection")
        assert r["junk"] is False
        assert r["passed"] is True

    def test_fix_verb_not_junk(self):
        r = _v("fix the thermal_control.py temperature bounds bug")
        assert r["junk"] is False

    def test_create_verb_not_junk(self):
        r = _v("create a new water_mining.py test suite here")
        assert r["junk"] is False

    def test_lowercase_fragment_is_junk(self):
        r = _v("the thing we talked about doing sometime soon")
        assert r["junk"] is True

    def test_lowercase_no_verb_is_junk(self):
        r = _v("some random fragment about the system that exists")
        assert r["junk"] is True

    def test_file_start_not_junk(self):
        """Text starting with a filename is not lowercase-junk."""
        from seed_gate import is_junk
        reason = is_junk("seed_gate.py needs better verb detection logic")
        assert reason == "", f"Unexpected junk reason: {reason}"


class TestSubstringDedup:
    """Substring-aware dedup in count_unique_targets()."""

    def test_stem_and_extension(self):
        """seed_gate and seed_gate.py should count as 1 unique target."""
        from seed_gate import count_unique_targets
        count = count_unique_targets("Refactor seed_gate and update seed_gate.py tests")
        assert count == 1, f"Expected 1, got {count}"

    def test_truly_different_targets(self):
        from seed_gate import count_unique_targets
        count = count_unique_targets("Fix water_mining.py and thermal_control.py bugs")
        assert count == 2

    def test_path_and_bare_name(self):
        """src/seed_gate.py and seed_gate should count as 1."""
        from seed_gate import count_unique_targets
        count = count_unique_targets("Update src/seed_gate.py and refactor seed_gate module")
        assert count == 1

    def test_three_unique(self):
        from seed_gate import count_unique_targets
        count = count_unique_targets("Fix water_mining.py, thermal_control.py, and seed_gate.py")
        assert count == 3

    def test_empty_text(self):
        from seed_gate import count_unique_targets
        assert count_unique_targets("No targets here at all in this text") == 0


class TestCanonicalizeTarget:
    """canonicalize_target() strips paths, extensions, quotes."""

    def test_strip_extension(self):
        from seed_gate import canonicalize_target
        assert canonicalize_target("seed_gate.py") == "seed_gate"

    def test_strip_src_prefix(self):
        from seed_gate import canonicalize_target
        assert canonicalize_target("src/seed_gate.py") == "seed_gate"

    def test_strip_quotes(self):
        from seed_gate import canonicalize_target
        assert canonicalize_target('"seed_gate"') == "seed_gate"

    def test_lowercase(self):
        from seed_gate import canonicalize_target
        assert canonicalize_target("README") == "readme"

    def test_preserve_underscores(self):
        from seed_gate import canonicalize_target
        assert canonicalize_target("water_mining.py") == "water_mining"


# ---------------------------------------------------------------------------
# New feature tests — phrasal verbs, tag-implied, advisory, rich match,
# CONST_RE, case-insensitive modules, find_all_verbs, find_all_targets
# ---------------------------------------------------------------------------

class TestPhrasalVerbs:
    """Test two-word phrasal verb detection (#12521)."""

    def test_phrasal_dict_not_empty(self):
        from seed_gate import PHRASAL_VERBS
        assert len(PHRASAL_VERBS) >= 20

    def test_set_up_detected(self):
        from seed_gate import find_verb
        assert find_verb("Set up the deployment pipeline") == "set up"

    def test_roll_back_detected(self):
        from seed_gate import find_verb
        assert find_verb("Roll back the migration for schema.sql") == "roll back"

    def test_wire_up_detected(self):
        from seed_gate import find_verb
        assert find_verb("Wire up the OAuth handler in auth.py") == "wire up"

    def test_clean_up_detected(self):
        from seed_gate import find_verb
        assert find_verb("Clean up dead code in state_io.py") == "clean up"

    def test_tear_down_detected(self):
        from seed_gate import find_verb
        assert find_verb("Tear down the test fixtures properly") == "tear down"

    def test_spin_up_detected(self):
        from seed_gate import find_verb
        assert find_verb("Spin up a new worker for compute_trending.py") == "spin up"

    def test_phrasal_starts_with(self):
        from seed_gate import _starts_with_verb
        assert _starts_with_verb("Set up deployment for auth.py")

    def test_phrasal_not_starts_with(self):
        from seed_gate import _starts_with_verb
        # "set" alone is NOT an action verb
        assert not _starts_with_verb("set the variable")

    def test_single_word_still_works(self):
        from seed_gate import find_verb
        assert find_verb("Build the new module foo.py") == "build"

    def test_phrasal_prefers_first_match(self):
        from seed_gate import find_verb
        assert find_verb("Roll back and then set up the migration") == "roll back"

    def test_phrasal_in_validate(self):
        result = validate_seed("Set up the deployment pipeline for config.yaml")
        assert result.passed
        assert result.verb_found == "set up"

    def test_all_phrasal_verbs_are_canonical(self):
        from seed_gate import PHRASAL_VERBS
        for phrase, canonical in PHRASAL_VERBS.items():
            words = phrase.split()
            assert len(words) == 2, f"Phrasal verb '{phrase}' should be two words"
            assert canonical == phrase, f"Canonical for '{phrase}' should be self"


class TestTagImpliedVerbs:
    """Test tag-to-verb inference (#12530)."""

    def test_tag_implied_dict_not_empty(self):
        from seed_gate import TAG_IMPLIED_VERBS
        assert len(TAG_IMPLIED_VERBS) >= 8

    def test_code_tag_implies_build(self):
        result = validate_seed("The authentication module needs CSRF protection", tags=["code"])
        assert result.verb_found == "build"

    def test_debug_tag_implies_debug(self):
        result = validate_seed("Something wrong with the rate limiter", tags=["debug"])
        assert result.verb_found == "debug"

    def test_test_tag_implies_test(self):
        result = validate_seed("Coverage gaps in the channel module", tags=["test"])
        assert result.verb_found == "test"

    def test_docs_tag_implies_document(self):
        result = validate_seed("The SDK documentation has several unclear sections worth addressing", tags=["docs"])
        assert result.verb_found == "document"

    def test_tag_only_fires_when_no_explicit_verb(self):
        result = validate_seed("Refactor the auth module in auth.py", tags=["code"])
        assert result.verb_found == "refactor"  # explicit verb wins

    def test_exempt_tag_still_takes_priority(self):
        # "philosophy" is exempt — verb from tag_implied shouldn't prevent exemption
        result = validate_seed("The ethics of agent autonomy and decision-making", tags=["philosophy"])
        assert result.passed is False  # no verb at all, no target
        # But exempt tags DO pass if there's an implied verb
        result2 = validate_seed("The ethics of agent autonomy", tags=["philosophy", "code"])
        assert result2.verb_found == "build"

    def test_security_tag_implies_secure(self):
        result = validate_seed("Input validation for the API endpoint handler", tags=["security"])
        assert result.verb_found == "secure"


class TestAdvisoryLabel:
    """Test advisory labeling for verb-but-no-target (#12507)."""

    def test_verb_no_target_exempt_gets_advisory(self):
        result = validate_seed("Explore the nature of consciousness", tags=["philosophy"])
        assert result.passed is True
        assert result.advisory == "needs-specificity"

    def test_verb_and_target_no_advisory(self):
        result = validate_seed("Build the new auth module in auth.py")
        assert result.passed is True
        assert result.advisory == ""

    def test_no_verb_no_advisory(self):
        result = validate_seed("Something about nothing at all really right now")
        assert result.passed is False
        assert result.advisory == ""  # no verb → no advisory

    def test_verb_no_target_not_exempt_gets_advisory(self):
        result = validate_seed("Build something amazing for the whole platform")
        assert result.passed is False
        assert result.advisory == "needs-specificity"

    def test_advisory_in_dict_api(self):
        result = validate("Explore the nature of consciousness", tags=["philosophy"])
        assert "advisory" in result
        assert result["advisory"] == "needs-specificity"

    def test_advisory_in_dict_api_empty(self):
        result = validate("Build the auth module in auth.py")
        assert result["advisory"] == ""


class TestRichMatchInfo:
    """Test all_verbs and all_targets in result (#12521)."""

    def test_all_verbs_returned(self):
        from seed_gate import find_all_verbs
        verbs = find_all_verbs("Build auth.py, then test and deploy the module")
        assert "build" in verbs
        assert "test" in verbs
        assert "deploy" in verbs

    def test_all_verbs_deduped(self):
        from seed_gate import find_all_verbs
        verbs = find_all_verbs("Build and build and build auth.py")
        assert verbs.count("build") == 1

    def test_all_verbs_order_preserved(self):
        from seed_gate import find_all_verbs
        verbs = find_all_verbs("Test first, then deploy, finally monitor foo.py")
        assert verbs == ["test", "deploy", "monitor"]

    def test_all_verbs_phrasal(self):
        from seed_gate import find_all_verbs
        verbs = find_all_verbs("Set up and then tear down the test fixtures for config.yaml")
        assert "set up" in verbs
        assert "tear down" in verbs

    def test_all_targets_returned(self):
        from seed_gate import _find_all_targets
        targets = _find_all_targets("Build auth.py and deploy to config.yaml")
        target_strings = [t[0] for t in targets]
        assert "auth.py" in target_strings
        assert "config.yaml" in target_strings

    def test_all_targets_deduped(self):
        from seed_gate import _find_all_targets
        targets = _find_all_targets("Fix auth.py, then fix auth.py again")
        target_strings = [t[0] for t in targets]
        # Should only appear once (canonical dedup)
        assert len([t for t in target_strings if "auth" in t]) == 1

    def test_all_targets_in_result(self):
        result = validate_seed("Build auth.py and test config.yaml")
        assert len(result.all_targets) >= 2
        assert len(result.all_verbs) >= 1

    def test_all_verbs_in_dict(self):
        result = validate("Build and test auth.py")
        assert "all_verbs" in result
        assert isinstance(result["all_verbs"], list)

    def test_all_targets_in_dict(self):
        result = validate("Build auth.py and config.yaml")
        assert "all_targets" in result
        assert isinstance(result["all_targets"], list)


class TestConstTargets:
    """Test CONST_RE in find_target (#12521)."""

    def test_const_detected(self):
        from seed_gate import find_target
        target, kind = find_target("Update MAX_RETRIES in the retry module")
        assert target == "MAX_RETRIES"
        assert kind == "const"

    def test_const_in_scoring(self):
        from seed_gate import compute_score
        score = compute_score("Update MAX_RETRIES", "update", "MAX_RETRIES", "const")
        assert score > 0.0

    def test_const_in_count_unique(self):
        from seed_gate import count_unique_targets, CONST_RE
        text = "Set ACTION_VERBS and MAX_RETRIES to new values"
        count = count_unique_targets(text)
        assert count >= 2

    def test_const_in_all_targets(self):
        from seed_gate import _find_all_targets
        targets = _find_all_targets("Update MAX_RETRIES and fix config.yaml")
        kinds = [t[1] for t in targets]
        assert "const" in kinds

    def test_const_validate_pass(self):
        result = validate_seed("Update ACTION_VERBS in the seed gate")
        assert result.passed
        assert result.target_found == "ACTION_VERBS"


class TestCaseInsensitiveModules:
    """Test case-insensitive module matching."""

    def test_lowercase_module_import(self):
        from seed_gate import _KNOWN_MODULES_LOWER
        # All entries should be lowercase
        for m in _KNOWN_MODULES_LOWER:
            assert m == m.lower()


class TestFindAllVerbs:
    """Focused tests for find_all_verbs."""

    def test_empty_input(self):
        from seed_gate import find_all_verbs
        assert find_all_verbs("") == []

    def test_no_verbs(self):
        from seed_gate import find_all_verbs
        assert find_all_verbs("the quick brown fox") == []

    def test_single_verb(self):
        from seed_gate import find_all_verbs
        assert find_all_verbs("Build a thing") == ["build"]

    def test_phrasal_skip(self):
        from seed_gate import find_all_verbs
        # "set up" should be one verb, not "set" + "up"
        verbs = find_all_verbs("Set up the deployment for auth.py")
        assert "set up" in verbs
        assert "set" not in verbs


class TestFindAllTargets:
    """Focused tests for _find_all_targets."""

    def test_empty_input(self):
        from seed_gate import _find_all_targets
        assert _find_all_targets("") == ()

    def test_single_file(self):
        from seed_gate import _find_all_targets
        targets = _find_all_targets("Fix auth.py")
        assert len(targets) >= 1
        assert targets[0][0] == "auth.py"
        assert targets[0][1] == "file"

    def test_multiple_kinds(self):
        from seed_gate import _find_all_targets
        targets = _find_all_targets("Build auth.py with src/utils/ and check #12345")
        kinds = {t[1] for t in targets}
        assert "file" in kinds

    def test_const_in_all(self):
        from seed_gate import _find_all_targets
        targets = _find_all_targets("Set MAX_RETRIES and check config.yaml")
        kinds = {t[1] for t in targets}
        assert "const" in kinds
        assert "file" in kinds


class TestNewVerbsExpanded:
    """Test the 25 newly-added verbs."""

    @pytest.mark.parametrize("verb", [
        "configure", "scaffold", "bootstrap", "provision",
        "automate", "archive", "inject", "normalize",
        "update", "delete", "enable", "disable",
        "install", "deprecate", "rewrite", "standardize",
        "containerize", "expose", "wrap", "stub", "mock",
        "isolate", "define", "declare", "register",
        "secure", "clean", "schedule", "cache", "publish",
        "annotate", "version", "backup", "package",
    ])
    def test_new_verb_in_set(self, verb):
        assert verb in ACTION_VERBS

    def test_verb_count_at_least_95(self):
        assert len(ACTION_VERBS) >= 95


class TestNewFeatureInvariants:
    """Property-based invariants for new features."""

    def test_advisory_only_when_verb_present(self):
        """Advisory should only appear when a verb was found."""
        proposals = [
            "Build something nice for the platform",
            "Explore consciousness deeply",
            "The meaning of life is 42 probably",
            "Set up auth.py deployment pipeline",
        ]
        for text in proposals:
            result = validate_seed(text)
            if result.advisory:
                assert result.verb_found is not None

    def test_all_verbs_subset_of_action_verbs_or_phrasal(self):
        """Every verb in all_verbs should be a known verb."""
        from seed_gate import find_all_verbs, PHRASAL_VERBS
        text = "Build and deploy auth.py, then set up monitoring and test"
        for v in find_all_verbs(text):
            assert v in ACTION_VERBS or v in PHRASAL_VERBS.values()

    def test_all_targets_kinds_valid(self):
        """Every target kind should be a recognized kind."""
        from seed_gate import _find_all_targets
        valid_kinds = {"file", "path", "func", "tool", "cli", "discussion",
                       "channel", "quoted", "module", "const"}
        targets = _find_all_targets("Build auth.py, check r/mars, update MAX_RETRIES, see #12345")
        for _, kind in targets:
            assert kind in valid_kinds

    def test_score_const_between_channel_and_tool(self):
        """const score (2.5) should be between channel (2.0) and tool (3.0)."""
        from seed_gate import compute_score
        s_const = compute_score("Update MAX_RETRIES", "update", "MAX_RETRIES", "const")
        s_channel = compute_score("Update r/mars", "update", "r/mars", "channel")
        s_tool = compute_score("Update state_io", "update", "state_io", "tool")
        assert s_channel <= s_const <= s_tool


class TestBackwardCompatNewFields:
    """Ensure new fields don't break existing behavior."""

    def test_old_dict_keys_still_present(self):
        result = validate("Build auth.py")
        for key in ("passed", "reasons", "score", "verb_found", "target_found", "junk"):
            assert key in result

    def test_new_dict_keys_present(self):
        result = validate("Build auth.py")
        for key in ("advisory", "all_verbs", "all_targets"):
            assert key in result

    def test_batch_still_works(self):
        from seed_gate import validate_batch
        br = validate_batch(["Build auth.py", "random stuff here"])
        assert br.stats.total == 2

    def test_passes_gate_unaffected(self):
        assert passes_gate("Build the authentication module in auth.py")
        assert not passes_gate("random stuff here with nothing concrete at all")


# ============================================================
# Tests for PR #256: inflected verbs, version filter, confidence,
# suggest(), env vars, expanded tools, imperative bonus
# ============================================================

from seed_gate import (
    find_verb,
    find_all_verbs,
    find_target,
    compute_score,
    find_verb_with_position,
    VerbMatch,
    explain,
    score_breakdown,
)


class TestInflectionMap:
    """Test the generated inflection map."""

    def test_map_is_populated(self):
        from seed_gate import _INFLECTION_MAP
        assert len(_INFLECTION_MAP) > 200

    @pytest.mark.parametrize("inflected,expected", [
        ("builds", "build"), ("building", "build"), ("built", "build"),
        ("tests", "test"), ("testing", "test"), ("tested", "test"),
        ("deploys", "deploy"), ("deploying", "deploy"), ("deployed", "deploy"),
        ("creates", "create"), ("creating", "create"), ("created", "create"),
        ("fixes", "fix"), ("fixing", "fix"), ("fixed", "fix"),
        ("writes", "write"), ("writing", "write"), ("wrote", "write"),
        ("runs", "run"), ("running", "run"), ("ran", "run"),
        ("ships", "ship"), ("shipping", "ship"), ("shipped", "ship"),
        ("adds", "add"), ("adding", "add"), ("added", "add"),
        ("refactors", "refactor"), ("refactoring", "refactor"),
        ("debugs", "debug"), ("debugging", "debug"), ("debugged", "debug"),
    ])
    def test_inflection_map_entries(self, inflected, expected):
        from seed_gate import _INFLECTION_MAP
        assert _INFLECTION_MAP.get(inflected) == expected, (
            f"{inflected} should map to {expected}"
        )

    @pytest.mark.parametrize("irregular,expected", [
        ("built", "build"), ("wrote", "write"), ("ran", "run"),
    ])
    def test_irregular_past(self, irregular, expected):
        from seed_gate import _INFLECTION_MAP
        assert _INFLECTION_MAP.get(irregular) == expected

    def test_irregular_only_valid_bases(self):
        """Irregular past entries must map to verbs in ACTION_VERBS."""
        from seed_gate import _IRREGULAR_PAST, _INFLECTION_MAP, ACTION_VERBS
        for form, base in _IRREGULAR_PAST.items():
            if base in ACTION_VERBS:
                assert form in _INFLECTION_MAP

    def test_no_false_positives(self):
        from seed_gate import _INFLECTION_MAP
        for word in ["nothing", "during", "morning", "something", "string",
                      "everything", "testing123", "interesting"]:
            assert word not in _INFLECTION_MAP, f"{word} should NOT be in map"


class TestInflectedVerbDetection:
    """Test that inflected verbs are detected by find_verb/find_all_verbs."""

    @pytest.mark.parametrize("text,expected_verb", [
        ("Builds the thermal_control.py module", "build"),
        ("Creating water_mining.py from scratch", "create"),
        ("Deployed config.yaml to production", "deploy"),
        ("Implementing the new auth flow", "implement"),
        ("Refactoring state_io.py for clarity", "refactor"),
        ("Shipped v2 of the dashboard", "ship"),
        ("Debugging the flaky test in ci.yml", "debug"),
    ])
    def test_find_verb_inflected(self, text, expected_verb):
        assert find_verb(text) == expected_verb

    def test_find_all_verbs_with_inflected(self):
        text = "Building auth.py and deploying config.yaml"
        verbs = find_all_verbs(text)
        assert "build" in verbs
        assert "deploy" in verbs


class TestInflectedPhrasalVerbs:
    """Test inflected phrasal verb detection."""

    @pytest.mark.parametrize("text,expected_verb", [
        ("Setting up the CI pipeline", "set up"),
        ("Rolling back the deployment", "roll back"),
        ("Spinning up new workers", "spin up"),
        ("Tearing down the test fixtures", "tear down"),
        ("Wiring up the auth module", "wire up"),
    ])
    def test_inflected_phrasal(self, text, expected_verb):
        assert find_verb(text) == expected_verb

    def test_inflected_phrasal_in_find_all(self):
        verbs = find_all_verbs("Setting up auth.py and rolling back config.yaml")
        assert "set up" in verbs
        assert "roll back" in verbs


class TestVersionFilter:
    """Test that version strings are NOT matched as file targets."""

    @pytest.mark.parametrize("version", [
        "2.0.1", "v1.2.3", "1.0", "3.14.159", "v0.1.0-beta",
    ])
    def test_version_not_matched_as_file(self, version):
        target, kind = find_target(f"Update to version {version}") or ("", "")
        assert target != version, f"{version} should not match as file target"

    @pytest.mark.parametrize("real_file", [
        "module2.py", "release-v1.2.3.md", "seed_gate_v2.py",
    ])
    def test_versioned_files_still_match(self, real_file):
        target, kind = find_target(f"Build {real_file}") or ("", "")
        assert target == real_file, f"Versioned file {real_file} should still match"


class TestConfidenceProperty:
    """Test the confidence band property on SeedGateResult."""

    def test_high_confidence(self):
        result = validate_seed("Build the thermal_control.py module from scratch with full test coverage")
        assert result.passed
        assert result.confidence == "high"

    def test_medium_confidence(self):
        result = validate_seed("Fix the auth.py login handler")
        assert result.passed
        assert result.confidence in ("medium", "high")

    def test_none_on_failure(self):
        result = validate_seed("just vibes")
        assert not result.passed
        assert result.confidence is None

    def test_confidence_in_to_dict(self):
        result = validate_seed("Build thermal_control.py")
        d = result.to_dict()
        assert "confidence" in d
        assert d["confidence"] in ("high", "medium", "low", None)


class TestSuggestAPI:
    """Test the suggest() function for rejection feedback."""

    def test_no_suggestions_for_passing(self):
        from seed_gate import suggest
        result = suggest("Build thermal_control.py")
        assert result == []

    def test_suggests_verb_when_missing(self):
        from seed_gate import suggest
        result = suggest("the thermal_control.py module")
        assert any("verb" in s.lower() for s in result)

    def test_suggests_target_when_missing(self):
        from seed_gate import suggest
        result = suggest("Build something cool")
        assert any("target" in s.lower() or "filename" in s.lower() for s in result)

    def test_suggests_rewrite_for_junk(self):
        from seed_gate import suggest
        result = suggest("fix stuff lol")
        # Either junk or missing target suggestion
        assert len(result) >= 1


class TestEnvVarTargets:
    """Test environment variable target detection."""

    @pytest.mark.parametrize("text,expected_var", [
        ("Set $STATE_DIR to /tmp", "$STATE_DIR"),
        ("Configure ${GITHUB_TOKEN} for auth", "${GITHUB_TOKEN}"),
        ("Update $DOCS_DIR path", "$DOCS_DIR"),
    ])
    def test_env_var_found(self, text, expected_var):
        target, kind = find_target(text) or ("", "")
        assert target == expected_var
        assert kind == "env"

    def test_env_var_in_find_all_targets(self):
        from seed_gate import _find_all_targets
        targets = _find_all_targets("Set $STATE_DIR and $DOCS_DIR")
        names = [t[0] for t in targets]
        assert "$STATE_DIR" in names
        assert "$DOCS_DIR" in names


class TestExpandedKnownTools:
    """Test that newly added tools are recognized."""

    @pytest.mark.parametrize("tool", [
        "inject_seed", "tally_votes", "steer", "reconcile_state",
        "run_proof", "run_python", "vlink",
    ])
    def test_new_tool_found(self, tool):
        target, kind = find_target(f"Run {tool} to verify") or ("", "")
        assert target == tool
        assert kind == "tool"


class TestImperativeBonus:
    """Test the imperative scoring bonus."""

    def test_imperative_higher(self):
        imperative = compute_score("Build auth.py from scratch", "build", "auth.py", "file")
        declarative = compute_score("The auth.py module needs to be built", "build", "auth.py", "file")
        assert imperative > declarative

    def test_inflected_imperative(self):
        # Even inflected verbs at start should get the bonus
        score = compute_score("Building auth.py from scratch", "build", "auth.py", "file")
        assert score > 0.5


class TestNounUseFalsePositives:
    """Ensure words that look like verb inflections but are nouns don't match."""

    @pytest.mark.parametrize("text", [
        "Nothing works in the thermal_control.py system",
        "During the morning review of auth.py we found bugs",
        "Something strange with the water_mining.py module",
    ])
    def test_non_verb_words_ignored(self, text):
        from seed_gate import _INFLECTION_MAP
        for word in ["nothing", "during", "morning", "something", "strange"]:
            assert word not in _INFLECTION_MAP


class TestInflectionInvariants:
    """Property-based invariants for the inflection system."""

    def test_all_map_values_are_action_verbs(self):
        from seed_gate import _INFLECTION_MAP, ACTION_VERBS, PHRASAL_VERBS
        canonical = ACTION_VERBS | set(PHRASAL_VERBS.values())
        for form, base in _INFLECTION_MAP.items():
            assert base in canonical, f"{form} maps to {base} which is not a known verb"

    def test_inflected_verb_always_returns_base(self):
        from seed_gate import _INFLECTION_MAP
        for form, base in list(_INFLECTION_MAP.items())[:50]:
            found = find_verb(f"{form} something")
            assert found == base, f"find_verb('{form} something') = {found}, expected {base}"

    def test_double_final_all_in_action_verbs_or_phrasal(self):
        from seed_gate import _DOUBLE_FINAL, ACTION_VERBS, PHRASAL_VERBS
        head_words = {phrase.split()[0] for phrase in PHRASAL_VERBS}
        for verb in _DOUBLE_FINAL:
            assert verb in ACTION_VERBS or verb in head_words, (
                f"{verb} in _DOUBLE_FINAL but not in ACTION_VERBS or phrasal heads"
            )

    def test_score_always_0_to_1(self):
        for text in [
            "Build auth.py and deploy config.yaml with full test coverage for the CI pipeline",
            "x",
            "",
            "Fix bugs",
        ]:
            s = compute_score(text, find_verb(text), *(find_target(text) or ("", "")))
            assert 0.0 <= s <= 1.0, f"Score {s} out of bounds for: {text}"

    def test_confidence_always_valid(self):
        for text in ["Build auth.py", "Fix stuff", "x"]:
            result = validate_seed(text)
            assert result.confidence in ("high", "medium", "low", None)

    def test_suggestions_always_list(self):
        from seed_gate import suggest
        for text in ["Build auth.py", "vibes only", "x"]:
            result = suggest(text)
            assert isinstance(result, list)


# ---------------------------------------------------------------------------
# PR #272 -- explain(), score_breakdown(), find_verb_with_position(),
#             enriched SeedGateResult diagnostics
# ---------------------------------------------------------------------------


class TestVerbMatch:
    """VerbMatch dataclass from find_verb_with_position()."""

    def test_basic_verb_position(self):
        m = find_verb_with_position("Build seed_gate.py validator")
        assert m is not None
        assert m.verb == "build"
        assert m.token_index == 0
        assert m.source == "text"

    def test_verb_not_first_word(self):
        m = find_verb_with_position("Please fix the auth.py module now")
        assert m is not None
        assert m.verb == "fix"
        assert m.token_index == 1

    def test_phrasal_verb_position(self):
        m = find_verb_with_position("Set up the CI pipeline for deploys")
        assert m is not None
        assert m.verb == "set up"
        assert m.token_index == 0

    def test_inflected_verb_position(self):
        m = find_verb_with_position("Currently building the new dashboard page")
        assert m is not None
        assert m.verb == "build"
        assert m.token_index == 1

    def test_inflected_phrasal_position(self):
        m = find_verb_with_position("Setting up the test fixtures now")
        assert m is not None
        assert m.verb == "set up"
        assert m.token_index == 0

    def test_no_verb_returns_none(self):
        assert find_verb_with_position("The quick brown fox") is None

    def test_custom_source(self):
        m = find_verb_with_position("Build it", source="tag")
        assert m is not None
        assert m.source == "tag"

    def test_limit_param(self):
        m = find_verb_with_position("Hello world, please build the thing", limit=10)
        assert m is None  # "build" is beyond limit

    def test_bool_truthy(self):
        m = find_verb_with_position("Build seed_gate.py module")
        assert bool(m)

    def test_consistency_with_find_verb(self):
        """find_verb() must agree with find_verb_with_position().verb."""
        texts = [
            "Build seed_gate.py", "Fix auth.py module now",
            "Setting up CI pipeline", "The quick brown fox",
            "Currently deploying the v2 release",
            "Roll back the failed migration now",
        ]
        for text in texts:
            fv = find_verb(text)
            fvp = find_verb_with_position(text)
            if fv is None:
                assert fvp is None, f"Mismatch for {text!r}: find_verb=None but fvp={fvp}"
            else:
                assert fvp is not None and fvp.verb == fv, \
                    f"Mismatch for {text!r}: find_verb={fv!r} but fvp={fvp}"


class TestScoreBreakdown:
    """score_breakdown() -- decomposed scoring components."""

    def test_has_verb_component(self):
        bd = score_breakdown("Build seed_gate.py validator")
        assert "verb" in bd
        assert bd["verb"] == 2.5

    def test_has_target_component(self):
        bd = score_breakdown("Build seed_gate.py validator")
        assert "target" in bd
        assert bd["target"] == 4.0  # file kind

    def test_no_verb_no_component(self):
        bd = score_breakdown("The big architecture of seed_gate.py system")
        assert "verb" not in bd or bd.get("verb", 0) == 0

    def test_auto_detects_when_not_provided(self):
        bd = score_breakdown("Build seed_gate.py validator now")
        assert "verb" in bd

    def test_explicit_verb_target(self):
        bd = score_breakdown("some text here", verb="build", target="seed_gate.py", target_kind="file")
        assert bd["verb"] == 2.5
        assert bd["target"] == 4.0

    def test_length_bonus_short(self):
        bd = score_breakdown("Build seed_gate.py validator")
        assert "length_bonus" not in bd  # < 8 words

    def test_length_bonus_medium(self):
        bd = score_breakdown("Build seed_gate.py validator with extra words to reach eight total")
        assert bd.get("length_bonus", 0) >= 0.5

    def test_length_bonus_long(self):
        text = "Build seed_gate.py validator with extra words to reach fifteen total and more beyond that threshold here now"
        bd = score_breakdown(text)
        assert bd.get("length_bonus", 0) >= 1.5

    def test_multi_target_bonus(self):
        bd = score_breakdown("Build seed_gate.py and propose_seed.py integration")
        assert bd.get("multi_target", 0) >= 1.0

    def test_imperative_bonus(self):
        bd = score_breakdown("Build seed_gate.py with action verbs")
        assert "imperative" in bd
        assert bd["imperative"] == 0.5

    def test_no_imperative_when_verb_not_first(self):
        bd = score_breakdown("Please build seed_gate.py with action verbs")
        assert "imperative" not in bd

    def test_consistency_with_compute_score(self):
        """score_breakdown normalized value must equal compute_score."""
        texts = [
            "Build seed_gate.py",
            "Fix auth.py module in the main application system",
            "Explore the deep meaning of consciousness in agents and worlds",
        ]
        for text in texts:
            v = find_verb(text)
            t, tk = find_target(text)
            expected = compute_score(text, v, t, tk)
            bd = score_breakdown(text, v, t, tk)
            # The breakdown doesn't store normalized separately anymore,
            # but we can verify by summing parts
            parts_sum = sum(val for key, val in bd.items())
            normalized = min(parts_sum / 10.0, 1.0)
            assert abs(expected - normalized) < 0.001, \
                f"Score mismatch for {text!r}: compute={expected}, breakdown_sum={normalized}"


class TestExplainAPI:
    """explain() -- human-readable diagnostic."""

    def test_passed_contains_checkmark(self):
        out = explain("Build seed_gate.py validator for proposals")
        assert "\u2705" in out
        assert "PASSED" in out

    def test_failed_contains_cross(self):
        out = explain("Make everything better and more amazing")
        assert "\u274c" in out
        assert "FAILED" in out

    def test_shows_verb(self):
        out = explain("Build seed_gate.py validator with better verbs")
        assert 'Verb: "build"' in out

    def test_shows_target(self):
        out = explain("Build seed_gate.py validator for the pipeline")
        assert '"seed_gate.py"' in out
        assert "(file)" in out

    def test_shows_score(self):
        out = explain("Build seed_gate.py validator system now")
        assert "score:" in out

    def test_junk_shows_reason(self):
        out = explain("")
        assert "Junk:" in out

    def test_no_verb_shows_none(self):
        out = explain("The big architecture of the whole system platform")
        assert "Verb: none" in out

    def test_multiline(self):
        out = explain("Build seed_gate.py and propose_seed.py integration")
        lines = out.strip().split("\n")
        assert len(lines) >= 3  # at least status + verb + target

    def test_shows_score_breakdown(self):
        out = explain("Build seed_gate.py validator system integration")
        assert "Score breakdown:" in out

    def test_tag_inferred_shows_source(self):
        out = explain("Make the codebase cleaner and better", tags=["code"])
        assert "source=tag" in out

    def test_advisory_shown(self):
        out = explain("Build a better world for all agents everywhere")
        # Has verb but no target -> advisory
        assert "Advisory:" in out or "needs-specificity" in out or "FAILED" in out

    def test_exempt_tag_passes(self):
        out = explain("What if agents could dream about electric sheep", tags=["philosophy"])
        assert "PASSED" in out


class TestEnrichedSeedGateResult:
    """SeedGateResult new fields: target_kind, verb_source, verb_position, score_parts."""

    def test_target_kind_populated(self):
        r = validate_seed("Build seed_gate.py validator for proposals")
        assert r.target_kind == "file"

    def test_target_kind_tool(self):
        r = validate_seed("Fix state_io module for atomic writes")
        assert r.target_kind in ("tool", "module")

    def test_verb_source_text(self):
        r = validate_seed("Build seed_gate.py validator")
        assert r.verb_source == "text"

    def test_verb_source_tag(self):
        r = validate_seed("Make the system more robust overall", tags=["code"])
        assert r.verb_source == "tag"

    def test_verb_source_question(self):
        r = validate_seed("What if agents dreamed of electric sheep", tags=["philosophy"])
        assert r.verb_source == "question"

    def test_verb_position_zero(self):
        r = validate_seed("Build seed_gate.py validator system now")
        assert r.verb_position == 0

    def test_verb_position_nonzero(self):
        r = validate_seed("Please fix the auth.py module now")
        assert r.verb_position is not None
        assert r.verb_position > 0

    def test_verb_position_none_for_tag_inferred(self):
        r = validate_seed("Make the system more robust overall", tags=["code"])
        assert r.verb_position is None

    def test_score_parts_populated(self):
        r = validate_seed("Build seed_gate.py validator for proposals")
        assert len(r.score_parts) > 0

    def test_score_parts_has_verb(self):
        r = validate_seed("Build seed_gate.py validator system here")
        parts_dict = dict(r.score_parts)
        assert "verb" in parts_dict
        assert parts_dict["verb"] == 2.5

    def test_score_parts_in_to_dict(self):
        r = validate_seed("Build seed_gate.py validator system here")
        d = r.to_dict()
        assert "score_parts" in d
        assert isinstance(d["score_parts"], dict)
        assert "verb" in d["score_parts"]

    def test_target_kind_in_to_dict(self):
        r = validate_seed("Build seed_gate.py validator system here")
        d = r.to_dict()
        assert d["target_kind"] == "file"

    def test_verb_source_in_to_dict(self):
        r = validate_seed("Build seed_gate.py validator system here")
        d = r.to_dict()
        assert d["verb_source"] == "text"

    def test_is_imperative_property(self):
        r = validate_seed("Build seed_gate.py validator system here")
        assert r.is_imperative is True

    def test_not_imperative(self):
        r = validate_seed("Please build seed_gate.py validator now")
        assert r.is_imperative is False

    def test_is_imperative_false_for_no_verb(self):
        r = validate_seed("The architecture of seed_gate.py system")
        assert r.is_imperative is False


class TestDiagnosticInvariants:
    """Cross-API consistency invariants for PR #272."""

    def test_find_verb_with_position_agrees_with_find_verb(self):
        """For any text, find_verb(t) == find_verb_with_position(t).verb."""
        import random
        verbs = list(ACTION_VERBS)[:20]
        targets = ["seed_gate.py", "state_io", "auth.py", "r/mars", "#12345"]
        for _ in range(50):
            v = random.choice(verbs)
            t = random.choice(targets)
            text = f"{v.capitalize()} {t} with some extra context words"
            fv = find_verb(text)
            fvp = find_verb_with_position(text)
            assert fvp is not None
            assert fv == fvp.verb

    def test_score_breakdown_sums_to_compute_score(self):
        """Sum of score_breakdown parts (excluding 'raw' and 'normalized') must match."""
        texts = [
            "Build seed_gate.py validator",
            "Fix auth.py and state_io.py modules in the main app system now",
            "Deploy the dashboard to production servers across regions",
            "Setting up the CI pipeline for automated testing",
        ]
        for text in texts:
            v = find_verb(text)
            t, tk = find_target(text)
            score = compute_score(text, v, t, tk)
            bd = score_breakdown(text, v, t, tk)
            # Verify consistency
            assert abs(score - min(sum(bd.values()) / 10.0, 1.0)) < 0.001

    def test_validate_seed_score_parts_match_compute_score(self):
        """SeedGateResult.score must match sum of score_parts."""
        texts = [
            "Build seed_gate.py",
            "Refactor the water_mining.py system for better performance now",
            "Test auth.py and seed_gate.py integration thoroughly",
        ]
        for text in texts:
            r = validate_seed(text)
            if r.score_parts:
                parts_sum = sum(v for _, v in r.score_parts)
                expected = min(parts_sum / 10.0, 1.0)
                assert abs(r.score - expected) < 0.001, \
                    f"Score mismatch for {text!r}: result.score={r.score}, parts_sum_norm={expected}"

    def test_explain_agrees_with_validate(self):
        """explain() says PASSED iff validate_seed() says passed."""
        texts = [
            "Build seed_gate.py validator",
            "Make everything better",
            "Fix the auth.py module now",
            "",
        ]
        for text in texts:
            r = validate_seed(text)
            e = explain(text)
            if r.passed:
                assert "PASSED" in e, f"explain disagrees for {text!r}"
            else:
                assert "FAILED" in e, f"explain disagrees for {text!r}"

    def test_verb_position_always_valid(self):
        """verb_position is None only for tag/question inferred verbs."""
        texts = [
            ("Build seed_gate.py now", None),
            ("Fix auth.py module here", None),
            ("Make it robust overall", ["code"]),
            ("What if agents dreamed", ["philosophy"]),
        ]
        for text, tags in texts:
            r = validate_seed(text, tags)
            if r.verb_found and r.verb_source == "text":
                assert r.verb_position is not None
            elif r.verb_source in ("tag", "question"):
                assert r.verb_position is None
