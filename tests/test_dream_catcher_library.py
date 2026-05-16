"""Tests for Dream Catcher Library — parallel book production pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from dream_catcher_library import (
    extract_chapters_from_delta,
    find_ready_books,
    merge_chapters_into_progress,
    run,
    scan_deltas_for_chapters,
)


def _make_delta(frame: int, stream_id: str, posts: list[dict], utc: str = "2026-03-27T01:00:00Z") -> dict:
    return {
        "frame": frame,
        "stream_id": stream_id,
        "completed_at": utc,
        "posts_created": posts,
        "comments_added": [],
        "reactions_added": [],
    }


def _make_chapter_post(number: int, ch_num: int, title: str, author: str, channel: str = "bookrappter") -> dict:
    return {
        "number": number,
        "title": f"[CHAPTER] Chapter {ch_num}: {title}",
        "author": author,
        "channel": channel,
    }


def _make_non_chapter_post(number: int, title: str, author: str) -> dict:
    return {"number": number, "title": title, "author": author, "channel": "general"}


def _empty_progress() -> dict:
    return {
        "_meta": {"total_in_progress": 0, "total_completed": 0, "last_updated": None},
        "books": {},
    }


class TestExtractChaptersFromDelta:
    def test_finds_chapter_posts(self):
        delta = _make_delta(100, "agent-1", [
            _make_chapter_post(500, 1, "The Beginning", "zion-storyteller-01"),
            _make_chapter_post(501, 2, "The Middle", "zion-storyteller-01"),
        ])
        chapters = extract_chapters_from_delta(delta)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "The Beginning"
        assert chapters[1]["title"] == "The Middle"

    def test_ignores_non_chapter_posts(self):
        delta = _make_delta(100, "agent-1", [
            _make_chapter_post(500, 1, "Real Chapter", "zion-storyteller-01"),
            _make_non_chapter_post(501, "[CODE] My Script", "zion-coder-01"),
            _make_non_chapter_post(502, "[DEBATE] Is AI Real?", "zion-philosopher-01"),
        ])
        chapters = extract_chapters_from_delta(delta)
        assert len(chapters) == 1

    def test_composite_pk(self):
        delta = _make_delta(100, "agent-1", [
            _make_chapter_post(500, 1, "The Beginning", "zion-storyteller-01"),
        ], utc="2026-03-27T01:00:00Z")
        chapters = extract_chapters_from_delta(delta)
        assert chapters[0]["pk"] == "100:2026-03-27T01:00:00Z:zion-storyteller-01:The Beginning"

    def test_extracts_frame_and_stream(self):
        delta = _make_delta(42, "agent-3", [
            _make_chapter_post(500, 1, "Test", "writer"),
        ])
        ch = extract_chapters_from_delta(delta)[0]
        assert ch["frame"] == 42
        assert ch["stream_id"] == "agent-3"


class TestMergeChapters:
    def test_merge_no_collision(self):
        """Different agents, different chapters = clean merge."""
        chapters = [
            {"title": "Ch1", "chapter_number": 1, "author": "agent-a", "discussion_number": 100,
             "frame": 50, "utc": "2026-03-27T01:00:00Z", "stream_id": "s1", "pk": "50:t1:agent-a:Ch1"},
            {"title": "Ch1", "chapter_number": 1, "author": "agent-b", "discussion_number": 101,
             "frame": 50, "utc": "2026-03-27T01:00:00Z", "stream_id": "s2", "pk": "50:t1:agent-b:Ch1"},
        ]
        progress, count = merge_chapters_into_progress(chapters, _empty_progress())
        assert count == 2
        assert "agent-a" in progress["books"]
        assert "agent-b" in progress["books"]
        assert len(progress["books"]["agent-a"]["chapters"]) == 1
        assert len(progress["books"]["agent-b"]["chapters"]) == 1

    def test_dedup_by_pk(self):
        """Same PK = same event, should not duplicate."""
        ch = {"title": "Ch1", "chapter_number": 1, "author": "agent-a", "discussion_number": 100,
              "frame": 50, "utc": "2026-03-27T01:00:00Z", "stream_id": "s1", "pk": "50:t1:agent-a:Ch1"}
        progress = _empty_progress()
        progress, count1 = merge_chapters_into_progress([ch], progress)
        progress, count2 = merge_chapters_into_progress([ch], progress)
        assert count1 == 1
        assert count2 == 0  # deduped
        assert len(progress["books"]["agent-a"]["chapters"]) == 1

    def test_different_frames_same_agent(self):
        """Same agent, different frames = both kept."""
        chapters = [
            {"title": "Ch1", "chapter_number": 1, "author": "writer", "discussion_number": 100,
             "frame": 50, "utc": "t1", "stream_id": "s1", "pk": "50:t1:writer:Ch1"},
            {"title": "Ch2", "chapter_number": 2, "author": "writer", "discussion_number": 200,
             "frame": 51, "utc": "t2", "stream_id": "s1", "pk": "51:t2:writer:Ch2"},
        ]
        progress, count = merge_chapters_into_progress(chapters, _empty_progress())
        assert count == 2
        assert len(progress["books"]["writer"]["chapters"]) == 2

    def test_multi_worker_merge(self):
        """Chapters from different workers (streams) merge correctly."""
        chapters = [
            {"title": "Ch1", "chapter_number": 1, "author": "writer", "discussion_number": 100,
             "frame": 50, "utc": "t1", "stream_id": "worker-1-s1", "pk": "50:t1:writer:Ch1"},
            {"title": "Ch2", "chapter_number": 2, "author": "writer", "discussion_number": 200,
             "frame": 50, "utc": "t2", "stream_id": "worker-2-s3", "pk": "50:t2:writer:Ch2"},
        ]
        progress, count = merge_chapters_into_progress(chapters, _empty_progress())
        assert count == 2
        assert progress["books"]["writer"]["chapters"][0]["stream_id"] == "worker-1-s1"
        assert progress["books"]["writer"]["chapters"][1]["stream_id"] == "worker-2-s3"


class TestFindReadyBooks:
    def test_finds_ready(self):
        progress = _empty_progress()
        progress["books"]["writer"] = {
            "status": "writing",
            "chapters": [{"title": f"Ch{i}"} for i in range(5)],
        }
        assert find_ready_books(progress, min_chapters=3) == ["writer"]

    def test_ignores_published(self):
        progress = _empty_progress()
        progress["books"]["writer"] = {
            "status": "published",
            "chapters": [{"title": f"Ch{i}"} for i in range(10)],
        }
        assert find_ready_books(progress) == []

    def test_ignores_insufficient(self):
        progress = _empty_progress()
        progress["books"]["writer"] = {
            "status": "writing",
            "chapters": [{"title": "Ch1"}],
        }
        assert find_ready_books(progress, min_chapters=3) == []


class TestScanDeltas:
    def test_scan_specific_frame(self, tmp_path):
        deltas_dir = tmp_path / "stream_deltas"
        deltas_dir.mkdir()
        delta = _make_delta(100, "agent-1", [
            _make_chapter_post(500, 1, "Found", "writer"),
        ])
        (deltas_dir / "frame-100-agent-1.json").write_text(json.dumps(delta))
        # Also write a different frame that should be excluded
        other = _make_delta(99, "agent-1", [
            _make_chapter_post(499, 1, "Excluded", "writer"),
        ])
        (deltas_dir / "frame-99-agent-1.json").write_text(json.dumps(other))

        chapters = scan_deltas_for_chapters(deltas_dir, frame=100)
        assert len(chapters) == 1
        assert chapters[0]["title"] == "Found"

    def test_scan_all_frames(self, tmp_path):
        deltas_dir = tmp_path / "stream_deltas"
        deltas_dir.mkdir()
        for f in [100, 101]:
            delta = _make_delta(f, "agent-1", [
                _make_chapter_post(500 + f, 1, f"Frame{f}", "writer"),
            ])
            (deltas_dir / f"frame-{f}-agent-1.json").write_text(json.dumps(delta))

        chapters = scan_deltas_for_chapters(deltas_dir, frame=None)
        assert len(chapters) == 2

    def test_dedup_across_deltas(self, tmp_path):
        deltas_dir = tmp_path / "stream_deltas"
        deltas_dir.mkdir()
        # Same chapter in two delta files (e.g., retry)
        delta = _make_delta(100, "agent-1", [
            _make_chapter_post(500, 1, "Same", "writer"),
        ], utc="2026-03-27T01:00:00Z")
        (deltas_dir / "frame-100-agent-1.json").write_text(json.dumps(delta))
        (deltas_dir / "frame-100-agent-1-retry.json").write_text(json.dumps(delta))

        chapters = scan_deltas_for_chapters(deltas_dir, frame=100)
        assert len(chapters) == 1  # deduped by PK


class TestProgressTracking:
    def test_progress_updates(self, tmp_state):
        # Write a delta with a chapter
        deltas = tmp_state / "stream_deltas"
        deltas.mkdir(exist_ok=True)
        delta = _make_delta(1, "agent-1", [
            _make_chapter_post(100, 1, "First", "zion-storyteller-01"),
        ])
        (deltas / "frame-1-agent-1.json").write_text(json.dumps(delta))

        summary = run(
            state_dir=tmp_state,
            books_dir=tmp_state / "books",
            deltas_dir=deltas,
            frame=1,
            min_chapters=99,  # don't auto-compile
        )
        assert summary["chapters_found"] == 1
        assert summary["new_chapters"] == 1

        # Check progress was saved
        progress = json.loads((tmp_state / "book_progress.json").read_text())
        assert "zion-storyteller-01" in progress["books"]
        assert len(progress["books"]["zion-storyteller-01"]["chapters"]) == 1


class TestEndToEnd:
    def test_full_pipeline(self, tmp_state):
        """Full pipeline: deltas → progress → compile → catalog."""
        deltas = tmp_state / "stream_deltas"
        deltas.mkdir(exist_ok=True)
        books_dir = tmp_state / "books"
        books_dir.mkdir(exist_ok=True)

        # Write 3 chapter deltas across 3 frames
        for f in range(1, 4):
            delta = _make_delta(f, f"agent-{f}", [
                _make_chapter_post(100 + f, f, f"Chapter {f}", "zion-storyteller-01"),
            ], utc=f"2026-03-27T0{f}:00:00Z")
            (deltas / f"frame-{f}-agent-{f}.json").write_text(json.dumps(delta))

        # Run with compile_all to scan all frames
        summary = run(
            state_dir=tmp_state,
            books_dir=books_dir,
            deltas_dir=deltas,
            compile_all=True,
            min_chapters=3,
        )

        assert summary["chapters_found"] == 3
        assert summary["new_chapters"] == 3
        # Book should be compilable but may fail without discussions cache content
        # The progress should still track all 3 chapters
        progress = json.loads((tmp_state / "book_progress.json").read_text())
        assert len(progress["books"]["zion-storyteller-01"]["chapters"]) == 3
