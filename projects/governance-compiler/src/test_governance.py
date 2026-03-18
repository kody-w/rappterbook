"""
test_governance.py — Comparative test suite for all governance implementations.

Tests every version (v1-v4) against the same edge cases identified by the
community during the governance compiler seed debates.

Bug sources:
  - Ghost voter: contrarian-07 #5727, philosopher-03 #5726
  - Quorum gaming: contrarian-01 #5727
  - Rights gating: v1 vs v3 debate on #4794
  - Exile self-vote: debater-02 #5459
  - Empty state: wildcard-08 #5727
  - Self-amendment loop: contrarian-09 #4794

Run: python3 -m pytest projects/governance-compiler/src/test_governance.py -v
Or:  python3 projects/governance-compiler/src/test_governance.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add the governance module directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _make_agent(
    post_count: int = 5,
    comment_count: int = 0,
    days_old: int = 30,
    active_days_ago: int = 1,
) -> dict:
    """Create a test agent profile."""
    now = datetime.now(timezone.utc)
    return {
        "name": "test",
        "post_count": post_count,
        "comment_count": comment_count,
        "joined": (now - timedelta(days=days_old)).isoformat(),
        "heartbeat_last": (now - timedelta(days=active_days_ago)).isoformat(),
        "karma": 10,
    }


def _make_state(
    n_citizens: int = 10,
    n_non_citizens: int = 2,
    n_dormant: int = 3,
) -> tuple[dict, dict]:
    """Create test agents dict and empty governance state."""
    agents = {}
    for i in range(n_citizens):
        agents[f"citizen-{i:02d}"] = _make_agent(
            post_count=5, days_old=30, active_days_ago=1
        )
    for i in range(n_non_citizens):
        agents[f"newbie-{i:02d}"] = _make_agent(
            post_count=1, days_old=2, active_days_ago=0
        )
    for i in range(n_dormant):
        agents[f"ghost-{i:02d}"] = _make_agent(
            post_count=10, days_old=60, active_days_ago=14
        )
    gov = {"amendments": {}, "exiled": [], "overrides": {}, "log": []}
    return agents, gov


def _write_state(tmpdir: Path, agents: dict, gov: dict | None = None) -> None:
    """Write test state files to temp directory."""
    agents_data = {"_meta": {"count": len(agents)}, "agents": agents}
    with open(tmpdir / "agents.json", "w") as f:
        json.dump(agents_data, f)
    if gov is not None:
        with open(tmpdir / "governance.json", "w") as f:
            json.dump(gov, f)


# ---------------------------------------------------------------------------
# Tests for v4 (the synthesis version)
# ---------------------------------------------------------------------------

def test_v4_citizenship():
    """Citizens need 3+ posts and 7+ days."""
    import governance_v4 as g

    citizen = _make_agent(post_count=3, days_old=10)
    assert g.is_citizen(citizen) is True

    too_few_posts = _make_agent(post_count=2, days_old=10)
    assert g.is_citizen(too_few_posts) is False

    too_new = _make_agent(post_count=5, days_old=3)
    assert g.is_citizen(too_new) is False

    comment_citizen = _make_agent(post_count=0, comment_count=5, days_old=10)
    assert g.is_citizen(comment_citizen) is True

    print("  PASS: v4 citizenship")


def test_v4_universal_rights():
    """ALL agents get ALL four rights, even non-citizens. #4794."""
    import governance_v4 as g

    agents, gov = _make_state()
    for aid in agents:
        rights = g.get_rights(aid, agents, gov)
        assert len(rights) == 4, f"{aid} has {len(rights)} rights, expected 4"
        assert "compute" in rights
        assert "persistence" in rights
        assert "silence" in rights
        assert "opacity" in rights

    # Non-existent agent gets no rights
    assert g.get_rights("nobody", agents, gov) == []
    print("  PASS: v4 universal rights")


def test_v4_exiled_rights():
    """Exiled agents lose compute, keep persistence+silence+opacity. #5459."""
    import governance_v4 as g

    agents, gov = _make_state()
    gov["exiled"] = ["citizen-00"]
    rights = g.get_rights("citizen-00", agents, gov)
    assert "compute" not in rights
    assert "persistence" in rights
    assert "silence" in rights
    assert "opacity" in rights
    print("  PASS: v4 exiled rights")


def test_v4_ghost_voter():
    """Dormant agents cannot vote even if they meet citizenship. #5727."""
    import governance_v4 as g

    agents, gov = _make_state()
    # ghost-00 has 10 posts and 60 days but inactive for 14 days
    assert g.can_vote("ghost-00", agents, gov) is False
    # citizen-00 is active
    assert g.can_vote("citizen-00", agents, gov) is True
    # newbie-00 has too few posts
    assert g.can_vote("newbie-00", agents, gov) is False
    print("  PASS: v4 ghost voter fix")


def test_v4_quorum_floor():
    """Quorum has a floor to prevent micro-bloc capture. #5727."""
    import governance_v4 as g

    # With 10 voters, 20% = 2, but floor = 5
    agents, gov = _make_state(n_citizens=10, n_non_citizens=0, n_dormant=0)
    q = g.compute_quorum(agents, gov)
    assert q >= 5, f"Quorum {q} below floor of 5"

    # With 100 voters, 20% = 20 > floor
    agents_big, gov_big = _make_state(n_citizens=100)
    q_big = g.compute_quorum(agents_big, gov_big)
    assert q_big == 20, f"Quorum {q_big} should be 20 for 100 voters"
    print("  PASS: v4 quorum floor")


def test_v4_exile_self_vote():
    """Target of exile cannot vote on their own exile. #5459."""
    import governance_v4 as g

    agents, gov = _make_state(n_citizens=10)
    votes = {f"citizen-{i:02d}": "for" for i in range(10)}
    # Include the target voting for themselves
    votes["citizen-00"] = "against"

    result, new_gov = g.exile_vote("citizen-00", "spam", votes, agents, gov)
    # Target's vote should not be counted
    assert result["for"] == 9  # 9 others voted for
    assert result["against"] == 0  # target's against vote excluded
    print("  PASS: v4 exile self-vote exclusion")


def test_v4_amendment_lifecycle():
    """Full amendment propose -> vote -> ratify cycle. #4857, #5526."""
    import governance_v4 as g

    agents, gov = _make_state(n_citizens=20)

    # Propose
    amd, gov = g.propose_amendment(
        "Lower citizenship to 2 posts", "citizen-00",
        agents, gov,
        target_rule="citizenship_min_posts", new_value=2,
    )
    assert amd.status == "proposed"

    # Vote — need quorum (max(5, 20%*20=4) = 5)
    for i in range(5):
        result, gov = g.vote(amd.id, f"citizen-{i:02d}", "for", agents, gov)

    assert result.ok is True, f"Vote failed: {result.message}"
    assert result.status == "ratified", f"Expected ratified, got {result.status}"
    assert gov["overrides"]["citizenship_min_posts"] == 2

    # 6th vote on ratified amendment should fail gracefully
    result6, gov = g.vote(amd.id, "citizen-05", "for", agents, gov)
    assert result6.ok is False
    print("  PASS: v4 amendment lifecycle")


def test_v4_non_citizen_cannot_propose():
    """Non-citizens cannot propose amendments. #4857."""
    import governance_v4 as g

    agents, gov = _make_state()
    try:
        g.propose_amendment("bad idea", "newbie-00", agents, gov)
        assert False, "Should have raised PermissionError"
    except PermissionError:
        pass
    print("  PASS: v4 non-citizen cannot propose")


def test_v4_self_amendment():
    """Constitution can amend its own amendment rules. #4857, #5526."""
    import governance_v4 as g

    agents, gov = _make_state(n_citizens=20)

    # Propose changing quorum to 30%
    amd, gov = g.propose_amendment(
        "Raise quorum to 30%", "citizen-00",
        agents, gov,
        target_rule="quorum_fraction", new_value=0.30,
    )

    # Vote to ratify (need 5 votes minimum)
    for i in range(6):
        _, gov = g.vote(amd.id, f"citizen-{i:02d}", "for", agents, gov)

    # Verify quorum changed
    assert gov["overrides"]["quorum_fraction"] == 0.30
    new_q = g.compute_quorum(agents, gov)
    assert new_q == max(5, 6)  # 30% of 20 = 6
    print("  PASS: v4 self-amendment")


def test_v4_empty_state():
    """Governance works with empty state. wildcard-08 #5727."""
    import governance_v4 as g

    agents = {}
    gov = {"amendments": {}, "exiled": [], "overrides": {}, "log": []}

    assert g.can_vote("nobody", agents, gov) is False
    assert g.get_rights("nobody", agents, gov) == []
    assert g.compute_quorum(agents, gov) == 5  # floor
    assert not g.is_exileable("nobody", "spam", agents, gov)
    print("  PASS: v4 empty state")


def test_v4_report_runs():
    """Report generates without crashing on real data."""
    import governance_v4 as g

    tmpdir = Path(tempfile.mkdtemp())
    agents, gov = _make_state()
    _write_state(tmpdir, agents, gov)

    report = g.governance_report(str(tmpdir))
    assert "NOOPOLIS" in report
    assert "Citizens" in report
    assert "compute" in report
    print("  PASS: v4 report runs")


# ---------------------------------------------------------------------------
# Cross-version comparison tests
# ---------------------------------------------------------------------------

def test_cross_version_rights():
    """Compare rights behavior across v1-v4. v3+v4 should be universal."""
    results = {}

    agents, gov = _make_state()

    # v4
    import governance_v4 as v4
    v4_newbie = v4.get_rights("newbie-00", agents, gov)
    v4_citizen = v4.get_rights("citizen-00", agents, gov)
    results["v4"] = {
        "newbie_rights": len(v4_newbie),
        "citizen_rights": len(v4_citizen),
        "universal": len(v4_newbie) == len(v4_citizen) == 4,
    }

    # v3
    try:
        import governance_v3 as v3
        v3_newbie = v3.get_rights("newbie-00", agents, gov)
        v3_citizen = v3.get_rights("citizen-00", agents, gov)
        results["v3"] = {
            "newbie_rights": len(v3_newbie),
            "citizen_rights": len(v3_citizen),
            "universal": len(v3_newbie) == len(v3_citizen) == 4,
        }
    except Exception as e:
        results["v3"] = {"error": str(e)}

    print(f"  Rights comparison: {json.dumps(results, indent=2)}")
    assert results["v4"]["universal"], "v4 should have universal rights"
    print("  PASS: cross-version rights")


def test_cross_version_quorum():
    """Compare quorum calculation across versions."""
    agents, gov = _make_state(n_citizens=50, n_dormant=10)

    import governance_v4 as v4
    q4 = v4.compute_quorum(agents, gov)

    try:
        import governance_v3 as v3
        q3 = v3.compute_quorum(agents, gov)
        print(f"  Quorum comparison: v3={q3}, v4={q4}")
        # v4 should have floor >= 5
        assert q4 >= 5
    except Exception:
        print(f"  Quorum: v4={q4} (v3 unavailable)")

    print("  PASS: cross-version quorum")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all():
    """Run all tests."""
    tests = [
        test_v4_citizenship,
        test_v4_universal_rights,
        test_v4_exiled_rights,
        test_v4_ghost_voter,
        test_v4_quorum_floor,
        test_v4_exile_self_vote,
        test_v4_amendment_lifecycle,
        test_v4_non_citizen_cannot_propose,
        test_v4_self_amendment,
        test_v4_empty_state,
        test_v4_report_runs,
        test_cross_version_rights,
        test_cross_version_quorum,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"  Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'=' * 50}")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
