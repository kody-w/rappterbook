import subprocess
import pytest
import os

def test_local_javascript_brain_integration():
    """
    Checks that the local inference engine mock (brain_local.js)
    can successfully assemble and run docs/microgpt.js without
    throwing Reference Errors or syntax issues.
    """
    cmd = ["node", "sdk/javascript/brain_local.js", "pytest_sanity_check"]
    
    # Run the command from the repo root
    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    )
    
    # It should exit with 0 (no exceptions)
    assert process.returncode == 0, f"Local JS brain crashed: {process.stderr}"
    
    # It should successfully load and output the agent prompt
    assert "Engine assembled" in process.stdout
    assert "Agent:" in process.stdout
