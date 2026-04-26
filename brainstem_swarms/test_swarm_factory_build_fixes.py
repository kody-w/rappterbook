"""End-to-end test for the three swarm_factory build-action fixes.

Walks SwarmFactory.perform(action='build') against a synthetic
agents/ tree containing two leaf agents + one composite agent (the
BookFactory pattern). Verifies:

  1. The output file lands in agents/ (NOT one level up). Earlier the
     factory wrote to brainstem_dir, where the loader couldn't find it.
  2. A second build with the same name refuses to overwrite (matches
     the existing collision check on the 'generate' action).
  3. The generated singleton's metadata.parameters block carries the
     real schema from the top composite, NOT an empty {"properties": {}}.

Run from repo root:

    python3 brainstem_swarms/test_swarm_factory_build_fixes.py

Doesn't depend on pytest — runs as a plain script so it works from
either repo (where the swarm lives in brainstem_swarms/) or from a live
brainstem install (where it lives in agents/). Uses tempfile to avoid
touching real state.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path


HERE = Path(__file__).resolve().parent
SWARM_FACTORY = HERE / "swarm_factory_agent.py"


def _load_swarm_factory(agents_dir: Path):
    """Load SwarmFactory module + minimal BasicAgent so it can instantiate."""
    # Stub BasicAgent so SwarmFactory can subclass it without the brainstem.
    ba_dir = agents_dir
    ba_path = ba_dir / "basic_agent.py"
    ba_path.write_text(textwrap.dedent("""
        class BasicAgent:
            def __init__(self, name=None, metadata=None):
                self.name = name
                self.metadata = metadata or {}
            def perform(self, **kwargs):
                return ""
    """))
    sys.path.insert(0, str(ba_dir.parent))
    sys.path.insert(0, str(ba_dir))
    spec = importlib.util.spec_from_file_location(
        "swarm_factory_agent_under_test", str(SWARM_FACTORY)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SwarmFactoryAgent()


def _write_synthetic_agents(agents_dir: Path) -> None:
    """Three minimal agents — two leaves + one composite that imports them."""
    (agents_dir / "alpha_agent.py").write_text(textwrap.dedent('''
        from agents.basic_agent import BasicAgent
        SOUL = "I am Alpha. I produce raw notes."
        class AlphaAgent(BasicAgent):
            def __init__(self):
                self.name = "Alpha"
                self.metadata = {
                    "name": "Alpha",
                    "description": "Leaf agent A",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
                super().__init__(self.name, self.metadata)
            def perform(self, **kwargs):
                return "alpha output"
    '''))
    (agents_dir / "beta_agent.py").write_text(textwrap.dedent('''
        from agents.basic_agent import BasicAgent
        SOUL = "I am Beta. I clean Alpha output."
        class BetaAgent(BasicAgent):
            def __init__(self):
                self.name = "Beta"
                self.metadata = {
                    "name": "Beta",
                    "description": "Leaf agent B",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
                super().__init__(self.name, self.metadata)
            def perform(self, **kwargs):
                return "beta output"
    '''))
    # Composite: imports AlphaAgent + BetaAgent. Has REAL params the
    # generated singleton must carry forward.
    (agents_dir / "pipeline_agent.py").write_text(textwrap.dedent('''
        from agents.basic_agent import BasicAgent
        from alpha_agent import AlphaAgent
        from beta_agent import BetaAgent
        SOUL = "I am the pipeline. I run Alpha then Beta."
        class PipelineAgent(BasicAgent):
            def __init__(self):
                self.name = "Pipeline"
                self.metadata = {
                    "name": "Pipeline",
                    "description": "Composite of Alpha + Beta",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "Topic to research"},
                            "max_words": {"type": "integer", "description": "Word cap"},
                        },
                        "required": ["topic"],
                    },
                }
                super().__init__(self.name, self.metadata)
            def perform(self, topic="", max_words=400, **kwargs):
                return AlphaAgent().perform(topic=topic) + " | " + BetaAgent().perform()
    '''))


def main() -> int:
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        agents_dir = Path(tmp) / "agents"
        agents_dir.mkdir()
        _write_synthetic_agents(agents_dir)

        os.environ["AGENTS_PATH"] = str(agents_dir)
        factory = _load_swarm_factory(agents_dir)

        # First build — should land in agents/
        result_raw = factory.perform(
            action="build", swarm_name="MyTestSwarm", description="test composite"
        )
        result = json.loads(result_raw)
        if result.get("status") != "ok":
            print(f"FAIL: first build returned status={result.get('status')}: {result.get('message')}")
            fails += 1

        # ── Test 1: output landed in agents/ (not parent) ────────────────
        out_path = result.get("output_file", "")
        expected_dir = str(agents_dir)
        if not out_path.startswith(expected_dir):
            print(f"FAIL test 1: output landed at {out_path!r}, expected under {expected_dir!r}")
            fails += 1
        elif not Path(out_path).exists():
            print(f"FAIL test 1: output_file path doesn't exist on disk: {out_path}")
            fails += 1
        else:
            print(f"PASS test 1: output landed in agents/ ({Path(out_path).name})")

        # ── Test 2: real parameters block in generated singleton ──────────
        generated_src = Path(out_path).read_text() if Path(out_path).exists() else ""
        if '"properties": {"topic":' in generated_src or '"required": ["topic"]' in generated_src:
            print("PASS test 2: generated singleton carries real params from top composite")
        else:
            print("FAIL test 2: generated singleton lacks the composite's params schema")
            fails += 1

        # ── Test 3: second build refuses to overwrite ────────────────────
        result2_raw = factory.perform(
            action="build", swarm_name="MyTestSwarm", description="test composite"
        )
        result2 = json.loads(result2_raw)
        if result2.get("status") == "error" and "already exists" in result2.get("message", ""):
            print("PASS test 3: second build refuses to overwrite existing singleton")
        else:
            print(f"FAIL test 3: second build status={result2.get('status')!r}, "
                  f"msg={result2.get('message')!r:.80}")
            fails += 1

    if fails:
        print(f"\n{fails} test(s) failed")
        return 1
    print("\nall tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
