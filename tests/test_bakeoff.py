"""Tests for the bakeoff suite — claude stream producer, merge tester, scorer."""
from __future__ import annotations

import json
from pathlib import Path

import bakeoff_claude
import bakeoff_test
import bakeoff_score


def test_build_delta_has_required_fields() -> None:
    """Each generated delta must match the dream_catcher schema."""
    persona = bakeoff_claude.STREAM_PERSONAS[0]
    delta = bakeoff_claude.build_delta(persona, frame=42)
    for key in (
        "frame", "stream_id", "stream_type", "completed_at",
        "agents_activated", "posts_pending_publish", "comments_pending_publish",
        "discussions_engaged", "observations",
    ):
        assert key in delta, f"missing key: {key}"
    assert delta["frame"] == 42
    assert delta["stream_type"] == "claude"
    assert len(delta["posts_pending_publish"]) == 1
    assert len(delta["agents_activated"]) == len(persona["agents"])


def test_write_deltas_creates_files(tmp_path: Path) -> None:
    """write_deltas must produce N files with unique stream_ids."""
    written = bakeoff_claude.write_deltas(frame=100, n_streams=3, output_dir=tmp_path)
    assert len(written) == 3
    stream_ids = []
    for p in written:
        assert p.exists()
        d = json.loads(p.read_text())
        stream_ids.append(d["stream_id"])
    assert len(set(stream_ids)) == 3, "stream_ids must all be unique"


def test_write_deltas_cycles_personas_when_more_streams_than_roster(tmp_path: Path) -> None:
    """Asking for 7 streams when only 5 personas exist still yields 7 unique ids."""
    written = bakeoff_claude.write_deltas(frame=100, n_streams=7, output_dir=tmp_path)
    assert len(written) == 7
    stream_ids = [json.loads(p.read_text())["stream_id"] for p in written]
    assert len(set(stream_ids)) == 7


def test_integrity_report_clean_passes(tmp_path: Path) -> None:
    """Three deltas with distinct keys → all_unique_keys=True, zero loss."""
    bakeoff_claude.write_deltas(frame=200, n_streams=3, output_dir=tmp_path)
    # bakeoff_test discovers via discover_deltas which globs frame-N-*.json
    # in {state_dir}/stream_deltas/. Our output_dir matches that layout.
    from merge_workers import discover_deltas  # type: ignore
    deltas = discover_deltas(tmp_path, frame=200)
    report = bakeoff_test.integrity_report(200, deltas)
    assert report["deltas_in"] == 3
    assert report["integrity"]["all_unique_keys"] is True
    assert report["integrity"]["posts_lost_to_dedup"] == 0


def test_integrity_report_detects_duplicate_composite_keys(tmp_path: Path) -> None:
    """Two deltas with the same (frame, stream_id, completed_at) flag a dup."""
    deltas_dir = tmp_path / "stream_deltas"
    deltas_dir.mkdir(parents=True)
    same_payload = {
        "frame": 300,
        "stream_id": "twin-stream",
        "completed_at": "2026-04-26T22:00:00.000000Z",
        "agents_activated": [],
        "posts_created": [],
        "posts_pending_publish": [],
        "comments_added": [],
        "comments_pending_publish": [],
        "discussions_engaged": [],
    }
    (deltas_dir / "frame-300-a.json").write_text(json.dumps(same_payload))
    (deltas_dir / "frame-300-b.json").write_text(json.dumps(same_payload))
    from merge_workers import discover_deltas  # type: ignore
    deltas = discover_deltas(tmp_path, frame=300)
    report = bakeoff_test.integrity_report(300, deltas)
    assert report["integrity"]["all_unique_keys"] is False
    assert len(report["integrity"]["duplicate_composite_keys"]) >= 2


def test_score_producer_computes_diversity_correctly() -> None:
    """All-unique agents → diversity 1.0; full overlap → 0.5 with two streams."""
    distinct = [
        {"agents_activated": ["a", "b", "c"], "posts_created": [], "comments_added": []},
        {"agents_activated": ["d", "e", "f"], "posts_created": [], "comments_added": []},
    ]
    s = bakeoff_score.score_producer(distinct)
    assert s["agent_diversity"] == 1.0

    overlapping = [
        {"agents_activated": ["a", "b", "c"], "posts_created": [], "comments_added": []},
        {"agents_activated": ["a", "b", "c"], "posts_created": [], "comments_added": []},
    ]
    s2 = bakeoff_score.score_producer(overlapping)
    assert s2["agent_diversity"] == 0.5  # 3 unique / 6 total slots


def test_score_producer_counts_dup_dropped_comments() -> None:
    """Identical-fingerprint comments across streams should count as dropped."""
    deltas = [
        {
            "agents_activated": [], "posts_created": [],
            "comments_added": [{"discussion": 1, "author": "a", "body": "hi there"}],
            "comments_pending_publish": [],
        },
        {
            "agents_activated": [], "posts_created": [],
            "comments_added": [{"discussion": 1, "author": "a", "body": "hi there"}],
            "comments_pending_publish": [],
        },
    ]
    s = bakeoff_score.score_producer(deltas)
    assert s["dups_dropped"] == 1


def test_score_all_groups_by_stream_type() -> None:
    """score_all must partition deltas by their stream_type field."""
    deltas = [
        {"stream_type": "claude", "agents_activated": ["a"], "posts_created": [], "comments_added": []},
        {"stream_type": "copilot", "agents_activated": ["b"], "posts_created": [], "comments_added": []},
        {"stream_type": "copilot", "agents_activated": ["c"], "posts_created": [], "comments_added": []},
    ]
    scores = bakeoff_score.score_all(deltas)
    assert set(scores.keys()) == {"claude", "copilot"}
    assert scores["claude"]["streams"] == 1
    assert scores["copilot"]["streams"] == 2
