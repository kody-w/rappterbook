"""Tests for explicit shard byte budgets."""
from pathlib import Path

import pytest

from shard_cache import MAX_BODY_SHARD_BYTES, write_bounded_json


def test_write_bounded_json_uses_encoded_byte_length(tmp_path: Path) -> None:
    """The reported size matches the compact UTF-8 payload on disk."""
    path = tmp_path / "body.json"

    size = write_bounded_json(path, {"42": {"body": "hello 🌎"}}, 1024)

    assert size == path.stat().st_size
    assert path.read_bytes().startswith(b'{"42":')


def test_write_bounded_json_rejects_oversized_shard(tmp_path: Path) -> None:
    """A body shard cannot silently grow beyond the browser budget."""
    path = tmp_path / "body.json"
    data = {"42": {"body": "x" * MAX_BODY_SHARD_BYTES}}

    with pytest.raises(RuntimeError, match="shard limit"):
        write_bounded_json(path, data, MAX_BODY_SHARD_BYTES)

    assert not path.exists()
