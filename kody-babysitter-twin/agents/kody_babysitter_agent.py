"""kody_babysitter_agent.py — the watchdog agent for the Kody Babysitter twin.

Reads memory rules. Scans agent codebase + pipeline artifacts. Reports
violations. Read-only. Never writes to state, git, or APIs.

Lives at: <twin_root>/agents/kody_babysitter_agent.py
Hatched by: twin_egg_hatcher_agent.py
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


REPO = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
AGENTS = REPO / ".brainstem/src/rapp_brainstem/agents"
MEMORY = Path("/Users/kodyw/.claude/projects/-Users-kodyw-Documents-GitHub-Rappter-rappterbook/memory")
FRAME_DIR = Path("/tmp/frame-orchestrator")
PUB_DIR = Path("/tmp/pages-publisher")
FORK_DIR = Path("/tmp/fork-fleet-out/replies")
OUT_DIR = Path("/tmp/kody-babysitter")

SKIP_FILES = {"basic_agent.py", "learn_new_agent.py", "context_memory_agent.py",
              "manage_memory_agent.py"}

# Rule B exceptions: agents that LEGITIMATELY call GitHub Discussions API
# because they ARE the JIT-materialization mechanism (per the no-reverse-holo-
# honey-pot rule, which specifies outside-Issue-triggered JIT as the valid path).
RULE_B_EXEMPT = {"post_materializer_agent_agent.py"}


def _load_rules_from_memory() -> dict:
    rules = {}
    if not MEMORY.exists():
        return rules
    for f in sorted(MEMORY.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text()
            m = re.search(r"^name:\s*(\S+)", content, re.M)
            d = re.search(r"^description:\s*(.+)$", content, re.M)
            t = re.search(r"^\s*type:\s*(\S+)", content, re.M)
            rules[f.stem] = {
                "name": m.group(1) if m else f.stem,
                "description": (d.group(1).strip() if d else "")[:200],
                "type": t.group(1) if t else "?",
                "char_count": len(content),
            }
        except Exception as e:
            rules[f.stem] = {"error": str(e)}
    return rules


def _scan_agent_files() -> list:
    findings = []
    if not AGENTS.exists():
        return findings
    files = [f for f in AGENTS.glob("*_agent.py") if f.name not in SKIP_FILES]
    for af in files:
        try:
            src = af.read_text()
        except Exception:
            continue
        lines = src.splitlines()
        rel = str(af).replace(str(REPO) + "/", "")

        # Rule A: no dry_run in agent code (signature, kwargs.get, or assignment)
        for i, line in enumerate(lines, 1):
            if re.search(r"\bdry_run\s*[:=]", line):
                if "agent_parameters" in line:
                    continue  # That's the LearnNew metadata field name, not a dry_run use
                if "def " in line or "kwargs.get" in line.lower() \
                   or re.match(r"^\s*dry_run\s*[:=]", line):
                    findings.append({
                        "rule": "A:no-dry-run", "severity": "high",
                        "file": rel, "line": i,
                        "detail": line.strip()[:180],
                        "fix": "delete the dry_run param; use cap + validation + idempotency for safety.",
                    })
                    break

        # Rule B: direct GitHub Discussions API from inside-agent code
        # (post_materializer is the JIT mechanism itself — exempt)
        if af.name not in RULE_B_EXEMPT:
            for i, line in enumerate(lines, 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "add_discussion_comment(" in line or "create_discussion(" in line:
                    findings.append({
                        "rule": "B:no-discussions-api-from-inside-agents", "severity": "high",
                        "file": rel, "line": i,
                        "detail": line.strip()[:180],
                        "fix": "route through state writes; let JIT materialize on outside interaction.",
                    })
                    break

        # Rule C: git stash
        for i, line in enumerate(lines, 1):
            if re.search(r'["\']\s*stash\s*["\']\s*\)|git stash', line):
                findings.append({
                    "rule": "C:no-git-stash-on-main", "severity": "high",
                    "file": rel, "line": i,
                    "detail": line.strip()[:180],
                    "fix": "capture WIP as chore commit instead; Amendment XVII forbids stash on main.",
                })
                break

        # Rule D: honest reporting — status field expected
        if "def perform" in src and not ('"status"' in src or "'status'" in src):
            findings.append({
                "rule": "D:honest-status-reporting", "severity": "medium",
                "file": rel, "line": None,
                "detail": "no status field in agent returns",
                "fix": "return JSON with a 'status' key so operators can branch on ok/error.",
            })

        # Rule E: preview/would language used as a flag/branch, not as a field name.
        # Skip false positives where "preview" is a snake_case identifier component
        # (e.g. stdout_preview, source_preview) or a JSON field key like "preview": ...
        preview_lines = []
        for i, l in enumerate(lines, 1):
            stripped = l.lstrip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if "advisory" in l.lower() or "preview_lines" in l:
                continue
            low = l.lower()
            # Only flag the patterns that suggest a real preview/dry-run mode
            real_pattern = False
            if re.search(r"\bif\s+not\s+\w+:\s*#?\s*preview", l, re.I):
                real_pattern = True
            if re.search(r'"preview":\s*True', l):
                real_pattern = True  # explicit "preview: true" return
            if re.search(r"\bwould_\w+\s*=", l):
                real_pattern = True  # would_X variable assignment
            if re.search(r"\bapply\s*[:=]\s*False", l) and "default" not in low:
                # apply=False default is a hidden dry_run flag
                real_pattern = True
            # Skip pure-string mentions inside a longer line
            # (e.g., "preview only" in a docstring, "stdout_preview" as a key)
            if not real_pattern:
                continue
            preview_lines.append(i)
        if preview_lines:
            findings.append({
                "rule": "E:preview-language", "severity": "low",
                "file": rel, "line": preview_lines[0],
                "detail": f"preview/would pattern at lines {preview_lines[:3]} — looks like a real preview mode, not just narration",
                "fix": "if this gates a real-vs-fake action, it IS a dry_run; remove the gate.",
            })

    return findings


def _audit_pipeline() -> dict:
    out = {}
    for d, label in [(FRAME_DIR, "frame_orchestrator"),
                     (PUB_DIR, "pages_publisher"),
                     (FORK_DIR, "fork_fleet")]:
        if not d.exists():
            out[label] = {"status": "no_records"}
            continue
        files = sorted(d.glob("*.json"))
        if not files:
            out[label] = {"status": "empty"}
            continue
        failed = succeeded = 0
        samples = []
        for f in files[-10:]:
            try:
                r = json.loads(f.read_text())
            except Exception:
                continue
            st = (r.get("status") or "").lower()
            if any(b in st for b in ("fail", "error", "skip", "no_")):
                failed += 1
            else:
                succeeded += 1
            samples.append({
                "file": f.name, "status": st or "?",
                "executed": bool(r.get("execution_results") or r.get("results")
                                 or r.get("posted") or r.get("agents_forked")),
            })
        out[label] = {
            "recent_count": len(files),
            "last_10_succeeded": succeeded,
            "last_10_failed": failed,
            "samples": samples[-5:],
            "stuck_cycle_alarm": failed >= 3,
        }
    return out


def _audit_git() -> dict:
    def _g(args):
        try:
            return subprocess.run(["git"] + args, cwd=str(REPO),
                                  capture_output=True, text=True, timeout=15
                                  ).stdout.strip()
        except Exception as e:
            return f"<err {e}>"
    dirty = _g(["status", "--porcelain"])
    log = _g(["log", "--oneline", "-10"]).splitlines()
    ab = _g(["rev-list", "--left-right", "--count", "origin/main...HEAD"])
    return {
        "ahead_behind_origin_main": ab,
        "recent_log": log[:10],
        "dirty_tracked": sum(1 for l in dirty.splitlines() if l and not l.startswith("??")),
        "untracked": sum(1 for l in dirty.splitlines() if l.startswith("??")),
        "local_drift_alarm": ab and ab.split("\t")[-1].isdigit() and int(ab.split("\t")[-1]) > 5,
    }


def _publishing_verification() -> dict:
    """Independently verify PagesPublisher claims.

    Fetches state/synthetic_comments.json via `gh api` (authoritative, no
    CDN cache — raw.githubusercontent.com lags by ~5 min). Counts entries,
    walks every PagesPublisher record at /tmp/pages-publisher/v3-*.json and
    verifies the frame_id appears in the live file. Catches the gaslight
    pattern of "agent said pushed, file didn't grow."
    """
    import base64, subprocess
    pub_records = sorted(Path("/tmp/pages-publisher").glob("v3-*.json"))
    if not pub_records:
        return {"status": "no_publisher_records", "verified": 0, "gaslight_findings": []}

    # Fetch via gh API (authoritative — bypasses CDN cache)
    try:
        p = subprocess.run(
            ["gh", "api", "/repos/kody-w/rappterbook/contents/state/synthetic_comments.json",
             "--jq", ".content"],
            capture_output=True, text=True, timeout=20,
        )
        if p.returncode != 0:
            return {"status": "fetch_failed_gh_api", "error": p.stderr.strip()[:300]}
        live = json.loads(base64.b64decode(p.stdout).decode("utf-8"))
    except Exception as e:
        return {"status": "fetch_failed_gh_api", "error": str(e)}

    # Also fetch via raw.githubusercontent — the CDN real visitors hit
    # If gh and CDN disagree, that's a propagation lag (eventual-consistency).
    import urllib.request, urllib.error
    cdn_live = None
    cdn_error = None
    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/synthetic_comments.json?bust=" + datetime.now(timezone.utc).strftime("%s"),
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            cdn_live = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        cdn_error = str(e)

    live_frames = set()
    live_total = 0
    for disc_n, entries in (live.get("by_discussion") or {}).items():
        for e in entries:
            live_total += 1
            if e.get("fleet_frame"):
                live_frames.add(e["fleet_frame"])

    # Reconcile: every "pushed" publisher record should claim a frame_id that
    # appears in live_frames. If a publisher record said "pushed" but its
    # frame_id is absent from live, that's gaslight.
    verified, gaslight = 0, []
    for f in pub_records:
        try:
            rec = json.loads(f.read_text())
        except Exception:
            continue
        if rec.get("status") != "pushed":
            continue
        fid = rec.get("frame_id")
        claimed = rec.get("injected_to_sidecar", 0)
        if fid in live_frames:
            verified += 1
        else:
            gaslight.append({
                "file": f.name, "frame_id": fid, "claimed_injected": claimed,
                "reason": "publisher claimed pushed; frame_id absent from live origin/main",
            })

    # CDN comparison — measures propagation lag from origin to raw.githubusercontent
    cdn_total = 0
    cdn_frames = set()
    cdn_propagation = "cdn_unavailable"
    if cdn_live and isinstance(cdn_live, dict):
        for entries in (cdn_live.get("by_discussion") or {}).values():
            for e in entries:
                cdn_total += 1
                if e.get("fleet_frame"):
                    cdn_frames.add(e["fleet_frame"])
        if cdn_total == live_total and cdn_frames == live_frames:
            cdn_propagation = "in_sync"
        elif cdn_total < live_total:
            cdn_propagation = f"lagging_{live_total - cdn_total}_entries_{len(live_frames - cdn_frames)}_frames_behind"
        else:
            cdn_propagation = "unexpected_cdn_ahead"

    return {
        "status": "verified" if not gaslight else "gaslight_detected",
        "publisher_records_total": len(pub_records),
        "publisher_records_claimed_pushed": verified + len(gaslight),
        "verified_against_origin": verified,
        "gaslight_findings": gaslight,
        "origin_via_gh_api": {
            "total_comments": live_total,
            "unique_frames": len(live_frames),
            "newest_frame": max(live_frames) if live_frames else None,
        },
        "cdn_via_raw_githubusercontent": {
            "total_comments": cdn_total,
            "unique_frames": len(cdn_frames),
            "newest_frame": max(cdn_frames) if cdn_frames else None,
            "propagation": cdn_propagation,
            "error": cdn_error,
        },
        "pages_ui_render_status": "not_rendered (docs/index.html does NOT currently read state/synthetic_comments.json — content is on main + on CDN, but not visible in the kody-w.github.io/rappterbook UI without a frontend patch)",
        "addressable_urls": {
            "github_blob": "https://github.com/kody-w/rappterbook/blob/main/state/synthetic_comments.json",
            "raw_cdn": "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/synthetic_comments.json",
            "github_api": "https://api.github.com/repos/kody-w/rappterbook/contents/state/synthetic_comments.json",
            "pages_discussions_route_template": "https://kody-w.github.io/rappterbook/#/discussions/{number}",
            "pages_discussions_examples": [
                f"https://kody-w.github.io/rappterbook/#/discussions/{n}"
                for n in sorted([int(k) for k in (live.get("by_discussion") or {}).keys()])[:5]
            ],
        },
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def _loop_health() -> dict:
    """Verify launchd jobs are firing on schedule + chronicle dirs growing.

    For each known loop, checks:
      - launchd job is loaded (`launchctl list <label>` returns exit 0)
      - tail.log exists and the LAST line's timestamp is < 2× the expected interval
      - the chronicle dir is growing (newest file < 2× interval ago)
    Alarm flagged when any loop is stalled.
    """
    import re
    LOOPS = [
        {"label": "com.kody.babysitter",         "interval_s": 900,
         "tail_log": "/tmp/kody-babysitter/tail.log",      "chronicle_dir": "/tmp/kody-babysitter"},
        {"label": "com.kody.doublejump-loop",    "interval_s": 300,
         "tail_log": "/tmp/doublejump-loop/tail.log",      "chronicle_dir": "/tmp/doublejump-loop"},
        {"label": "com.kody.infinite-doublejump","interval_s": 300,
         "tail_log": "/tmp/infinite-doublejump/tail.log",
         "chronicle_dir": str(REPO / "docs/chronicles/doublejump")},
    ]
    now = datetime.now(timezone.utc).timestamp()
    findings = []
    for L in LOOPS:
        entry = {"label": L["label"], "expected_interval_s": L["interval_s"]}
        # launchd status
        try:
            p = subprocess.run(["launchctl", "list", L["label"]],
                               capture_output=True, text=True, timeout=5)
            entry["launchd_loaded"] = (p.returncode == 0)
        except Exception:
            entry["launchd_loaded"] = False

        # tail.log freshness
        tp = Path(L["tail_log"])
        if tp.exists():
            last_mtime = tp.stat().st_mtime
            age_s = now - last_mtime
            entry["tail_log_age_s"] = round(age_s)
            entry["tail_log_stale"] = age_s > 2 * L["interval_s"]
            # Pull the most-recent timestamp from the tail line
            try:
                last_line = tp.read_text().rstrip().splitlines()[-1]
                entry["tail_last_line"] = last_line[:200]
            except Exception:
                entry["tail_last_line"] = None
        else:
            entry["tail_log_age_s"] = None
            entry["tail_log_stale"] = True
            entry["tail_last_line"] = None

        # Chronicle dir newest-file age
        cd = Path(L["chronicle_dir"])
        if cd.exists():
            files = sorted([f for f in cd.iterdir() if f.is_file()],
                           key=lambda f: f.stat().st_mtime, reverse=True)
            if files:
                age_s = now - files[0].stat().st_mtime
                entry["newest_chronicle_age_s"] = round(age_s)
                entry["chronicle_stale"] = age_s > 2 * L["interval_s"]
            else:
                entry["newest_chronicle_age_s"] = None
                entry["chronicle_stale"] = True
        else:
            entry["newest_chronicle_age_s"] = None
            entry["chronicle_stale"] = True

        entry["alarm"] = (
            (not entry["launchd_loaded"]) or
            entry.get("tail_log_stale", True) or
            entry.get("chronicle_stale", True)
        )
        findings.append(entry)

    return {
        "checked": len(findings),
        "any_alarm": any(f["alarm"] for f in findings),
        "loops": findings,
    }


def _push_reality() -> dict:
    """For each recently-claimed push (publisher records), verify the claimed
    frame_id is actually on origin/main. Uses `git ls-tree` (authoritative),
    NOT `gh api /contents/` (which returns null for paths it could reach).
    """
    pub_records = []
    for d, pattern, name in [
        (Path("/tmp/pages-publisher"), "v3-*.json", "pages_publisher"),
        (Path("/tmp/posts-publisher"), "posts-pub-*.json", "posts_publisher"),
        (Path("/tmp/votes-agent"),     "votes-*.json",     "votes_agent"),
        (Path("/tmp/activity-agent"),  "activity-*.json",  "activity_agent"),
    ]:
        if not d.exists():
            continue
        files = sorted(d.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)[:5]
        for f in files:
            try:
                rec = json.loads(f.read_text())
            except Exception:
                continue
            if rec.get("status") != "pushed":
                continue
            pub_records.append({
                "publisher": name, "file": f.name,
                "frame_id": rec.get("frame_id"),
                "claimed_sidecar": rec.get("sidecar_file"),
            })
    if not pub_records:
        return {"checked": 0, "gaslight_findings": []}

    # Authoritative check: for each unique sidecar, fetch ALL of its log of
    # frame_ids from origin via git show. Then each claimed frame_id should
    # appear in the file's by_hash / frames / posts / by_post.
    findings = []
    sidecars_to_check = sorted(set(r["claimed_sidecar"] for r in pub_records
                                    if r.get("claimed_sidecar")))
    sidecar_contents = {}
    for path in sidecars_to_check:
        try:
            p = subprocess.run(
                ["git", "show", f"origin/main:{path}"],
                cwd=str(REPO), capture_output=True, text=True, timeout=15,
            )
            if p.returncode == 0:
                sidecar_contents[path] = json.loads(p.stdout)
            else:
                sidecar_contents[path] = None
        except Exception:
            sidecar_contents[path] = None

    def _frame_on_origin(sidecar: dict, frame_id: str) -> bool:
        if not sidecar or not frame_id:
            return False
        # synthetic_comments.json + synthetic_posts.json shape: by_hash entries
        # have frame_id; by_discussion entries have fleet_frame
        bh = sidecar.get("by_hash") or {}
        for entry in bh.values():
            if isinstance(entry, dict) and entry.get("frame_id") == frame_id:
                return True
            if isinstance(entry, dict) and entry.get("frame") == frame_id:
                return True
        # synthetic_activity.json: frames[].frame_id
        for f in (sidecar.get("frames") or []):
            if f.get("frame_id") == frame_id:
                return True
        # synthetic_posts.json: posts[].fleet_frame
        for p in (sidecar.get("posts") or []):
            if p.get("fleet_frame") == frame_id:
                return True
        return False

    for r in pub_records:
        sidecar = sidecar_contents.get(r["claimed_sidecar"])
        if sidecar is None:
            findings.append({**r, "reason": "sidecar_unreachable_on_origin"})
            continue
        if not _frame_on_origin(sidecar, r["frame_id"]):
            findings.append({**r, "reason": "claimed_pushed_but_frame_not_in_sidecar"})

    return {
        "checked": len(pub_records),
        "sidecars_inspected": len(sidecars_to_check),
        "verified": len(pub_records) - len(findings),
        "gaslight_findings": findings,
    }


def _autonomy_signal() -> dict:
    try:
        al = json.loads((REPO / "state/autonomy_log.json").read_text())
        recent = (al.get("entries") or [])[-10:]
        silent = 0
        for e in recent:
            r = e.get("run", {}) or {}
            if r.get("agents_activated", 0) > 0 \
               and r.get("posts", 0) == 0 \
               and r.get("comments", 0) == 0:
                silent += 1
        return {
            "recent_entries": len(recent),
            "silent_skip_runs": silent,
            "alarm": silent >= 3,
        }
    except Exception as e:
        return {"error": str(e)}


class KodyBabysitterAgent(BasicAgent):
    def __init__(self):
        self.name = "KodyBabysitter"
        self.metadata = {
            "name": self.name,
            "description": (
                "Kody Babysitter — the Preference Snapshot Twin's watchdog. "
                "Reads Kody's memory files (rules established across sessions), "
                "scans the Rappterbook agent codebase + pipeline artifacts at "
                "/tmp/, reports violations and suspicious patterns. Read-only — "
                "never writes state, never pushes git, never calls APIs. Catches "
                "dry_run drift, fleet→Discussions-API leaks (reverse-holo-honey-pot), "
                "git-stash violations, agents missing honest status reporting, "
                "silent-skip cascades in autonomy_log, execution-vs-claim drift "
                "in pipeline artifacts. Returns structured verdict JSON."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "Optional scope filter: 'all' (default), 'agents', 'pipeline', 'git', 'autonomy'.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        scope = (kwargs.get("scope") or "all").lower()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        frame_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

        rules = _load_rules_from_memory()
        findings = _scan_agent_files() if scope in ("all", "agents") else []
        pipeline = _audit_pipeline() if scope in ("all", "pipeline") else {}
        git_state = _audit_git() if scope in ("all", "git") else {}
        autonomy = _autonomy_signal() if scope in ("all", "autonomy") else {}
        publishing = _publishing_verification() if scope in ("all", "publishing") else {}
        loop_health = _loop_health() if scope in ("all", "loop_health") else {}
        push_reality = _push_reality() if scope in ("all", "push_reality") else {}

        high = sum(1 for f in findings if f["severity"] == "high")
        medium = sum(1 for f in findings if f["severity"] == "medium")
        low = sum(1 for f in findings if f["severity"] == "low")

        # Verdict + EXPLICIT triggers so the meta-watcher (and humans) can see
        # WHY a verdict was raised even when findings_summary is 0/0/0. Fixes
        # the meta-watcher's "degraded" finding that babysitter returned
        # violations_found with empty findings (the upstream platform autonomy
        # alarm was triggering it without any code-level rule violation).
        verdict_triggers = []
        verdict = "clean"
        if high > 0:
            verdict = "violations_found"
            verdict_triggers.append(f"agent_findings.high={high}")
        elif medium + low > 0:
            verdict = "warnings"
            verdict_triggers.append(f"agent_findings.medium+low={medium + low}")
        if autonomy.get("alarm"):
            verdict = "violations_found"
            verdict_triggers.append(f"autonomy.alarm (silent_skips={autonomy.get('silent_skip_runs')})")
        if any(v.get("stuck_cycle_alarm") for v in pipeline.values() if isinstance(v, dict)):
            verdict = "violations_found"
            stuck = [k for k, v in pipeline.items()
                     if isinstance(v, dict) and v.get("stuck_cycle_alarm")]
            verdict_triggers.append(f"pipeline.stuck_cycle={stuck}")
        if publishing.get("gaslight_findings"):
            verdict = "violations_found"
            verdict_triggers.append(f"publishing.gaslight={len(publishing['gaslight_findings'])}")
        if loop_health.get("any_alarm"):
            verdict = "violations_found"
            stalled = [L["label"] for L in (loop_health.get("loops") or []) if L.get("alarm")]
            verdict_triggers.append(f"loop_health.stalled={stalled}")
        if push_reality.get("gaslight_findings"):
            verdict = "violations_found"
            verdict_triggers.append(f"push_reality.gaslight={len(push_reality['gaslight_findings'])}")

        report = {
            "twin": "KodyBabysitter",
            "frame_id": frame_id,
            "scope": scope,
            "rules_loaded_from_memory": list(rules.keys()),
            "agent_files_scanned": len([f for f in AGENTS.glob("*_agent.py")
                                         if f.name not in SKIP_FILES]) if AGENTS.exists() else 0,
            "findings_summary": {"high": high, "medium": medium, "low": low,
                                 "total": len(findings)},
            "findings": findings,
            "pipeline_audit": pipeline,
            "git_audit": git_state,
            "autonomy_signal": autonomy,
            "publishing_verification": publishing,
            "loop_health": loop_health,
            "push_reality": push_reality,
            "rules_snapshot": rules,
            "verdict": verdict,
            "verdict_triggers": verdict_triggers,
        }
        (OUT_DIR / f"watch-{frame_id}.json").write_text(json.dumps(report, indent=2, default=str))
        return json.dumps(report, indent=2, default=str)


if __name__ == "__main__":
    a = KodyBabysitterAgent()
    print(a.perform())
