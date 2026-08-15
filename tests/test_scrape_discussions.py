import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scrape_discussions


def test_full_scrape_follows_pagination_past_legacy_8000_cap(monkeypatch):
    calls = {"count": 0}

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
