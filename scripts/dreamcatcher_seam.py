#!/usr/bin/env python3
"""Validate Dreamcatcher plans for the public Rappterbook inbox seam."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath

SCHEMA = "dreamcatcher-delta/1.0"
PRODUCER = {"name": "twin-dreamcatcher", "version": "0.2.0"}
STATUSES = {"A", "M", "D", "R", "C", "T", "U"}
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
MANIFEST_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:/")


class DreamcatcherManifestError(ValueError):
    """A Dreamcatcher manifest is malformed, stale, or unsafe to consume."""


def _reject_non_finite(value: str) -> None:
    """Reject non-standard JSON numeric constants."""
    raise DreamcatcherManifestError(
        f"non-finite JSON value {value!r} is not allowed"
    )


def _parse_finite_float(value: str) -> float:
    """Reject JSON numbers that overflow Python floats."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise DreamcatcherManifestError(
            f"non-finite JSON number {value!r} is not allowed"
        )
    return parsed


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    """Build an object while rejecting duplicate JSON keys."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise DreamcatcherManifestError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_manifest(path: Path) -> dict:
    """Load one regular, non-symlink manifest with strict JSON semantics."""
    if path.suffix != ".json":
        raise DreamcatcherManifestError(f"manifest must be a .json file: {path}")
    if path.is_symlink():
        raise DreamcatcherManifestError(f"manifest must not be a symlink: {path}")
    if not path.exists() or not path.is_file():
        raise DreamcatcherManifestError(f"manifest does not exist: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
            parse_float=_parse_finite_float,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DreamcatcherManifestError(
            f"manifest is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise DreamcatcherManifestError("manifest must be a JSON object")
    return value


def _normalize_path(value: object, field: str) -> str:
    """Require one normalized repository-relative POSIX path."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise DreamcatcherManifestError(f"{field} is not a normalized path")
    if value.startswith("/") or WINDOWS_ABSOLUTE_PATTERN.match(value):
        raise DreamcatcherManifestError(f"{field} must be relative: {value!r}")
    components = value.split("/")
    if any(":" in component for component in components):
        raise DreamcatcherManifestError(
            f"{field} contains a drive-qualified or colon path component"
        )
    if any(component in {"", ".", ".."} for component in components):
        raise DreamcatcherManifestError(f"{field} escapes its root: {value!r}")
    path = PurePosixPath(value)
    if path.as_posix() != value:
        raise DreamcatcherManifestError(f"{field} is not normalized: {value!r}")
    return value


def _string_list(value: object, field: str) -> list[str]:
    """Require unique, non-empty strings."""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise DreamcatcherManifestError(
            f"{field} must be a list of non-empty strings"
        )
    if len(value) != len(set(value)):
        raise DreamcatcherManifestError(f"{field} contains duplicates")
    return value


def _validate_blob(value: object, field: str) -> None:
    """Validate one optional blob summary used for freshness checks."""
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"sha256", "bytes"}:
        raise DreamcatcherManifestError(f"{field} is invalid")
    digest = value["sha256"]
    size = value["bytes"]
    if not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
        raise DreamcatcherManifestError(f"{field}.sha256 is invalid")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise DreamcatcherManifestError(f"{field}.bytes is invalid")


def _validate_repository(value: object) -> None:
    """Validate repository identity and its canonical generation path filter."""
    fields = {
        "base_commit", "head_commit", "includes_worktree", "path_filter",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise DreamcatcherManifestError(
            "repository fields must include path_filter and match the schema"
        )
    for field in ("base_commit", "head_commit"):
        commit = value[field]
        if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
            raise DreamcatcherManifestError(f"repository.{field} is invalid")
    if not isinstance(value["includes_worktree"], bool):
        raise DreamcatcherManifestError(
            "repository.includes_worktree must be a boolean"
        )
    path_filter = value["path_filter"]
    if not isinstance(path_filter, list):
        raise DreamcatcherManifestError(
            "repository.path_filter must be an array"
        )
    normalized = [
        _normalize_path(path, f"repository.path_filter[{index}]")
        for index, path in enumerate(path_filter)
    ]
    if len(normalized) != len(set(normalized)):
        raise DreamcatcherManifestError(
            "repository.path_filter contains duplicates"
        )
    if normalized != sorted(normalized):
        raise DreamcatcherManifestError(
            "repository.path_filter must be deterministically sorted"
        )


def _validate_change(change: object, index: int) -> str:
    """Validate the change fields needed to trust its search-plan record."""
    required = {
        "status", "path", "before", "after", "line_ranges",
        "entity_ids", "search_scopes",
    }
    allowed = required | {"old_path", "similarity"}
    if not isinstance(change, dict):
        raise DreamcatcherManifestError(f"changes[{index}] must be an object")
    if required - set(change) or set(change) - allowed:
        raise DreamcatcherManifestError(
            f"changes[{index}] has unsupported or missing fields"
        )
    status = change["status"]
    if status not in STATUSES:
        raise DreamcatcherManifestError(f"changes[{index}].status is invalid")
    path = _normalize_path(change["path"], f"changes[{index}].path")
    if status in {"R", "C"}:
        _normalize_path(change.get("old_path"), f"changes[{index}].old_path")
    elif "old_path" in change:
        raise DreamcatcherManifestError(
            f"changes[{index}].old_path is only valid for rename or copy"
        )
    _validate_blob(change["before"], f"changes[{index}].before")
    _validate_blob(change["after"], f"changes[{index}].after")
    if status == "A" and (change["before"] is not None or change["after"] is None):
        raise DreamcatcherManifestError(f"changes[{index}] has invalid add blobs")
    if status == "D" and (change["before"] is None or change["after"] is not None):
        raise DreamcatcherManifestError(f"changes[{index}] has invalid delete blobs")
    if status not in {"A", "D"} and (
        change["before"] is None or change["after"] is None
    ):
        raise DreamcatcherManifestError(
            f"changes[{index}] requires before and after blobs"
        )
    if not isinstance(change["line_ranges"], list):
        raise DreamcatcherManifestError(f"changes[{index}].line_ranges is invalid")
    _string_list(change["entity_ids"], f"changes[{index}].entity_ids")
    _string_list(change["search_scopes"], f"changes[{index}].search_scopes")
    return path


def _expected_search_plan(changes: list[dict]) -> dict:
    """Derive the canonical public query plan from validated changes."""
    paths: set[str] = set()
    deleted_paths: set[str] = set()
    renamed_paths: list[dict[str, str]] = []
    entity_ids: set[str] = set()
    scopes: set[str] = set()
    queries: set[tuple[str, str]] = set()
    for change in changes:
        path = change["path"]
        paths.add(path)
        queries.add(("path", path))
        if change["status"] == "D":
            deleted_paths.add(path)
        if change["status"] == "R":
            renamed_paths.append({"from": change["old_path"], "to": path})
        if change.get("old_path"):
            queries.add(("path", change["old_path"]))
        for entity_id in change["entity_ids"]:
            entity_ids.add(entity_id)
            queries.add(("entity", entity_id))
        for scope in change["search_scopes"]:
            scopes.add(scope)
            queries.add(("scope", scope))
    return {
        "paths": sorted(paths),
        "deleted_paths": sorted(deleted_paths),
        "renamed_paths": sorted(
            renamed_paths,
            key=lambda item: (item["from"], item["to"]),
        ),
        "entity_ids": sorted(entity_ids),
        "scopes": sorted(scopes),
        "queries": [
            {"kind": kind, "value": value}
            for kind, value in sorted(queries)
        ],
    }


def _canonical_id(manifest: dict) -> str:
    """Compute the canonical content ID without manifest_id."""
    payload = {
        key: value for key, value in manifest.items()
        if key != "manifest_id"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_manifest(manifest: dict) -> dict[str, dict]:
    """Validate the consumer contract and index changes by path."""
    fields = {
        "schema", "producer", "repository", "source",
        "changes", "search_plan", "manifest_id",
    }
    if set(manifest) != fields:
        raise DreamcatcherManifestError("manifest fields do not match the schema")
    if manifest["schema"] != SCHEMA:
        raise DreamcatcherManifestError(
            f"unsupported schema {manifest['schema']!r}"
        )
    if manifest["producer"] != PRODUCER:
        raise DreamcatcherManifestError(
            "producer must be twin-dreamcatcher 0.2.0"
        )
    _validate_repository(manifest["repository"])
    if not isinstance(manifest["source"], dict):
        raise DreamcatcherManifestError("source must be an object")
    changes = manifest["changes"]
    if not isinstance(changes, list):
        raise DreamcatcherManifestError("changes must be an array")
    changes_by_path = {}
    for index, change in enumerate(changes):
        path = _validate_change(change, index)
        if path in changes_by_path:
            raise DreamcatcherManifestError(f"duplicate changed path {path}")
        changes_by_path[path] = change
    expected = sorted(
        changes,
        key=lambda item: (item["path"], item.get("old_path", ""), item["status"]),
    )
    if changes != expected:
        raise DreamcatcherManifestError("changes must be deterministically sorted")
    if manifest["search_plan"] != _expected_search_plan(changes):
        raise DreamcatcherManifestError(
            "search_plan does not match change records"
        )
    manifest_id = manifest["manifest_id"]
    if (
        not isinstance(manifest_id, str)
        or not MANIFEST_ID_PATTERN.fullmatch(manifest_id)
        or manifest_id != _canonical_id(manifest)
    ):
        raise DreamcatcherManifestError(
            "manifest_id does not match the canonical payload"
        )
    return changes_by_path


def _state_relative(wire_path: str) -> PurePosixPath:
    """Map a wire path into the configured STATE_DIR namespace."""
    parts = PurePosixPath(wire_path).parts
    if len(parts) < 2 or parts[0] != "state":
        raise DreamcatcherManifestError(
            f"planned path is outside configured STATE_DIR: {wire_path}"
        )
    return PurePosixPath(*parts[1:])


def _planned_file(
    state_dir: Path,
    state_root: Path,
    relative: PurePosixPath,
    wire_path: str,
    expected_parent: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve one current planned file without symlinks or root escapes."""
    candidate = state_dir.joinpath(*relative.parts)
    current = state_dir
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise DreamcatcherManifestError(
                f"planned path must not use symlinks: {wire_path}"
            )
    if not candidate.exists():
        raise DreamcatcherManifestError(
            f"planned file does not exist: {wire_path}"
        )
    if not candidate.is_file():
        raise DreamcatcherManifestError(
            f"planned path is not a regular file: {wire_path}"
        )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(state_root)
    except (OSError, ValueError) as exc:
        raise DreamcatcherManifestError(
            f"planned path is outside configured STATE_DIR: {wire_path}"
        ) from exc
    if expected_parent is not None and resolved.parent != expected_parent:
        raise DreamcatcherManifestError(
            "planned inbox file does not resolve directly under "
            f"configured STATE_DIR/inbox: {wire_path}"
        )
    return candidate, resolved


def _verify_blob(candidate: Path, change: dict, wire_path: str) -> None:
    """Verify the current file bytes against the planned after blob."""
    summary = change.get("after")
    if not isinstance(summary, dict):
        raise DreamcatcherManifestError(
            f"planned file has no after blob: {wire_path}"
        )
    try:
        content = candidate.read_bytes()
    except OSError as exc:
        raise DreamcatcherManifestError(
            f"cannot read planned file {wire_path}: {exc}"
        ) from exc
    digest = hashlib.sha256(content).hexdigest()
    if len(content) != summary["bytes"] or digest != summary["sha256"]:
        raise DreamcatcherManifestError(
            f"planned file does not match manifest blob: {wire_path}"
        )


def _resolved_inbox_root(state_dir: Path, state_root: Path) -> Path:
    """Resolve and validate the configured inbox directory."""
    inbox_dir = state_dir / "inbox"
    try:
        inbox_root = (state_root / "inbox").resolve(strict=True)
    except OSError as exc:
        raise DreamcatcherManifestError(
            f"configured STATE_DIR/inbox does not exist: {inbox_dir}"
        ) from exc
    if not inbox_root.is_dir():
        raise DreamcatcherManifestError(
            f"configured STATE_DIR/inbox is not a directory: {inbox_dir}"
        )
    return inbox_root


def _planned_inbox_paths(
    manifest: dict,
    changes_by_path: dict[str, dict],
    state_dir: Path,
) -> list[Path]:
    """Validate planned files and select direct inbox JSON deltas."""
    if not state_dir.exists() or not state_dir.is_dir():
        raise DreamcatcherManifestError(
            f"configured STATE_DIR does not exist: {state_dir}"
        )
    state_root = state_dir.resolve(strict=True)
    inbox_root = _resolved_inbox_root(state_dir, state_root)
    selected: list[Path] = []
    seen_files: set[str] = set()
    for wire_path in manifest["search_plan"]["paths"]:
        relative = _state_relative(wire_path)
        change = changes_by_path[wire_path]
        is_inbox_path = relative.parts[0] == "inbox"
        if change["status"] == "D":
            if is_inbox_path:
                raise DreamcatcherManifestError(
                    f"planned inbox path is deleted: {wire_path}"
                )
            continue
        if is_inbox_path and (len(relative.parts) != 2 or relative.suffix != ".json"):
            raise DreamcatcherManifestError(
                f"planned inbox path must match state/inbox/*.json: {wire_path}"
            )
        candidate, resolved = _planned_file(
            state_dir,
            state_root,
            relative,
            wire_path,
            inbox_root if is_inbox_path else None,
        )
        _verify_blob(candidate, change, wire_path)
        if not is_inbox_path:
            continue
        file_key = os.path.normcase(str(resolved))
        if file_key in seen_files:
            raise DreamcatcherManifestError(
                f"duplicate planned inbox path: {wire_path}"
            )
        seen_files.add(file_key)
        selected.append(candidate)
    return selected


def load_planned_inbox_paths(
    manifest_path: Path,
    state_dir: Path,
) -> list[Path]:
    """Load a Dreamcatcher manifest and return its safe inbox delta paths."""
    manifest = _load_manifest(Path(manifest_path))
    changes_by_path = _validate_manifest(manifest)
    for change in manifest["changes"]:
        _state_relative(change["path"])
        if change.get("old_path"):
            _state_relative(change["old_path"])
    return _planned_inbox_paths(manifest, changes_by_path, Path(state_dir))
