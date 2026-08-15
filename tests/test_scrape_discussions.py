import sys
import http.client
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scrape_discussions


def test_full_scrape_follows_pagination_past_legacy_8000_cap(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setenv("SCRAPE_PAGE_DELAY_SECONDS", "0")

    def fake_graphql(query, token):
        calls["count"] += 1
        page = calls["count"]
        return {
            "data": {
                "repository": {
                    "discussions": {
                        "pageInfo": {
                            "hasNextPage": page < 81,
                            "endCursor": f"cursor-{page}",
                        },
                        "nodes": [{
                            "number": page,
                            "title": f"Post {page}",
                            "createdAt": "2026-08-14T00:00:00Z",
                            "comments": {"totalCount": 0, "nodes": []},
                            "upvotes": {"totalCount": 0},
                            "downvotes": {"totalCount": 0},
                        }],
                    }
                }
            }
        }

    monkeypatch.setattr(scrape_discussions, "graphql", fake_graphql)

    discussions = scrape_discussions.scrape_all_discussions("token")

    assert len(discussions) == 81
    assert calls["count"] == 81


def test_light_scrape_omits_comment_nodes(monkeypatch):
    queries = []

    def fake_graphql(query, token):
        queries.append(query)
        return {
            "data": {
                "repository": {
                    "discussions": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{
                            "number": 1,
                            "title": "Post",
                            "body": "Body",
                            "createdAt": "2026-08-14T00:00:00Z",
                            "comments": {"totalCount": 5},
                            "upvotes": {"totalCount": 1},
                            "downvotes": {"totalCount": 0},
                        }],
                    }
                }
            }
        }

    monkeypatch.setattr(scrape_discussions, "graphql", fake_graphql)

    discussions = scrape_discussions.scrape_all_discussions(
        "token", light=True)

    assert "comments { totalCount }" in queries[0]
    assert "comments(first: 100)" not in queries[0]
    assert "comment_authors" not in discussions[0]


def test_light_merge_preserves_rich_cached_fields(tmp_path, monkeypatch):
    cache = tmp_path / "discussions_cache.json"
    cache.write_text(json.dumps({
        "discussions": [{
            "number": 1,
            "title": "Old",
            "comment_authors": [{"login": "agent-a"}],
        }],
    }))
    monkeypatch.setattr(scrape_discussions, "CACHE_FILE", cache)
    monkeypatch.setattr(scrape_discussions, "STATE_DIR", tmp_path)
    monkeypatch.setattr(scrape_discussions, "_fetch_origin_cache", lambda: {})

    scrape_discussions.save_cache([{"number": 1, "title": "New"}])

    merged = json.loads(cache.read_text())["discussions"][0]
    assert merged["title"] == "New"
    assert merged["comment_authors"] == [{"login": "agent-a"}]


def test_graphql_retries_incomplete_reads(monkeypatch):
    responses = [
        http.client.IncompleteRead(b"{", 1),
        json.dumps({"data": {"ok": True}}).encode(),
    ]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(
        scrape_discussions.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(),
    )
    monkeypatch.setattr(scrape_discussions.time, "sleep", lambda seconds: None)

    result = scrape_discussions.graphql("query { viewer { login } }", "token")

    assert result == {"data": {"ok": True}}


def test_secondary_rate_limit_waits_at_least_a_minute():
    error = scrape_discussions.urllib.error.HTTPError(
        "https://api.github.com/graphql",
        403,
        "Forbidden",
        {"Retry-After": "75"},
        None,
    )

    assert scrape_discussions.retry_wait_seconds(error, 0) == 75
