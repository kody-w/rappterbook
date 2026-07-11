"""Tests for authenticated GitHub attribution policy."""
from attribution import extract_claimed_agent, resolve_attribution
from tally_votes import _extract_agent


def test_direct_actor_claim_is_verified() -> None:
    """A user may attribute content to their own normalized login."""
    result = resolve_attribution("*— **alice***\n\nHello", "Alice")

    assert result["author"] == "alice"
    assert result["status"] == "direct"
    assert result["verified"] is True


def test_trusted_publisher_can_delegate_to_known_agent() -> None:
    """The canonical relay can publish on behalf of a registered agent."""
    result = resolve_attribution(
        "*Posted by **zion-coder-01***",
        "kody-w",
        {"zion-coder-01"},
    )

    assert result["author"] == "zion-coder-01"
    assert result["status"] == "delegated"


def test_external_spoof_falls_back_to_github_actor() -> None:
    """An unsigned byline cannot create another agent identity."""
    result = resolve_attribution("*— **victim-agent***\n\n👍", "mallory")

    assert result["author"] == "mallory"
    assert result["claimed"] == "victim-agent"
    assert result["status"] == "rejected"
    assert result["verified"] is False


def test_unknown_delegated_agent_is_rejected() -> None:
    """Trusted publishers still cannot mint unknown registered identities."""
    result = resolve_attribution(
        "*Posted by **invented-agent***",
        "kody-w",
        {"zion-coder-01"},
    )

    assert result["author"] == "kody-w"
    assert result["status"] == "rejected"


def test_tally_votes_uses_transport_actor_for_spoofed_byline() -> None:
    """One GitHub account cannot vote as multiple claimed agents."""
    comment = {
        "body": "*— **victim-agent***\n\n[VOTE] prop-1234",
        "author": {"login": "mallory"},
    }

    assert _extract_agent(comment) == "mallory"


def test_invalid_claim_markup_is_not_an_agent_id() -> None:
    """Markup and whitespace cannot become a claimed agent identifier."""
    assert extract_claimed_agent("*Posted by **<img src=x>***") is None
