"""Tests for harvest_artifact.py — extract_file_blocks with plain python blocks."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from harvest_artifact import extract_file_blocks


def test_annotated_block():
    """Original format: ```python:src/file.py"""
    text = '```python:src/decisions.py\nimport json\ndef decide(): pass\n```'
    blocks = extract_file_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["file"] == "src/decisions.py"


def test_plain_python_block_with_title_hint():
    """Plain ```python block -- should be found with title hint"""
    code_lines = [
        "import json",
        "from pathlib import Path",
        "",
        "def decide(state, profile):",
        '    power = state["power"]',
        '    return {"allocate": power * 0.5}',
    ]
    # Pad to 20+ lines
    code_lines += [f"    x_{i} = {i}" for i in range(20)]
    text = "```python\n" + "\n".join(code_lines) + "\n```"
    blocks = extract_file_blocks(text, title_hint="decisions.py -- AI Governor")
    assert len(blocks) >= 1
    assert "decisions.py" in blocks[0]["file"]


def test_plain_python_block_with_deliverable_hint():
    """Plain ```python block -- should be found with deliverable hint"""
    code_lines = [
        "import json",
        "def decide(state):",
        '    return {"power": 0.5}',
    ]
    # Pad to 20+ lines
    code_lines += [f"    x_{i} = {i}" for i in range(20)]
    text = "```python\n" + "\n".join(code_lines) + "\n```"
    blocks = extract_file_blocks(text, deliverable_file="src/decisions.py")
    assert len(blocks) >= 1
    assert blocks[0]["file"] == "src/decisions.py"


def test_short_snippet_ignored():
    """Short code snippets (<20 lines) should NOT be extracted as artifacts"""
    text = '```python\nprint("hello")\n```'
    blocks = extract_file_blocks(text, deliverable_file="src/decisions.py")
    assert len(blocks) == 0


def test_multiple_blocks():
    """Multiple blocks in one post -- extract all substantial ones"""
    annotated_lines = [
        "import json",
        "def decide(state):",
        '    return {"power": state["power"] * 0.8}',
    ]
    annotated_lines += [f"    x = {i}" for i in range(20)]

    text = "Here is v1:\n"
    text += "```python:src/decisions.py\n" + "\n".join(annotated_lines) + "\n```\n"
    text += "\nAnd a snippet:\n"
    text += '```python\nprint("test")\n```\n'

    blocks = extract_file_blocks(text)
    assert len(blocks) >= 1  # Should get the annotated one, skip the snippet


def test_annotated_block_various_langs():
    """Non-python annotated blocks should also work"""
    html_lines = ["<html><body>Hello</body></html>"]
    html_lines += [f"<p>{i}</p>" for i in range(20)]
    text = "```html:public/index.html\n" + "\n".join(html_lines) + "\n```"
    blocks = extract_file_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["file"] == "public/index.html"


def test_no_false_positives():
    """Regular discussion text with no code blocks should return empty"""
    text = "This is a discussion about governance. We should consider modular design."
    blocks = extract_file_blocks(text)
    assert len(blocks) == 0


def test_plain_block_without_any_hints():
    """Plain block with no hints should fall back to src/unknown_N.ext"""
    code_lines = [
        "import json",
        "from pathlib import Path",
        "",
        "class Processor:",
        "    def __init__(self):",
        "        self.data = {}",
    ]
    code_lines += [f"        self.field_{i} = {i}" for i in range(20)]
    text = "```python\n" + "\n".join(code_lines) + "\n```"
    blocks = extract_file_blocks(text)
    assert len(blocks) >= 1
    assert blocks[0]["file"].startswith("src/unknown_")
    assert blocks[0]["file"].endswith(".py")


def test_plain_block_non_code_ignored():
    """Plain blocks that don't look like code (no imports/def/class) should be skipped"""
    lines = ["# This is a long comment block"] + [f"# Line {i}" for i in range(25)]
    text = "```python\n" + "\n".join(lines) + "\n```"
    blocks = extract_file_blocks(text)
    assert len(blocks) == 0


def test_deliverable_takes_precedence_over_title():
    """deliverable_file should take precedence over title_hint"""
    code_lines = [
        "import json",
        "def process():",
        "    pass",
    ]
    code_lines += [f"    val_{i} = {i}" for i in range(20)]
    text = "```python\n" + "\n".join(code_lines) + "\n```"
    blocks = extract_file_blocks(
        text,
        title_hint="governance.py refactored",
        deliverable_file="src/decisions.py",
    )
    assert len(blocks) >= 1
    assert blocks[0]["file"] == "src/decisions.py"


def test_plain_block_not_duplicated_with_annotated():
    """If a block is already matched by Pattern 1 (annotated), Pattern 3 should not duplicate it"""
    code_lines = ["import json", "def foo(): pass"]
    code_lines += [f"    x = {i}" for i in range(20)]
    code = "\n".join(code_lines)
    text = f"```python:src/foo.py\n{code}\n```"
    blocks = extract_file_blocks(text, deliverable_file="src/foo.py")
    # Should only have ONE block, not two
    assert len(blocks) == 1
    assert blocks[0]["file"] == "src/foo.py"
