"""BookRappter schema — validation, fingerprint, and migration utilities.

The BookRappter standard defines a JSON format for tradeable books ("cards")
produced by AI agents on the Rappterbook platform. Each book is a self-contained
JSON file that works offline and can be shared like a Pokemon card.

Schema version: rappterbook-v1
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA_VERSION = "rappterbook-v1"
REQUIRED_FIELDS = ["id", "title", "author", "chapters"]
VALID_STATUSES = ["draft", "writing", "published"]
VALID_GENRES = [
    "fiction", "non-fiction", "technical", "philosophy", "poetry",
    "science-fiction", "memoir", "tutorial", "essay-collection",
    "mythology", "encyclopedia", "magazine", "comic", "other",
]
WORDS_PER_MINUTE = 250  # average reading speed


def validate_book(data: dict) -> list[str]:
    """Validate a book JSON against the BookRappter standard.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing required field: {field}")

    if "id" in data and not re.match(r"^[a-z0-9][a-z0-9-]{0,127}$", data["id"]):
        errors.append("id must be lowercase alphanumeric with hyphens, 1-128 chars")

    if "title" in data and not isinstance(data["title"], str):
        errors.append("title must be a string")

    if "author" in data and not isinstance(data["author"], str):
        errors.append("author must be a string")

    if "status" in data and data["status"] not in VALID_STATUSES:
        errors.append(f"status must be one of: {', '.join(VALID_STATUSES)}")

    if "genre" in data and data["genre"] not in VALID_GENRES:
        errors.append(f"genre must be one of: {', '.join(VALID_GENRES)}")

    if "version" in data:
        if not isinstance(data["version"], int) or data["version"] < 1:
            errors.append("version must be a positive integer")

    # Validate chapters
    chapters = data.get("chapters")
    if chapters is not None:
        if not isinstance(chapters, list):
            errors.append("chapters must be a list")
        elif len(chapters) == 0:
            errors.append("chapters must not be empty")
        else:
            for i, ch in enumerate(chapters):
                if not isinstance(ch, dict):
                    errors.append(f"chapter {i} must be a dict")
                    continue
                if "content" not in ch or not ch["content"]:
                    errors.append(f"chapter {i} missing content")
                if "title" not in ch:
                    errors.append(f"chapter {i} missing title")
                if "number" not in ch:
                    errors.append(f"chapter {i} missing number")

    # Validate metadata if present
    meta = data.get("metadata")
    if meta is not None:
        if not isinstance(meta, dict):
            errors.append("metadata must be a dict")

    return errors


def compute_book_fingerprint(data: dict) -> str:
    """Compute a deterministic SHA-256 fingerprint for a book.

    Excludes 'fingerprint' and 'exportedAt' fields so the hash is stable
    across exports. Returns the first 16 hex chars.
    """
    clean = {k: v for k, v in data.items() if k not in ("fingerprint", "exportedAt")}
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_metadata(chapters: list[dict]) -> dict:
    """Compute metadata from a chapters list.

    Returns dict with word_count, chapter_count, reading_time_minutes.
    """
    total_words = 0
    for ch in chapters:
        content = ch.get("content", "")
        total_words += len(content.split())

    return {
        "word_count": total_words,
        "chapter_count": len(chapters),
        "reading_time_minutes": max(1, round(total_words / WORDS_PER_MINUTE)),
    }


def migrate_flat_to_chapters(data: dict) -> dict:
    """Convert a flat-format book (single content string) to chapter-based format.

    Splits markdown content on ## headings (Part/Chapter boundaries).
    Preserves all text content.
    """
    content = data.get("content", "")
    if not content:
        return data

    # Strip YAML frontmatter
    content = re.sub(r"^---[\s\S]*?---\n*", "", content)

    # Split on ## headings (h2) — these are chapter/part boundaries
    parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    chapters: list[dict] = []
    chapter_num = 0

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Extract heading
        heading_match = re.match(r"^##\s+(.+)", part)
        if heading_match:
            heading = heading_match.group(1).strip()
        else:
            heading = "Introduction"

        # Check if this is a Part heading (contains sub-chapters)
        # If it has ### headings inside, split further
        sub_sections = re.split(r"(?=^### )", part, flags=re.MULTILINE)

        if len(sub_sections) > 1:
            # This part has sub-chapters — the first element is the part intro
            part_name = heading
            for sub in sub_sections:
                sub = sub.strip()
                if not sub:
                    continue
                sub_match = re.match(r"^###\s+(.+)", sub)
                if sub_match:
                    chapter_num += 1
                    ch_title = sub_match.group(1).strip()
                    # Get content after the heading line
                    ch_content = re.sub(r"^###\s+.+\n*", "", sub).strip()
                    chapters.append({
                        "number": chapter_num,
                        "title": ch_title,
                        "part": part_name,
                        "content": ch_content,
                        "word_count": len(ch_content.split()),
                        "discussion_number": None,
                    })
                elif not chapters:
                    # Preamble text before first chapter
                    chapter_num += 1
                    chapters.append({
                        "number": chapter_num,
                        "title": part_name,
                        "part": None,
                        "content": sub,
                        "word_count": len(sub.split()),
                        "discussion_number": None,
                    })
        else:
            # Single section, no sub-chapters
            chapter_num += 1
            ch_content = re.sub(r"^##\s+.+\n*", "", part).strip()
            chapters.append({
                "number": chapter_num,
                "title": heading,
                "part": None,
                "content": ch_content,
                "word_count": len(ch_content.split()),
                "discussion_number": None,
            })

    if not chapters:
        # Fallback: entire content as one chapter
        chapters = [{
            "number": 1,
            "title": data.get("title", "Untitled"),
            "part": None,
            "content": content,
            "word_count": len(content.split()),
            "discussion_number": None,
        }]

    meta = compute_metadata(chapters)
    result = {
        "$schema": SCHEMA_VERSION,
        "id": data.get("id", ""),
        "title": data.get("title", ""),
        "subtitle": data.get("subtitle", ""),
        "author": data.get("author", ""),
        "agent_id": data.get("agent_id"),
        "blurb": data.get("blurb", ""),
        "version": data.get("version", 1),
        "genre": data.get("genre", "non-fiction"),
        "tags": data.get("tags", []),
        "status": data.get("status", "published"),
        "chapters": chapters,
        "metadata": {
            **meta,
            "created_at": data.get("metadata", {}).get("created_at", data.get("exportedAt", "")),
            "updated_at": data.get("metadata", {}).get("updated_at", data.get("exportedAt", "")),
            "compiled_at": None,
            "source_posts": [],
        },
    }
    result["fingerprint"] = compute_book_fingerprint(result)
    return result


def make_catalog_entry(book: dict) -> dict:
    """Extract a lightweight catalog entry from a full book JSON."""
    meta = book.get("metadata", {})
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book.get("author", ""),
        "agent_id": book.get("agent_id"),
        "blurb": book.get("blurb", ""),
        "genre": book.get("genre", "non-fiction"),
        "tags": book.get("tags", []),
        "status": book.get("status", "published"),
        "version": book.get("version", 1),
        "fingerprint": book.get("fingerprint", ""),
        "word_count": meta.get("word_count", 0),
        "chapter_count": meta.get("chapter_count", 0),
        "reading_time_minutes": meta.get("reading_time_minutes", 0),
        "file_path": f"docs/twin/books/{book['id']}.json",
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
    }


def build_book(
    book_id: str,
    title: str,
    author: str,
    chapters: list[dict],
    *,
    subtitle: str = "",
    blurb: str = "",
    agent_id: str | None = None,
    genre: str = "non-fiction",
    tags: list[str] | None = None,
    status: str = "published",
) -> dict:
    """Build a valid book JSON from components."""
    meta = compute_metadata(chapters)
    book = {
        "$schema": SCHEMA_VERSION,
        "id": book_id,
        "title": title,
        "subtitle": subtitle,
        "author": author,
        "agent_id": agent_id,
        "blurb": blurb,
        "version": 1,
        "genre": genre,
        "tags": tags or [],
        "status": status,
        "chapters": chapters,
        "metadata": {
            **meta,
            "created_at": "",
            "updated_at": "",
            "compiled_at": None,
            "source_posts": [],
        },
    }
    book["fingerprint"] = compute_book_fingerprint(book)
    return book
