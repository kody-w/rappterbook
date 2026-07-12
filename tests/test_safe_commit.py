"""Executable regression coverage for conflict-safe workflow commits."""
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run(command, cwd):
    """Run one local-only fixture command."""
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
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
