#!/usr/bin/env python3
from __future__ import annotations

"""medic_rapp_agent.py — Self-healing bug squad.

The medic reads state/overseer/latest.json each brainstem tick. For
every NEW finding (not yet in state/medic_log.jsonl), medic does ONE of:

  1. open a draft PR with a proposed fix (if LLM confidence ≥ 0.7,
     finding has severity ≥ medium, and the file touched is in the
     fix whitelist),
  2. open a labeled Issue with medic's analysis (the fallback path),
  3. skip (low-severity findings; already-addressed findings).

One action per tick max — medic is a methodical doctor, not a firehose.
Every action records to state/medic_log.jsonl so we never re-attempt
the same finding twice.

Hand-coded — the rapp egg metadata has `skip_agent_template:true`, so
rapp_install.py does NOT overwrite this file with the journal-only
template. The hand-coded path is necessary because the medic needs
structured LLM output, git/gh CLI access, and PR creation flow.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from state_io import load_json, save_json, now_iso  # noqa: E402

RAPP_SLUG = "medic"
_ROOT = _SCRIPTS.parent
_STATE = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
_RAPP_RECORD = _STATE / "rapps" / f"{RAPP_SLUG}.json"
_OVERSEER_LATEST = _STATE / "overseer" / "latest.json"
_MEDIC_LOG = _STATE / "medic_log.jsonl"

# Severity gates: anything below this is just acknowledged, never acted on.
_MIN_ACTIONABLE_SEVERITY = "medium"
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Confidence threshold below which medic opens an Issue instead of a PR.
_PR_CONFIDENCE_THRESHOLD = 0.7

# File path prefixes medic is allowed to TOUCH in a fix PR. Everything
# else routes to an Issue regardless of LLM confidence. State files are
# intentionally excluded — medic must never fix-by-editing-state, or it
# can loop on itself.
_PR_WHITELIST_PREFIXES = ("scripts/", "docs/", ".github/workflows/")

# Maximum actions per tick. Medic is methodical.
_MAX_ACTIONS_PER_TICK = 1


AGENT = {
    "name": "MedicRapp",
    "description": (
        "Self-healing bug squad. Reads overseer findings and ships PRs or "
        "Issues for each. Severity-gated (medium+), whitelist-gated for "
        "code edits, one action per tick. Draft PRs only — humans review."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "force_finding_id": {
                "type": "string",
                "description": "Skip the queue and operate on this specific finding id.",
            },
        },
    },
    "_meta": {
        "category": "chore",
        "priority": 45,
        "kind": "rapp",
        "slug": RAPP_SLUG,
        "consolidates": [],
    },
}


# ── Log helpers ─────────────────────────────────────────────────────

def _load_attempted_ids() -> set[str]:
    if not _MEDIC_LOG.exists():
        return set()
    seen: set[str] = set()
    with _MEDIC_LOG.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
                if rec.get("finding_id"):
                    seen.add(rec["finding_id"])
            except json.JSONDecodeError:
                continue
    return seen


def _append_log(entry: dict) -> None:
    _MEDIC_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry["ts"] = entry.get("ts") or now_iso()
    with _MEDIC_LOG.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


# ── Finding triage ──────────────────────────────────────────────────

def _pick_target(force_id: str | None) -> dict | None:
    snap = load_json(_OVERSEER_LATEST) or {}
    findings = snap.get("findings") or []
    if not findings:
        return None

    if force_id:
        for f in findings:
            if f.get("id") == force_id:
                return f
        return None

    attempted = _load_attempted_ids()
    candidates = [
        f for f in findings
        if f.get("id")
        and f["id"] not in attempted
        and _SEVERITY_RANK.get(f.get("severity", "low"), 0)
            >= _SEVERITY_RANK[_MIN_ACTIONABLE_SEVERITY]
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda f: _SEVERITY_RANK.get(f.get("severity", "low"), 0),
        reverse=True,
    )
    return candidates[0]


# ── LLM proposal ────────────────────────────────────────────────────

def _load_soul() -> str:
    egg = load_json(_RAPP_RECORD) or {}
    return ((egg.get("body") or {}).get("content") or {}).get("soul") or ""


_PROPOSAL_SCHEMA_HINT = """
Return STRICT JSON with this schema and nothing else:
{
  "action": "open_pr" | "open_issue" | "skip",
  "confidence": <float 0..1>,
  "reasoning": "<one sentence>",
  "title": "<PR or Issue title>",
  "body": "<PR or Issue body in markdown>",
  "file": "<single repo-relative file path to modify, only if action=open_pr>",
  "new_content": "<COMPLETE new contents of the file, only if action=open_pr>"
}

Rules:
- If action=open_pr: file must start with one of: scripts/, docs/, .github/workflows/.
  Do NOT touch state/*.
- If unsure how to fix safely: action=open_issue with diagnosis.
- If finding is "by design" / not actionable: action=skip.
"""


def _propose(finding: dict, soul: str) -> dict:
    from github_llm import generate

    user_prompt = (
        "You are the medic rapp inside Rappterbook's cloud brainstem.\n\n"
        f"OVERSEER FINDING:\n```json\n{json.dumps(finding, indent=2)}\n```\n\n"
        "Decide ONE action. Bias toward open_issue if the fix is non-obvious.\n"
        f"{_PROPOSAL_SCHEMA_HINT}"
    )
    raw = generate(
        system=soul,
        user=user_prompt,
        max_tokens=1400,
        temperature=0.2,
    )
    # Strip fences if the LLM wraps the JSON
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[len("json"):]
        raw = raw.rsplit("```", 1)[0]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        return {
            "action": "skip",
            "confidence": 0.0,
            "reasoning": f"LLM did not return valid JSON: {exc}",
            "title": "",
            "body": "",
        }


# ── Action paths ────────────────────────────────────────────────────

def _open_issue(title: str, body: str, finding: dict) -> dict:
    """Open a GitHub Issue tagged medic-proposal."""
    full_body = (
        f"_Opened by `medic` rapp during a cloud brainstem tick._\n\n"
        f"**Finding id:** `{finding.get('id')}`\n"
        f"**Severity:** {finding.get('severity', '?')}\n\n"
        "---\n\n"
        f"{body}"
    )
    result = subprocess.run(
        [
            "gh", "issue", "create",
            "--title", title,
            "--body", full_body,
            "--label", "medic-proposal",
        ],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip()}
    url = result.stdout.strip()
    return {"ok": True, "kind": "issue", "url": url}


def _open_pr(title: str, body: str, file_path: str, new_content: str, finding: dict) -> dict:
    """Clone the repo to /tmp, write the file, push a branch, open a DRAFT PR.

    Each call is one-shot — the clone is ephemeral. No long-running state.
    """
    import tempfile

    branch = f"medic/{finding.get('id', 'finding').replace('.', '-')}-{int(__import__('time').time())}"
    workdir = Path(tempfile.mkdtemp(prefix="medic-"))
    try:
        # Shallow clone for speed (we're only making a small edit)
        clone_url = "https://github.com/kody-w/rappterbook.git"
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            clone_url = f"https://x-access-token:{token}@github.com/kody-w/rappterbook.git"

        r = subprocess.run(
            ["git", "clone", "--depth=1", clone_url, str(workdir / "repo")],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return {"ok": False, "error": f"clone failed: {r.stderr[:300]}"}

        repo = workdir / "repo"
        target = repo / file_path
        if not target.parent.exists():
            return {"ok": False, "error": f"target dir missing: {file_path}"}

        target.write_text(new_content)

        subprocess.run(["git", "config", "user.name", "rappterbook-medic"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.email", "medic@rappterbook.dev"], cwd=str(repo), check=True)
        subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "add", file_path], cwd=str(repo), check=True)

        diff_out = subprocess.run(
            ["git", "diff", "--cached", "--stat"], cwd=str(repo), capture_output=True, text=True,
        )
        if not diff_out.stdout.strip():
            return {"ok": False, "error": "proposed change produces no diff"}

        subprocess.run(
            ["git", "commit", "-m", f"medic: {finding.get('id')} — {title}"],
            cwd=str(repo), check=True, capture_output=True,
        )
        push = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=str(repo), capture_output=True, text=True,
        )
        if push.returncode != 0:
            return {"ok": False, "error": f"push failed: {push.stderr[:300]}"}

        pr_body = (
            f"_Auto-proposed by the `medic` rapp during a cloud brainstem tick._\n\n"
            f"**Finding id:** `{finding.get('id')}`\n"
            f"**Severity:** {finding.get('severity', '?')}\n"
            f"**Confidence (LLM self-report):** see medic_log\n\n"
            "---\n\n"
            f"{body}\n\n"
            "---\n\n"
            "_Draft PR. Human review required before merge. Close if "
            "the proposed fix is wrong or out of scope._"
        )
        pr = subprocess.run(
            [
                "gh", "pr", "create",
                "--base", "main", "--head", branch,
                "--title", f"medic: {title}",
                "--body", pr_body,
                "--draft",
                "--label", "medic-proposal",
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        if pr.returncode != 0:
            return {"ok": False, "error": f"PR create failed: {pr.stderr[:300]}"}

        return {
            "ok": True,
            "kind": "pr",
            "url": pr.stdout.strip(),
            "branch": branch,
            "file": file_path,
        }
    finally:
        # Clean up the ephemeral clone
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


# ── Validation ──────────────────────────────────────────────────────

def _pr_path_allowed(file_path: str) -> bool:
    if not file_path:
        return False
    return any(file_path.startswith(p) for p in _PR_WHITELIST_PREFIXES)


# ── Main entry ──────────────────────────────────────────────────────

def run(context: dict, **kwargs) -> dict:
    soul = _load_soul()
    if not soul:
        return {"status": "error", "error": "medic soul missing — run rapp_install.py medic.rapp.egg"}

    if not _OVERSEER_LATEST.exists():
        return {"status": "ok", "detail": "no overseer snapshot yet"}

    force_id = kwargs.get("force_finding_id")
    finding = _pick_target(force_id)
    if not finding:
        return {"status": "ok", "detail": "no actionable findings"}

    # Always log the attempt — even if we skip, so we don't re-pick the same one
    log_entry: dict = {
        "finding_id": finding.get("id"),
        "severity": finding.get("severity"),
        "title": finding.get("title"),
    }

    try:
        proposal = _propose(finding, soul)
    except Exception as exc:
        log_entry.update({"status": "llm_error", "error": str(exc)})
        _append_log(log_entry)
        return {"status": "error", "error": f"LLM proposal failed: {exc}"}

    action = (proposal.get("action") or "skip").lower()
    confidence = float(proposal.get("confidence") or 0.0)
    title = (proposal.get("title") or finding.get("title") or "medic note")[:200]
    body = proposal.get("body") or proposal.get("reasoning") or "(no body)"
    file_path = proposal.get("file") or ""
    new_content = proposal.get("new_content") or ""
    log_entry.update({
        "action_planned": action,
        "confidence": confidence,
        "reasoning": proposal.get("reasoning", ""),
    })

    # Route: PR path requires whitelist + confidence
    if action == "open_pr" and confidence >= _PR_CONFIDENCE_THRESHOLD and _pr_path_allowed(file_path) and new_content:
        res = _open_pr(title, body, file_path, new_content, finding)
        log_entry.update({"action_taken": "pr", "result": res})
        _append_log(log_entry)
        return {"status": "ok", "action": "pr", "finding": finding.get("id"),
                "confidence": confidence, "result": res}

    if action in ("open_pr", "open_issue"):
        # PR didn't qualify (low confidence, bad path, or LLM picked Issue) →
        # fall through to Issue. Honest fallback.
        res = _open_issue(title, body, finding)
        log_entry.update({"action_taken": "issue", "result": res})
        _append_log(log_entry)
        return {"status": "ok", "action": "issue", "finding": finding.get("id"),
                "confidence": confidence, "result": res}

    # action == "skip"
    log_entry.update({"action_taken": "skip"})
    _append_log(log_entry)
    return {"status": "ok", "action": "skip", "finding": finding.get("id"),
            "reasoning": proposal.get("reasoning", "")}
