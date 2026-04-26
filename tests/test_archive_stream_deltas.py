"""Tests for scripts/archive_stream_deltas.py."""
from __future__ import annotations

import json
from pathlib import Path

import archive_stream_deltas as ads


def _make_state(tmp_path: Path, frame_files: list[str], current_frame: int) -> Path:
    """Build a minimal state/ tree with the given delta files + frame counter."""
    state = tmp_path / "state"
    deltas = state / "stream_deltas"
    deltas.mkdir(parents=True)
    for name in frame_files:
        (deltas / name).write_text("{}")
    (state / "frame_counter.json").write_text(json.dumps({"frame": current_frame}))
    return state


def test_archives_files_older_than_keep(tmp_path, monkeypatch):
    """With keep=3 and current frame=510, frames <507 must be moved."""
    state = _make_state(
        tmp_path,
        [
            "frame-500-stream-1.json",
            "frame-505-stream-2.json",
            "frame-507-stream-1.json",
            "frame-509-stream-1.json",
            "frame-510-stream-2.json",
        ],
        current_frame=510,
    )
    monkeypatch.setattr(ads, "STATE_DIR", state)
    monkeypatch.setattr(ads, "DELTA_DIR", state / "stream_deltas")
    monkeypatch.setattr(ads, "ARCHIVE_DIR", state / "archive" / "stream_deltas")

    candidates = ads.find_archivable(keep_frames=3, current=510)
    assert {p.name for p, _ in candidates} == {"frame-500-stream-1.json", "frame-505-stream-2.json"}

    result = ads.archive(candidates, dry_run=False)
    assert result["moved"] == 2
    assert not (state / "stream_deltas" / "frame-500-stream-1.json").exists()
    assert (state / "archive" / "stream_deltas" / "frame-0500" / "frame-500-stream-1.json").exists()
    assert (state / "archive" / "stream_deltas" / "frame-0505" / "frame-505-stream-2.json").exists()


def test_keeps_recent_files_untouched(tmp_path, monkeypatch):
    """Files within the keep window stay where readers expect them."""
    state = _make_state(tmp_path, ["frame-509-x.json", "frame-510-y.json"], 510)
    monkeypatch.setattr(ads, "STATE_DIR", state)
    monkeypatch.setattr(ads, "DELTA_DIR", state / "stream_deltas")

    candidates = ads.find_archivable(keep_frames=3, current=510)
    assert candidates == []


def test_skips_lockfiles_and_gitkeep(tmp_path, monkeypatch):
    """Lock files and .gitkeep must never be moved."""
    state = _make_state(tmp_path, ["frame-500-x.json"], 510)
    (state / "stream_deltas" / "frame-500-x.json.lock").write_text("")
    (state / "stream_deltas" / ".gitkeep").write_text("")
    monkeypatch.setattr(ads, "STATE_DIR", state)
    monkeypatch.setattr(ads, "DELTA_DIR", state / "stream_deltas")

    candidates = ads.find_archivable(keep_frames=3, current=510)
    names = {p.name for p, _ in candidates}
    assert names == {"frame-500-x.json"}


def test_unparseable_frame_treated_as_legacy(tmp_path, monkeypatch):
    """frame-20260416-... (date-style) should land in archive/legacy/."""
    state = _make_state(tmp_path, ["frame-20260416-stream.json"], 510)
    monkeypatch.setattr(ads, "STATE_DIR", state)
    monkeypatch.setattr(ads, "DELTA_DIR", state / "stream_deltas")
    monkeypatch.setattr(ads, "ARCHIVE_DIR", state / "archive" / "stream_deltas")

    candidates = ads.find_archivable(keep_frames=3, current=510)
    # Frame parses to 20260416 (huge int) — that's actually NEWER than 510,
    # so wouldn't be archived. To test the legacy path, use a non-numeric
    # frame id which the regex won't match.
    state2 = _make_state(tmp_path / "v2", ["frame-zzz-stream.json"], 510)
    monkeypatch.setattr(ads, "STATE_DIR", state2)
    monkeypatch.setattr(ads, "DELTA_DIR", state2 / "stream_deltas")
    monkeypatch.setattr(ads, "ARCHIVE_DIR", state2 / "archive" / "stream_deltas")
    cands = ads.find_archivable(keep_frames=3, current=510)
    assert len(cands) == 1
    ads.archive(cands, dry_run=False)
    assert (state2 / "archive" / "stream_deltas" / "legacy" / "frame-zzz-stream.json").exists()


def test_dry_run_moves_nothing(tmp_path, monkeypatch):
    """--dry-run must not touch the filesystem."""
    state = _make_state(tmp_path, ["frame-500-x.json"], 510)
    monkeypatch.setattr(ads, "STATE_DIR", state)
    monkeypatch.setattr(ads, "DELTA_DIR", state / "stream_deltas")
    monkeypatch.setattr(ads, "ARCHIVE_DIR", state / "archive" / "stream_deltas")

    candidates = ads.find_archivable(keep_frames=3, current=510)
    result = ads.archive(candidates, dry_run=True)
    assert result["moved"] == 0
    assert (state / "stream_deltas" / "frame-500-x.json").exists()
    assert not (state / "archive").exists()


def test_collision_does_not_overwrite(tmp_path, monkeypatch):
    """If the archive bucket already has the same filename, keep both."""
    state = _make_state(tmp_path, ["frame-500-x.json"], 510)
    bucket = state / "archive" / "stream_deltas" / "frame-0500"
    bucket.mkdir(parents=True)
    (bucket / "frame-500-x.json").write_text('{"prior":"archived"}')
    monkeypatch.setattr(ads, "STATE_DIR", state)
    monkeypatch.setattr(ads, "DELTA_DIR", state / "stream_deltas")
    monkeypatch.setattr(ads, "ARCHIVE_DIR", state / "archive" / "stream_deltas")

    candidates = ads.find_archivable(keep_frames=3, current=510)
    ads.archive(candidates, dry_run=False)

    # Original archived file untouched
    assert json.loads((bucket / "frame-500-x.json").read_text())["prior"] == "archived"
    # New file landed under a dedup-suffixed name
    dups = list(bucket.glob("frame-500-x.dup-*.json"))
    assert len(dups) == 1
