"""LisPy agents must load when the brainstem is imported from scripts/ (as cloud_brainstem.py does)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_lispy_agents_load_from_scripts_dir():
    code = (
        "import sys; sys.path.insert(0, 'scripts');"
        "from pathlib import Path;"
        "from brainstem.rappter_agent import _load_lispy_agent;"
        "paths = sorted(Path('scripts/brainstem/agents').glob('*_agent.lispy'));"
        "assert paths, 'no lispy agents found';"
        "loaded = [p.name for p in paths if _load_lispy_agent(p)];"
        "print(len(loaded), len(paths));"
        "assert loaded, 'no lispy agent loaded'"
    )
    # A fresh interpreter, so other tests' sys.path changes cannot hide the bug.
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No module named 'lispy'" not in result.stdout
