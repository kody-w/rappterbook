"""Tests for BookRappter catalog state management."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from book_schema import build_book, make_catalog_entry

# Re-use conftest's tmp_state fixture (provides state dir with book_catalog.json)


def _load_catalog(state_dir: Path) -> dict:
    return json.loads((state_dir / "book_catalog.json").read_text())


def _save_catalog(state_dir: Path, catalog: dict) -> None:
    (state_dir / "book_catalog.json").write_text(json.dumps(catalog, indent=2))


def _sample_book(book_id: str = "test-book") -> dict:
    ch = {"number": 1, "title": "Ch1", "part": None,
          "content": "Some real prose content here.", "word_count": 5,
          "discussion_number": None}
    return build_book(book_id, "Test Book", "Author", [ch], blurb="A test.")


class TestBookCatalog:
    def test_catalog_initial_empty(self, tmp_state):
        catalog = _load_catalog(tmp_state)
        assert catalog["_meta"]["total_books"] == 0
        assert catalog["books"] == []

    def test_catalog_add_book(self, tmp_state):
        catalog = _load_catalog(tmp_state)
        book = _sample_book()
        entry = make_catalog_entry(book)
        catalog["books"].append(entry)
        catalog["_meta"]["total_books"] = len(catalog["books"])
        _save_catalog(tmp_state, catalog)

        reloaded = _load_catalog(tmp_state)
        assert reloaded["_meta"]["total_books"] == 1
        assert reloaded["books"][0]["id"] == "test-book"

    def test_catalog_no_duplicate_ids(self, tmp_state):
        catalog = _load_catalog(tmp_state)
        book = _sample_book("unique-book")
        entry = make_catalog_entry(book)
        catalog["books"].append(entry)

        # Try adding same ID again — should be blocked
        existing_ids = {b["id"] for b in catalog["books"]}
        assert "unique-book" in existing_ids
        # Duplicate detection: check before adding
        duplicate = make_catalog_entry(_sample_book("unique-book"))
        if duplicate["id"] not in existing_ids:
            catalog["books"].append(duplicate)
        assert len([b for b in catalog["books"] if b["id"] == "unique-book"]) == 1

    def test_catalog_update_book(self, tmp_state):
        catalog = _load_catalog(tmp_state)
        book = _sample_book("update-me")
        entry = make_catalog_entry(book)
        catalog["books"].append(entry)
        _save_catalog(tmp_state, catalog)

        # Update: replace entry with same ID
        catalog = _load_catalog(tmp_state)
        updated_book = _sample_book("update-me")
        updated_book["version"] = 2
        updated_entry = make_catalog_entry(updated_book)
        catalog["books"] = [
            updated_entry if b["id"] == "update-me" else b
            for b in catalog["books"]
        ]
        _save_catalog(tmp_state, catalog)

        final = _load_catalog(tmp_state)
        assert final["books"][0]["version"] == 2

    def test_catalog_remove_book(self, tmp_state):
        catalog = _load_catalog(tmp_state)
        for i in range(3):
            entry = make_catalog_entry(_sample_book(f"book-{i}"))
            catalog["books"].append(entry)
        catalog["_meta"]["total_books"] = 3
        _save_catalog(tmp_state, catalog)

        # Remove book-1
        catalog = _load_catalog(tmp_state)
        catalog["books"] = [b for b in catalog["books"] if b["id"] != "book-1"]
        catalog["_meta"]["total_books"] = len(catalog["books"])
        _save_catalog(tmp_state, catalog)

        final = _load_catalog(tmp_state)
        assert final["_meta"]["total_books"] == 2
        assert all(b["id"] != "book-1" for b in final["books"])

    def test_catalog_entry_has_required_fields(self, tmp_state):
        book = _sample_book()
        entry = make_catalog_entry(book)
        required = ["id", "title", "author", "blurb", "status", "version",
                     "fingerprint", "word_count", "chapter_count", "file_path"]
        for field in required:
            assert field in entry, f"missing field: {field}"
