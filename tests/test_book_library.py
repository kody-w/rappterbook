"""Tests for the book library system — manifest, book files, and book.html integrity."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = REPO_ROOT / "docs" / "twin" / "books"
BOOK_HTML = REPO_ROOT / "docs" / "book.html"

# ── Manifest tests ──


def test_library_json_exists():
    """library.json manifest must exist."""
    assert (BOOKS_DIR / "library.json").exists()


def test_library_json_valid():
    """library.json must be valid JSON with expected structure."""
    data = json.loads((BOOKS_DIR / "library.json").read_text())
    assert "_meta" in data
    assert "books" in data
    assert isinstance(data["books"], list)
    assert len(data["books"]) >= 1


def test_library_json_has_dewey_classes():
    """Manifest must have dewey_classes lookup."""
    data = json.loads((BOOKS_DIR / "library.json").read_text())
    assert "dewey_classes" in data
    classes = data["dewey_classes"]
    # Must have the 10 top-level Dewey classes
    for num in ["000", "100", "200", "300", "400", "500", "600", "700", "800", "900"]:
        assert num in classes, f"Missing Dewey class {num}"


def test_library_book_entries_have_required_fields():
    """Each book entry must have id, title, author, file, dewey."""
    data = json.loads((BOOKS_DIR / "library.json").read_text())
    for book in data["books"]:
        assert "id" in book, f"Book missing id: {book}"
        assert "title" in book, f"Book missing title: {book}"
        assert "file" in book, f"Book missing file: {book}"
        assert "dewey" in book, f"Book missing dewey: {book.get('id')}"
        assert "dewey_label" in book, f"Book missing dewey_label: {book.get('id')}"


def test_library_book_files_exist():
    """Every file referenced in library.json must exist on disk."""
    data = json.loads((BOOKS_DIR / "library.json").read_text())
    for book in data["books"]:
        filepath = BOOKS_DIR / book["file"]
        assert filepath.exists(), f"Missing book file: {filepath}"


def test_library_no_duplicate_ids():
    """Book IDs must be unique."""
    data = json.loads((BOOKS_DIR / "library.json").read_text())
    ids = [b["id"] for b in data["books"]]
    assert len(ids) == len(set(ids)), f"Duplicate IDs found: {ids}"


# ── Book file tests ──


@pytest.fixture
def all_book_jsons():
    """Load all .json book files from the books directory."""
    books = []
    for f in BOOKS_DIR.glob("*.json"):
        if f.name == "library.json":
            continue
        data = json.loads(f.read_text())
        data["_filename"] = f.name
        books.append(data)
    return books


def test_book_json_has_required_fields(all_book_jsons):
    """Each book JSON must have id, title, and either content or chapters."""
    for book in all_book_jsons:
        assert "id" in book, f"Missing id in {book['_filename']}"
        assert "title" in book, f"Missing title in {book['_filename']}"
        has_content = "content" in book and len(book["content"]) > 100
        has_chapters = "chapters" in book and len(book["chapters"]) >= 1
        assert has_content or has_chapters, f"Missing content/chapters in {book['_filename']}"


def test_book_json_ids_match_filenames(all_book_jsons):
    """Book id should match its filename (minus .json)."""
    for book in all_book_jsons:
        expected_id = book["_filename"].replace(".json", "")
        assert book["id"] == expected_id, f"ID mismatch: {book['id']} != {expected_id}"


def test_book_content_has_chapters(all_book_jsons):
    """Books should have at least one chapter (via content headings or chapters array)."""
    for book in all_book_jsons:
        if "chapters" in book:
            assert len(book["chapters"]) >= 1, f"No chapters in {book['_filename']}"
        elif "content" in book:
            chapters = re.findall(r"^## ", book["content"], re.MULTILINE)
            assert len(chapters) >= 1, f"No chapters found in {book['_filename']}"
        else:
            pytest.fail(f"No content or chapters in {book['_filename']}")


# ── book.html integrity tests ──


def test_book_html_exists():
    """book.html must exist."""
    assert BOOK_HTML.exists()


def test_book_html_no_inline_book_constants():
    """book.html should NOT contain inline book content (moved to remote)."""
    html = BOOK_HTML.read_text()
    assert "BOOK_THE_EXPANSIVE_CODER" not in html
    assert "BOOK_THE_SWARM_ARCHITECTURE" not in html
    assert "BOOK_ZERO_TO_SWARM" not in html
    assert "BUILTIN_BOOKS" not in html


def test_book_html_has_remote_config():
    """book.html should have remote library config."""
    html = BOOK_HTML.read_text()
    assert "raw.githubusercontent.com" in html
    assert "fetchLibraryManifest" in html
    assert "fetchBookContent" in html


def test_book_html_has_tts_panel():
    """book.html should have TTS/audiobook panel."""
    html = BOOK_HTML.read_text()
    assert "ttsPanel" in html
    assert "elevenlabs" in html.lower()
    assert "azure" in html.lower()
    assert "generateAudiobook" in html


def test_book_html_has_dewey_rendering():
    """book.html should group books by Dewey class."""
    html = BOOK_HTML.read_text()
    assert "dewey-section" in html
    assert "dewey_label" in html
    assert "dewey-tag" in html


def test_book_html_accepts_md_import():
    """book.html file input should accept .md files."""
    html = BOOK_HTML.read_text()
    assert ".md" in html
    assert "parseMarkdownFile" in html


def test_book_html_valid_js_syntax():
    """The JavaScript in book.html must parse without syntax errors."""
    html = BOOK_HTML.read_text()
    # Extract script content
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert match, "No <script> block found"
    js = match.group(1)
    # Use Node.js to check syntax
    result = subprocess.run(
        ["node", "-e", f"new Function({json.dumps(js)})"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"JS syntax error: {result.stderr}"


# ── TTS text preparation tests (inline JS logic validation) ──


def test_tts_chapter_splitting_logic():
    """Validate that markdown splits into chapters at ## boundaries."""
    sample_md = """# Book Title

Intro paragraph.

## Chapter 1: First

First chapter content here.

## Chapter 2: Second

Second chapter content.

### Subsection

More content.
"""
    # Simulate the JS split logic in Python
    parts = re.split(r"(?=^## )", sample_md, flags=re.MULTILINE)
    # First part is intro, rest are chapters
    assert len(parts) == 3  # intro + 2 chapters
    assert "Chapter 1" in parts[1]
    assert "Chapter 2" in parts[2]


def test_tts_chunk_text_logic():
    """Validate text chunking at paragraph boundaries."""
    # Simulate chunkText(text, maxLen) in Python
    text = "\n\n".join([f"Paragraph {i}. " * 20 for i in range(10)])
    max_len = 500
    chunks = []
    paragraphs = text.split("\n\n")
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_len and current:
            chunks.append(current.strip())
            current = ""
        current += para + "\n\n"
    if current.strip():
        chunks.append(current.strip())

    assert len(chunks) > 1, "Should split into multiple chunks"
    for chunk in chunks:
        assert len(chunk) <= max_len + 200, f"Chunk too long: {len(chunk)}"


def test_tts_markdown_cleanup():
    """Narrator text should strip markdown formatting."""
    md_text = "**bold** and *italic* and `code` and [link](http://x.com)"
    # Simulate cleanup
    text = md_text
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    assert text == "bold and italic and code and link"


def test_tts_code_blocks_replaced():
    """Code blocks should be replaced with [code example omitted]."""
    md_text = """Some text.

```python
def hello():
    pass
```

More text."""
    text = re.sub(r"```[\s\S]*?```", "\n\n[code example omitted for audio]\n\n", md_text)
    assert "[code example omitted for audio]" in text
    assert "def hello" not in text
