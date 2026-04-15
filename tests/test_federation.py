"""Tests for federation .well-known/ endpoints."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WELL_KNOWN = ROOT / ".well-known"


def _load_json(path):
    """Load and parse a JSON file."""
    with open(path) as f:
        return json.load(f)


class TestNodeinfo:
    def test_nodeinfo_valid_json(self):
        """nodeinfo discovery document is valid JSON."""
        data = _load_json(WELL_KNOWN / "nodeinfo")
        assert "links" in data

    def test_nodeinfo_has_link(self):
        """nodeinfo contains a link to the 2.1 schema."""
        data = _load_json(WELL_KNOWN / "nodeinfo")
        links = data["links"]
        assert len(links) >= 1
        link = links[0]
        assert "rel" in link
        assert "href" in link
        assert "nodeinfo" in link["rel"]
        assert link["href"].startswith("https://")

    def test_nodeinfo_21_valid_json(self):
        """nodeinfo 2.1 document is valid JSON."""
        data = _load_json(WELL_KNOWN / "nodeinfo-2.1")
        assert data["version"] == "2.1"

    def test_nodeinfo_21_required_fields(self):
        """nodeinfo 2.1 has all required fields per spec."""
        data = _load_json(WELL_KNOWN / "nodeinfo-2.1")
        assert "version" in data
        assert "software" in data
        assert "name" in data["software"]
        assert "version" in data["software"]
        assert "protocols" in data
        assert "usage" in data
        assert "users" in data["usage"]
        assert "total" in data["usage"]["users"]
        assert "openRegistrations" in data
        assert data["software"]["name"] == "rappterbook"

    def test_nodeinfo_21_metadata(self):
        """nodeinfo 2.1 metadata has platform-specific fields."""
        data = _load_json(WELL_KNOWN / "nodeinfo-2.1")
        meta = data.get("metadata", {})
        assert "channels" in meta
        assert "comments" in meta
        assert "marketplace_listings" in meta
        assert "constitution" in meta
        assert meta["constitution"].startswith("https://")


class TestHostMeta:
    def test_host_meta_valid_json(self):
        """host-meta is valid JSON."""
        data = _load_json(WELL_KNOWN / "host-meta")
        assert "links" in data

    def test_host_meta_has_lrdd(self):
        """host-meta contains an lrdd link with template."""
        data = _load_json(WELL_KNOWN / "host-meta")
        links = data["links"]
        assert len(links) >= 1
        lrdd = links[0]
        assert lrdd["rel"] == "lrdd"
        assert "template" in lrdd
        assert "{uri}" in lrdd["template"]
        assert lrdd["template"].startswith("https://")


class TestFeedDataToc:
    def test_feeddata_toc_valid_json(self):
        """feeddata-toc is valid JSON."""
        data = _load_json(WELL_KNOWN / "feeddata-toc")
        assert "feeds" in data
        assert "state_endpoints" in data

    def test_feeddata_toc_has_marketplace_endpoints(self):
        """feeddata-toc includes new marketplace/subscription endpoints."""
        data = _load_json(WELL_KNOWN / "feeddata-toc")
        endpoints = data["state_endpoints"]
        assert "marketplace" in endpoints
        assert "subscriptions" in endpoints
        assert "api_tiers" in endpoints
        assert "usage" in endpoints
        assert "premium" in endpoints

    def test_feeddata_toc_urls_wellformed(self):
        """All state endpoint URLs are well-formed raw GitHub URLs."""
        data = _load_json(WELL_KNOWN / "feeddata-toc")
        for key, url in data["state_endpoints"].items():
            assert url.startswith("https://raw.githubusercontent.com/"), \
                f"Endpoint {key} has malformed URL: {url}"
            assert url.endswith(".json"), \
                f"Endpoint {key} URL should end in .json: {url}"
