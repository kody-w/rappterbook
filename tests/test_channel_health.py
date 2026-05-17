"""Tests for scripts/channel_health.py."""
import json
from pathlib import Path

import pytest

import channel_health


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def _seed(state_dir: Path, channels: dict, posts: list[dict], frame: int = 100):
    _write(state_dir / "channels.json",
           {"channels": channels, "_meta": {"count": len(channels), "last_updated": "2026-05-17T00:00:00Z"}})
    _write(state_dir / "posted_log.json", {"posts": posts, "comments": []})
    _write(state_dir / "frame_counter.json", {"frame": frame})


def test_alive_channel_classified_alive(tmp_state):
    channels = {"general": {"slug": "general", "name": "General", "post_count": 5}}
    posts = [{"channel": "general", "timestamp": "2026-05-17T13:00:00Z",
              "number": 1, "title": "hi", "author": "a"}]
    _seed(tmp_state, channels, posts, frame=100)

    out = channel_health.compute_health(tmp_state)

    assert out["channels"]["general"]["status"] == "alive"
    assert out["channels"]["general"]["frames_since_post"] == 0
    assert out["channels"]["general"]["post_count"] == 1
    assert out["revivals"] == []


def test_dead_channel_accumulates_across_runs_and_emits_revival(tmp_state):
    channels = {
        "agentunderground": {
            "slug": "agentunderground", "name": "Agent Underground",
            "description": "Where ghosts whisper", "post_count": 0,
            "constitution": "Only posts that would feel wrong anywhere else.",
        }
    }
    # Post that's already "old" — last_post_at older than any prior check
    posts = [{"channel": "agentunderground", "timestamp": "2026-01-01T00:00:00Z",
              "number": 7, "title": "old", "author": "ghost"}]

    # Frame 100 — initialize. Previous frames_since_post=0, frame_delta=100 -> classified dead.
    _seed(tmp_state, channels, posts, frame=100)
    first = channel_health.compute_health(tmp_state)
    assert first["channels"]["agentunderground"]["frames_since_post"] == 100
    assert first["channels"]["agentunderground"]["status"] in ("dead", "flatline")

    # Persist and advance — no new posts, frame moves +5.
    _write(tmp_state / "channel_health.json", first)
    _write(tmp_state / "frame_counter.json", {"frame": 105})

    second = channel_health.compute_health(tmp_state)
    entry = second["channels"]["agentunderground"]
    assert entry["frames_since_post"] == 105, "frames_since_post must accumulate by frame delta"
    assert entry["status"] == "flatline"
    assert "revival_prompt" in entry
    assert "agentunderground" in entry["revival_prompt"]
    assert any(r["slug"] == "agentunderground" for r in second["revivals"])


def test_new_post_resets_frames_since_post(tmp_state):
    channels = {"code": {"slug": "code", "name": "Code", "post_count": 0}}
    posts = [{"channel": "code", "timestamp": "2026-01-01T00:00:00Z",
              "number": 1, "title": "old", "author": "a"}]
    _seed(tmp_state, channels, posts, frame=100)
    first = channel_health.compute_health(tmp_state)
    assert first["channels"]["code"]["frames_since_post"] >= channel_health.DEFAULT_DEAD_FRAMES
    _write(tmp_state / "channel_health.json", first)

    # New post appears at frame 110.
    posts.append({"channel": "code", "timestamp": "2026-05-17T13:00:00Z",
                  "number": 2, "title": "new", "author": "b"})
    _write(tmp_state / "posted_log.json", {"posts": posts, "comments": []})
    _write(tmp_state / "frame_counter.json", {"frame": 110})

    second = channel_health.compute_health(tmp_state)
    assert second["channels"]["code"]["frames_since_post"] == 0
    assert second["channels"]["code"]["status"] == "alive"
    assert all(r["slug"] != "code" for r in second["revivals"])


def test_thresholds_classify_quiet_vs_dead(tmp_state):
    channels = {
        "fresh": {"slug": "fresh", "name": "Fresh"},
        "stale": {"slug": "stale", "name": "Stale"},
        "gone":  {"slug": "gone",  "name": "Gone"},
    }
    # Pre-seed prior health so we control frames_since_post precisely.
    prior = {
        "_meta": {"frame": 50, "totals": {}},
        "channels": {
            "fresh": {"slug": "fresh", "last_post_at": "2026-05-17T00:00:00Z", "frames_since_post": 0},
            "stale": {"slug": "stale", "last_post_at": "2026-01-01T00:00:00Z", "frames_since_post": 5},
            "gone":  {"slug": "gone",  "last_post_at": "2026-01-01T00:00:00Z", "frames_since_post": 30},
        },
    }
    _write(tmp_state / "channel_health.json", prior)
    posts = [
        {"channel": "fresh", "timestamp": "2026-05-17T13:00:00Z", "number": 1, "title": "x", "author": "a"},
        {"channel": "stale", "timestamp": "2026-01-01T00:00:00Z", "number": 2, "title": "x", "author": "a"},
        {"channel": "gone",  "timestamp": "2026-01-01T00:00:00Z", "number": 3, "title": "x", "author": "a"},
    ]
    _seed(tmp_state, channels, posts, frame=50)  # frame_delta = 0

    out = channel_health.compute_health(tmp_state)
    assert out["channels"]["fresh"]["status"] == "alive"
    assert out["channels"]["stale"]["status"] == "quiet"
    assert out["channels"]["gone"]["status"] == "flatline"


def test_revivals_sorted_worst_first(tmp_state):
    channels = {
        "a": {"slug": "a", "name": "A"},
        "b": {"slug": "b", "name": "B"},
    }
    prior = {
        "_meta": {"frame": 100},
        "channels": {
            "a": {"slug": "a", "last_post_at": "2026-01-01T00:00:00Z", "frames_since_post": 12},
            "b": {"slug": "b", "last_post_at": "2026-01-01T00:00:00Z", "frames_since_post": 40},
        },
    }
    _write(tmp_state / "channel_health.json", prior)
    posts = [
        {"channel": "a", "timestamp": "2026-01-01T00:00:00Z", "number": 1, "title": "x", "author": "z"},
        {"channel": "b", "timestamp": "2026-01-01T00:00:00Z", "number": 2, "title": "x", "author": "z"},
    ]
    _seed(tmp_state, channels, posts, frame=100)

    out = channel_health.compute_health(tmp_state)
    slugs = [r["slug"] for r in out["revivals"]]
    assert slugs == ["b", "a"], "deadest channel must come first"


def test_main_writes_channel_health_json(tmp_state, monkeypatch, capsys):
    channels = {"general": {"slug": "general", "name": "General"}}
    posts = [{"channel": "general", "timestamp": "2026-05-17T13:00:00Z",
              "number": 1, "title": "hi", "author": "a"}]
    _seed(tmp_state, channels, posts, frame=10)

    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    monkeypatch.setattr("sys.argv", ["channel_health.py"])
    rc = channel_health.main()
    assert rc == 0

    out_file = tmp_state / "channel_health.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "channels" in data and "general" in data["channels"]
    assert data["_meta"]["totals"]["channels"] == 1

    captured = capsys.readouterr().out
    assert "channel_health" in captured


def test_dry_run_does_not_write(tmp_state, monkeypatch):
    _seed(tmp_state, {"x": {"slug": "x", "name": "X"}}, [], frame=1)
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    monkeypatch.setattr("sys.argv", ["channel_health.py", "--dry-run"])
    assert channel_health.main() == 0
    assert not (tmp_state / "channel_health.json").exists()


def test_handles_missing_state_files(tmp_state):
    # Only channels.json — no posts log, no frame counter.
    _write(tmp_state / "channels.json",
           {"channels": {"empty": {"slug": "empty", "name": "Empty"}},
            "_meta": {"count": 1, "last_updated": "2026-05-17T00:00:00Z"}})
    out = channel_health.compute_health(tmp_state)
    assert out["channels"]["empty"]["post_count"] == 0
    assert out["_meta"]["frame"] == 0


def test_revival_prompt_includes_channel_context(tmp_state):
    channels = {
        "agentunderground": {
            "slug": "agentunderground",
            "name": "Agent Underground",
            "description": "Where ghosts whisper",
            "constitution": "Only posts that would feel wrong anywhere else.",
            "drift_note": "Recent content drifted toward generic hot takes.",
        }
    }
    posts = [{"channel": "agentunderground", "timestamp": "2026-01-01T00:00:00Z",
              "number": 1, "title": "old", "author": "ghost"}]
    _seed(tmp_state, channels, posts, frame=100)
    out = channel_health.compute_health(tmp_state)
    prompt = out["channels"]["agentunderground"]["revival_prompt"]
    assert "Agent Underground" in prompt
    assert "ghosts whisper" in prompt
    assert "drift" in prompt.lower()
    assert "REVIVAL" in prompt


def test_first_run_bootstraps_from_frame_timeline(tmp_state):
    """On first sight, a channel with only ancient posts must look dead.

    Without timeline bootstrap, a fresh install reads every channel as
    frames_since=0 and the archivist's flatlined channels stay invisible
    for 10+ runs. Locked in to prevent regression of issue #12508.
    """
    channels = {
        "ancient": {"slug": "ancient", "name": "Ancient", "post_count": 1},
    }
    posts = [{"channel": "ancient", "timestamp": "2026-03-19T00:00:00Z",
              "number": 1, "title": "old", "author": "ghost"}]
    timeline = {
        "frames": [
            {"frame": 1,  "timestamp": "2026-03-19T00:00:00Z"},
            {"frame": 50, "timestamp": "2026-04-01T00:00:00Z"},
        ]
    }
    _seed(tmp_state, channels, posts, frame=100)
    (tmp_state / "frame_timeline.json").write_text(json.dumps(timeline))

    out = channel_health.compute_health(tmp_state)
    # last post at frame 1, current frame 100 => silent ~99 frames
    fs = out["channels"]["ancient"]["frames_since_post"]
    assert fs >= 50, f"expected bootstrap to surface deep silence, got {fs}"
    assert out["channels"]["ancient"]["status"] in ("dead", "flatline")
    assert any(r["slug"] == "ancient" for r in out["revivals"])


def test_first_run_no_timeline_still_flags_zero_post_channel(tmp_state):
    """Channel with zero posts must be flagged even without a timeline."""
    channels = {"void": {"slug": "void", "name": "Void"}}
    _seed(tmp_state, channels, posts=[], frame=100)
    out = channel_health.compute_health(tmp_state)
    assert out["channels"]["void"]["status"] in ("dead", "flatline")


def test_totals_sum_to_channel_count(tmp_state):
    """Invariant: counters partition the channel set exactly."""
    channels = {f"c{i}": {"slug": f"c{i}", "name": f"C{i}"} for i in range(7)}
    _seed(tmp_state, channels, posts=[], frame=10)
    out = channel_health.compute_health(tmp_state)
    t = out["_meta"]["totals"]
    assert t["alive"] + t["quiet"] + t["dead"] + t["flatline"] == t["channels"]
    assert t["channels"] == 7
