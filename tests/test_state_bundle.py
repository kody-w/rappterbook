"""Failure-injection tests for recoverable multi-file JSON bundles."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import state_io


def _write(path: Path, value: int) -> None:
    """Write one small JSON fixture."""
    path.write_text(json.dumps({"value": value}) + "\n")


def test_bundle_promotes_every_file(tmp_path: Path) -> None:
    """A successful bundle makes every new projection visible."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, 1)
    _write(second, 1)

    state_io.save_json_bundle({
        first: {"value": 2},
        second: {"value": 2},
    })

    assert json.loads(first.read_text())["value"] == 2
    assert json.loads(second.read_text())["value"] == 2
    assert not (tmp_path / ".state-transaction.json").exists()


def test_bundle_rolls_back_partial_promotion(tmp_path: Path) -> None:
    """Failure on the second replacement restores the complete old bundle."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, 1)
    _write(second, 1)
    real_replace = os.replace
    failed = False

    def fail_second_prepared(source, target):
        nonlocal failed
        if (
            Path(target) == second
            and Path(source).name.endswith(".new")
            and not failed
        ):
            failed = True
            raise OSError("injected second-file failure")
        return real_replace(source, target)

    with patch("state_io.os.replace", side_effect=fail_second_prepared):
        with pytest.raises(OSError, match="injected second-file failure"):
            state_io.save_json_bundle({
                first: {"value": 2},
                second: {"value": 2},
            })

    assert json.loads(first.read_text())["value"] == 1
    assert json.loads(second.read_text())["value"] == 1
    assert not (tmp_path / ".state-transaction.json").exists()
    assert not list(tmp_path.glob(".state-tx-*"))


def test_recovery_rolls_back_interrupted_bundle(tmp_path: Path) -> None:
    """A durable journal repairs split state on the next startup."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, 2)
    _write(second, 1)
    transaction = tmp_path / ".state-tx-interrupted"
    transaction.mkdir()
    first_backup = transaction / "0.bak"
    second_backup = transaction / "1.bak"
    _write(first_backup, 1)
    _write(second_backup, 1)
    journal = {
        "transaction_dir": str(transaction),
        "entries": [
            {
                "target": str(first),
                "prepared": str(transaction / "0.new"),
                "backup": str(first_backup),
                "existed": True,
            },
            {
                "target": str(second),
                "prepared": str(transaction / "1.new"),
                "backup": str(second_backup),
                "existed": True,
            },
        ],
    }
    (tmp_path / ".state-transaction.json").write_text(json.dumps(journal))

    assert state_io.recover_json_bundle(tmp_path) is True

    assert json.loads(first.read_text())["value"] == 1
    assert json.loads(second.read_text())["value"] == 1
    assert not transaction.exists()
    assert not (tmp_path / ".state-transaction.json").exists()
