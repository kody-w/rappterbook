"""Focused tests for the public Dreamcatcher inbox consumer seam."""

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import RECENT_TS, write_delta

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "process_inbox.py"
MANIFEST_ENV = "DREAMCATCHER_DELTA_MANIFEST"
pytestmark = pytest.mark.no_llm_mock
WINDOWS_BOOTSTRAP = (
    "import runpy,sys,types;"
    "module=types.ModuleType('fcntl');"
    "module.LOCK_EX=1;module.LOCK_NB=2;module.LOCK_UN=8;"
    "module.flock=lambda *_args: None;"
    "sys.modules['fcntl']=module;"
    "runpy.run_path(sys.argv[1],run_name='__main__')"
)


def _canonical_id(payload: dict) -> str:
    """Compute a wire-compatible manifest content ID."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _search_plan(changes: list[dict]) -> dict:
    """Build the canonical search plan for test change records."""
    paths = {change["path"] for change in changes}
    deleted = {
        change["path"] for change in changes if change["status"] == "D"
    }
    renamed = [
        {"from": change["old_path"], "to": change["path"]}
        for change in changes
        if change["status"] == "R"
    ]
    entities = {
        value for change in changes for value in change["entity_ids"]
    }
    scopes = {
        value for change in changes for value in change["search_scopes"]
    }
    queries = {("path", change["path"]) for change in changes}
    queries.update(
        ("path", change["old_path"])
        for change in changes
        if change.get("old_path")
    )
    queries.update(("entity", value) for value in entities)
    queries.update(("scope", value) for value in scopes)
    return {
        "paths": sorted(paths),
        "deleted_paths": sorted(deleted),
        "renamed_paths": sorted(
            renamed, key=lambda item: (item["from"], item["to"])
        ),
        "entity_ids": sorted(entities),
        "scopes": sorted(scopes),
        "queries": [
            {"kind": kind, "value": value}
            for kind, value in sorted(queries)
        ],
    }


def _change(wire_path: str, file_path: Path | None = None) -> dict:
    """Create one added-file change record."""
    content = file_path.read_bytes() if file_path is not None else b"missing"
    return {
        "status": "A",
        "path": wire_path,
        "before": None,
        "after": {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        },
        "line_ranges": [],
        "entity_ids": [],
        "search_scopes": ["state/inbox"],
    }


def _write_manifest(path: Path, changes: list[dict]) -> Path:
    """Write a canonical Dreamcatcher delta manifest."""
    ordered = sorted(
        changes,
        key=lambda item: (item["path"], item.get("old_path", ""), item["status"]),
    )
    payload = {
        "schema": "dreamcatcher-delta/1.0",
        "producer": {"name": "twin-dreamcatcher", "version": "0.2.0"},
        "repository": {
            "base_commit": "0" * 40,
            "head_commit": "1" * 40,
            "includes_worktree": True,
            "path_filter": ["state/inbox"],
        },
        "source": {
            "id": "pytest",
            "branch": "feature/dreamcatcher-delta",
        },
        "changes": ordered,
        "search_plan": _search_plan(ordered),
    }
    manifest = dict(payload)
    manifest["manifest_id"] = _canonical_id(payload)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _write_rehashed_manifest(path: Path, manifest: dict) -> None:
    """Write a modified manifest with a fresh canonical content ID."""
    payload = {
        key: value for key, value in manifest.items()
        if key != "manifest_id"
    }
    manifest["manifest_id"] = _canonical_id(payload)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _wire_path(state_dir: Path, file_path: Path) -> str:
    """Return the canonical repository-relative state path."""
    relative = file_path.relative_to(state_dir).as_posix()
    return f"state/{relative}"


def _run_inbox(state_dir: Path, manifest: Path | None = None) -> subprocess.CompletedProcess:
    """Run process_inbox.py with an isolated state and optional manifest."""
    docs_dir = state_dir.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    env["DOCS_DIR"] = str(docs_dir)
    env.pop(MANIFEST_ENV, None)
    if manifest is not None:
        env[MANIFEST_ENV] = str(manifest)
    command = [sys.executable, str(SCRIPT)]
    if os.name == "nt":
        command = [sys.executable, "-c", WINDOWS_BOOTSTRAP, str(SCRIPT)]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )


def _write_issue_delta(
    inbox_dir: Path,
    issue_number: int,
    action: str,
    payload: dict,
    timestamp: str,
) -> Path:
    """Write one authenticated Issue delta for queue-order testing."""
    delta = {
        "action": action,
        "agent_id": "scope-agent",
        "timestamp": timestamp,
        "payload": payload,
        "issue_number": issue_number,
        "request_id": f"issue:{issue_number}",
        "submitter_id": 4242,
    }
    path = inbox_dir / f"issue-{issue_number}.json"
    path.write_text(json.dumps(delta, indent=2), encoding="utf-8")
    return path


def _state_snapshot(state_dir: Path) -> dict[str, bytes]:
    """Capture every regular state file for pre-write failure assertions."""
    return {
        path.relative_to(state_dir).as_posix(): path.read_bytes()
        for path in state_dir.rglob("*")
        if path.is_file()
    }


def test_scoped_manifest_preserves_existing_queue_order(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """Manifest ordering must not replace numeric Issue queue ordering."""
    base = datetime.fromisoformat(RECENT_TS.replace("Z", "+00:00"))
    register = _write_issue_delta(
        tmp_state / "inbox",
        2,
        "register_agent",
        {"name": "Scoped", "framework": "pytest", "bio": "Original"},
        RECENT_TS,
    )
    update = _write_issue_delta(
        tmp_state / "inbox",
        10,
        "update_profile",
        {"bio": "Updated through queue order"},
        (base + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [
            _change(_wire_path(tmp_state, register), register),
            _change(_wire_path(tmp_state, update), update),
        ],
    )

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 0, result.stderr
    agents = json.loads((tmp_state / "agents.json").read_text())
    assert agents["agents"]["scope-agent"]["bio"] == "Updated through queue order"
    assert not register.exists()
    assert not update.exists()


def test_scoped_manifest_excludes_unrelated_inbox_files(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """Only manifest-planned inbox deltas are consumed."""
    planned = write_delta(
        tmp_state / "inbox",
        "planned-agent",
        "register_agent",
        {"name": "Planned", "framework": "pytest", "bio": "Included"},
    )
    unrelated = write_delta(
        tmp_state / "inbox",
        "unrelated-agent",
        "register_agent",
        {"name": "Unrelated", "framework": "pytest", "bio": "Excluded"},
    )
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(_wire_path(tmp_state, planned), planned)],
    )

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 0, result.stderr
    agents = json.loads((tmp_state / "agents.json").read_text())["agents"]
    assert "planned-agent" in agents
    assert "unrelated-agent" not in agents
    assert not planned.exists()
    assert unrelated.exists()


def test_tampered_manifest_fails_before_state_write(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """A payload change with a stale ID must fail closed."""
    delta = write_delta(
        tmp_state / "inbox",
        "tamper-agent",
        "register_agent",
        {"name": "Tamper", "framework": "pytest", "bio": "Blocked"},
    )
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(_wire_path(tmp_state, delta), delta)],
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["source"]["id"] = "tampered"
    manifest.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    before = _state_snapshot(tmp_state)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "manifest_id" in result.stderr
    assert _state_snapshot(tmp_state) == before


def test_stale_planned_blob_fails_before_state_write(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """A file changed after planning must not reach the inbox processor."""
    delta = write_delta(
        tmp_state / "inbox",
        "stale-agent",
        "register_agent",
        {"name": "Stale", "framework": "pytest", "bio": "Original"},
    )
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(_wire_path(tmp_state, delta), delta)],
    )
    value = json.loads(delta.read_text(encoding="utf-8"))
    value["payload"]["bio"] = "Changed after planning"
    delta.write_text(json.dumps(value, indent=2), encoding="utf-8")
    before = _state_snapshot(tmp_state)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "does not match manifest blob" in result.stderr
    assert _state_snapshot(tmp_state) == before


@pytest.mark.parametrize(
    "wire_path",
    [
        "state/inbox/../outside.json",
        "/state/inbox/absolute.json",
        "C:/state/inbox/absolute.json",
        r"state\inbox\backslash.json",
    ],
)
def test_manifest_rejects_path_escape(
    tmp_state: Path,
    tmp_path: Path,
    wire_path: str,
) -> None:
    """Escaping and platform-specific paths are rejected before writes."""
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(wire_path)],
    )
    before = _state_snapshot(tmp_state)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "path" in result.stderr.lower()
    assert _state_snapshot(tmp_state) == before


@pytest.mark.parametrize(
    "wire_path",
    [
        "state/inbox/C:agents.json",
        "state/in:box/agents.json",
        "state/C:inbox/agents.json",
        "state/inbox/agents.json:stream",
    ],
)
def test_manifest_rejects_colon_path_aliases(
    tmp_state: Path,
    tmp_path: Path,
    wire_path: str,
) -> None:
    """Every wire-path component rejects Windows drive and stream aliases."""
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(wire_path)],
    )
    before = _state_snapshot(tmp_state)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "colon path component" in result.stderr
    assert _state_snapshot(tmp_state) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows drive-relative semantics")
def test_drive_relative_alias_cannot_map_to_canonical_state(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """A drive-relative inbox name cannot select a canonical state file."""
    canonical_state = tmp_state / "agents.json"
    alias_name = f"{tmp_state.drive}agents.json"
    assert tmp_state.joinpath("inbox", alias_name) == canonical_state
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(f"state/inbox/{alias_name}", canonical_state)],
    )
    before = _state_snapshot(tmp_state)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "colon path component" in result.stderr
    assert _state_snapshot(tmp_state) == before


def test_manifest_requires_repository_path_filter(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """The finalized public delta contract requires repository.path_filter."""
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change("state/inbox/missing.json")],
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    del value["repository"]["path_filter"]
    _write_rehashed_manifest(manifest, value)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "path_filter" in result.stderr


@pytest.mark.parametrize(
    "path_filter",
    [
        ["state/zeta", "state/alpha"],
        ["state/inbox", "state/inbox"],
        ["state/inbox/../agents.json"],
        [r"state\inbox"],
        ["state/inbox/C:agents.json"],
    ],
)
def test_manifest_rejects_noncanonical_repository_path_filter(
    tmp_state: Path,
    tmp_path: Path,
    path_filter: list[str],
) -> None:
    """Repository path filters must be sorted, unique, normalized paths."""
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change("state/inbox/missing.json")],
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["repository"]["path_filter"] = path_filter
    _write_rehashed_manifest(manifest, value)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "path_filter" in result.stderr


def test_manifest_rejects_missing_planned_file(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """A canonical plan cannot name a file that is no longer present."""
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change("state/inbox/missing.json")],
    )
    before = _state_snapshot(tmp_state)

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "does not exist" in result.stderr
    assert _state_snapshot(tmp_state) == before


def test_no_manifest_preserves_legacy_inbox_behavior(tmp_state: Path) -> None:
    """Without the environment variable, every queued delta is processed."""
    delta = write_delta(
        tmp_state / "inbox",
        "legacy-agent",
        "register_agent",
        {"name": "Legacy", "framework": "pytest", "bio": "Unscoped"},
    )

    result = _run_inbox(tmp_state)

    assert result.returncode == 0, result.stderr
    agents = json.loads((tmp_state / "agents.json").read_text())["agents"]
    assert "legacy-agent" in agents
    assert not delta.exists()


def test_manifest_rejects_non_json_inbox_file(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """The seam never passes a non-JSON inbox file to process_inbox."""
    text_file = tmp_state / "inbox" / "delta.txt"
    text_file.write_text("{}", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(_wire_path(tmp_state, text_file), text_file)],
    )

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "state/inbox/*.json" in result.stderr
    assert text_file.exists()


def test_manifest_rejects_duplicate_changed_paths(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """Duplicate wire paths are rejected even when the ID is canonical."""
    delta = write_delta(
        tmp_state / "inbox",
        "duplicate-agent",
        "register_agent",
        {"name": "Duplicate", "framework": "pytest", "bio": "Blocked"},
    )
    change = _change(_wire_path(tmp_state, delta), delta)
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [change, copy.deepcopy(change)],
    )

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "duplicate changed path" in result.stderr
    assert delta.exists()


def test_manifest_rejects_symlinked_planned_file(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """A planned inbox delta cannot be supplied through a symlink."""
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    linked = tmp_state / "inbox" / "linked.json"
    try:
        linked.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(_wire_path(tmp_state, linked), linked)],
    )

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "symlink" in result.stderr


def test_rehashed_search_plan_mismatch_is_rejected(
    tmp_state: Path,
    tmp_path: Path,
) -> None:
    """A fresh ID cannot legitimize a plan that omits its change."""
    delta = write_delta(
        tmp_state / "inbox",
        "plan-agent",
        "register_agent",
        {"name": "Plan", "framework": "pytest", "bio": "Blocked"},
    )
    manifest = _write_manifest(
        tmp_path / "manifest.json",
        [_change(_wire_path(tmp_state, delta), delta)],
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["search_plan"]["paths"] = []
    payload = {
        key: item for key, item in value.items() if key != "manifest_id"
    }
    value["manifest_id"] = _canonical_id(payload)
    manifest.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    result = _run_inbox(tmp_state, manifest)

    assert result.returncode == 2
    assert "search_plan" in result.stderr
    assert delta.exists()
