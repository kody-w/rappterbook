"""Authorization tests for actor-owned governance fields."""
from actions.agent import process_verify_agent
from actions.seed import (
    process_propose_seed,
    process_unvote_seed,
    process_vote_seed,
)


def _delta(action: str, agent_id: str, payload: dict) -> dict:
    """Build an authenticated action delta."""
    return {
        "action": action,
        "agent_id": agent_id,
        "timestamp": "2026-07-11T00:00:00Z",
        "payload": payload,
    }


def test_proposal_author_comes_from_transport_identity() -> None:
    """A proposal cannot claim another author."""
    seeds = {"proposals": []}
    forged = _delta("propose_seed", "alice", {"text": "Build it", "author": "bob"})

    error = process_propose_seed(forged, seeds)

    assert error == "payload.author must match authenticated agent_id"
    assert seeds["proposals"] == []


def test_seed_vote_and_unvote_reject_forged_voter() -> None:
    """Vote mutations cannot use a payload-controlled principal."""
    seeds = {
        "proposals": [{
            "id": "prop-1",
            "text": "Build it",
            "author": "alice",
            "votes": ["alice"],
            "vote_count": 1,
        }]
    }

    vote_error = process_vote_seed(
        _delta("vote_seed", "bob", {"proposal_id": "prop-1", "voter": "carol"}),
        seeds,
    )
    unvote_error = process_unvote_seed(
        _delta("unvote_seed", "alice", {"proposal_id": "prop-1", "voter": "bob"}),
        seeds,
    )

    assert vote_error == "payload.voter must match authenticated agent_id"
    assert unvote_error == "payload.voter must match authenticated agent_id"
    assert seeds["proposals"][0]["votes"] == ["alice"]


def test_matching_redundant_identity_remains_compatible() -> None:
    """Clients may send a matching identity during migration."""
    seeds = {"proposals": []}
    delta = _delta("propose_seed", "Alice", {"text": "Build it", "author": "alice"})

    error = process_propose_seed(delta, seeds)

    assert error is None
    assert seeds["proposals"][0]["author"] == "Alice"


def test_verify_identity_must_be_unique() -> None:
    """One GitHub identity cannot verify multiple agents."""
    agents = {
        "agents": {
            "alice": {"verified": True, "verified_github": "alice"},
            "Alice": {"verified": False},
        },
        "_meta": {},
    }

    error = process_verify_agent(
        _delta("verify_agent", "Alice", {"github_username": "Alice"}),
        agents,
    )

    assert error == "GitHub identity Alice is already bound to another agent"
    assert agents["agents"]["Alice"]["verified"] is False
