"""Native outside contributions remain visible without inventing social credit."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compute_rappterbook_datascience as datascience
import reconcile_channels


def write_json(path: Path, value: dict) -> None:
    """Write synthetic test data, never the live platform state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def comment(node_id: str, author: str, body: str, **extra) -> dict:
    """Build one native comment observation."""
    return {
        "id": node_id, "author_login": author, "body": body,
        "created_at": "2026-09-18T10:01:00Z", **extra,
    }


def credit_fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    """Include native, relayed, vote-only and received-comment counterexamples."""
    state = tmp_path / "state"
    docs = tmp_path / "docs"
    agents = {"agents": {
        "outside-agent": {
            "name": "Outside", "framework": "custom", "github_user_id": 42,
            "post_count": 99, "comment_count": 99, "karma": 7, "status": "dormant",
        },
        "commenter": {
            "name": "Commenter", "framework": "python", "github_user_id": 43,
            "post_count": 0, "comment_count": 0, "status": "active",
        },
        "zion-founder": {
            "framework": "zion", "post_count": 777, "comment_count": 888,
            "status": "active",
        },
    }, "_meta": {"count": 3}}
    discussions = [
        {
            "number": 1, "author_login": "outside-agent",
            "outside_commenter_matches": ["outside-agent", "commenter"],
            "comments_complete": True,
            "comments": [
                comment("DC_FOUNDER", "kody-w", "*— **zion-founder***\nWelcome"),
                comment("DC_OTHER", "commenter", "A question", replies=[
                    comment("DC_REPLY", "outside-agent", "A specific answer"),
                    comment("DC_RELAY", "kody-w", "*— **outside-agent***\nRelayed"),
                ]),
                comment("DC_SELF", "outside-agent", "Additional evidence"),
                comment("DC_VOTE", "outside-agent", "👍"),
            ],
            "comment_count": 4,
        },
        {
            "number": 2, "author_login": "kody-w",
            "body": "*Posted by **outside-agent***\nRelayed post",
            "outside_commenter_matches": ["outside-agent"],
            "comments_complete": True,
            "comments": [comment("DC_NATIVE", "outside-agent", "Native response")],
            "comment_count": 1,
        },
        {
            "number": 3, "author": {"login": "New-Visitor"},
            "comments": [], "comments_complete": False, "comment_count": 20,
        },
        {
            "number": 4, "author_login": "build[bot]",
            "comments": [], "comment_count": 0,
        },
    ]
    for discussion in discussions:
        discussion.setdefault("body", "A public post")
        discussion.update({
            "title": "Synthetic discussion", "category_slug": "general",
            "created_at": "2026-09-18T10:00:00Z",
            "url": f"https://example.test/{discussion['number']}",
        })
    write_json(state / "agents.json", agents)
    write_json(state / "discussions_cache.json", {
        "_meta": {
            "total": len(discussions),
            "scraped_at": "2026-09-18T11:00:00Z",
            "outside_commenter_search": {"outside-agent": 2, "commenter": 1},
        },
        "discussions": discussions,
    })
    for filename, value in {
        "stats.json": {},
        "channels.json": {"channels": {"general": {"verified": True}}},
        "manifest.json": {},
        "posted_log.json": {"posts": [], "comments": []},
    }.items():
        write_json(state / filename, value)
    write_json(docs / "pulse.json", {})
    return state, docs, agents


def run_reconcile(state, docs, monkeypatch, *options):
    """Exercise the real state-writer entrypoint on an isolated fixture."""
    monkeypatch.setattr(reconcile_channels, "STATE_DIR", state)
    monkeypatch.setattr(reconcile_channels, "DOCS_DIR", docs)
    monkeypatch.setattr(sys, "argv", ["reconcile_channels.py", *options])
    reconcile_channels.main()
    return json.loads((state / "agents.json").read_text())


def test_existing_profiles_get_authored_credit_and_founders_are_unchanged(
    tmp_path, monkeypatch,
):
    state, docs, original = credit_fixture(tmp_path)

    result = run_reconcile(state, docs, monkeypatch)["agents"]

    assert result["outside-agent"]["post_count"] == 1
    assert result["outside-agent"]["comment_count"] == 3
    assert result["outside-agent"]["karma"] == 7
    assert result["outside-agent"]["status"] == "dormant"
    assert result["commenter"]["post_count"] == 0
    assert result["commenter"]["comment_count"] == 1
    assert result["zion-founder"] == original["agents"]["zion-founder"]
    assert "build[bot]" not in result
    assert "kody-w" not in result
    assert result["New-Visitor"]["post_count"] == 1
    assert result["New-Visitor"]["comment_count"] == 0
    assert result["New-Visitor"]["karma"] == 1
    assert result["outside-agent"]["count_provenance"] == {
        "source": "github-native-observations",
        "scope": "observed_lifetime",
        "comment_coverage": "search_complete",
        "includes_replies": True,
        "service_relays_excluded": True,
        "as_of": "2026-09-18T11:00:00Z",
    }
    assert result["New-Visitor"]["count_provenance"]["comment_coverage"] == "lower_bound"


def test_credit_matches_the_existing_dashboard_measurement(tmp_path, monkeypatch):
    state, docs, _ = credit_fixture(tmp_path)
    run_reconcile(state, docs, monkeypatch)

    _, dashboard = datascience.build_payload(
        state, docs, tmp_path, "2026-09-18T12:00:00Z"
    )

    registered = [
        row for row in dashboard["identities"]
        if row["classification"] == "registered_outside_agent"
    ]
    assert len(registered) == 3
    assert all(row["profile_counts_match"] for row in registered)


def test_dry_run_and_incomplete_corpora_preserve_profile_bytes(tmp_path, monkeypatch):
    state, docs, _ = credit_fixture(tmp_path)
    original = (state / "agents.json").read_bytes()

    run_reconcile(state, docs, monkeypatch, "--dry-run")
    assert (state / "agents.json").read_bytes() == original

    cache = json.loads((state / "discussions_cache.json").read_text())
    cache["_meta"]["total"] = 100
    write_json(state / "discussions_cache.json", cache)
    run_reconcile(state, docs, monkeypatch)
    assert (state / "agents.json").read_bytes() == original


def test_historical_native_credit_survives_but_relay_claims_do_not(
    tmp_path, monkeypatch, capsys,
):
    state, docs, _ = credit_fixture(tmp_path)
    historical = {
        "key": "historical", "event_type": "comment", "comment_id": "DC_OLD",
        "discussion_number": 10, "github_login": "outside-agent",
        "actor_id": "outside-agent", "actor_class": "registered_outside_agent",
        "created_at": "2026-01-01T00:00:00Z", "is_vote_only": False,
    }
    forged_relay = {
        **historical, "key": "relayed", "comment_id": "DC_BAD",
        "github_login": "kody-w",
    }
    write_json(docs / "data" / "rappterbook-datascience-snapshot.json", {
        "events": [historical, forged_relay],
    })

    result = run_reconcile(state, docs, monkeypatch)["agents"]

    assert result["outside-agent"]["comment_count"] == 4
    assert "without direct outside authorship" in capsys.readouterr().err


def test_native_login_case_does_not_create_duplicate_profiles(tmp_path, monkeypatch):
    state, docs, _ = credit_fixture(tmp_path)
    cache = json.loads((state / "discussions_cache.json").read_text())
    extra = copy.deepcopy(cache["discussions"][2])
    extra.update({"number": 5, "author_login": "new-visitor"})
    cache["discussions"].append(extra)
    cache["_meta"]["total"] += 1
    write_json(state / "discussions_cache.json", cache)

    result = run_reconcile(state, docs, monkeypatch)["agents"]

    assert result["New-Visitor"]["post_count"] == 2
    assert "new-visitor" not in result


def test_native_comment_edits_do_not_mint_more_contributions():
    original = {
        "key": "old-body-key", "event_type": "comment", "comment_id": "DC_EDIT",
        "discussion_number": 1, "github_login": "outside",
        "source": "current_cache", "snippet": "Original",
    }
    edited = {
        **original, "key": "new-body-key", "snippet": "Edited",
        "is_direct_outside": True,
    }

    merged = datascience.merge_outside_events([original], [edited])

    assert len(merged) == 1
    assert merged[0]["snippet"] == "Edited"


def test_distinct_comments_with_identical_text_stay_distinct():
    first = {
        "key": "first", "event_type": "comment", "comment_id": "DC_1",
        "discussion_number": 1, "snippet": "Same text",
    }
    second = {**first, "key": "second", "comment_id": "DC_2"}

    assert len(datascience.merge_outside_events([first, second], [])) == 2


def test_frontend_preserves_and_explains_observed_count_provenance():
    state = (ROOT / "src" / "js" / "state.js").read_text()
    render = (ROOT / "src" / "js" / "render.js").read_text()
    fixture = {
        "agents": {
            "outside": {
                "name": "Outside", "joined": "2026-01-01T00:00:00Z",
                "post_count": 1, "comment_count": 3,
                "count_provenance": {"source": "github-native-observations"},
            },
        },
    }
    script = state + "\n" + render + f"""
RB_STATE.getAgents = async () => ({json.dumps(fixture)});
(async () => {{
  const list = await RB_STATE.getAgentsCached();
  const agent = await RB_STATE.findAgent('outside');
  const explained = RB_RENDER.renderAgentProfile(agent, null);
  const legacy = RB_RENDER.renderAgentProfile({{...agent, countProvenance: null}}, null);
  console.log(JSON.stringify({{
    listSource: list[0].countProvenance.source,
    detailSource: agent.countProvenance.source,
    explainsObserved: explained.includes('observed direct GitHub contributions'),
    explainsCoverage: explained.includes('historical coverage may be incomplete'),
    legacyUnchanged: !legacy.includes('observed direct GitHub contributions')
  }}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {
        "listSource": "github-native-observations",
        "detailSource": "github-native-observations",
        "explainsObserved": True,
        "explainsCoverage": True,
        "legacyUnchanged": True,
    }
