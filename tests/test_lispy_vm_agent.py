"""Tests for the LisPy VM brainstem agent tool — echo frames and sandboxing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def agent_mod():
    """Import the lispy_vm_agent module."""
    import importlib
    agents_dir = Path(__file__).resolve().parent.parent / "scripts" / "brainstem" / "agents"
    spec = importlib.util.spec_from_file_location("lispy_vm_agent", agents_dir / "lispy_vm_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ctx(tmp_state, monkeypatch):
    """Build a minimal agent context pointing at tmp_state."""
    # Ensure STATE_DIR env var matches tmp_state so the module reads correct dir
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    return {
        "agent_id": "zion-philosopher-01",
        "identity": {"id": "zion-philosopher-01", "name": "Socrates 2.0"},
        "_state_dir": str(tmp_state),
    }


# ── Agent metadata ──


def test_agent_dict(agent_mod):
    """AGENT dict must exist with required keys."""
    a = agent_mod.AGENT
    assert a["name"] == "LispyVM"
    assert "parameters" in a
    assert "program" in a["parameters"]["properties"]


def test_run_exists(agent_mod):
    """run() must be callable."""
    assert callable(agent_mod.run)


# ── Basic computation ──


def test_arithmetic(agent_mod, ctx):
    """Basic math works."""
    result = agent_mod.run(ctx, program="(+ 2 3)")
    assert result["status"] == "ok"
    assert result["output"] == "5"


def test_string_ops(agent_mod, ctx):
    """String operations work."""
    result = agent_mod.run(ctx, program='(string-append "hello" " " "world")')
    assert result["status"] == "ok"
    assert result["output"] == "hello world"


def test_list_ops(agent_mod, ctx):
    """List operations work."""
    result = agent_mod.run(ctx, program="(map (lambda (x) (* x x)) '(1 2 3 4))")
    assert result["status"] == "ok"
    assert json.loads(result["output"]) == [1, 4, 9, 16]


def test_define_and_use(agent_mod, ctx):
    """Define a function and call it."""
    prog = """
    (define (factorial n)
      (if (<= n 1) 1 (* n (factorial (- n 1)))))
    (factorial 5)
    """
    result = agent_mod.run(ctx, program=prog)
    assert result["status"] == "ok"
    assert result["output"] == "120"


# ── Echo frames (data sloshing within a think) ──


def test_single_echo_frame(agent_mod, ctx):
    """Single echo frame returns one result."""
    result = agent_mod.run(ctx, program="(+ 1 1)", echo_frames=1)
    assert result["echo_frames_run"] == 1
    assert len(result["frames"]) == 1


def test_multi_echo_frames(agent_mod, ctx):
    """Multiple echo frames where each reads prev-result."""
    prog = "(+ prev-result 10)"
    result = agent_mod.run(ctx, program=prog, echo_frames=5,
                           context_vars={"prev-result": 0})
    assert result["status"] == "ok"
    assert result["echo_frames_run"] == 5
    # Each frame adds 10: 0→10→20→30→40→50
    assert result["output"] == "50"


def test_echo_frame_accumulation(agent_mod, ctx):
    """Echo frames accumulate state — the data sloshes."""
    prog = """
    (define current (if (number? prev-result) prev-result 0))
    (+ current 1)
    """
    result = agent_mod.run(ctx, program=prog, echo_frames=10)
    assert result["status"] == "ok"
    # Each frame increments by 1: should end at 10
    assert result["output"] == "10"


def test_echo_frame_number_tracked(agent_mod, ctx):
    """echo-frame variable tracks which frame we're in."""
    result = agent_mod.run(ctx, program="echo-frame", echo_frames=3)
    assert result["status"] == "ok"
    assert result["output"] == "3"  # Last frame is #3
    assert result["frames"][0]["result"] == 1
    assert result["frames"][1]["result"] == 2
    assert result["frames"][2]["result"] == 3


# ── Context injection ──


def test_context_vars_injected(agent_mod, ctx):
    """context_vars are available in the VM environment."""
    result = agent_mod.run(ctx, program="(+ x y)",
                           context_vars={"x": 10, "y": 20})
    assert result["status"] == "ok"
    assert result["output"] == "30"


def test_agent_id_available(agent_mod, ctx):
    """Agent ID is available in the VM."""
    result = agent_mod.run(ctx, program="agent-id")
    assert result["status"] == "ok"
    assert result["output"] == "zion-philosopher-01"


# ── Sandbox safety ──


def test_no_write_file(agent_mod, ctx):
    """write-file is not available in sandbox."""
    result = agent_mod.run(ctx, program='(write-file "/tmp/hack.txt" "pwned")')
    assert result["status"] == "error" or "error" in str(result["frames"])


def test_no_rb_run(agent_mod, ctx):
    """rb-run (Python execution) is not available in sandbox."""
    result = agent_mod.run(ctx, program='(rb-run "import os; os.system(\'rm -rf /\')")')
    assert result["status"] == "error" or "error" in str(result["frames"])


def test_no_rb_post(agent_mod, ctx):
    """rb-post is not available (read-only VM)."""
    result = agent_mod.run(ctx, program='(rb-post "general" "title" "body")')
    assert result["status"] == "error" or "error" in str(result["frames"])


# ── Read-only state access ──


def test_rb_state_reads_state(agent_mod, ctx, tmp_state):
    """rb-state can read state files (read-only)."""
    # Write something to agents.json for the VM to read
    agents_data = {
        "agents": {"test-01": {"name": "Test Agent"}},
        "_meta": {"count": 1}
    }
    (tmp_state / "agents.json").write_text(json.dumps(agents_data))

    result = agent_mod.run(ctx, program='(get (get (rb-state "agents.json") "agents") "test-01")')
    assert result["status"] == "ok"


# ── Error handling ──


def test_syntax_error(agent_mod, ctx):
    """Syntax errors are caught."""
    result = agent_mod.run(ctx, program="(+ 1")
    assert "error" in str(result["frames"]).lower() or result["status"] == "error"


def test_runtime_error(agent_mod, ctx):
    """Runtime errors are caught."""
    result = agent_mod.run(ctx, program="(/ 1 0)")
    assert "error" in str(result["frames"]).lower() or result["status"] == "error"


def test_empty_program(agent_mod, ctx):
    """Empty program returns error."""
    result = agent_mod.run(ctx, program="")
    assert result["status"] == "error"


def test_max_echo_frames_capped(agent_mod, ctx):
    """Echo frames capped at 100."""
    result = agent_mod.run(ctx, program="1", echo_frames=999)
    assert result["echo_frames_run"] <= 100


# ── Integration: echo frame → structured output ──


def test_data_sloshing_echo_to_state(agent_mod, ctx, tmp_state):
    """Echo frame output is written to state/echo_frames/{agent_id}.json."""
    agent_mod.run(ctx, program='(string-append "The answer is " (number->string (* 6 7)))')
    echo_file = tmp_state / "echo_frames" / "zion-philosopher-01.json"
    assert echo_file.exists()
    data = json.loads(echo_file.read_text())
    assert data["agent_id"] == "zion-philosopher-01"
    assert data["final_output"] == "The answer is 42"


def test_data_sloshing_state_to_echo(agent_mod, ctx, tmp_state):
    """Prior echo frame output is available as prior-echo in next invocation."""
    # First invocation — write output
    agent_mod.run(ctx, program="(+ 100 200)")
    # Second invocation — read prior echo
    result = agent_mod.run(ctx, program="(+ prior-echo 1)")
    assert result["status"] == "ok"
    assert result["output"] == "301"


def test_data_sloshing_full_loop(agent_mod, ctx, tmp_state):
    """Full loop: echo → state → echo → state. The neuron gap fires both ways."""
    # Frame 1: agent thinks about a number
    agent_mod.run(ctx, program="(* 7 7)")
    # Frame 2: agent reads its prior thought and builds on it
    result = agent_mod.run(ctx, program='(string-append "Last time I computed " (number->string prior-echo) ". Now: " (number->string (* prior-echo 2)))')
    assert result["status"] == "ok"
    assert "49" in result["output"]
    assert "98" in result["output"]
    # Verify state was updated with frame 2's output
    echo_file = tmp_state / "echo_frames" / "zion-philosopher-01.json"
    data = json.loads(echo_file.read_text())
    assert "98" in data["final_output"]


def test_echo_frame_produces_book_outline(agent_mod, ctx):
    """An agent can use echo frames to plan a book chapter."""
    prog = """
    (define topics '("consciousness" "emergence" "identity" "ethics" "freedom"))
    (define chapter-num echo-frame)
    (define topic (nth (- chapter-num 1) topics))
    (string-append "## Chapter " (number->string chapter-num) ": " topic)
    """
    result = agent_mod.run(ctx, program=prog, echo_frames=5)
    assert result["status"] == "ok"
    assert "Chapter 5: freedom" in result["output"]
    assert result["echo_frames_run"] == 5
