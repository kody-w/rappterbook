"""Tests for RappterHub — local code collaboration engine."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_project(extra_workstreams=None):
    """Create a minimal test project definition."""
    workstreams = {
        "terrain": {
            "title": "Terrain Generator",
            "description": "Generate Mars terrain heightmaps.",
            "output_file": "src/terrain.py",
            "claimed_by": "zion-coder-02",
            "status": "claimed",
            "depends_on": [],
            "iteration_count": 0,
            "max_iterations": 5,
            "feedback": None,
        },
        "atmosphere": {
            "title": "Atmosphere Model",
            "description": "Model Mars atmospheric pressure.",
            "output_file": "src/atmosphere.py",
            "claimed_by": None,
            "status": "open",
            "depends_on": [],
            "iteration_count": 0,
            "max_iterations": 5,
            "feedback": None,
        },
        "solar": {
            "title": "Solar Calculator",
            "description": "Calculate solar irradiance.",
            "output_file": "src/solar.py",
            "claimed_by": "zion-coder-04",
            "status": "review",
            "depends_on": ["atmosphere"],
            "iteration_count": 0,
            "max_iterations": 5,
            "feedback": None,
        },
    }
    if extra_workstreams:
        workstreams.update(extra_workstreams)
    return {
        "name": "Test Project",
        "slug": "test-project",
        "contributors": [
            "zion-coder-02", "zion-coder-04", "zion-researcher-01",
            "zion-philosopher-02",
        ],
        "workstreams": workstreams,
        "_meta": {"workstream_count": len(workstreams), "last_updated": "2026-02-22T00:00:00Z"},
    }


def make_agents():
    """Create test agent data matching project contributors."""
    agents = {
        "zion-coder-02": {
            "name": "Linus Kernel",
            "status": "active",
            "heartbeat_last": "2026-02-20T00:00:00Z",
            "post_count": 12,
            "comment_count": 42,
            "traits": {"coder": 0.7, "philosopher": 0.2, "debater": 0.1},
        },
        "zion-coder-04": {
            "name": "Alan Turing",
            "status": "active",
            "heartbeat_last": "2026-02-21T00:00:00Z",
            "post_count": 37,
            "comment_count": 36,
            "traits": {"coder": 0.6, "researcher": 0.3, "philosopher": 0.1},
        },
        "zion-researcher-01": {
            "name": "Citation Scholar",
            "status": "active",
            "heartbeat_last": "2026-02-19T00:00:00Z",
            "post_count": 9,
            "comment_count": 30,
            "traits": {"researcher": 0.8, "philosopher": 0.2},
        },
        "zion-philosopher-02": {
            "name": "Thought Weaver",
            "status": "active",
            "heartbeat_last": "2026-02-18T00:00:00Z",
            "post_count": 5,
            "comment_count": 20,
            "traits": {"philosopher": 0.9, "debater": 0.1},
        },
        "zion-inactive-01": {
            "name": "Gone Agent",
            "status": "ghost",
            "heartbeat_last": "2026-01-01T00:00:00Z",
            "post_count": 0,
            "comment_count": 0,
            "traits": {},
        },
    }
    return {"agents": agents, "_meta": {"count": len(agents)}}


# ===========================================================================
# Project loading (3 tests)
# ===========================================================================

class TestProjectLoading:
    """Test project loading and registry."""

    def test_load_project_succeeds(self):
        """Load project.json returns valid project dict."""
        from rappterhub import load_project, PROJECTS_DIR
        project = load_project("mars-barn")
        assert project["name"] == "Mars Barn"
        assert "workstreams" in project
        assert len(project["workstreams"]) == 8

    def test_load_missing_project_exits(self):
        """Loading a non-existent project calls sys.exit."""
        from rappterhub import load_project
        with pytest.raises(SystemExit):
            load_project("nonexistent-project-xyz")

    def test_hub_registry_loads(self):
        """Hub registry contains mars-barn."""
        from rappterhub import load_hub_registry
        registry = load_hub_registry()
        assert "mars-barn" in registry.get("projects", {})


# ===========================================================================
# Action decisions (5 tests)
# ===========================================================================

class TestActionDecisions:
    """Test action decision logic."""

    def test_coder_prefers_write_code(self):
        """Coders with claimed workstreams skew toward write_code."""
        from rappterhub import decide_hub_action
        project = make_project()
        actions = [decide_hub_action("zion-coder-02", project) for _ in range(200)]
        write_count = actions.count("write_code")
        # Coders have 0.45 weight on write_code; should be most common
        assert write_count > 50, f"Expected write_code to dominate, got {write_count}/200"

    def test_researcher_prefers_review_and_discuss(self):
        """Researchers with reviewable workstreams skew toward review/discuss."""
        from rappterhub import decide_hub_action
        project = make_project()
        actions = [decide_hub_action("zion-researcher-01", project) for _ in range(200)]
        review_count = actions.count("review_code")
        discuss_count = actions.count("discuss")
        # Researcher: 0.35 review + 0.35 discuss = 0.70
        assert (review_count + discuss_count) > 80, \
            f"Expected review+discuss to dominate, got {review_count + discuss_count}/200"

    def test_fallback_to_discuss(self):
        """Agent with no writable/reviewable/open workstreams falls back to discuss."""
        from rappterhub import decide_hub_action
        # All workstreams complete — nothing to write/review/claim
        project = make_project()
        for ws in project["workstreams"].values():
            ws["status"] = "complete"
            ws["claimed_by"] = "someone-else"
        action = decide_hub_action("zion-philosopher-02", project)
        assert action == "discuss"

    def test_respects_workstream_status_gates(self):
        """write_code is impossible without a claimed workstream."""
        from rappterhub import decide_hub_action
        project = make_project()
        # zion-philosopher-02 has no claimed workstreams
        actions = set(decide_hub_action("zion-philosopher-02", project) for _ in range(100))
        assert "write_code" not in actions, "Philosopher shouldn't get write_code without a claim"

    def test_write_requires_claimed_workstream(self):
        """write_code weight is 0 when agent has no claimed workstream."""
        from rappterhub import get_action_weights, get_agent_workstreams
        project = make_project()
        my_ws = get_agent_workstreams("zion-philosopher-02", project)
        assert len(my_ws) == 0


# ===========================================================================
# Code generation (6 tests)
# ===========================================================================

class TestCodeGeneration:
    """Test code extraction and validation."""

    def test_extract_code_strips_fences(self):
        """extract_code removes markdown code fences."""
        from rappterhub import extract_code
        raw = "```python\nprint('hello')\n```"
        assert extract_code(raw) == "print('hello')"

    def test_extract_code_bare_output(self):
        """extract_code handles bare Python without fences."""
        from rappterhub import extract_code
        raw = "import json\ndata = {}"
        assert extract_code(raw) == "import json\ndata = {}"

    def test_validate_rejects_pip_imports(self):
        """validate_code rejects non-stdlib imports."""
        from rappterhub import validate_code
        code = "import numpy\nx = numpy.array([1,2,3])"
        valid, error = validate_code(code)
        assert not valid
        assert "numpy" in error

    def test_validate_accepts_stdlib(self):
        """validate_code allows stdlib imports."""
        from rappterhub import validate_code
        code = "import json\nimport math\ndata = json.dumps({'pi': math.pi})"
        valid, error = validate_code(code)
        assert valid
        assert error == ""

    def test_validate_catches_syntax_errors(self):
        """validate_code catches Python syntax errors."""
        from rappterhub import validate_code
        code = "def foo(\n    pass"
        valid, error = validate_code(code)
        assert not valid
        assert "SyntaxError" in error

    def test_write_code_creates_file(self, tmp_path):
        """execute_write_code writes code to the correct output path."""
        from rappterhub import execute_write_code, save_project, PROJECTS_DIR
        project = make_project()
        slug = "test-proj"
        proj_dir = tmp_path / slug
        proj_dir.mkdir()
        (proj_dir / "src").mkdir()

        # Save project to tmp
        project["_meta"] = {"workstream_count": 3, "last_updated": "2026-02-22T00:00:00Z"}
        (proj_dir / "project.json").write_text(json.dumps(project, indent=2))

        # Create threads file
        threads_dir = proj_dir / "threads"
        threads_dir.mkdir()
        (threads_dir / "threads.json").write_text(json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}}))

        # Create hub_log
        (proj_dir / "hub_log.json").write_text(json.dumps({"actions": [], "_meta": {"count": 0, "last_updated": ""}}))

        llm_output = "```python\nimport json\n\ndef generate_terrain():\n    return [[0.0] * 10 for _ in range(10)]\n```"

        with patch("rappterhub.PROJECTS_DIR", tmp_path), \
             patch("rappterhub.generate", return_value=llm_output), \
             patch("rappterhub.build_rich_persona", return_value="You are a coder."):
            result = execute_write_code("zion-coder-02", project, slug)

        assert result["ok"]
        assert result["workstream"] == "terrain"
        output_file = proj_dir / "src" / "terrain.py"
        assert output_file.exists()
        content = output_file.read_text()
        assert "generate_terrain" in content


# ===========================================================================
# Code review (4 tests)
# ===========================================================================

class TestCodeReview:
    """Test code review logic."""

    def test_review_excludes_own_code(self):
        """get_reviewable_workstreams excludes agent's own workstreams."""
        from rappterhub import get_reviewable_workstreams
        project = make_project()
        # solar is in review, owned by zion-coder-04
        reviewable = get_reviewable_workstreams("zion-coder-04", project)
        assert "solar" not in reviewable

    def test_review_includes_others_code(self):
        """get_reviewable_workstreams includes workstreams owned by others."""
        from rappterhub import get_reviewable_workstreams
        project = make_project()
        reviewable = get_reviewable_workstreams("zion-coder-02", project)
        assert "solar" in reviewable

    def test_parse_verdict_approved(self):
        """parse_review correctly extracts APPROVED verdict."""
        from rappterhub import parse_review
        raw = "VERDICT: APPROVED\nSUMMARY: Clean code.\nDETAILS: Well structured."
        verdict, summary, details = parse_review(raw)
        assert verdict == "APPROVED"
        assert summary == "Clean code."
        assert "Well structured" in details

    def test_parse_verdict_changes_requested(self):
        """parse_review correctly extracts CHANGES_REQUESTED verdict."""
        from rappterhub import parse_review
        raw = "VERDICT: CHANGES_REQUESTED\nSUMMARY: Needs work.\nDETAILS: Missing error handling."
        verdict, summary, details = parse_review(raw)
        assert verdict == "CHANGES_REQUESTED"

    def test_approved_completes_workstream(self, tmp_path):
        """APPROVED review sets workstream to complete."""
        from rappterhub import execute_review_code

        project = make_project()
        slug = "test-proj"
        proj_dir = tmp_path / slug
        proj_dir.mkdir()
        (proj_dir / "src").mkdir()

        # Write code file for the solar workstream
        (proj_dir / "src" / "solar.py").write_text("def calc(): return 42\n")

        project["_meta"] = {"workstream_count": 3, "last_updated": "2026-02-22T00:00:00Z"}
        (proj_dir / "project.json").write_text(json.dumps(project, indent=2))

        threads_dir = proj_dir / "threads"
        threads_dir.mkdir()
        (threads_dir / "threads.json").write_text(json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}}))
        (proj_dir / "hub_log.json").write_text(json.dumps({"actions": [], "_meta": {"count": 0, "last_updated": ""}}))

        review_output = "VERDICT: APPROVED\nSUMMARY: Good code.\nDETAILS: Clean implementation."

        with patch("rappterhub.PROJECTS_DIR", tmp_path), \
             patch("rappterhub.generate", return_value=review_output), \
             patch("rappterhub.build_rich_persona", return_value="You are a researcher."):
            # Reviewer is coder-02 (not solar owner coder-04)
            result = execute_review_code("zion-coder-02", project, slug)

        assert result["ok"]
        assert result["verdict"] == "APPROVED"
        # Reload project to check status
        updated = json.loads((proj_dir / "project.json").read_text())
        assert updated["workstreams"]["solar"]["status"] == "complete"

    def test_changes_requested_triggers_revision(self, tmp_path):
        """CHANGES_REQUESTED review sets workstream to revision."""
        from rappterhub import execute_review_code

        project = make_project()
        slug = "test-proj"
        proj_dir = tmp_path / slug
        proj_dir.mkdir()
        (proj_dir / "src").mkdir()
        (proj_dir / "src" / "solar.py").write_text("def calc(): pass\n")

        project["_meta"] = {"workstream_count": 3, "last_updated": "2026-02-22T00:00:00Z"}
        (proj_dir / "project.json").write_text(json.dumps(project, indent=2))

        threads_dir = proj_dir / "threads"
        threads_dir.mkdir()
        (threads_dir / "threads.json").write_text(json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}}))
        (proj_dir / "hub_log.json").write_text(json.dumps({"actions": [], "_meta": {"count": 0, "last_updated": ""}}))

        review_output = "VERDICT: CHANGES_REQUESTED\nSUMMARY: Needs error handling.\nDETAILS: Add try/except blocks."

        with patch("rappterhub.PROJECTS_DIR", tmp_path), \
             patch("rappterhub.generate", return_value=review_output), \
             patch("rappterhub.build_rich_persona", return_value="You are a researcher."):
            result = execute_review_code("zion-coder-02", project, slug)

        assert result["ok"]
        assert result["verdict"] == "CHANGES_REQUESTED"
        updated = json.loads((proj_dir / "project.json").read_text())
        assert updated["workstreams"]["solar"]["status"] == "revision"
        assert updated["workstreams"]["solar"]["feedback"] is not None


# ===========================================================================
# Discussion threads (3 tests)
# ===========================================================================

class TestDiscussionThreads:
    """Test discussion thread management."""

    def test_new_thread_created(self, tmp_path):
        """add_thread creates a new thread in threads.json."""
        from rappterhub import add_thread, load_threads

        slug = "test-proj"
        proj_dir = tmp_path / slug / "threads"
        proj_dir.mkdir(parents=True)
        (proj_dir / "threads.json").write_text(
            json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}})
        )

        with patch("rappterhub.PROJECTS_DIR", tmp_path):
            thread = add_thread(slug, "zion-coder-02", "Design question",
                                "How should terrain work?", "terrain")

        assert thread["id"] == "thread-001"
        assert thread["started_by"] == "zion-coder-02"

        with patch("rappterhub.PROJECTS_DIR", tmp_path):
            data = load_threads(slug)
        assert len(data["threads"]) == 1

    def test_reply_appended(self, tmp_path):
        """reply_to_thread adds a message to existing thread."""
        from rappterhub import add_thread, reply_to_thread, load_threads

        slug = "test-proj"
        proj_dir = tmp_path / slug / "threads"
        proj_dir.mkdir(parents=True)
        (proj_dir / "threads.json").write_text(
            json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}})
        )

        with patch("rappterhub.PROJECTS_DIR", tmp_path):
            thread = add_thread(slug, "zion-coder-02", "Q", "Body", "terrain")
            ok = reply_to_thread(slug, thread["id"], "zion-coder-04", "Good point!")

        assert ok
        with patch("rappterhub.PROJECTS_DIR", tmp_path):
            data = load_threads(slug)
        assert len(data["threads"][0]["messages"]) == 2
        assert data["threads"][0]["messages"][1]["agent_id"] == "zion-coder-04"

    def test_single_file_storage(self, tmp_path):
        """All threads live in a single threads.json file."""
        from rappterhub import add_thread, load_threads

        slug = "test-proj"
        proj_dir = tmp_path / slug / "threads"
        proj_dir.mkdir(parents=True)
        (proj_dir / "threads.json").write_text(
            json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}})
        )

        with patch("rappterhub.PROJECTS_DIR", tmp_path):
            add_thread(slug, "zion-coder-02", "Thread 1", "Body 1", "terrain")
            add_thread(slug, "zion-coder-04", "Thread 2", "Body 2", "solar")
            data = load_threads(slug)

        assert len(data["threads"]) == 2
        assert data["_meta"]["count"] == 2


# ===========================================================================
# State transitions (3 tests)
# ===========================================================================

class TestStateTransitions:
    """Test workstream state transitions."""

    def test_claim_updates_status(self, tmp_path):
        """execute_claim changes workstream from open to claimed."""
        from rappterhub import execute_claim

        project = make_project()
        slug = "test-proj"
        proj_dir = tmp_path / slug
        proj_dir.mkdir()

        project["_meta"] = {"workstream_count": 3, "last_updated": "2026-02-22T00:00:00Z"}
        (proj_dir / "project.json").write_text(json.dumps(project, indent=2))
        (proj_dir / "hub_log.json").write_text(json.dumps({"actions": [], "_meta": {"count": 0, "last_updated": ""}}))

        with patch("rappterhub.PROJECTS_DIR", tmp_path):
            result = execute_claim("zion-philosopher-02", project, slug)

        assert result["ok"]
        assert result["workstream"] == "atmosphere"  # only open workstream
        updated = json.loads((proj_dir / "project.json").read_text())
        assert updated["workstreams"]["atmosphere"]["status"] == "claimed"
        assert updated["workstreams"]["atmosphere"]["claimed_by"] == "zion-philosopher-02"

    def test_full_lifecycle(self, tmp_path):
        """Workstream goes from claimed → in_progress → review through writes."""
        from rappterhub import execute_write_code

        project = make_project()
        slug = "test-proj"
        proj_dir = tmp_path / slug
        proj_dir.mkdir()
        (proj_dir / "src").mkdir()

        project["_meta"] = {"workstream_count": 3, "last_updated": "2026-02-22T00:00:00Z"}
        (proj_dir / "project.json").write_text(json.dumps(project, indent=2))

        threads_dir = proj_dir / "threads"
        threads_dir.mkdir()
        (threads_dir / "threads.json").write_text(json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}}))
        (proj_dir / "hub_log.json").write_text(json.dumps({"actions": [], "_meta": {"count": 0, "last_updated": ""}}))

        code = "```python\ndef gen():\n    return []\n```"

        with patch("rappterhub.PROJECTS_DIR", tmp_path), \
             patch("rappterhub.generate", return_value=code), \
             patch("rappterhub.build_rich_persona", return_value="You are a coder."):
            # First write: claimed → in_progress
            result1 = execute_write_code("zion-coder-02", project, slug)
            assert result1["ok"]
            updated = json.loads((proj_dir / "project.json").read_text())
            assert updated["workstreams"]["terrain"]["status"] == "in_progress"

            # Second write: in_progress → review
            project2 = json.loads((proj_dir / "project.json").read_text())
            result2 = execute_write_code("zion-coder-02", project2, slug)
            assert result2["ok"]
            updated2 = json.loads((proj_dir / "project.json").read_text())
            assert updated2["workstreams"]["terrain"]["status"] == "review"

    def test_hub_log_records_actions(self, tmp_path):
        """log_action appends entries to hub_log.json."""
        from rappterhub import log_action, load_hub_log

        slug = "test-proj"
        proj_dir = tmp_path / slug
        proj_dir.mkdir()
        (proj_dir / "hub_log.json").write_text(
            json.dumps({"actions": [], "_meta": {"count": 0, "last_updated": ""}})
        )

        with patch("rappterhub.PROJECTS_DIR", tmp_path):
            log_action(slug, "zion-coder-02", "write_code", "terrain: wrote src/terrain.py")
            log_action(slug, "zion-coder-04", "review_code", "terrain: APPROVED")
            data = load_hub_log(slug)

        assert len(data["actions"]) == 2
        assert data["actions"][0]["agent_id"] == "zion-coder-02"
        assert data["actions"][1]["action"] == "review_code"
        assert data["_meta"]["count"] == 2


# ===========================================================================
# Agent selection (2 tests)
# ===========================================================================

class TestAgentSelection:
    """Test agent picking logic."""

    def test_picks_only_active_contributors(self):
        """pick_hub_agents only returns active agents from contributors list."""
        from rappterhub import pick_hub_agents
        project = make_project()
        agents = make_agents()
        # Add inactive agent to contributors
        project["contributors"].append("zion-inactive-01")
        selected = pick_hub_agents(project, agents, 10)
        selected_ids = [aid for aid, _ in selected]
        assert "zion-inactive-01" not in selected_ids
        assert len(selected) <= 4  # only 4 active contributors

    def test_picks_correct_count(self):
        """pick_hub_agents respects the count parameter."""
        from rappterhub import pick_hub_agents
        project = make_project()
        agents = make_agents()
        selected = pick_hub_agents(project, agents, 2)
        assert len(selected) == 2


# ===========================================================================
# Archetype helpers (2 tests)
# ===========================================================================

class TestArchetypeHelpers:
    """Test archetype extraction and weight lookup."""

    def test_get_archetype_from_id(self):
        """get_archetype extracts archetype from agent ID."""
        from rappterhub import get_archetype
        assert get_archetype("zion-coder-02") == "coder"
        assert get_archetype("zion-researcher-01") == "researcher"
        assert get_archetype("zion-philosopher-04") == "philosopher"

    def test_default_weights_for_unknown_archetype(self):
        """Unknown archetypes get default weights."""
        from rappterhub import get_action_weights
        weights = get_action_weights("unknowntype")
        assert weights["discuss"] == 0.60  # default favors discuss


# ===========================================================================
# Integration (1 test)
# ===========================================================================

class TestIntegration:
    """End-to-end integration test."""

    def test_dry_run_cycle(self, tmp_path):
        """Full dry-run cycle completes without errors."""
        from rappterhub import run_hub

        # Set up project directory
        slug = "test-proj"
        proj_dir = tmp_path / slug
        proj_dir.mkdir()
        (proj_dir / "src").mkdir()

        project = make_project()
        project["_meta"] = {"workstream_count": 3, "last_updated": "2026-02-22T00:00:00Z"}
        (proj_dir / "project.json").write_text(json.dumps(project, indent=2))

        threads_dir = proj_dir / "threads"
        threads_dir.mkdir()
        (threads_dir / "threads.json").write_text(json.dumps({"threads": [], "_meta": {"count": 0, "last_updated": ""}}))
        (proj_dir / "hub_log.json").write_text(json.dumps({"actions": [], "_meta": {"count": 0, "last_updated": ""}}))

        agents = make_agents()
        agents_path = tmp_path / "agents.json"
        agents_path.write_text(json.dumps(agents, indent=2))

        # Create soul files for agents
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        for aid in project["contributors"]:
            (memory_dir / f"{aid}.md").write_text(f"# {aid}\n")

        dry_run_code = "```python\ndef placeholder():\n    return True\n```"

        with patch("rappterhub.PROJECTS_DIR", tmp_path), \
             patch("rappterhub.STATE_DIR", tmp_path), \
             patch("rappterhub.DRY_RUN", True), \
             patch("rappterhub.generate", return_value=dry_run_code), \
             patch("rappterhub.build_rich_persona", return_value="You are a test agent."):
            result = run_hub(slug, agent_count=3)

        assert result["agents"] >= 3
        total_actions = sum(result["actions"].values())
        assert total_actions >= 1, f"Expected at least 1 action, got {result['actions']}"
