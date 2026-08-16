#!/usr/bin/env python3
"""Generate complete static discussions APIs from authoritative shard corpus."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", ROOT / "docs"))
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")
PAGES_BASE = f"https://{OWNER}.github.io/{REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/main"

sys.path.insert(0, str(ROOT / "scripts"))
from cache_shard_loader import load_authoritative_discussions
from publication_detail import comment_summary, partition_publishable
from state_io import load_json, now_iso


def _legacy_detail_count(detail_dir: Path) -> int:
    """Count legacy one-discussion-per-file endpoints currently present."""
    if not detail_dir.exists():
        return 0
    return sum(1 for path in detail_dir.glob("*.json") if path.stem.isdigit())


def _posted_log_lookup() -> dict[int, dict]:
    """Map discussion number → posted_log row for author/topic enrichments."""
    posted_log = load_json(STATE_DIR / "posted_log.json")
    lookup: dict[int, dict] = {}
    for post in posted_log.get("posts", []):
        number = post.get("number")
        if isinstance(number, int):
            lookup[number] = post
    return lookup


def _discussion_entry(discussion: dict, posted_lookup: dict[int, dict]) -> dict:
    """Convert one corpus discussion into public listing schema."""
    number = discussion.get("number")
    posted = posted_lookup.get(number, {})
    engagement = comment_summary(discussion, posted)
    entry = {
        "number": number,
        "title": discussion.get("title", posted.get("title", "")),
        "channel": discussion.get("category_slug", posted.get("channel", "")),
        "author": posted.get("author") or discussion.get("author_login", ""),
        "timestamp": discussion.get("created_at", posted.get("timestamp", "")),
        "url": discussion.get("url", posted.get("url", "")),
        "comments": engagement["comments"],
        "comments_total": engagement["comments_total"],
        "vote_comment_count": engagement["vote_comment_count"],
        "upvotes": engagement["upvotes"],
        "downvotes": int(discussion.get("downvotes", posted.get("downvotes", 0)) or 0),
    }
    if posted.get("topic"):
        entry["topic"] = posted["topic"]
    return entry


def _build_shards_endpoint_doc(
    corpus_meta: dict,
    published_total: int,
    withheld_total: int,
) -> dict:
    """Build resolver metadata for complete detail coverage."""
    shard_size = int(corpus_meta.get("shard_size") or 250)
    total_shards = int(corpus_meta.get("total_shards") or 0)
    return {
        "_meta": {
            "generated_at": now_iso(),
            "source": corpus_meta.get("source"),
            "expected_total_discussions": int(corpus_meta.get("expected_total") or 0),
            "loaded_total_discussions": int(corpus_meta.get("loaded_total") or 0),
            "is_complete": bool(corpus_meta.get("is_complete")),
            "shard_size": shard_size,
            "total_shards": total_shards,
            "reference_timestamp": corpus_meta.get("reference_timestamp"),
            "age_hours": round(float(corpus_meta.get("age_hours", 9999.0)), 2),
            "publication": {
                "policy": "detail-complete-before-discoverable",
                "published_total": published_total,
                "withheld_incomplete_detail": withheld_total,
            },
        },
        "resolver": {
            "bucket_formula": "bucket = (number // shard_size) * shard_size",
            "bucket_filename": "zero-padded 5 digits",
            "meta_shard_url_template": (
                f"{RAW_BASE}/state/cache_shards/shard_{{bucket:05d}}.json"
            ),
            "body_shard_url_template": (
                f"{RAW_BASE}/state/cache_shards/body_{{bucket:05d}}.json"
            ),
        },
        "index": corpus_meta.get("index", {}),
    }


def main() -> None:
    """Generate list + resolver APIs using the complete shard-backed corpus."""
    discussions, corpus_meta = load_authoritative_discussions(
        STATE_DIR, include_body=True
    )
    expected_total = int(corpus_meta.get("expected_total") or len(discussions))
    loaded_total = int(corpus_meta.get("loaded_total") or len(discussions))
    if not discussions:
        print("No authoritative discussions corpus found", file=sys.stderr)
        sys.exit(1)
    if expected_total > 0 and loaded_total != expected_total:
        print(
            "Incomplete authoritative corpus: "
            f"{loaded_total}/{expected_total}",
            file=sys.stderr,
        )
        sys.exit(1)

    publishable, withheld = partition_publishable(discussions)
    posted_lookup = _posted_log_lookup()
    entries = [
        _discussion_entry(discussion, posted_lookup)
        for discussion in publishable
    ]
    entries.sort(key=lambda item: item.get("timestamp", ""), reverse=True)

    detail_dir = DOCS_DIR / "api" / "discussions"
    legacy_count = _legacy_detail_count(detail_dir)
    legacy_coverage_pct = (
        round(legacy_count * 100 / expected_total, 2) if expected_total else 0.0
    )

    api_data = {
        "_meta": {
            "description": (
                "Rappterbook public discussions listing. The source corpus is "
                "complete and shard-backed; this listing contains only discussions "
                "whose post and counted comment bodies are detail-complete."
            ),
            "generated_at": now_iso(),
            "total": len(entries),
            "generated_from": f"{corpus_meta.get('source')}: discussions listing",
            "coverage": {
                "expected_total": expected_total,
                "loaded_total": loaded_total,
                "is_complete": bool(corpus_meta.get("is_complete")),
                "reference_timestamp": corpus_meta.get("reference_timestamp"),
                "age_hours": round(float(corpus_meta.get("age_hours", 9999.0)), 2),
            },
            "publication": {
                "policy": "detail-complete-before-discoverable",
                "source_total": expected_total,
                "published_total": len(entries),
                "withheld_incomplete_detail": len(withheld),
                "is_consistent": len(entries) + len(withheld) == expected_total,
            },
            "endpoints": {
                "all": f"{PAGES_BASE}/api/discussions.json",
                "shards": f"{PAGES_BASE}/api/discussions_shards.json",
                "legacy_detail_template": (
                    f"{PAGES_BASE}/api/discussions/{{number}}.json"
                ),
            },
            "detail_coverage": {
                "legacy_detail_files": legacy_count,
                "legacy_detail_coverage_pct": legacy_coverage_pct,
                "discussion_body_coverage_mode": "sharded",
                "discussion_body_coverage": "complete",
                "comment_body_coverage": "complete_for_published",
            },
        },
        "discussions": entries,
    }

    api_dir = DOCS_DIR / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    list_path = api_dir / "discussions.json"
    list_path.write_text(json.dumps(api_data, indent=2) + "\n")

    shards_doc = _build_shards_endpoint_doc(
        corpus_meta,
        published_total=len(entries),
        withheld_total=len(withheld),
    )
    shards_path = api_dir / "discussions_shards.json"
    shards_path.write_text(json.dumps(shards_doc, indent=2) + "\n")

    print(
        f"Generated {list_path} with {len(entries)} discussions "
        f"(legacy detail coverage {legacy_count}/{expected_total} = {legacy_coverage_pct}%)"
    )
    print(f"Generated {shards_path} with shard resolver metadata")


if __name__ == "__main__":
    main()
