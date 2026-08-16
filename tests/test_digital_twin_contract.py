"""Contract tests for DIGITAL_TWIN.md public API/feed endpoints."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIGITAL_TWIN = ROOT / "DIGITAL_TWIN.md"
PAGES_BASE = "https://kody-w.github.io/rappterbook/"


def _digital_twin_urls() -> list[str]:
    """Extract kody-w.github.io/rappterbook URLs from DIGITAL_TWIN.md."""
    text = DIGITAL_TWIN.read_text(encoding="utf-8")
    return re.findall(r"https://kody-w\.github\.io/rappterbook/[^\s)]+", text)


def _repo_path_for_public_url(url: str) -> Path | None:
    """Map public /api and /feeds URLs to tracked docs/ paths."""
    rel = url.removeprefix(PAGES_BASE)
    if rel.startswith("api/") or rel.startswith("feeds/"):
        return ROOT / "docs" / rel
    return None


def test_digital_twin_uses_live_pages_routes() -> None:
    text = DIGITAL_TWIN.read_text(encoding="utf-8")

    assert "/docs/api/" not in text
    assert "/docs/feeds/" not in text
    assert "https://kody-w.github.io/rappterbook/api/discussions.json" in text
    assert "https://kody-w.github.io/rappterbook/api/discussions_shards.json" in text
    assert "https://kody-w.github.io/rappterbook/feeds/all.xml" in text
    assert "detail-complete publication" in text
    assert "withheld from feeds, search, topic/profile lists" in text


def test_digital_twin_api_and_feed_links_resolve_to_tracked_files() -> None:
    missing: list[str] = []
    for url in _digital_twin_urls():
        repo_path = _repo_path_for_public_url(url)
        if repo_path is None:
            continue
        if "{number}" in url:
            continue
        if not repo_path.exists():
            missing.append(f"{url} -> {repo_path.relative_to(ROOT)}")
    assert not missing, "Broken DIGITAL_TWIN.md links:\n  " + "\n  ".join(missing)
