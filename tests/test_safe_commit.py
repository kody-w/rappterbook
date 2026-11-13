"""Executable regression coverage for conflict-safe workflow commits."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def run(command, cwd, env=None):
    """Run one local-only fixture command."""
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
        env=env,
    )


def git(cwd, *arguments):
    return run(["git", *arguments], cwd)


def test_depth_two_clone_preserves_ancestry_with_repeated_message(tmp_path):
    """A repeated commit message in a depth-2 clone preserves ancestry."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "depth-two"
    git(tmp_path, "init", "--bare", str(origin))
    git(tmp_path, "init", "-b", "main", str(seed))
    git(seed, "config", "user.name", "fixture")
    git(seed, "config", "user.email", "fixture@users.noreply.github.com")

    (seed / "scripts").mkdir()
    (seed / "state").mkdir()
    shutil.copy2(ROOT / "scripts" / "safe_commit.sh", seed / "scripts")
    (seed / "scripts" / "state_io.py").write_text(
        'print("State consistency OK")\n'
    )
    (seed / "state" / "value.json").write_text('{"value": 1}\n')
    (seed / "history.txt").write_text("one\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "fixture root")

    (seed / "history.txt").write_text("one\ntwo\n")
    git(seed, "add", "history.txt")
    git(seed, "commit", "-m", "fixture middle")
    repeated_message = "chore: process fixture state"
    (seed / "history.txt").write_text("one\ntwo\nthree\n")
    git(seed, "add", "history.txt")
    git(seed, "commit", "-m", repeated_message)
    previous_head = git(seed, "rev-parse", "HEAD").stdout.strip()
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "main")

    git(
        tmp_path,
        "clone",
        "--depth=2",
        "--branch",
        "main",
        origin.as_uri(),
        str(clone),
    )
    assert git(clone, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"

    (clone / "state" / "value.json").write_text('{"value": 2}\n')
    result = run(
        [
            "bash",
            "scripts/safe_commit.sh",
            repeated_message,
            "state/value.json",
        ],
        clone,
    )

    assert "Push succeeded" in result.stdout
    head_with_parent = git(clone, "rev-list", "--parents", "-n", "1", "HEAD")
    assert len(head_with_parent.stdout.split()) == 2
    assert head_with_parent.stdout.split()[1] == previous_head
    assert git(
        tmp_path,
        "--git-dir",
        str(origin),
        "rev-list",
        "--count",
        "main",
    ).stdout.strip() == "4"


def test_unchanged_directory_is_not_committed(tmp_path):
    """Directory arguments never broaden recovery beyond changed paths."""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    git(tmp_path, "init", "--bare", str(origin))
    git(tmp_path, "init", "-b", "main", str(repo))
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@users.noreply.github.com")
    (repo / "scripts").mkdir()
    (repo / "state" / "changed").mkdir(parents=True)
    (repo / "state" / "untouched").mkdir()
    shutil.copy2(ROOT / "scripts" / "safe_commit.sh", repo / "scripts")
    (repo / "scripts" / "state_io.py").write_text(
        'print("State consistency OK")\n'
    )
    (repo / "state" / "changed" / "value.json").write_text('{"value": 1}\n')
    (repo / "state" / "untouched" / "value.json").write_text('{"value": 1}\n')
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture root")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-u", "origin", "main")

    (repo / "state" / "changed" / "value.json").write_text('{"value": 2}\n')
    run(
        [
            "bash",
            "scripts/safe_commit.sh",
            "fixture update",
            "state/changed/",
            "state/untouched/",
            "state/untouched/value.json",
        ],
        repo,
    )

    changed_paths = git(repo, "show", "--format=", "--name-only", "HEAD")
    assert changed_paths.stdout.splitlines() == ["state/changed/value.json"]


def test_explicit_local_preference_keeps_recomputed_state(tmp_path):
    """Derived outputs may opt into keeping their recomputed conflict side."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    worker = tmp_path / "worker"
    concurrent = tmp_path / "concurrent"
    git(tmp_path, "init", "--bare", str(origin))
    git(tmp_path, "init", "-b", "main", str(seed))
    git(seed, "config", "user.name", "fixture")
    git(seed, "config", "user.email", "fixture@users.noreply.github.com")
    (seed / "scripts").mkdir()
    (seed / "state").mkdir()
    shutil.copy2(ROOT / "scripts" / "safe_commit.sh", seed / "scripts")
    (seed / "scripts" / "state_io.py").write_text(
        'print("State consistency OK")\n'
    )
    (seed / "state" / "value.json").write_text('{"value": 1}\n')
    git(seed, "add", ".")
    git(seed, "commit", "-m", "fixture root")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "main")
    git(tmp_path, "clone", "--branch", "main", origin.as_uri(), str(worker))
    git(tmp_path, "clone", "--branch", "main", origin.as_uri(), str(concurrent))
    git(concurrent, "config", "user.name", "fixture")
    git(concurrent, "config", "user.email", "fixture@users.noreply.github.com")

    (worker / "state" / "value.json").write_text('{"value": 2}\n')
    (concurrent / "state" / "value.json").write_text('{"value": 3}\n')
    git(concurrent, "add", "state/value.json")
    git(concurrent, "commit", "-m", "concurrent update")
    git(concurrent, "push", "origin", "main")

    env = os.environ.copy()
    env["SAFE_COMMIT_PREFER_LOCAL"] = "state/value.json"
    run(
        [
            "bash",
            "scripts/safe_commit.sh",
            "derived update",
            "state/value.json",
        ],
        worker,
        env=env,
    )

    payload = git(
        tmp_path,
        "--git-dir",
        str(origin),
        "show",
        "main:state/value.json",
    )
    assert json.loads(payload.stdout)["value"] == 2


def reconcile_conflict_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Prepare local-only clones with a cached post and a newer remote post."""
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    git(tmp_path, "init", "--bare", str(origin))
    git(tmp_path, "init", "-b", "main", str(seed))
    git(seed, "config", "user.name", "fixture")
    git(seed, "config", "user.email", "fixture@users.noreply.github.com")
    (seed / "scripts").mkdir()
    (seed / "state").mkdir()
    (seed / "docs").mkdir()
    shutil.copy2(ROOT / "scripts/safe_commit.sh", seed / "scripts")
    (seed / "scripts/state_io.py").write_text('print("State consistency OK")\n')
    (seed / "scripts/reconcile_channels.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "assert sys.argv[1:] == ['--require-authoritative']\n"
        "state = Path('state')\n"
        "posts = json.loads((state / 'posted_log.json').read_text())['posts']\n"
        "cached = json.loads((state / 'discussions_cache.json').read_text())['posts']\n"
        "posts = sorted(set(posts + cached))\n"
        "(state / 'posted_log.json').write_text(json.dumps({'posts': posts}))\n"
        "(state / 'channels.json').write_text(json.dumps({'post_count': len(posts)}))\n"
    )
    for filename, payload in {
        "state/posted_log.json": {"posts": [1]},
        "state/channels.json": {"post_count": 1},
        "state/stats.json": {}, "state/agents.json": {}, "docs/pulse.json": {},
    }.items():
        (seed / filename).write_text(json.dumps(payload))
    (seed / ".gitignore").write_text("state/discussions_cache.json\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "fixture root")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "main")
    worker, concurrent = tmp_path / "worker", tmp_path / "concurrent"
    for clone in (worker, concurrent):
        git(tmp_path, "clone", "--branch", "main", origin.as_uri(), str(clone))
        git(clone, "config", "user.name", "fixture")
        git(clone, "config", "user.email", "fixture@users.noreply.github.com")
    return origin, worker, concurrent


@pytest.mark.parametrize("conflicting", [False, True], ids=["clean-rebase", "conflict"])
def test_reconcile_after_rebase_preserves_remote_and_cached_posts(
    tmp_path: Path, conflicting: bool
) -> None:
    """A successful retry must publish the repair, not silently discard it."""
    origin, worker, concurrent = reconcile_conflict_fixture(tmp_path)
    (worker / "state/discussions_cache.json").write_text('{"posts": [1, 2]}')
    if conflicting:
        (worker / "state/posted_log.json").write_text('{"posts": [1, 2]}')
        (worker / "state/channels.json").write_text('{"post_count": 2}')
    else:
        (worker / "docs/pulse.json").write_text('{"changed": true}')
    (concurrent / "state/posted_log.json").write_text('{"posts": [1, 3]}')
    (concurrent / "state/channels.json").write_text('{"post_count": 99}')
    git(concurrent, "add", "state/posted_log.json", "state/channels.json")
    git(concurrent, "commit", "-m", "newer remote state")
    git(concurrent, "push", "origin", "main")
    env = os.environ.copy()
    env["SAFE_COMMIT_RECONCILE_CHANNELS"] = "true"

    run(
        ["bash", "scripts/safe_commit.sh", "reconciled counts",
         "state/posted_log.json", "state/channels.json", "state/stats.json",
         "state/agents.json", "docs/pulse.json"],
        worker, env=env,
    )

    for filename, expected in {
        "posted_log.json": {"posts": [1, 2, 3]},
        "channels.json": {"post_count": 3},
    }.items():
        published = git(
            tmp_path, "--git-dir", str(origin), "show", f"main:state/{filename}",
        )
        assert json.loads(published.stdout) == expected


def test_failed_recompute_does_not_publish_a_success(tmp_path: Path) -> None:
    """A failed post-rebase rebuild must stop before the retrying push."""
    origin, worker, concurrent = reconcile_conflict_fixture(tmp_path)
    (worker / "state/channels.json").write_text('{"post_count": 2}')
    (worker / "scripts/reconcile_channels.py").write_text(
        "raise SystemExit('incomplete authoritative corpus')\n",
    )
    (concurrent / "state/channels.json").write_text('{"post_count": 3}')
    git(concurrent, "add", "state/channels.json")
    git(concurrent, "commit", "-m", "newer remote state")
    git(concurrent, "push", "origin", "main")
    env = os.environ.copy()
    env["SAFE_COMMIT_RECONCILE_CHANNELS"] = "true"

    with pytest.raises(subprocess.CalledProcessError) as failure:
        run(
            ["bash", "scripts/safe_commit.sh", "reconciled counts",
             "state/channels.json"],
            worker, env=env,
        )

    assert "incomplete authoritative corpus" in failure.value.stderr
    assert "Push succeeded" not in failure.value.stdout
    published = git(
        tmp_path, "--git-dir", str(origin), "show", "main:state/channels.json",
    )
    assert json.loads(published.stdout) == {"post_count": 3}
