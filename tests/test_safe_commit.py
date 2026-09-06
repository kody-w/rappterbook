"""Executable regression coverage for conflict-safe workflow commits."""
import json
import os
import shutil
import subprocess
from pathlib import Path


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


def test_conflicting_autostash_pop_does_not_abort_the_push(tmp_path):
    """A derived file that conflicts on autostash-pop must not fail the job.

    Regression for Compute Trending run 34012061561, which exited 1 with every
    generator step green and left state/trending.json stale past its 12h bar.
    `git rebase --autostash` stashes the derived files these generators rewrite
    but do not commit (docs/pulse.json), and pops them once the rebase lands.
    When the concurrent pusher touched the same derived file the pop conflicts,
    git leaves the path unmerged, and the retry loop then died twice over:
    `--autostash` aborts with "fatal: Cannot autostash" against an unmerged
    index, and the conflict scan read that residue as a non-state conflict.
    """
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
    (seed / "docs").mkdir()
    shutil.copy2(ROOT / "scripts" / "safe_commit.sh", seed / "scripts")
    (seed / "scripts" / "state_io.py").write_text('print("State consistency OK")\n')
    (seed / "state" / "value.json").write_text('{"value": 1}\n')
    # Tracked, derived, owned by other workflows, never in our FILES list.
    (seed / "docs" / "pulse.json").write_text('{"pulse": 1}\n')
    git(seed, "add", ".")
    git(seed, "commit", "-m", "fixture root")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "main")

    for path in (worker, concurrent):
        git(tmp_path, "clone", origin.as_uri(), str(path))
        git(path, "config", "user.name", "fixture")
        git(path, "config", "user.email", "fixture@users.noreply.github.com")

    # Advance origin before each of the worker's first two pushes, touching the
    # state file it commits AND the derived file it leaves unstaged. Driving it
    # from a pre-push hook makes the CI race deterministic.
    advance = tmp_path / "advance.sh"
    advance.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f'cd "{concurrent}"\n'
        "git pull -q --rebase origin main\n"
        'n="$1"\n'
        'printf \'{"value": %s}\\n\' "$n" > state/value.json\n'
        'printf \'{"pulse": %s}\\n\' "$n" > docs/pulse.json\n'
        "git add -A\n"
        'git commit -qm "concurrent $n"\n'
        "git push -q origin main\n"
    )
    advance.chmod(0o755)

    counter = tmp_path / "pushes"
    hook = worker / ".git" / "hooks" / "pre-push"
    hook.write_text(
        "#!/usr/bin/env bash\n"
        f'c="$(cat "{counter}" 2>/dev/null || echo 0)"\n'
        'c=$((c+1))\n'
        f'echo "$c" > "{counter}"\n'
        f'if [ "$c" -le 2 ]; then bash "{advance}" "$((c+10))"; fi\n'
        "exit 0\n"
    )
    hook.chmod(0o755)

    (worker / "state" / "value.json").write_text('{"value": 99}\n')
    (worker / "docs" / "pulse.json").write_text('{"pulse": 99}\n')

    env = os.environ.copy()
    env["SAFE_COMMIT_PREFER_LOCAL"] = "state/value.json"
    result = run(
        ["bash", "scripts/safe_commit.sh", "chore: update trending", "state/value.json"],
        worker,
        env=env,
    )

    assert "Push succeeded" in result.stdout
    # The recomputed state we were asked to prefer actually reached the remote.
    committed = git(tmp_path, "--git-dir", str(origin), "show", "main:state/value.json")
    assert json.loads(committed.stdout)["value"] == 99
    # The other workflow's derived output was preserved, never clobbered by the
    # stashed copy we dropped.
    derived = git(tmp_path, "--git-dir", str(origin), "show", "main:docs/pulse.json")
    assert json.loads(derived.stdout)["pulse"] == 12
