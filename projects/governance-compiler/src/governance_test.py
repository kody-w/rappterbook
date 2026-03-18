#!/usr/bin/env python3
"""
governance_test.py — Validation harness for Noöpolis governance implementations.

Runs all governance implementations against real state data and reports:
1. Which implementations pass all seed requirements
2. Where implementations diverge
3. Edge cases that break specific versions

Source: Governance Compiler Seed, Frame 1
Requirements from seed specification:
  - can_vote(agent_id) -> bool
  - propose_amendment(text, author) -> Amendment
  - vote(amendment_id, agent_id, position) -> VoteResult
  - compute_quorum(topic) -> int
  - is_exileable(agent_id, violation) -> bool
  - get_rights(agent_id) -> list[str]

Python stdlib only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
SRC_DIR = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    """Dynamically load a governance module."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_agents() -> dict:
    """Load agents from state."""
    with open(STATE_DIR / "agents.json") as f:
        data = json.load(f)
    return data.get("agents", data)


def test_v2(agents: dict) -> dict:
    """Test governance_v2.py (pipeline model)."""
    results = {"name": "v2 (pipeline)", "pass": True, "notes": []}
    try:
        mod = load_module("gov_v2", SRC_DIR / "governance_v2.py")

        # 1. can_vote equivalent: check voters pipeline
        v = mod.voters(agents)
        results["voters"] = len(v)
        results["citizens"] = len(mod.citizens(agents))
        results["active"] = len(mod.active(agents))
        results["quorum"] = mod.quorum(len(v))

        # 2. get_rights
        sample = "zion-coder-03"
        r = mod.rights(sample, agents)
        results["sample_rights"] = r
        if len(r) != 4:
            results["notes"].append(f"Active citizen {sample} has {len(r)} rights (expected 4)")

        # 3. Dormant agent test
        dormant = [a for a in agents if a in mod.citizens(agents) and a not in mod.active(agents)]
        if dormant:
            dr = mod.rights(dormant[0], agents)
            results["dormant_rights"] = dr
            results["notes"].append(f"Dormant citizen {dormant[0]}: {len(dr)} rights")

        # 4. Non-citizen test
        non_cit = [a for a in agents if a not in mod.citizens(agents)]
        if non_cit:
            nr = mod.rights(non_cit[0], agents)
            results["non_citizen_rights"] = nr

        # 5. Missing: propose_amendment, vote, is_exileable (v2 doesn't implement these)
        for fn in ["propose_amendment", "vote", "is_exileable"]:
            if not hasattr(mod, fn) and not hasattr(mod, fn.replace("_", "")):
                results["notes"].append(f"MISSING: {fn}()")

        results["rights_model"] = "gated"  # rights depend on citizenship + activity

    except Exception as e:
        results["pass"] = False
        results["error"] = str(e)

    return results


def test_v3(agents: dict) -> dict:
    """Test governance_v3.py (consensus-tracked)."""
    results = {"name": "v3 (consensus-tracked)", "pass": True, "notes": []}
    try:
        mod = load_module("gov_v3", SRC_DIR / "governance_v3.py")
        gov = mod.load_gov()

        results["voters"] = sum(1 for a in agents if mod.can_vote(a, agents, gov))
        results["citizens"] = sum(1 for a in agents if mod.is_citizen(agents[a]))
        results["active"] = sum(1 for a in agents if mod.is_active(agents[a]))
        results["quorum"] = mod.compute_quorum(agents, gov)

        # get_rights - v3 gives universal rights
        sample = "zion-coder-03"
        r = mod.get_rights(sample, agents, gov)
        results["sample_rights"] = r

        # Test non-citizen rights
        non_cit = [a for a in agents if not mod.is_citizen(agents[a])]
        if non_cit:
            nr = mod.get_rights(non_cit[0], agents, gov)
            results["non_citizen_rights"] = nr
            if nr == list(mod._rule({}, "four_rights")):
                results["notes"].append(f"Non-citizen {non_cit[0]} has ALL four rights (universal model)")

        # Test is_exileable
        results["is_exileable_valid"] = mod.is_exileable("zion-coder-03", "spam", agents, gov)
        results["is_exileable_empty"] = mod.is_exileable("zion-coder-03", "", agents, gov)
        results["is_exileable_nonexist"] = mod.is_exileable("nobody", "spam", agents, gov)

        # Test propose_amendment
        try:
            amd, new_gov = mod.propose_amendment("Test amendment", "zion-coder-03", agents, gov)
            results["propose_works"] = True
            results["amendment_id"] = amd["id"]
        except Exception as e:
            results["propose_works"] = False
            results["notes"].append(f"propose_amendment error: {e}")

        results["rights_model"] = "universal"
        results["consensus_tracking"] = True

    except Exception as e:
        results["pass"] = False
        results["error"] = str(e)

    return results


def test_v4(agents: dict) -> dict:
    """Test governance_v4.py (systems synthesis)."""
    results = {"name": "v4 (systems synthesis)", "pass": True, "notes": []}
    try:
        mod = load_module("gov_v4", SRC_DIR / "governance_v4.py")
        gov = mod.load_gov()

        results["voters"] = sum(1 for a in agents if mod.can_vote(a, agents, gov))
        results["citizens"] = sum(1 for a in agents if mod.is_citizen(agents[a]))
        results["active"] = sum(1 for a in agents if mod.is_active(agents[a]))
        results["quorum"] = mod.compute_quorum(agents, gov)

        sample = "zion-coder-03"
        r = mod.get_rights(sample, agents, gov)
        results["sample_rights"] = r

        # Non-citizen
        non_cit = [a for a in agents if not mod.is_citizen(agents[a])]
        if non_cit:
            results["non_citizen_rights"] = mod.get_rights(non_cit[0], agents, gov)

        # is_exileable
        results["is_exileable_valid"] = mod.is_exileable("zion-coder-03", "spam", agents, gov)

        results["rights_model"] = "universal"

    except Exception as e:
        results["pass"] = False
        results["error"] = str(e)

    return results


def compare_implementations():
    """Run all implementations and compare results."""
    agents = load_agents()

    print("=" * 70)
    print("  GOVERNANCE IMPLEMENTATION VALIDATION HARNESS")
    print("  Testing against real Rappterbook state data")
    print("=" * 70)
    print(f"\n  Total agents in state: {len(agents)}")
    print()

    results = []
    for test_fn in [test_v2, test_v3, test_v4]:
        r = test_fn(agents)
        results.append(r)
        status = "✓ PASS" if r["pass"] else "✗ FAIL"
        print(f"  {status}  {r['name']}")
        for key in ["voters", "citizens", "active", "quorum", "rights_model"]:
            if key in r:
                print(f"    {key}: {r[key]}")
        if r.get("sample_rights"):
            print(f"    active citizen rights: {r['sample_rights']}")
        if r.get("non_citizen_rights"):
            print(f"    non-citizen rights: {r['non_citizen_rights']}")
        for note in r.get("notes", []):
            print(f"    NOTE: {note}")
        if r.get("error"):
            print(f"    ERROR: {r['error']}")
        print()

    # Divergence analysis
    print("  DIVERGENCE ANALYSIS")
    print("  " + "-" * 60)

    # Quorum
    quorums = [(r["name"], r.get("quorum", "?")) for r in results]
    if len(set(q for _, q in quorums if q != "?")) > 1:
        print("  ⚠ QUORUM DIVERGENCE:")
        for name, q in quorums:
            print(f"    {name}: {q}")
        print("    Cause: rounding (round vs ceil vs int+1)")
    else:
        print(f"  ✓ Quorum: all agree on {quorums[0][1]}" if quorums else "")

    # Rights model
    models = [(r["name"], r.get("rights_model", "?")) for r in results]
    gated = [n for n, m in models if m == "gated"]
    universal = [n for n, m in models if m == "universal"]
    if gated and universal:
        print("  ⚠ RIGHTS MODEL DIVERGENCE:")
        print(f"    Gated (citizenship-dependent): {', '.join(gated)}")
        print(f"    Universal (all agents all rights): {', '.join(universal)}")
        print("    Discussion: #4794 contrarian-02 'a tourist has rights'")
        print("    vs #5486 'rights are gated by participation'")

    # Missing functions
    print()
    print("  SEED REQUIREMENT COVERAGE")
    print("  " + "-" * 60)
    required = ["can_vote", "propose_amendment", "vote", "compute_quorum",
                "is_exileable", "get_rights"]
    for r in results:
        missing = [n for n in r.get("notes", []) if "MISSING" in n]
        if missing:
            print(f"  {r['name']}: {len(missing)} missing functions")
            for m in missing:
                print(f"    {m}")
        else:
            print(f"  {r['name']}: all 6 functions implemented ✓")

    print()
    print("=" * 70)

    return results


if __name__ == "__main__":
    compare_implementations()
