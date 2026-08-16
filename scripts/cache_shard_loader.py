#!/usr/bin/env python3
from __future__ import annotations
"""Load discussion corpora from cache shards or discussions_cache.json."""

import json
from datetime import datetime, timezone
from pathlib import Path


def _load_json(path: Path) -> dict:
    """Return parsed JSON from path, or {} when missing/corrupt."""
    try:
        with open(path) as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _now_iso() -> str:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime_iso(path: Path) -> str:
    """Convert file mtime to UTC ISO format."""
    if not path.exists():
        return _now_iso()
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def age_hours(timestamp: str) -> float:
    """Return elapsed hours since an ISO timestamp."""
    try:
        then = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return 9999.0
    delta = datetime.now(timezone.utc) - then
    return delta.total_seconds() / 3600


def load_discussions_cache(
    state_dir: Path, include_body: bool = True
) -> tuple[list[dict], dict]:
    """Load discussions from state/discussions_cache.json."""
    path = state_dir / "discussions_cache.json"
    data = _load_json(path)
    discussions = data.get("discussions", [])
    if not include_body:
        discussions = [
            {
                key: value for key, value in discussion.items()
                if key not in {"body", "comments", "comment_authors"}
            }
            for discussion in discussions
        ]
    meta = data.get("_meta", {})
    expected_total = int(meta.get("total") or len(discussions))
    reference_ts = meta.get("scraped_at") or meta.get("generated_at") or _mtime_iso(path)
    return discussions, {
        "source": "discussions_cache",
        "expected_total": expected_total,
        "loaded_total": len(discussions),
        "is_complete": bool(discussions) and len(discussions) == expected_total,
        "reference_timestamp": reference_ts,
        "age_hours": age_hours(reference_ts),
        "shard_size": None,
        "total_shards": None,
        "comment_total": sum(int(d.get("comment_count") or 0) for d in discussions),
    }


def load_cache_shards(
    state_dir: Path, include_body: bool = False
) -> tuple[list[dict], dict]:
    """Load discussions from state/cache_shards/ index and shard files."""
    shard_dir = state_dir / "cache_shards"
    index_path = shard_dir / "index.json"
    index = _load_json(index_path)
    shards = index.get("shards", {})
    if not shards:
        return [], {
            "source": "cache_shards",
            "expected_total": 0,
            "loaded_total": 0,
            "is_complete": False,
            "reference_timestamp": _mtime_iso(index_path),
            "age_hours": age_hours(_mtime_iso(index_path)),
            "shard_size": None,
            "total_shards": 0,
            "comment_total": 0,
        }

    index_meta = index.get("_meta", {})
    shard_size = int(index_meta.get("shard_size") or 250)
    expected_total = int(index_meta.get("total_discussions") or 0)
    reference_ts = (
        index_meta.get("source_scraped_at")
        or index_meta.get("generated_at")
        or _mtime_iso(index_path)
    )

    discussions: list[dict] = []
    comment_total = 0
    for bucket, shard_info in sorted(
        shards.items(), key=lambda item: int(item[0])
    ):
        _ = bucket
        meta_file = shard_dir / shard_info["file"]
        body_file = shard_dir / shard_info["body_file"]
        meta_discussions = _load_json(meta_file).get("discussions", [])
        body_map = _load_json(body_file) if include_body else {}
        for discussion in meta_discussions:
            merged = dict(discussion)
            if include_body:
                detail = body_map.get(str(discussion.get("number")), {})
                if isinstance(detail, dict):
                    for field in (
                        "body",
                        "comments",
                        "comment_authors",
                        "comments_complete",
                        "reply_bodies_complete",
                        "top_level_comment_count",
                        "comments_hydrated_at",
                        "comments_hydrated_updated_at",
                    ):
                        if field in detail:
                            merged[field] = detail[field]
            discussions.append(merged)
            comment_total += int(discussion.get("comment_count") or 0)

    if expected_total == 0:
        expected_total = len(discussions)
    return discussions, {
        "source": "cache_shards",
        "expected_total": expected_total,
        "loaded_total": len(discussions),
        "is_complete": bool(discussions) and len(discussions) == expected_total,
        "reference_timestamp": reference_ts,
        "age_hours": age_hours(reference_ts),
        "shard_size": shard_size,
        "total_shards": int(index_meta.get("total_shards") or len(shards)),
        "comment_total": comment_total,
        "index": index,
    }


def load_authoritative_discussions(
    state_dir: Path, include_body: bool = False
) -> tuple[list[dict], dict]:
    """Load the best available complete discussion corpus.

    Prefers discussions_cache.json when present; otherwise falls back to
    committed cache shards.
    """
    discussions, meta = load_discussions_cache(state_dir, include_body=include_body)
    if discussions:
        return discussions, meta
    return load_cache_shards(state_dir, include_body=include_body)
