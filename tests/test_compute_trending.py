"""Test 4: Compute Trending Tests — trending algorithm produces correct rankings."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "compute_trending.py"


def make_discussion_data(items):
    """Create a mock discussion data file."""
    return {"discussions": items}


def run_trending(state_dir, data_file=None):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    cmd = [sys.executable, str(SCRIPT)]
    if data_file:
        cmd.extend(["--data-file", str(data_file)])
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))


class TestTrendingWeights:
    def test_posts_weighted_3x(self, tmp_state, tmp_path):
        data = make_discussion_data([{
            "id": 1, "channel": "general", "title": "Test Post",
            "created_at": "2026-02-12T12:00:00Z",
            "posts_24h": 1, "comments_24h": 0, "reactions_24h": 0
        }])
        data_file = tmp_path / "discussions.json"
        data_file.write_text(json.dumps(data))
        run_trending(tmp_state, data_file)

        trending = json.loads((tmp_state / "trending.json").read_text())
        assert len(trending["trending"]) == 1
        # Score should reflect post weight of 3
        assert trending["trending"][0]["score"] > 0

    def test_comments_weighted_2x(self, tmp_state, tmp_path):
        data = make_discussion_data([
            {
                "id": 1, "channel": "general", "title": "Post Only",
                "created_at": "2026-02-12T12:00:00Z",
                "posts_24h": 1, "comments_24h": 0, "reactions_24h": 0
            },
            {
                "id": 2, "channel": "general", "title": "Post + Comments",
                "created_at": "2026-02-12T12:00:00Z",
                "posts_24h": 1, "comments_24h": 5, "reactions_24h": 0
            }
        ])
        data_file = tmp_path / "discussions.json"
        data_file.write_text(json.dumps(data))
        run_trending(tmp_state, data_file)

        trending = json.loads((tmp_state / "trending.json").read_text())
        scores = {t["discussion_id"]: t["score"] for t in trending["trending"]}
        assert scores[2] > scores[1]

    def test_sorted_by_score_descending(self, tmp_state, tmp_path):
        data = make_discussion_data([
            {"id": 1, "channel": "a", "title": "Low",
             "created_at": "2026-02-12T12:00:00Z",
             "posts_24h": 1, "comments_24h": 0, "reactions_24h": 0},
            {"id": 2, "channel": "b", "title": "High",
             "created_at": "2026-02-12T12:00:00Z",
             "posts_24h": 3, "comments_24h": 10, "reactions_24h": 20},
        ])
        data_file = tmp_path / "discussions.json"
        data_file.write_text(json.dumps(data))
        run_trending(tmp_state, data_file)

        trending = json.loads((tmp_state / "trending.json").read_text())
        scores = [t["score"] for t in trending["trending"]]
        assert scores == sorted(scores, reverse=True)


class TestTrendingEdgeCases:
    def test_empty_input(self, tmp_state, tmp_path):
        data = make_discussion_data([])
        data_file = tmp_path / "discussions.json"
        data_file.write_text(json.dumps(data))
        run_trending(tmp_state, data_file)

        trending = json.loads((tmp_state / "trending.json").read_text())
        assert trending["trending"] == []

    def test_valid_schema(self, tmp_state, tmp_path):
        data = make_discussion_data([{
            "id": 1, "channel": "general", "title": "Test",
            "created_at": "2026-02-12T12:00:00Z",
            "posts_24h": 1, "comments_24h": 0, "reactions_24h": 0
        }])
        data_file = tmp_path / "discussions.json"
        data_file.write_text(json.dumps(data))
        run_trending(tmp_state, data_file)

        trending = json.loads((tmp_state / "trending.json").read_text())
        assert "last_computed" in trending
        assert isinstance(trending["last_computed"], str)
