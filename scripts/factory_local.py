#!/usr/bin/env python3
"""factory_local.py -- pull a Ready job off the factory board, build it locally,
promote it back into the assembly line.

The GitHub Project board (FACTORY_PROJECT, default kody-w/1) is the job queue.
Any machine pulls one Ready card, takes a lease on it, builds it in a local
checkout, runs the card's Acceptance command, and promotes the branch as a PR.
Branches are named worker-auto-pr-factory-<repo>-<n>-<slug>, so a PR pushed to
the same repository goes through agents/reviewer.py, the same gate as the
cloud worker. A PR from a fork is not gated and is reviewed by hand. See
docs/FACTORY_LOCAL.md.

Commands:
  list      Ready cards on the board (--platform, --repo filter)
  pull      claim one card (--card REPO#N or --next): lease comment,
            Status=Building, Agent=<id>, local branch and .factory/card.json
  check     run the card's Acceptance command after confirmation (--yes)
  promote   push, open or update the PR, Status=QA, release the lease
  release   give back a card not yet promoted: Status=Ready, Agent cleared,
            lease released
  status    the current card, lease time left and the last check (local only)

Only pull, promote and release write to GitHub, and --dry-run shows those
writes instead. Card titles, bodies and the Acceptance field are untrusted
data: nothing from a card reaches a shell (the acceptance command is split
with shlex and run as an argv list), and a card is built only when its issue
author is trusted (the repository owner plus FACTORY_CARD_AUTHORS, the rule
agents/worker.py uses).

If gh cannot resolve api.github.com intermittently, export GODEBUG=netdns=go.

Python 3.9+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import math
import secrets
import shlex
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import collect_cards  # noqa: E402  project_ref, project_board, clean
import export_board  # noqa: E402  item parsing helpers

DEFAULT_PROJECT = "kody-w/1"
DEFAULT_REPOS = "kody-w/rappterbook,kody-w/rappterverse,kody-w/mars-barn"
DEFAULT_LEASE_HOURS = 4.0
MAX_LEASE_HOURS = 24.0
GH_TIMEOUT = 120
GIT_TIMEOUT = 600
CHECK_TIMEOUT = 1800
TAIL_LINES = 30
MAX_ACCEPTANCE = 2000
MAX_NEXT_TRIES = 20
RENEW_MARGIN = timedelta(minutes=5)  # renew in place only with this much lease left
HEAD_SETTLE_TRIES = 5
SETTLE_DELAY = 2.0
MAX_FIX_PATHS = 10
SAFE_PATH_RE = re.compile(r"[A-Za-z0-9._@+-][A-Za-z0-9._/@+-]{0,199}")
REPLACEMENT = chr(0xFFFD)
TRUSTED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
AGENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")  # as agents/worker.py
MACHINE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
CARD_REF_RE = re.compile(r"^(?:([A-Za-z0-9-]{1,39})/)?([A-Za-z0-9._-]{1,100})#([1-9][0-9]{0,8})$")
LEASE_RE = re.compile(r"<!--\s*factory-lease\s+(\{[^<>]{1,600}\})\s*-->")
LOCAL_MARKER = "<!-- factory:local -->"
FACTORY_DIR = ".factory"
DNS_HINTS = ("no such host", "dial tcp", "lookup api.github.com", "temporary failure in name resolution")
TOKEN_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class Refused(Exception):
    """The command will not proceed; the message says why."""


class StopNext(Refused):
    """A refusal that ends `pull --next` instead of moving on to the next card:
    a local problem every card would hit, or a failure after the lease was
    taken."""


class GhError(RuntimeError):
    """A gh call failed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ── subprocess ───────────────────────────────────────────────────────────────

def default_runner(cmd: List[str], cwd: Optional[str] = None, input_text: Optional[str] = None,
                   timeout: float = GH_TIMEOUT, env: Optional[Dict[str, str]] = None
                   ) -> "subprocess.CompletedProcess[str]":
    """Run an argv list (never a shell). A timeout or a missing program becomes
    a failed result, never an exception. env=None inherits the environment,
    so GODEBUG=netdns=go reaches gh."""
    try:
        return subprocess.run(list(cmd), cwd=cwd, input=input_text, capture_output=True,
                              text=True, timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(cmd, 124, out, f"timed out after {timeout:g}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")


def _first_line(text: str, fallback: str) -> str:
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return collect_cards.clean(lines[0] if lines else fallback, 300, html=False)


class Gh:
    """The one wrapper every gh call goes through.

    Callable with a full ["gh", ...] argv, so collect_cards helpers can use it
    as their runner. Writes (write=True) are only printed under --dry-run.
    Project view/field-list results are cached for the run.
    """

    def __init__(self, runner: Runner, dry_run: bool = False) -> None:
        self.runner = runner
        self.dry_run = dry_run
        self.writes: List[List[str]] = []
        self._cache: Dict[Tuple[str, ...], "subprocess.CompletedProcess[str]"] = {}

    def __call__(self, cmd: List[str]) -> "subprocess.CompletedProcess[str]":
        return self.run(cmd[1:] if cmd and cmd[0] == "gh" else cmd)

    def run(self, args: List[str], input_text: Optional[str] = None,
            write: bool = False) -> "subprocess.CompletedProcess[str]":
        cmd = ["gh"] + [str(a) for a in args]
        if write:
            self.writes.append(cmd)
            if self.dry_run:
                print("[dry-run] would run: " + shlex.join(cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")
        key = tuple(cmd)
        cacheable = (not write and input_text is None and len(cmd) > 2
                     and cmd[1] == "project" and cmd[2] in ("view", "field-list"))
        if cacheable and key in self._cache:
            return self._cache[key]
        proc = self.runner(cmd, input_text=input_text, timeout=GH_TIMEOUT)
        if cacheable and proc.returncode == 0:
            self._cache[key] = proc
        return proc

    def json(self, args: List[str], input_text: Optional[str] = None, write: bool = False) -> Any:
        proc = self.run(args, input_text=input_text, write=write)
        if proc.returncode != 0:
            raise GhError(gh_reason(proc, " ".join(args[:2])))
        if write and self.dry_run:
            return None
        try:
            return json.loads(proc.stdout or "null")
        except ValueError:
            raise GhError(f"gh {' '.join(args[:2])} returned no JSON") from None


def gh_reason(proc: "subprocess.CompletedProcess[str]", what: str) -> str:
    reason = _first_line(proc.stderr or proc.stdout, f"gh {what} failed")
    if any(h in (proc.stderr or "").lower() for h in DNS_HINTS):
        reason += " (DNS lookup failed: try `export GODEBUG=netdns=go`)"
    return reason


def git(runner: Runner, cwd: Path, *args: str, timeout: float = GIT_TIMEOUT
        ) -> "subprocess.CompletedProcess[str]":
    return runner(["git", *args], cwd=str(cwd), timeout=timeout)


def git_out(runner: Runner, cwd: Path, *args: str) -> str:
    proc = git(runner, cwd, *args)
    if proc.returncode != 0:
        raise Refused(f"git {' '.join(args[:2])} failed: {_first_line(proc.stderr, 'error')}")
    return (proc.stdout or "").strip()


# ── trust ────────────────────────────────────────────────────────────────────

def trusted_authors(repo: str) -> set:
    """The repository owner plus FACTORY_CARD_AUTHORS (agents/worker.py's rule)."""
    extra = os.getenv("FACTORY_CARD_AUTHORS", "")
    logins = {repo.split("/")[0]} | set(extra.split(","))
    return {x.strip().lower() for x in logins if x.strip()}


def require_trusted_author(gh: Gh, repo: str, number: int) -> str:
    info = gh.json(["issue", "view", str(number), "--repo", repo, "--json", "author,state"])
    author = info.get("author") if isinstance(info, dict) and isinstance(info.get("author"), dict) else {}
    login = str(author.get("login") or "").strip().lower()
    if not login or login not in trusted_authors(repo):
        raise Refused(f"{repo}#{number} was not opened by a trusted author "
                      "(the repository owner or FACTORY_CARD_AUTHORS); not building it")
    if isinstance(info, dict) and str(info.get("state", "OPEN")).upper() != "OPEN":
        raise Refused(f"{repo}#{number} is closed")
    return login


# ── the board ────────────────────────────────────────────────────────────────

class Board:
    def __init__(self, gh: Gh, owner: str, number: int, repos: List[str]) -> None:
        self.gh, self.owner, self.number, self.repos = gh, owner, number, repos
        self._meta: Optional[dict] = None

    def meta(self) -> dict:
        """Project id and field ids, looked up by name at run time."""
        if self._meta is None:
            single = collect_cards.project_board(self.gh, self.number, self.owner)
            listed = self.gh.json(["project", "field-list", str(self.number), "--owner", self.owner,
                                   "--format", "json", "--limit", "100"])
            fields = {}
            for f in (listed.get("fields") if isinstance(listed, dict) else None) or []:
                if isinstance(f, dict) and isinstance(f.get("name"), str) and isinstance(f.get("id"), str):
                    fields[f["name"]] = f["id"]
            self._meta = {"id": single["id"], "single": single["fields"], "fields": fields}
        return self._meta

    def cards(self) -> List[dict]:
        data = self.gh.json(["project", "item-list", str(self.number), "--owner", self.owner,
                             "--format", "json", "--limit", str(export_board.ITEM_LIMIT)])
        raw = export_board._raw_items(data)
        total = data.get("totalCount") if isinstance(data, dict) else None
        if isinstance(total, int) and total > len(raw):
            print(f"warning: the board has {total} items, only {len(raw)} were read", file=sys.stderr)
        out = []
        for item in raw:
            card = parse_item(item, self.repos)
            if card:
                out.append(card)
        return out

    def find(self, repo: str, number: int) -> dict:
        for card in self.cards():
            if card["repo"].lower() == repo.lower() and card["number"] == number:
                return card
        raise Refused(f"{repo}#{number} is not on the board {self.owner}/{self.number}")

    def edit(self, item_id: str, name: str, *, option: Optional[str] = None,
             text: Optional[str] = None, number: Optional[float] = None,
             clear: bool = False) -> Optional[str]:
        """Set one field on a Project item. Returns a problem string or None."""
        try:
            meta = self.meta()
        except (RuntimeError, GhError) as exc:
            return f"{name}: board lookup failed: {exc}"
        cmd = ["project", "item-edit", "--id", item_id, "--project-id", meta["id"]]
        if option is not None:
            field_id, options = meta["single"].get(name, ("", {}))
            if not field_id or option not in options:
                return f"{name}={option} is not on the Project"
            cmd += ["--field-id", field_id, "--single-select-option-id", options[option]]
        else:
            field_id = meta["fields"].get(name)
            if not field_id:
                return f"{name} is not on the Project"
            cmd += ["--field-id", field_id]
            if clear:
                cmd.append("--clear")
            elif text is not None:
                cmd += ["--text", text]
            else:
                cmd += ["--number", str(number)]
        proc = self.gh.run(cmd, write=True)
        return None if proc.returncode == 0 else f"{name}: {gh_reason(proc, 'project item-edit')}"


def _text(value: Any, limit: int) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("text") or ""
    return export_board._clean_text(value, limit)


def parse_item(item: Any, repos: List[str]) -> Optional[dict]:
    """One gh project item -> a card dict, or None (not an issue in a linked repo)."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    if content.get("type") != "Issue":
        return None
    url = export_board._safe_url(content.get("url"))
    match = export_board._GH_URL.match(url or "")
    if not match or match.group(3) != "issues":
        return None
    repo = f"{match.group(1)}/{match.group(2)}"
    if repo.lower() not in {r.lower() for r in repos}:
        return None
    iterations = export_board._lookup(item, "Iterations")
    acceptance = export_board._lookup(item, "Acceptance")
    return {
        "item_id": item["id"], "repo": repo, "number": int(match.group(4)), "url": url,
        "title": _text(item.get("title") or content.get("title"), 200) or "(untitled)",
        "status": export_board.map_status(export_board._lookup(item, "Status")),
        "platform": _text(export_board._lookup(item, "Platform"), 60),
        "agent": _text(export_board._lookup(item, "Agent"), 64),
        "acceptance": export_board._UNSAFE_CHARS.sub(REPLACEMENT, acceptance.strip()[:MAX_ACCEPTANCE])
        if isinstance(acceptance, str) else "",
        "iterations": int(iterations) if isinstance(iterations, (int, float))
        and not isinstance(iterations, bool) and iterations >= 0 else 0,
    }


# ── leases ───────────────────────────────────────────────────────────────────

def lease_body(agent: str, machine: str, expires: datetime, nonce: str) -> str:
    marker = json.dumps({"agent": agent, "machine": machine, "expires": iso(expires),
                         "nonce": nonce}, sort_keys=True, separators=(",", ":"))
    return (f"Claimed for a local build by agent `{agent}` on `{machine}` until "
            f"{iso(expires)} (scripts/factory_local.py). The lease lapses on its own "
            f"after that.\n\n<!-- factory-lease {marker} -->\n")


def released_body(agent: str, why: str) -> str:
    return f"released: `{agent}` {collect_cards.clean(why, 300)}\n"


def read_claims(gh: Gh, repo: str, number: int) -> List[dict]:
    """Every lease marker on the issue's comments, ordered by the time of each
    comment's last write (then id): a claim renewed in place ranks by its
    renewal, so a stale lease brought back to life cannot outrank a newer
    claim."""
    data = gh.json(["api", f"repos/{repo}/issues/{number}/comments?per_page=100",
                    "--paginate", "--slurp"])
    flat: List[Any] = []
    for page in data if isinstance(data, list) else []:
        flat.extend(page if isinstance(page, list) else [page])
    trusted = trusted_authors(repo)
    claims = []
    for c in flat:
        if not isinstance(c, dict) or not isinstance(c.get("id"), int):
            continue
        match = LEASE_RE.search(str(c.get("body") or ""))
        if not match:
            continue
        try:
            lease = json.loads(match.group(1))
        except ValueError:
            continue
        expires = parse_iso(lease.get("expires")) if isinstance(lease, dict) else None
        agent = str(lease.get("agent", "")) if isinstance(lease, dict) else ""
        machine = str(lease.get("machine", "")) if isinstance(lease, dict) else ""
        if not expires or not AGENT_ID_RE.fullmatch(agent) or not MACHINE_RE.fullmatch(machine):
            continue
        written = parse_iso(c.get("updated_at")) or parse_iso(c.get("created_at"))
        if written:  # nobody holds a card longer than MAX_LEASE_HOURS per write
            expires = min(expires, written + timedelta(hours=MAX_LEASE_HOURS))
        user = c.get("user") if isinstance(c.get("user"), dict) else {}
        login = str(user.get("login") or "").lower()
        claims.append({
            "id": c["id"], "agent": agent, "machine": machine, "expires": expires,
            "created_at": str(c.get("created_at") or ""), "login": login,
            "written": written or datetime.min.replace(tzinfo=timezone.utc),
            "counted": login in trusted or c.get("author_association") in TRUSTED_ASSOCIATIONS,
        })
    return sorted(claims, key=lambda x: (x["written"], x["id"]))


def active_claims(claims: List[dict], now: datetime) -> List[dict]:
    """Unexpired claims from accounts that may claim (trusted logins and repo
    writers): a stranger's comment cannot block the card."""
    return [c for c in claims if c["counted"] and c["expires"] > now]


def post_comment(gh: Gh, repo: str, number: int, body: str) -> Optional[int]:
    data = gh.json(["api", f"repos/{repo}/issues/{number}/comments", "--method", "POST",
                    "--input", "-"], input_text=json.dumps({"body": body}), write=True)
    return data.get("id") if isinstance(data, dict) and isinstance(data.get("id"), int) else None


def edit_comment(gh: Gh, repo: str, comment_id: int, body: str) -> Optional[str]:
    proc = gh.run(["api", f"repos/{repo}/issues/comments/{int(comment_id)}", "--method", "PATCH",
                   "--input", "-"], input_text=json.dumps({"body": body}), write=True)
    return None if proc.returncode == 0 else gh_reason(proc, "api PATCH")


def take_lease(gh: Gh, repo: str, number: int, agent: str, machine: str,
               hours: float, now: datetime,
               clock: Optional[Callable[[], datetime]] = None) -> Tuple[int, datetime, bool]:
    """Compare-and-set claim. Returns (comment id, expiry, renewed).

    Refuses when another unexpired claim exists. Otherwise renews our own
    claim in place when it has more than RENEW_MARGIN left, or posts a new
    claim, and re-reads (at a fresh clock reading): the active claim with the
    oldest last write wins, and a loser marks its own claim released and
    backs off. A claim close to expiry, or expired, is never renewed in place
    (another machine may claim the card between our read and our write); its
    owner posts a new claim instead.
    """
    expires = now + timedelta(hours=hours)
    active = active_claims(read_claims(gh, repo, number), now)
    others = [c for c in active if (c["agent"], c["machine"]) != (agent, machine)]
    if others:
        o = others[0]
        raise Refused(f"{repo}#{number} is claimed by `{o['agent']}` on `{o['machine']}` "
                      f"until {iso(o['expires'])}")
    renewable = [c for c in active if c["expires"] - now > RENEW_MARGIN]
    nonce = secrets.token_hex(6)
    if gh.dry_run:
        print(f"[dry-run] would claim {repo}#{number} for {agent} on {machine} until {iso(expires)}")
        return 0, expires, bool(renewable)
    if renewable:
        mine = renewable[0]
        problem = edit_comment(gh, repo, mine["id"], lease_body(agent, machine, expires, nonce))
        if problem:
            raise Refused(f"could not renew the lease: {problem}")
        claim_id, renewed = mine["id"], True
    else:
        claim_id = post_comment(gh, repo, number, lease_body(agent, machine, expires, nonce))
        if claim_id is None:
            raise Refused("posting the claim comment returned no comment id")
        renewed = False
    after = read_claims(gh, repo, number)
    ours = next((c for c in after if c["id"] == claim_id), None)
    active = active_claims(after, clock() if clock else now)
    # Our own older claim (one too close to expiry to renew) does not compete.
    contenders = [c for c in active if c["id"] == claim_id or (c["agent"], c["machine"]) != (agent, machine)]
    if ours is None or not ours["counted"] or not contenders or contenders[0]["id"] != claim_id:
        winner = next((c for c in contenders if c["id"] != claim_id), None)
        edit_comment(gh, repo, claim_id, released_body(agent, "backed off: another claim landed first"))
        if ours is not None and not ours["counted"]:
            raise Refused("your GitHub account cannot claim cards here (not a repository "
                          "writer and not in FACTORY_CARD_AUTHORS); claim released")
        who = f"`{winner['agent']}` on `{winner['machine']}`" if winner else "another machine"
        raise Refused(f"{repo}#{number} was claimed first by {who}; backed off")
    for old in active:
        if old["id"] != claim_id and (old["agent"], old["machine"]) == (agent, machine):
            edit_comment(gh, repo, old["id"], released_body(agent, "superseded by a new claim"))
    return claim_id, expires, renewed


# ── local checkout ───────────────────────────────────────────────────────────

def factory_home() -> Path:
    return Path(os.getenv("FACTORY_LOCAL_HOME") or (Path.home() / ".rapp-factory")).expanduser()


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")
    slug = re.sub(r"^foreman-", "", slug)[:40].strip("-")
    return slug or "card"


def branch_name(repo: str, number: int, title: str) -> str:
    name = re.sub(r"[^a-z0-9._-]+", "-", repo.split("/")[1].lower()).strip("-.") or "repo"
    return f"worker-auto-pr-factory-{name}-{int(number)}-{slugify(title)}"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_dirty(runner: Runner, cwd: Path) -> bool:
    return bool(git_out(runner, cwd, "status", "--porcelain"))


def check_origin(runner: Runner, repo: str, workdir: Path) -> None:
    origin = git_out(runner, workdir, "remote", "get-url", "origin")
    if not re.search(r"github\.com[:/]" + re.escape(repo) + r"(?:\.git)?/?$", origin, re.IGNORECASE):
        raise Refused(f"{workdir} is a checkout of {origin!r}, not {repo}")


def check_existing_checkout(runner: Runner, repo: str, workdir: Path, branch: str) -> None:
    """Read-only checks of the checkout directory: absent or empty (it will be
    cloned), or a checkout of ``repo`` that is clean or already on ``branch``."""
    if not (workdir / ".git").exists():
        if workdir.exists() and (not workdir.is_dir() or any(workdir.iterdir())):
            raise Refused(f"{workdir} exists and is not a git checkout")
        return
    check_origin(runner, repo, workdir)
    current = git_out(runner, workdir, "rev-parse", "--abbrev-ref", "HEAD")
    if current != branch and is_dirty(runner, workdir):
        raise Refused(f"{workdir} has uncommitted changes on {current}; commit or stash them first")


def prepare_checkout(gh: Gh, runner: Runner, repo: str, workdir: Path, branch: str) -> str:
    """Clone or reuse a checkout, put it on ``branch`` (created from the default
    branch), and exclude .factory/ locally. Returns the default branch."""
    view = gh.json(["repo", "view", repo, "--json", "defaultBranchRef"])
    ref = view.get("defaultBranchRef") if isinstance(view, dict) else None
    base = ref.get("name") if isinstance(ref, dict) else None
    if not isinstance(base, str) or not BRANCH_RE.fullmatch(base):
        raise Refused(f"could not read the default branch of {repo}")
    if not (workdir / ".git").exists():
        check_existing_checkout(runner, repo, workdir, branch)
        workdir.parent.mkdir(parents=True, exist_ok=True)
        proc = gh.run(["repo", "clone", repo, str(workdir)])
        if proc.returncode != 0:
            raise Refused(f"clone failed: {gh_reason(proc, 'repo clone')}")
    check_origin(runner, repo, workdir)
    fetch = git(runner, workdir, "fetch", "origin", base)
    if fetch.returncode != 0:
        raise Refused(f"git fetch failed: {_first_line(fetch.stderr, 'error')}")
    current = git_out(runner, workdir, "rev-parse", "--abbrev-ref", "HEAD")
    if current != branch:
        if is_dirty(runner, workdir):
            raise Refused(f"{workdir} has uncommitted changes on {current}; commit or stash them first")
        exists = git(runner, workdir, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if exists.returncode == 0:
            git_out(runner, workdir, "checkout", branch)
        else:
            git_out(runner, workdir, "checkout", "--no-track", "-b", branch, f"origin/{base}")
    exclude = Path(git_out(runner, workdir, "rev-parse", "--git-path", "info/exclude"))
    exclude = exclude if exclude.is_absolute() else workdir / exclude
    try:
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if f"/{FACTORY_DIR}/" not in lines:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write(("\n" if lines and lines[-1] else "") + f"/{FACTORY_DIR}/\n")
    except OSError as exc:
        raise Refused(f"could not write {exclude}: {exc}")
    return base


def find_checkout(workdir: Optional[str]) -> Path:
    """--workdir, else the checkout containing the current directory, else the
    only checkout under the factory home that holds a card."""
    if workdir:
        path = Path(workdir).expanduser()
        if not (path / FACTORY_DIR / "card.json").is_file():
            raise Refused(f"{path} holds no pulled card")
        return path
    here = Path.cwd()
    for path in [here] + list(here.parents):
        if (path / FACTORY_DIR / "card.json").is_file():
            return path
    home = factory_home()
    found = sorted(p.parent.parent for p in home.glob(f"*/{FACTORY_DIR}/card.json")) if home.is_dir() else []
    if len(found) == 1:
        return found[0]
    if not found:
        raise Refused("no pulled card here or under " + str(home) + "; run `pull` first")
    raise Refused("several pulled cards; pass --workdir: " + ", ".join(str(p) for p in found))


def load_card(checkout: Path) -> dict:
    card = read_json(checkout / FACTORY_DIR / "card.json")
    if not card or not isinstance(card.get("repo"), str) or not isinstance(card.get("number"), int):
        raise Refused(f"{checkout / FACTORY_DIR / 'card.json'} is missing or malformed")
    return card


# ── acceptance ───────────────────────────────────────────────────────────────

def acceptance_argv(text: Any) -> Optional[List[str]]:
    """The card's acceptance command as an argv list (never a shell string).

    The field is either the bare command or prose with exactly one
    backtick-quoted span, which is the command (collected cards write prose
    around it). More than one span, or an unpaired backtick, is refused rather
    than guessed at. Control characters (terminal escapes, line breaks) and
    invisible formatting characters are refused, so what the confirmation
    prompt shows is what runs. Pipes, ';' and '$(...)' are not interpreted:
    they become plain arguments.
    """
    text = str(text or "").strip()
    if REPLACEMENT in text or export_board._UNSAFE_CHARS.search(text) or "\n" in text:
        return None
    ticks = text.count("`")
    if ticks not in (0, 2):
        return None
    match = re.search(r"`([^`\n]+)`", text)
    if ticks and not match:
        return None
    command = (match.group(1) if match else text).strip()
    if not command:
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    return argv or None


def scrubbed_env() -> Dict[str, str]:
    """The acceptance command runs without the GitHub tokens in the environment."""
    return {k: v for k, v in os.environ.items() if k not in TOKEN_ENV}


def confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def inert_code(text: str, limit: int = 300) -> str:
    """Card text made safe for an inline code span in a PR body: one line, no
    backticks (so the span cannot end early), no mentions, and no '#N' or
    issue URL that GitHub would read as a closing reference."""
    text = collect_cards.clean(text, limit, html=False).replace("`", "'")
    return text.replace("#", "#\u200b").replace("github.com", "github\u200b.com")


def fix_line(paths: Optional[List[str]]) -> str:
    """The 'Fix:' line scripts/factory_retro.py records (as in
    agents/worker.build_pr_body): the changed paths, each one checked against
    a plain-path pattern (no '#', backtick or space), at most MAX_FIX_PATHS."""
    safe = [p for p in (paths or []) if SAFE_PATH_RE.fullmatch(p) and ".." not in p.split("/")]
    if not safe:
        return "Fix: built locally with scripts/factory_local.py"
    shown = ", ".join(f"`{p}`" for p in safe[:MAX_FIX_PATHS])
    more = len(paths or []) - len(safe[:MAX_FIX_PATHS])
    return f"Fix: built locally, changed {shown}" + (f" and {more} more" if more > 0 else "")


def build_pr_body(card: dict, agent: str, check: dict, paths: Optional[List[str]] = None) -> str:
    """'Closes #N' (exactly one, for this card), 'Agent: <id>' and 'Fix:' as in
    agents/worker.build_pr_body, plus the acceptance command and the local
    check result. Card text stays inert; the check output stays out."""
    argv = check.get("command") if isinstance(check.get("command"), list) else []
    command = shlex.join(str(a) for a in argv) if argv else card.get("acceptance", "")
    passed = "pass" if check.get("passed") else "fail"
    lines = [
        LOCAL_MARKER, "Built and checked locally with `scripts/factory_local.py`.", "",
        fix_line(paths), "",
        f"Agent: {agent}", "",
        "## Acceptance", "", f"`{inert_code(command, 500)}`", "",
        "## Local check", "",
        f"- result: {passed} (exit {check.get('exit_code')}) in {check.get('duration_s')}s",
        f"- commit: {check.get('head')}",
        f"- machine: {card.get('machine', '')}",
        f"- ran at: {check.get('ran_at')}", "",
        f"Closes #{int(card['number'])}",
    ]
    return "\n".join(lines) + "\n"


# ── commands ─────────────────────────────────────────────────────────────────

class Ctx:
    def __init__(self, args: argparse.Namespace, runner: Runner, now: Callable[[], datetime]) -> None:
        self.args, self.runner, self.now = args, runner, now
        self.gh = Gh(runner, dry_run=getattr(args, "dry_run", False))
        self.explicit_project = bool(args.project or os.getenv("FACTORY_PROJECT"))
        ref = collect_cards.project_ref(args.project or os.getenv("FACTORY_PROJECT") or DEFAULT_PROJECT)
        if ref is None:
            raise Refused(f"bad project {args.project!r}: expected OWNER/NUMBER or a project URL")
        owner = ref[0] or DEFAULT_PROJECT.split("/")[0]
        repos = export_board.parse_repos(os.getenv("FACTORY_LOCAL_REPOS") or DEFAULT_REPOS)
        self.board = Board(self.gh, owner, ref[1], repos)

    def use_card(self, card: dict) -> None:
        """Work on the board the card was pulled from. An explicit --project or
        FACTORY_PROJECT that names another board is refused."""
        saved = card.get("project")
        ref = collect_cards.project_ref(saved) if isinstance(saved, str) else None
        if ref is None:
            return
        owner = ref[0] or DEFAULT_PROJECT.split("/")[0]
        if (owner.lower(), ref[1]) == (self.board.owner.lower(), self.board.number):
            return
        if self.explicit_project:
            raise Refused(f"{card.get('repo')}#{card.get('number')} was pulled from the board {owner}/{ref[1]}, "
                          f"not {self.board.owner}/{self.board.number}")
        self.board = Board(self.gh, owner, ref[1], self.board.repos)

    def resolve_repo(self, name: str) -> str:
        for repo in self.board.repos:
            if name.lower() in (repo.lower(), repo.split("/")[1].lower()):
                return repo
        raise Refused(f"{name} is not a linked repository ({', '.join(self.board.repos)})")


def agent_id(args: argparse.Namespace) -> str:
    agent = (getattr(args, "agent", None) or os.getenv("FACTORY_AGENT") or "").strip()
    if not AGENT_ID_RE.fullmatch(agent):
        raise Refused("pass --agent <id> (or set FACTORY_AGENT): letters, digits, '_' and '-'")
    return agent


def machine_label(args: argparse.Namespace) -> str:
    raw = getattr(args, "machine", None) or os.getenv("FACTORY_MACHINE") or socket.gethostname().split(".")[0]
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")[:64]
    return label if MACHINE_RE.fullmatch(label) else "machine"


def filtered(ctx: Ctx, cards: List[dict]) -> List[dict]:
    args = ctx.args
    repo = ctx.resolve_repo(args.repo) if getattr(args, "repo", None) else None
    platform = (getattr(args, "platform", None) or "").lower()
    keep = [c for c in cards if (not repo or c["repo"].lower() == repo.lower())
            and (not platform or c["platform"].lower() == platform)]
    order = {r.lower(): i for i, r in enumerate(ctx.board.repos)}
    return sorted(keep, key=lambda c: (order.get(c["repo"].lower(), 99), c["number"]))


def cmd_list(ctx: Ctx) -> int:
    cards = filtered(ctx, [c for c in ctx.board.cards() if c["status"] == "Ready"])
    if ctx.args.json:
        print(json.dumps(cards, indent=2, ensure_ascii=False))
        return 0
    if not cards:
        print("No Ready cards.")
        return 0
    for c in cards:
        print(f"{c['repo']}#{c['number']}  [{c['platform'] or '-'}]  {c['title']}")
        print(f"    acceptance: {_text(c['acceptance'], 160) or '(none)'}")
    return 0


def parse_card_ref(ctx: Ctx, ref: str) -> Tuple[str, int]:
    match = CARD_REF_RE.match(ref.strip())
    if not match:
        raise Refused(f"bad card {ref!r}: expected REPO#N or OWNER/REPO#N")
    name = f"{match.group(1)}/{match.group(2)}" if match.group(1) else match.group(2)
    return ctx.resolve_repo(name), int(match.group(3))


def card_workdir(args: argparse.Namespace, repo: str) -> Path:
    return Path(args.workdir).expanduser() if args.workdir else factory_home() / repo.split("/")[1]


def preflight_checkout(runner: Runner, repo: str, number: int, workdir: Path, branch: str) -> None:
    """Local checks made before any GitHub write, so a bad local state (another
    card still held here, a non-git or foreign directory, uncommitted changes)
    stops `pull` before it claims anything. Raises StopNext: the same problem
    would stop every card `pull --next` tried."""
    old = read_json(workdir / FACTORY_DIR / "card.json")
    if old and (old.get("repo"), old.get("number")) != (repo, number) and old.get("lease_expires"):
        raise StopNext(f"{workdir} holds {old.get('repo')}#{old.get('number')}, which is neither "
                       "promoted nor released; promote or release it first, or pass --workdir")
    try:
        check_existing_checkout(runner, repo, workdir, branch)
    except Refused as exc:
        raise StopNext(str(exc)) from None


def claim_card(ctx: Ctx, card: dict, agent: str, machine: str) -> int:
    args, gh = ctx.args, ctx.gh
    repo, number = card["repo"], card["number"]
    if card["status"] not in ("Ready", "Building"):
        raise Refused(f"{repo}#{number} is in {card['status']}, not Ready")
    if card["status"] == "Building" and not any(c["counted"] for c in read_claims(gh, repo, number)):
        # Building with no lease from an account that may claim: someone builds
        # it outside this lane (a stranger's marker does not count).
        raise Refused(f"{repo}#{number} is in Building with no lease; not taking it over")
    author = require_trusted_author(gh, repo, number)
    branch = branch_name(repo, number, card["title"])
    workdir = card_workdir(args, repo)
    preflight_checkout(ctx.runner, repo, number, workdir, branch)
    now = ctx.now()
    claim_id, expires, renewed = take_lease(gh, repo, number, agent, machine, args.lease_hours,
                                            now, clock=ctx.now)
    if gh.dry_run:
        print(f"[dry-run] would set Status=Building, Agent={agent} and check out {branch} in {workdir}")
        return 0
    try:
        base = prepare_checkout(gh, ctx.runner, repo, workdir, branch)
    except Refused as exc:
        if renewed:
            raise StopNext(f"{exc}. Your lease is held until {iso(expires)}; "
                           "fix this and pull again, or run `release`") from None
        problem = edit_comment(gh, repo, claim_id, released_body(agent, "local checkout failed"))
        if problem:
            raise StopNext(f"{exc}. Releasing the claim failed ({problem}); it lapses at "
                           f"{iso(expires)}. The board was not changed") from None
        raise StopNext(f"{exc}. The claim was released and the board was not changed") from None
    for problem in (ctx.board.edit(card["item_id"], "Status", option="Building"),
                    ctx.board.edit(card["item_id"], "Agent", text=agent)):
        if problem:
            print(f"warning: board not updated: {problem}", file=sys.stderr)
    old = read_json(workdir / FACTORY_DIR / "card.json") or {}
    keep = old if (old.get("repo"), old.get("number")) == (repo, number) else {}
    if not keep or keep.get("acceptance") != card["acceptance"]:
        try:  # a check of another card, or of an older Acceptance, proves nothing now
            (workdir / FACTORY_DIR / "last_check.json").unlink()
        except OSError:
            pass
    data = {
        "repo": repo, "number": number, "url": card["url"], "title": card["title"],
        "acceptance": card["acceptance"], "author": author, "item_id": card["item_id"],
        "project": f"{ctx.board.owner}/{ctx.board.number}", "agent": agent, "machine": machine,
        "branch": branch, "base": base, "claim_comment_id": claim_id,
        "lease_expires": iso(expires), "pulled_at": iso(now),
        "promoted_sha": keep.get("promoted_sha"), "pr_url": keep.get("pr_url"),
    }
    if isinstance(keep.get("pending_iterations"), dict):
        data["pending_iterations"] = keep["pending_iterations"]
    write_json(workdir / FACTORY_DIR / "card.json", data)
    print(f"{'Renewed' if renewed else 'Claimed'} {repo}#{number} until {iso(expires)}.")
    print(f"Checkout: {workdir} on {branch}")
    print(f"Acceptance: {_text(card['acceptance'], 200) or '(none)'}")
    return 0


def cmd_pull(ctx: Ctx) -> int:
    args = ctx.args
    agent, machine = agent_id(args), machine_label(args)
    if bool(args.card) == bool(args.next):
        raise Refused("pass exactly one of --card REPO#N or --next")
    if not math.isfinite(args.lease_hours) or args.lease_hours <= 0 or args.lease_hours > MAX_LEASE_HOURS:
        raise Refused(f"--lease-hours must be a number in (0, {MAX_LEASE_HOURS:g}]")
    if args.card:
        repo, number = parse_card_ref(ctx, args.card)
        return claim_card(ctx, ctx.board.find(repo, number), agent, machine)
    cards = ctx.board.cards()
    # Ready cards first; then Building cards, which claim_card takes over only
    # when their lease (from an account that may claim) has expired.
    candidates = (filtered(ctx, [c for c in cards if c["status"] == "Ready"])
                  + filtered(ctx, [c for c in cards if c["status"] == "Building"]))
    for card in candidates[:MAX_NEXT_TRIES]:
        try:
            return claim_card(ctx, card, agent, machine)
        except StopNext:
            raise
        except Refused as exc:
            print(f"skipping {card['repo']}#{card['number']}: {exc}")
    raise Refused("no Ready card (or Building card with an expired lease) could be claimed")


def positive_timeout(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise Refused("--timeout must be a positive number of seconds")
    return value


def cmd_check(ctx: Ctx) -> int:
    args = ctx.args
    timeout = positive_timeout(args.timeout)
    checkout = find_checkout(args.workdir)
    card = load_card(checkout)
    ctx.use_card(card)
    argv = acceptance_argv(card.get("acceptance"))
    if not argv:
        raise Refused(f"{card['repo']}#{card['number']} has no runnable Acceptance command "
                      "(one command, or prose with exactly one `backtick` span; no control characters)")
    require_trusted_author(ctx.gh, card["repo"], card["number"])
    print(f"Acceptance command for {card['repo']}#{card['number']} (card text, untrusted):")
    print("  " + shlex.join(argv))
    print(f"in {checkout} (run as an argv list, no shell; GitHub tokens removed from its environment)")
    if not confirm("Run it? [y/N] ", args.yes):
        raise Refused("not confirmed; pass --yes to run it")
    head = git_out(ctx.runner, checkout, "rev-parse", "HEAD")
    before = git_out(ctx.runner, checkout, "status", "--porcelain")
    started = time.monotonic()
    proc = ctx.runner(argv, cwd=str(checkout), timeout=timeout, env=scrubbed_env())
    duration = round(time.monotonic() - started, 2)
    after = git_out(ctx.runner, checkout, "status", "--porcelain")
    dirty, dirty_after, changed = bool(before), bool(after), after != before
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = [line[:300] for line in output.splitlines()[-TAIL_LINES:]]
    result = {"head": head, "dirty": dirty, "dirty_after": dirty_after, "tree_changed": changed,
              "exit_code": proc.returncode,
              "passed": proc.returncode == 0, "duration_s": duration, "command": argv,
              "ran_at": iso(ctx.now()), "tail": tail}
    write_json(checkout / FACTORY_DIR / "last_check.json", result)
    for line in tail:
        print("  | " + line)
    verdict = "PASS" if result["passed"] else "FAIL"
    note = ""
    if dirty:
        note = " (uncommitted changes: commit them and check again before promote)"
    elif changed:
        note = (" (the command changed the working tree: the tree it passed on is not HEAD;"
                " commit or discard the changes and check again before promote)")
    print(f"{verdict}: exit {proc.returncode} in {duration}s at {head[:12]}" + note)
    return 0 if result["passed"] and not changed else 1


def holder_conflict(ctx: Ctx, card: dict, agent: str, machine: str) -> Optional[dict]:
    """Another machine's unexpired claim, if one exists."""
    active = active_claims(read_claims(ctx.gh, card["repo"], card["number"]), ctx.now())
    return next((c for c in active if (c["agent"], c["machine"]) != (agent, machine)), None)


def same_repo_prs(gh: Gh, repo: str, branch: str, base: str) -> List[dict]:
    """PRs from ``branch`` of ``repo`` itself into ``base``. `gh pr list --head`
    also matches fork PRs with the same branch name (and factory branch names
    are predictable), so forks and other bases are dropped, as agents/worker.py
    and agents/reviewer.py drop them."""
    data = gh.json(["pr", "list", "--repo", repo, "--head", branch, "--state", "all", "--json",
                    "number,url,state,isCrossRepository,headRefName,baseRefName,headRefOid,"
                    "headRepositoryOwner"])
    owner = repo.split("/")[0].lower()
    keep = []
    for pr in data if isinstance(data, list) else []:
        if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
            continue
        head_owner = pr.get("headRepositoryOwner") if isinstance(pr.get("headRepositoryOwner"), dict) else {}
        if (pr.get("isCrossRepository") is False and pr.get("headRefName") == branch
                and pr.get("baseRefName") == base
                and str(head_owner.get("login") or "").lower() == owner):
            keep.append(pr)
    return keep


def changed_paths(runner: Runner, checkout: Path, base: str) -> List[str]:
    proc = git(runner, checkout, "diff", "--name-only", f"origin/{base}...HEAD")
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def wait_for_pr_head(gh: Gh, repo: str, branch: str, base: str, number: int, head: str) -> bool:
    """True once PR ``number`` reports ``head`` as its head commit (GitHub can
    take a moment after a push)."""
    for attempt in range(HEAD_SETTLE_TRIES):
        pr = next((p for p in same_repo_prs(gh, repo, branch, base) if p["number"] == number), None)
        if pr is None:
            return False
        if pr.get("headRefOid") == head:
            return True
        if attempt + 1 < HEAD_SETTLE_TRIES:
            time.sleep(SETTLE_DELAY)
    return False


def cmd_promote(ctx: Ctx) -> int:
    args, gh, runner = ctx.args, ctx.gh, ctx.runner
    checkout = find_checkout(args.workdir)
    card = load_card(checkout)
    ctx.use_card(card)
    repo, number, branch = card["repo"], card["number"], str(card.get("branch") or "")
    agent, machine, base = str(card.get("agent") or ""), str(card.get("machine") or ""), str(card.get("base") or "")
    if not (BRANCH_RE.fullmatch(branch) and BRANCH_RE.fullmatch(base) and AGENT_ID_RE.fullmatch(agent)):
        raise Refused("card.json has a malformed branch, base or agent; pull the card again")
    check = read_json(checkout / FACTORY_DIR / "last_check.json")
    head = git_out(runner, checkout, "rev-parse", "HEAD")
    if not check or check.get("passed") is not True:
        raise Refused("no passing check; run `check` first")
    if check.get("head") != head:
        raise Refused(f"the last check ran on {str(check.get('head'))[:12]}, HEAD is {head[:12]}; run `check` again")
    if check.get("dirty") or check.get("dirty_after") or check.get("tree_changed"):
        raise Refused("the last check ran with uncommitted changes (or made some); "
                      "commit or discard them and run `check` again")
    if check.get("command") != acceptance_argv(card.get("acceptance")):
        raise Refused("the last check ran a different command from the card's Acceptance; run `check` again")
    if is_dirty(runner, checkout):
        raise Refused("the checkout has uncommitted changes; commit or discard them and run `check` again")
    if git_out(runner, checkout, "rev-parse", "--abbrev-ref", "HEAD") != branch:
        raise Refused(f"the checkout is not on {branch}")
    if git_out(runner, checkout, "rev-list", "--count", f"origin/{base}..HEAD") in ("", "0"):
        raise Refused(f"no commits on {branch} beyond {base}; nothing to promote")
    require_trusted_author(gh, repo, number)
    other = holder_conflict(ctx, card, agent, machine)
    if other:
        raise Refused(f"`{other['agent']}` on `{other['machine']}` holds the card until "
                      f"{iso(other['expires'])} (your lease lapsed); not promoting")
    current = ctx.board.find(repo, number)
    if acceptance_argv(current["acceptance"]) != check.get("command"):
        raise Refused("the card's Acceptance on the board changed since it was pulled; "
                      "pull the card again and run `check`")
    prs = same_repo_prs(gh, repo, branch, base)
    # Iterations counts promotions of new work: it goes up when this branch
    # already had a PR (read from GitHub, so it survives release and re-pull)
    # at a different commit. A bump decided but not yet written is kept in
    # card.json and retried, so a failed board write cannot lose it.
    pending = card.get("pending_iterations")
    if isinstance(pending, dict) and pending.get("head") == head and isinstance(pending.get("value"), int):
        target: Optional[int] = pending["value"]
    elif prs and head not in {p.get("headRefOid") for p in prs}:
        target = current["iterations"] + 1
    else:
        target = None
    open_pr = next((p for p in prs if p.get("state") == "OPEN"), None)
    body = build_pr_body(card, agent, check, changed_paths(runner, checkout, base))
    if gh.dry_run:
        print(f"[dry-run] would push {head[:12]} to {branch}, "
              f"{'update PR #' + str(open_pr['number']) if open_pr else 'open a PR'}, set Status=QA"
              + (f", Iterations={target}" if target is not None else "") + ", release the lease")
        print(body)
        return 0
    if target is not None and card.get("pending_iterations") != {"head": head, "value": target}:
        card["pending_iterations"] = {"head": head, "value": target}
        write_json(checkout / FACTORY_DIR / "card.json", card)
    push = git(runner, checkout, "push", "origin", f"HEAD:refs/heads/{branch}")
    if push.returncode != 0:
        raise Refused(f"git push failed: {_first_line(push.stderr, 'error')}")
    if open_pr:
        if not wait_for_pr_head(gh, repo, branch, base, open_pr["number"], head):
            raise Refused(f"PR #{open_pr['number']} does not show the pushed commit {head[:12]} as its "
                          "head; not editing it. Run promote again in a moment")
        proc = gh.run(["pr", "edit", str(open_pr["number"]), "--repo", repo, "--body-file", "-"],
                      input_text=body, write=True)
        pr_url = str(open_pr.get("url") or "")
    else:
        title = f"factory: {collect_cards.clean(card.get('title', ''), 100, html=False)} ({repo.split('/')[1]} card {number})"
        proc = gh.run(["pr", "create", "--repo", repo, "--base", base, "--head", branch,
                       "--title", title, "--body-file", "-"], input_text=body, write=True)
        pr_url = ((proc.stdout or "").strip().splitlines() or [""])[-1]
    if proc.returncode != 0:
        raise Refused(f"PR not opened: {gh_reason(proc, 'pr')}. The branch is pushed; run promote again")
    problem = ctx.board.edit(current["item_id"], "Status", option="QA")
    if not problem and target is not None:
        problem = ctx.board.edit(current["item_id"], "Iterations", number=target)
    if problem:
        raise Refused(f"the PR is {pr_url}, but the board was not updated ({problem}); "
                      "the lease is kept. Run promote again")
    card.pop("pending_iterations", None)
    card.update({"promoted_sha": head, "pr_url": pr_url, "promoted_at": iso(ctx.now())})
    write_json(checkout / FACTORY_DIR / "card.json", card)
    if card.get("claim_comment_id") and card.get("lease_expires"):
        problem = edit_comment(gh, repo, int(card["claim_comment_id"]),
                               released_body(agent, f"promoted to {pr_url}"))
        if problem:
            print(f"error: promoted to {pr_url} (Status=QA), but the claim comment was not "
                  f"released ({problem}); run promote again", file=sys.stderr)
            return 1
    card["lease_expires"] = None
    write_json(checkout / FACTORY_DIR / "card.json", card)
    print(f"Promoted {repo}#{number}: {pr_url} (Status=QA"
          + (f", Iterations={target}" if target is not None else "") + ")")
    return 0


def cmd_release(ctx: Ctx) -> int:
    args, gh = ctx.args, ctx.gh
    checkout = find_checkout(args.workdir)
    card = load_card(checkout)
    ctx.use_card(card)
    repo, number = card["repo"], card["number"]
    agent, machine = str(card.get("agent") or ""), str(card.get("machine") or "")
    if not card.get("lease_expires"):
        where = f" ({card['pr_url']})" if card.get("pr_url") else ""
        raise Refused(f"{repo}#{number} was promoted{where} and its claim released: it is in the "
                      "line now, not yours to give back. Pull it again if it comes back to Ready")
    reason = args.reason or "gave the card back"
    other = holder_conflict(ctx, card, agent, machine)
    current = ctx.board.find(repo, number)
    ours = current["status"] == "Building" and current["agent"] in ("", agent)
    touch_board = not other and ours
    if gh.dry_run:
        print(f"[dry-run] would {'set Status=Ready, clear Agent' if touch_board else 'leave the board alone'}"
              f" and mark the claim released ({reason!r})")
        return 0
    problems = []
    if other:
        print(f"note: `{other['agent']}` holds the card now; leaving its board fields alone")
    elif not ours:
        print(f"note: the card is in {current['status']} (Agent {current['agent'] or 'empty'}), "
              "not Building for you; leaving its board fields alone")
    else:
        problems += [ctx.board.edit(current["item_id"], "Status", option="Ready"),
                     ctx.board.edit(current["item_id"], "Agent", clear=True)]
    if card.get("claim_comment_id"):
        problems.append(edit_comment(gh, repo, int(card["claim_comment_id"]),
                                     released_body(agent, reason)))
    problems = [p for p in problems if p]
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("Not released: the local card is kept so you can run `release` again.", file=sys.stderr)
        return 1
    for name in ("card.json", "last_check.json"):
        try:
            (checkout / FACTORY_DIR / name).unlink()
        except OSError:
            pass
    print(f"Released {repo}#{number}. The local branch {card.get('branch')} is kept.")
    return 0


def cmd_status(ctx: Ctx) -> int:
    checkout = find_checkout(ctx.args.workdir)
    card = load_card(checkout)
    print(f"Card:     {card['repo']}#{card['number']}  {card.get('title', '')}")
    print(f"Checkout: {checkout} on {card.get('branch')}")
    print(f"Agent:    {card.get('agent')} on {card.get('machine')}")
    print(f"Board:    {card.get('project')}")
    expires = parse_iso(card.get("lease_expires"))
    if expires is None:
        print("Lease:    released")
    else:
        left = (expires - ctx.now()).total_seconds()
        print(f"Lease:    {'expired' if left <= 0 else f'{int(left // 3600)}h {int(left % 3600 // 60)}m left'}"
              f" (until {iso(expires)})")
    check = read_json(checkout / FACTORY_DIR / "last_check.json")
    if not check:
        print("Check:    none yet")
    else:
        head = git(ctx.runner, checkout, "rev-parse", "HEAD")
        current = (head.stdout or "").strip() == check.get("head")
        print(f"Check:    {'pass' if check.get('passed') else 'fail'} (exit {check.get('exit_code')}, "
              f"{check.get('duration_s')}s) at {str(check.get('head'))[:12]}"
              f"{'' if current else ' -- HEAD has moved, check again'}")
    if card.get("pr_url"):
        print(f"PR:       {card['pr_url']}")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull a Ready card from the factory board, build and check it locally, "
                    "promote it back. If DNS for api.github.com fails, export GODEBUG=netdns=go.")
    parser.add_argument("--project", help=f"OWNER/NUMBER or project URL (default $FACTORY_PROJECT or {DEFAULT_PROJECT})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="Ready cards across the linked repositories")
    p.add_argument("--platform")
    p.add_argument("--repo")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("pull", help="claim one Ready card and prepare a local branch")
    p.add_argument("--card", metavar="REPO#N")
    p.add_argument("--next", action="store_true",
                   help="the first Ready card that can be claimed (then Building cards whose lease expired)")
    p.add_argument("--agent", help="agent id credited for the work (default $FACTORY_AGENT)")
    p.add_argument("--machine", help="machine label (default $FACTORY_MACHINE or the host name)")
    p.add_argument("--workdir", help="checkout directory (default ~/.rapp-factory/<repo>)")
    p.add_argument("--lease-hours", type=float, default=DEFAULT_LEASE_HOURS)
    p.add_argument("--platform")
    p.add_argument("--repo")
    p.add_argument("--dry-run", action="store_true", help="show GitHub writes instead of making them")

    p = sub.add_parser("check", help="run the card's Acceptance command after confirmation")
    p.add_argument("--workdir")
    p.add_argument("--yes", action="store_true", help="run without the interactive prompt")
    p.add_argument("--timeout", type=float, default=CHECK_TIMEOUT)

    p = sub.add_parser("promote", help="push, open or update the PR, Status=QA, release the lease")
    p.add_argument("--workdir")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("release", help="give the card back to Ready")
    p.add_argument("--workdir")
    p.add_argument("--reason")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("status", help="the current card, lease and last check")
    p.add_argument("--workdir")
    return parser


COMMANDS = {"list": cmd_list, "pull": cmd_pull, "check": cmd_check, "promote": cmd_promote,
            "release": cmd_release, "status": cmd_status}


def main(argv: Optional[List[str]] = None, runner: Optional[Runner] = None,
         now: Optional[Callable[[], datetime]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = Ctx(args, runner or default_runner, now or _now)
        return COMMANDS[args.command](ctx)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except (GhError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
