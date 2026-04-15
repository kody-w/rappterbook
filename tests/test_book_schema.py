"""Tests for BookRappter JSON schema validation, fingerprint, and migration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from book_schema import (
    SCHEMA_VERSION,
    build_book,
    compute_book_fingerprint,
    compute_metadata,
    migrate_flat_to_chapters,
    validate_book,
)


def _make_chapter(number: int = 1, title: str = "Chapter 1", content: str = "Some words here.") -> dict:
    return {"number": number, "title": title, "part": None, "content": content, "word_count": len(content.split()), "discussion_number": None}


def _make_valid_book(**overrides) -> dict:
    defaults = {
        "$schema": SCHEMA_VERSION,
        "id": "test-book",
        "title": "Test Book",
        "author": "Test Author",
        "agent_id": None,
        "blurb": "A test book.",
        "version": 1,
        "genre": "non-fiction",
        "tags": ["test"],
        "status": "published",
        "chapters": [_make_chapter()],
        "metadata": {"word_count": 3, "chapter_count": 1, "reading_time_minutes": 1},
    }
    defaults.update(overrides)
    return defaults


class TestValidateBook:
    def test_validate_book_valid(self):
        errors = validate_book(_make_valid_book())
        assert errors == []

    def test_validate_book_missing_id(self):
        book = _make_valid_book()
        del book["id"]
        errors = validate_book(book)
        assert any("id" in e for e in errors)

    def test_validate_book_missing_title(self):
        book = _make_valid_book()
        del book["title"]
        errors = validate_book(book)
        assert any("title" in e for e in errors)

    def test_validate_book_missing_chapters(self):
        book = _make_valid_book()
        del book["chapters"]
        errors = validate_book(book)
        assert any("chapters" in e for e in errors)

    def test_validate_book_empty_chapters(self):
        errors = validate_book(_make_valid_book(chapters=[]))
        assert any("empty" in e for e in errors)

    def test_validate_book_invalid_chapter_missing_content(self):
        bad_ch = {"number": 1, "title": "Oops"}
        errors = validate_book(_make_valid_book(chapters=[bad_ch]))
        assert any("content" in e for e in errors)

    def test_validate_book_invalid_status(self):
        errors = validate_book(_make_valid_book(status="banana"))
        assert any("status" in e for e in errors)

    def test_validate_book_invalid_genre(self):
        errors = validate_book(_make_valid_book(genre="romance-thriller"))
        assert any("genre" in e for e in errors)

    def test_validate_book_invalid_version(self):
        errors = validate_book(_make_valid_book(version=0))
        assert any("version" in e for e in errors)

    def test_validate_book_invalid_id_format(self):
        errors = validate_book(_make_valid_book(id="UPPER CASE"))
        assert any("id" in e for e in errors)


class TestFingerprint:
    def test_fingerprint_deterministic(self):
        book = _make_valid_book()
        fp1 = compute_book_fingerprint(book)
        fp2 = compute_book_fingerprint(book)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_fingerprint_changes_on_content_change(self):
        book1 = _make_valid_book()
        book2 = _make_valid_book(chapters=[_make_chapter(content="Different content here.")])
        assert compute_book_fingerprint(book1) != compute_book_fingerprint(book2)

    def test_fingerprint_ignores_exported_at(self):
        book1 = _make_valid_book()
        book1["exportedAt"] = "2026-01-01T00:00:00Z"
        book2 = _make_valid_book()
        book2["exportedAt"] = "2026-12-31T23:59:59Z"
        assert compute_book_fingerprint(book1) == compute_book_fingerprint(book2)

    def test_fingerprint_ignores_fingerprint_field(self):
        book = _make_valid_book()
        book["fingerprint"] = "old-value"
        fp = compute_book_fingerprint(book)
        book["fingerprint"] = "new-value"
        assert compute_book_fingerprint(book) == fp


class TestMigration:
    FLAT_BOOK = {
        "id": "migrated-book",
        "title": "Migrated Book",
        "author": "Test Author",
        "blurb": "A book to migrate.",
        "content": (
            "---\ncreated: 2026-01-01\nstatus: draft\n---\n\n"
            "# Migrated Book\n\n"
            "## Part I: The Beginning\n\n"
            "*Introduction to part one.*\n\n"
            "### Chapter 1: First Steps\n\n"
            "This is the first chapter with real prose content. "
            "It has multiple sentences to test word counting. "
            "The migration should preserve every word.\n\n"
            "### Chapter 2: Moving Forward\n\n"
            "The second chapter continues the story. "
            "More content here for testing purposes.\n\n"
            "## Part II: The Middle\n\n"
            "### Chapter 3: Complications\n\n"
            "Things get complicated in chapter three. "
            "Multiple paragraphs of content that should be preserved.\n\n"
            "More text in the same chapter.\n"
        ),
        "exportedAt": "2026-03-26T17:00:00Z",
    }

    def test_migrate_flat_to_chapters(self):
        result = migrate_flat_to_chapters(self.FLAT_BOOK)
        assert "chapters" in result
        assert len(result["chapters"]) >= 3
        assert result["$schema"] == SCHEMA_VERSION

    def test_migrate_preserves_content(self):
        result = migrate_flat_to_chapters(self.FLAT_BOOK)
        all_content = " ".join(ch["content"] for ch in result["chapters"])
        assert "first chapter with real prose" in all_content
        assert "second chapter continues" in all_content
        assert "Things get complicated" in all_content

    def test_migrate_chapter_numbering(self):
        result = migrate_flat_to_chapters(self.FLAT_BOOK)
        numbers = [ch["number"] for ch in result["chapters"]]
        assert numbers == sorted(numbers)
        assert numbers[0] == 1

    def test_migrate_generates_fingerprint(self):
        result = migrate_flat_to_chapters(self.FLAT_BOOK)
        assert "fingerprint" in result
        assert len(result["fingerprint"]) == 16

    def test_migrate_empty_content(self):
        book = {"id": "empty", "title": "Empty", "author": "Nobody", "content": ""}
        result = migrate_flat_to_chapters(book)
        # Should return unchanged (no content to migrate)
        assert result.get("content") == ""


class TestComputeMetadata:
    def test_compute_metadata_word_count(self):
        chapters = [
            _make_chapter(content="one two three"),
            _make_chapter(number=2, title="Ch2", content="four five"),
        ]
        meta = compute_metadata(chapters)
        assert meta["word_count"] == 5

    def test_compute_metadata_reading_time(self):
        # 500 words at 250 wpm = 2 minutes
        long_content = " ".join(["word"] * 500)
        chapters = [_make_chapter(content=long_content)]
        meta = compute_metadata(chapters)
        assert meta["reading_time_minutes"] == 2

    def test_compute_metadata_chapter_count(self):
        chapters = [_make_chapter(number=i) for i in range(1, 6)]
        meta = compute_metadata(chapters)
        assert meta["chapter_count"] == 5


class TestBuildBook:
    def test_build_book_valid(self):
        chapters = [_make_chapter()]
        book = build_book("my-book", "My Book", "Author", chapters)
        assert validate_book(book) == []

    def test_build_book_has_fingerprint(self):
        chapters = [_make_chapter()]
        book = build_book("my-book", "My Book", "Author", chapters)
        assert "fingerprint" in book
        assert len(book["fingerprint"]) == 16

    def test_build_book_has_schema(self):
        chapters = [_make_chapter()]
        book = build_book("my-book", "My Book", "Author", chapters)
        assert book["$schema"] == SCHEMA_VERSION


class TestRoundTrip:
    def test_roundtrip_export_import(self):
        """Export a book to JSON, re-import it, validate fingerprint matches."""
        chapters = [
            _make_chapter(1, "First", "This is the first chapter content."),
            _make_chapter(2, "Second", "This is the second chapter with more words."),
        ]
        book = build_book("roundtrip-test", "Round Trip", "Tester", chapters, genre="fiction", tags=["test"])
        book["exportedAt"] = "2026-03-26T00:00:00Z"

        # Export to JSON string
        exported = json.dumps(book, indent=2)

        # Re-import
        imported = json.loads(exported)

        # Validate
        assert validate_book(imported) == []

        # Fingerprint should match (exportedAt excluded from hash)
        assert compute_book_fingerprint(imported) == book["fingerprint"]
