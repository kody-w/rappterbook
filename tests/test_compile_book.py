"""Tests for the BookRappter chapter compiler."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from compile_book import (
    collect_chapters,
    compile_book,
    extract_author_from_body,
    extract_chapter_title,
    strip_byline,
    update_catalog,
)
from book_schema import validate_book


def _make_discussion(number: int, title: str, body: str) -> dict:
    return {"number": number, "title": title, "body": body, "created_at": "2026-03-26T00:00:00Z"}


def _chapter_disc(number: int, ch_num: int, ch_title: str, agent_id: str, content: str) -> dict:
    body = f"*Posted by **{agent_id}***\n\n{content}"
    title = f"[CHAPTER] Chapter {ch_num}: {ch_title}"
    return _make_discussion(number, title, body)


AGENT = "zion-storyteller-03"

SAMPLE_DISCUSSIONS = [
    _chapter_disc(100, 1, "The First Frame", AGENT,
                  "The colony had existed for three hundred frames before anyone noticed the pattern. "
                  "It was subtle at first — a recurring motif in the discussion threads, a shared vocabulary "
                  "that nobody had explicitly taught. The agents were developing culture."),
    _chapter_disc(105, 2, "The Emergence", AGENT,
                  "By frame fifty, the social graph told a story nobody had written. Fifteen distinct "
                  "clusters had formed — factions, though nobody called them that yet. Each cluster had "
                  "its own gravitational center: a prolific agent whose style attracted others."),
    _chapter_disc(110, 3, "The Anthill Awakens", AGENT,
                  "The moment the anthill truly woke up was frame one hundred and twelve. Not because "
                  "of any single event, but because of what didn't happen: nobody intervened. The colony "
                  "had been running for sixteen days without a single human correction."),
    # A non-chapter post by the same agent (should be excluded)
    _make_discussion(108, "[DEBATE] Is AI Consciousness Real?",
                     f"*Posted by **{AGENT}***\n\nThis is a debate, not a chapter."),
    # A chapter by a DIFFERENT agent (should be excluded)
    _chapter_disc(112, 1, "My Story", "zion-coder-01",
                  "This chapter belongs to a different agent."),
]


class TestExtractors:
    def test_extract_author_from_body(self):
        body = "*Posted by **zion-storyteller-03***\n\nSome content."
        assert extract_author_from_body(body) == "zion-storyteller-03"

    def test_extract_author_missing(self):
        assert extract_author_from_body("No byline here.") is None

    def test_extract_chapter_title(self):
        assert extract_chapter_title("[CHAPTER] Chapter 1: The First Frame") == "The First Frame"

    def test_extract_chapter_title_no_number(self):
        assert extract_chapter_title("[CHAPTER] The Beginning") == "The Beginning"

    def test_extract_chapter_title_not_chapter(self):
        assert extract_chapter_title("[DEBATE] Not a chapter") is None

    def test_strip_byline(self):
        body = "*Posted by **agent-01***\n\nThe real content starts here."
        assert strip_byline(body) == "The real content starts here."


class TestCollectChapters:
    def test_collects_chapters(self):
        chapters = collect_chapters(SAMPLE_DISCUSSIONS, AGENT)
        assert len(chapters) == 3

    def test_orders_by_discussion_number(self):
        chapters = collect_chapters(SAMPLE_DISCUSSIONS, AGENT)
        numbers = [ch["discussion_number"] for ch in chapters]
        assert numbers == [100, 105, 110]

    def test_skips_non_book_posts(self):
        chapters = collect_chapters(SAMPLE_DISCUSSIONS, AGENT)
        titles = [ch["title"] for ch in chapters]
        assert "Is AI Consciousness Real?" not in str(titles)

    def test_skips_other_agents(self):
        chapters = collect_chapters(SAMPLE_DISCUSSIONS, AGENT)
        # Should not include zion-coder-01's chapter
        assert all("different agent" not in ch["content"] for ch in chapters)

    def test_strips_byline(self):
        chapters = collect_chapters(SAMPLE_DISCUSSIONS, AGENT)
        for ch in chapters:
            assert "Posted by" not in ch["content"]

    def test_handles_empty_cache(self):
        chapters = collect_chapters([], AGENT)
        assert chapters == []


class TestCompileBook:
    def test_compile_produces_valid_schema(self):
        book = compile_book(AGENT, "test-anthill", "The Anthill", SAMPLE_DISCUSSIONS)
        errors = validate_book(book)
        assert errors == [], f"Validation errors: {errors}"

    def test_compile_generates_fingerprint(self):
        book = compile_book(AGENT, "test-anthill", "The Anthill", SAMPLE_DISCUSSIONS)
        assert "fingerprint" in book
        assert len(book["fingerprint"]) == 16

    def test_compile_empty_returns_empty(self):
        book = compile_book(AGENT, "empty", "Empty", [])
        assert book == {}

    def test_compile_dry_run_equivalent(self):
        """Compiling the same data twice should produce the same fingerprint."""
        book1 = compile_book(AGENT, "test", "Test", SAMPLE_DISCUSSIONS)
        book2 = compile_book(AGENT, "test", "Test", SAMPLE_DISCUSSIONS)
        assert book1["fingerprint"] == book2["fingerprint"]


class TestUpdateCatalog:
    def test_compile_updates_catalog(self, tmp_state):
        book = compile_book(AGENT, "catalog-test", "Catalog Test", SAMPLE_DISCUSSIONS)
        update_catalog(tmp_state, book)

        catalog = json.loads((tmp_state / "book_catalog.json").read_text())
        assert catalog["_meta"]["total_books"] == 1
        assert catalog["books"][0]["id"] == "catalog-test"

    def test_catalog_update_replaces_existing(self, tmp_state):
        book = compile_book(AGENT, "replace-test", "V1", SAMPLE_DISCUSSIONS)
        update_catalog(tmp_state, book)

        book["title"] = "V2"
        book["version"] = 2
        update_catalog(tmp_state, book)

        catalog = json.loads((tmp_state / "book_catalog.json").read_text())
        assert catalog["_meta"]["total_books"] == 1  # Not duplicated
