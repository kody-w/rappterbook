"""Tests for the SDK's rapplication read side (built from files the platform already keeps)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk" / "python"))

from rapp import Rapp

FILES = {
    "state/rapps.json": {"rapps": {"news": {"name": "News", "species": "rapp"}, "solo": {"name": "Solo"}}},
    "state/channels.json": {"channels": {"news": {"name": "News room", "tag": "N"}, "code": {"name": "Code"}}},
    "docs/api/media.json": {"media": [
        {"channel": "news", "media_type": "page", "public_path": "media/news/ui.html"},
        {"channel": "news", "media_type": "image", "public_path": "media/news/a.png"},
        {"channel": "code", "media_type": "page", "public_path": "media/code/x.html"},
    ]},
    "state/rapps/news.json": {"_format": "egg", "organism": {"slug": "news"}},
}


def make(files=FILES):
    r = Rapp()

    def fake(path):
        if path not in files:
            raise RuntimeError("not found: " + path)
        return json.loads(json.dumps(files[path]))

    r._fetch_json = fake
    return r


def test_lists_every_installed_rapplication_with_slug():
    apps = make().rapplications()
    assert [a["slug"] for a in apps] == ["news", "solo"]
    assert apps[0]["name"] == "News"


def test_room_is_the_channel_of_the_same_slug_or_none():
    apps = {a["slug"]: a for a in make().rapplications()}
    assert apps["news"]["room"] == {"slug": "news", "name": "News room", "tag": "N"}
    assert apps["solo"]["room"] is None


def test_pages_are_only_the_page_files_shared_into_that_room():
    apps = {a["slug"]: a for a in make().rapplications()}
    assert [p["public_path"] for p in apps["news"]["pages"]] == ["media/news/ui.html"]
    assert apps["solo"]["pages"] == []


def test_missing_media_list_gives_no_pages_not_an_error():
    files = {k: v for k, v in FILES.items() if k != "docs/api/media.json"}
    assert all(a["pages"] == [] for a in make(files).rapplications())


def test_one_rapplication_carries_its_egg():
    app = make().rapplication("news")
    assert app["egg"]["_format"] == "egg"
    assert make().rapplication("solo")["egg"] is None


def test_unknown_rapplication_raises_keyerror():
    with pytest.raises(KeyError):
        make().rapplication("nope")


def test_reads_the_real_registry_in_this_checkout():
    r = Rapp()
    r._fetch_json = lambda path: json.loads((ROOT / path).read_text())
    apps = r.rapplications()
    assert len(apps) == len(json.loads((ROOT / "state" / "rapps.json").read_text())["rapps"])
    assert all("room" in a and "pages" in a for a in apps)
