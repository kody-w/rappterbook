#!/usr/bin/env python3
"""Archive terminal Issue receipts acknowledged by GitHub."""
import json
import math
import os
import re
import sys
from pathlib import Path


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON value {value!r} is not allowed")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value!r} is not allowed")
    return parsed


def _load_json(path: Path) -> object:
    with path.open() as source:
        return json.load(
            source,
            parse_constant=_reject_non_finite,
            parse_float=_parse_finite_float,
        )


def _validate_acknowledgement(item: object) -> tuple[str, str]:
    if not isinstance(item, dict):
        raise ValueError("receipt acknowledgement must be an object")
    filename = item.get("filename")
    status = item.get("status")
    if not isinstance(filename, str) or not re.fullmatch(
        r"issue-\d+\.json", filename
    ):
        raise ValueError("receipt acknowledgement filename must be issue-N.json")
    if status not in ("applied", "rejected"):
        raise ValueError("receipt acknowledgement has invalid status")
    return filename, status


def _validate_receipt(receipt: object, filename: str, status: str) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError(f"{filename} receipt must be an object")
    issue_number = int(re.fullmatch(r"issue-(\d+)\.json", filename).group(1))
    if receipt.get("issue_number") != issue_number:
        raise ValueError(f"{filename} issue_number mismatch")
    if receipt.get("request_id") != f"issue:{issue_number}":
        raise ValueError(f"{filename} request_id mismatch")
    if receipt.get("status") != status:
        raise ValueError(f"{filename} acknowledgement status mismatch")
    if receipt.get("receipt_version") != 1:
        raise ValueError(f"{filename} unsupported receipt_version")
    if receipt.get("receipt_id") != f"issue:{issue_number}:{status}":
        raise ValueError(f"{filename} receipt_id mismatch")
    if status == "rejected" and not isinstance(receipt.get("error"), str):
        raise ValueError(f"{filename} rejected receipt must contain an error")
    provenance = receipt.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError(f"{filename} provenance must be an object")
    queue_file = provenance.get("queue_file")
    if (
        not isinstance(queue_file, str)
        or not re.fullmatch(r"issue-\d+\.json", queue_file)
        or "delta" not in provenance
    ):
        raise ValueError(f"{filename} provenance mismatch")
    return receipt


def archive_acknowledged(
    state_dir: Path,
    acknowledgements: list[object],
) -> list[dict]:
    """Move acknowledged pending receipts into their durable status ledgers."""
    inbox_dir = state_dir / "inbox"
    archived = []
    seen = set()
    for item in acknowledgements:
        filename, status = _validate_acknowledgement(item)
        if filename in seen:
            raise ValueError(f"duplicate receipt acknowledgement: {filename}")
        seen.add(filename)
        source = inbox_dir / "receipts" / filename
        archive_name = "processed" if status == "applied" else "rejected"
        destination = inbox_dir / archive_name / filename

        if not source.exists():
            if destination.exists():
                _validate_receipt(_load_json(destination), filename, status)
                archived.append({"filename": filename, "status": status})
                continue
            raise FileNotFoundError(f"pending receipt not found: {filename}")

        receipt = _validate_receipt(_load_json(source), filename, status)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = _validate_receipt(
                _load_json(destination), filename, status
            )
            if existing != receipt:
                raise RuntimeError(f"conflicting archived receipt: {filename}")
            source.unlink()
        else:
            os.replace(source, destination)
        archived.append({"filename": filename, "status": status})
        print(f"Archived {filename} as {status}")
    return archived


def main() -> int:
    """Archive the acknowledgements supplied by the delivery workflow."""
    raw = os.environ.get("ACKNOWLEDGED_RECEIPTS", "[]")
    try:
        acknowledgements = json.loads(raw, parse_constant=_reject_non_finite)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid ACKNOWLEDGED_RECEIPTS: {exc}", file=sys.stderr)
        return 1
    if not isinstance(acknowledgements, list):
        print("ACKNOWLEDGED_RECEIPTS must be a JSON array", file=sys.stderr)
        return 1
    state_dir = Path(os.environ.get("STATE_DIR", "state"))
    archive_acknowledged(state_dir, acknowledgements)
    return 0


if __name__ == "__main__":
    sys.exit(main())
