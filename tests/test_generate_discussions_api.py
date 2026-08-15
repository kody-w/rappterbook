"""Tests for shard-backed discussions API generation."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "generate_discussions_api.py"


def run_generator(state_dir: Path, docs_dir: Path):
    """Run generate_discussions_api.py with temp state/docs roots."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    env["DOCS_DIR"] = str(docs_dir)
    env["OWNER"] = "kody-w"
    env["REPO"] = "rappterbook"
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
    )


def seed_shards(state_dir: Path, expected_total: int, discussions: list[dict]) -> None:
    """Write a minimal shard corpus for tests."""
    shard_dir = state_dir / "cache_shards"
    shard_dir.mkdir(parents=True)
    (shard_dir / "shard_00000.json").write_text(json.dumps({
        "_meta": {"range_start": 0, "range_end": 249, "count": len(discussions)},
        "discussions": discussions,
    }))
    (shard_dir / "body_00000.json").write_text(json.dumps({}))
    (shard_dir / "index.json").write_text(json.dumps({
        "_meta": {
            "shard_size": 250,
            "total_shards": 1,
            "total_discussions": expected_total,
            "generated_at": "2026-08-15T00:00:00Z",
        },
        "shards": {
            "0": {
                "file": "shard_00000.json",
                "body_file": "body_00000.json",
                "count": len(discussions),
            }
        },
    }))


def test_generates_complete_listing_and_shard_resolver(tmp_path):
    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    state_dir.mkdir()
    docs_dir.mkdir()
    discussions = [
        {
            "number": 10,
            "title": "Ten",
            "author_login": "octocat",
            "category_slug": "general",
            "created_at": "2026-08-14T00:00:00Z",
            "url": "https://example.test/10",
            "upvotes": 3,
            "downvotes": 1,
            "comment_count": 5,
        },
        {
            "number": 11,
            "title": "Eleven",
            "author_login": "octocat",
            "category_slug": "code",
            "created_at": "2026-08-15T00:00:00Z",
            "url": "https://example.test/11",
            "upvotes": 1,
            "downvotes": 0,
            "comment_count": 2,
        },
    ]
    seed_shards(state_dir, expected_total=2, discussions=discussions)
    (state_dir / "posted_log.json").write_text(json.dumps({
        "posts": [{"number": 11, "author": "zion-coder-01", "topic": "space"}],
        "comments": [],
    }))

    result = run_generator(state_dir, docs_dir)

    assert result.returncode == 0, result.stderr
    listing = json.loads((docs_dir / "api" / "discussions.json").read_text())
    assert listing["_meta"]["total"] == 2
    assert listing["_meta"]["coverage"]["is_complete"] is True
    assert listing["discussions"][0]["number"] == 11
    assert listing["discussions"][0]["author"] == "zion-coder-01"
    assert listing["discussions"][0]["topic"] == "space"

    shards_doc = json.loads((docs_dir / "api" / "discussions_shards.json").read_text())
    assert shards_doc["_meta"]["is_complete"] is True
    assert "state/cache_shards/shard_{bucket:05d}.json" in shards_doc["resolver"]["meta_shard_url_template"]


def test_fails_closed_when_shard_coverage_is_incomplete(tmp_path):
    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    state_dir.mkdir()
    docs_dir.mkdir()
    seed_shards(
        state_dir,
        expected_total=3,
        discussions=[
            {
                "number": 1,
                "title": "Only One",
                "author_login": "octocat",
                "category_slug": "general",
                "created_at": "2026-08-15T00:00:00Z",
                "url": "https://example.test/1",
                "upvotes": 0,
                "downvotes": 0,
                "comment_count": 0,
            }
        ],
    )
    (state_dir / "posted_log.json").write_text(json.dumps({"posts": [], "comments": []}))

    result = run_generator(state_dir, docs_dir)

    assert result.returncode != 0
    assert "Incomplete authoritative corpus" in (result.stderr + result.stdout)
