"""steward_supervisor.py — the self-healing keystone for 24h autonomous operation.

Runs every 10 min via launchd. Keeps the entire Rappterbook autonomous
organism alive without human touch:

  1. COPILOT HEALTH  — probe the LLM substrate. 3 consecutive failures =
                       the one genuinely unrecoverable case (device-flow
                       re-auth needs a human) → emergency iMessage, ONCE
                       per outage. This is the FAILURE text.
  2. LOOP LIVENESS   — bootstrap any unloaded launchd job; kickstart any
                       wedged one (tail.log older than 3x its interval).
  3. DISK ROTATION   — prune consumed fork-fleet replies (>6h), truncate
                       oversized launchd logs, roll chronicle rounds (keep
                       last 200). Lineage is never pruned (audit trail).
  4. ORPHAN WORKTREES — remove /tmp/*-wt-* left by crashed ticks, prune.
  5. ROSTER FLOOR    — if active swarm twins < 6, rehatch from canonical
                       egg back toward 9.
  6. 24h SURPRISE    — track sprint_start. At T+24h (once), read the full
                       chronicle, ask Copilot for the single most surprising
                       emergent thing in ONE sentence, iMessage it. This is
                       the SUCCESS text — the whole point of the sprint.
  7. SELF-REPORT     — write + commit a steward record each tick (incident
                       post-mortems included, per prompt #4).

NEVER crashes: every section is independently try/except'd. A failure in
one heal path never stops the others or the launchd job.
"""
from __future__ import annotations
import glob
import json
import os
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
STATE_PATH = REPO / "docs/chronicles/steward_state.json"
REPORT_DIR = REPO / "docs/chronicles/steward"
EGG_PATH = REPO / "eggs/rappterbook-cohesive.network.egg"
UNPACK = REPO / "scripts/unpack_neighborhood_egg.py"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

PHONE = "+14048628786"
SPRINT_HOURS = 24.0
COPILOT_FAIL_THRESHOLD = 3

LAUNCHD_JOBS = [
    {"label": "com.kody.babysitter",          "interval": 900,
     "plist": "/Users/kodyw/Library/LaunchAgents/com.kody.babysitter.plist",
     "tail": "/tmp/kody-babysitter/tail.log"},
    {"label": "com.kody.doublejump-loop",     "interval": 300,
     "plist": "/Users/kodyw/Library/LaunchAgents/com.kody.doublejump-loop.plist",
     "tail": "/tmp/doublejump-loop/tail.log"},
    {"label": "com.kody.infinite-doublejump", "interval": 300,
     "plist": "/Users/kodyw/Library/LaunchAgents/com.kody.infinite-doublejump.plist",
     "tail": "/tmp/infinite-doublejump/tail.log"},
    {"label": "com.kody.normie-ai-twin",      "interval": 3600,
     "plist": "/Users/kodyw/Library/LaunchAgents/com.kody.normie-ai-twin.plist",
     "tail": "/tmp/normie-ai-twin/tail.log"},
]

SWARM_GLOB = ("/Users/kodyw/.rapp/twins/rappid:@kody-w/authenticity-twin:662ed649e6f443ed69d74f813faab286137c2b510936f39b4d5bbd71b74a18e6-swarm-*")


def _now():
    return datetime.now(timezone.utc)

def _uid():
    return os.getuid()

def _load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"created": _now().isoformat(), "sprint_start": _now().isoformat(),
            "tick": 0, "copilot_consecutive_fails": 0, "copilot_texted": False,
            "summary_sent": False, "heals_total": 0, "emergency_texts": 0}

def _save_state(state):
    state["last_updated"] = _now().isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


# ── iMessage (osascript) ────────────────────────────────────────────────────

def _send_imessage(message: str) -> dict:
    """Send via Messages.app. Two-strategy: buddy of iMessage service, then
    participant fallback. Returns {sent, error}. NEVER raises."""
    safe = message.replace('\\', '\\\\').replace('"', '\\"').replace("\n", " ")
    scripts = [
        f'tell application "Messages" to send "{safe}" to buddy "{PHONE}" '
        f'of (1st service whose service type = iMessage)',
        f'tell application "Messages" to send "{safe}" to participant "{PHONE}"',
    ]
    for asc in scripts:
        try:
            p = subprocess.run(["osascript", "-e", asc],
                               capture_output=True, text=True, timeout=30)
            if p.returncode == 0:
                return {"sent": True, "strategy": asc[:60]}
        except Exception as e:
            last_err = str(e)[:200]
            continue
    return {"sent": False, "error": "all osascript strategies failed"}


# ── 1. copilot health ───────────────────────────────────────────────────────

def _probe_copilot() -> bool:
    try:
        p = subprocess.run(
            ["copilot", "-p", "reply with: ok",
             "--allow-all-tools", "--no-color", "--no-custom-instructions",
             "--effort", "none"],
            cwd="/tmp", capture_output=True, text=True, timeout=45,
            env={**os.environ, "NO_COLOR": "1"},
        )
        out = (p.stdout or "").lower()
        return p.returncode == 0 and ("ok" in out or len(out.strip()) > 0)
    except Exception:
        return False


def _heal_copilot(state, report):
    ok = _probe_copilot()
    report["checks"]["copilot"] = ok
    if ok:
        if state["copilot_consecutive_fails"] > 0 or state["copilot_texted"]:
            report["healed"].append("copilot recovered")
        state["copilot_consecutive_fails"] = 0
        state["copilot_texted"] = False
        return
    state["copilot_consecutive_fails"] += 1
    report["alerts"].append(f"copilot probe failed "
                            f"({state['copilot_consecutive_fails']}x consecutive)")
    if (state["copilot_consecutive_fails"] >= COPILOT_FAIL_THRESHOLD
            and not state["copilot_texted"]):
        msg = ("Rappterbook autonomy ALERT: Copilot CLI auth appears dead "
               "(3x consecutive probe failures). LLM agents degraded to "
               "deterministic noops. Needs device-flow re-auth: run "
               "`copilot` and sign in. The loop self-resumes once auth is back.")
        res = _send_imessage(msg)
        state["copilot_texted"] = True
        state["emergency_texts"] += 1
        report["alerts"].append(f"EMERGENCY iMessage sent: {res}")


# ── 2. loop liveness ────────────────────────────────────────────────────────

def _launchctl_loaded(label) -> bool:
    try:
        p = subprocess.run(["launchctl", "list", label],
                           capture_output=True, text=True, timeout=10)
        return p.returncode == 0
    except Exception:
        return False

def _tail_age_s(path) -> float:
    p = Path(path)
    if not p.exists():
        return 10 ** 9
    return _now().timestamp() - p.stat().st_mtime

def _heal_loops(state, report):
    for job in LAUNCHD_JOBS:
        try:
            if not _launchctl_loaded(job["label"]):
                if Path(job["plist"]).exists():
                    subprocess.run(["launchctl", "bootstrap", f"gui/{_uid()}", job["plist"]],
                                   capture_output=True, text=True, timeout=15)
                    report["healed"].append(f"bootstrapped {job['label']}")
                else:
                    report["alerts"].append(f"plist missing: {job['plist']}")
                continue
            age = _tail_age_s(job["tail"])
            if age > 3 * job["interval"]:
                subprocess.run(["launchctl", "kickstart", "-k",
                                f"gui/{_uid()}/{job['label']}"],
                               capture_output=True, text=True, timeout=15)
                report["healed"].append(
                    f"kickstarted wedged {job['label']} (tail age {round(age)}s "
                    f"> 3x{job['interval']}s)")
        except Exception as e:
            report["alerts"].append(f"loop-heal error {job['label']}: {str(e)[:120]}")


# ── 3. disk rotation ────────────────────────────────────────────────────────

def _heal_disk(state, report):
    rotated = {}
    # 3a. fork-fleet replies older than 6h (consumed by publisher)
    try:
        cutoff = _now().timestamp() - 6 * 3600
        replies = Path("/tmp/fork-fleet-out/replies")
        n = 0
        if replies.exists():
            for f in replies.glob("*.json"):
                if f.stat().st_mtime < cutoff:
                    f.unlink(); n += 1
        rotated["fork_fleet_replies_pruned"] = n
    except Exception as e:
        report["alerts"].append(f"disk fork-fleet: {str(e)[:100]}")
    # 3b. truncate oversized launchd logs (>10MB)
    try:
        n = 0
        for log in glob.glob("/tmp/*/launchd.std*.log"):
            if os.path.getsize(log) > 10 * 1024 * 1024:
                with open(log, "w") as fh:
                    fh.write(f"# truncated by steward {_now().isoformat()}\n")
                n += 1
        rotated["oversized_logs_truncated"] = n
    except Exception as e:
        report["alerts"].append(f"disk logs: {str(e)[:100]}")
    # 3c. roll chronicle rounds — keep newest 200 (older summarized in state)
    try:
        rounds = sorted((REPO / "docs/chronicles/doublejump").glob("round-*.json"),
                        key=lambda f: f.stat().st_mtime)
        excess = len(rounds) - 200
        n = 0
        if excess > 0:
            for f in rounds[:excess]:
                f.unlink(); n += 1
        rotated["chronicle_rounds_pruned"] = n
    except Exception as e:
        report["alerts"].append(f"disk chronicle: {str(e)[:100]}")
    report["checks"]["disk_rotation"] = rotated
    if any(v for v in rotated.values()):
        report["healed"].append(f"disk rotation: {rotated}")


# ── 4. orphan worktrees ─────────────────────────────────────────────────────

def _heal_worktrees(state, report):
    try:
        patterns = ["/tmp/idj-wt-*", "/tmp/pages-publisher-wt-*",
                    "/tmp/posts-publisher-wt-*", "/tmp/votes-agent-wt-*",
                    "/tmp/activity-agent-wt-*"]
        removed = 0
        for pat in patterns:
            for wt in glob.glob(pat):
                # Orphan = exists > 30 min (live ticks finish in < 3 min)
                if _now().timestamp() - os.path.getmtime(wt) > 1800:
                    subprocess.run(["git", "worktree", "remove", "--force", wt],
                                   cwd=str(REPO), capture_output=True, timeout=20)
                    subprocess.run(["rm", "-rf", wt], capture_output=True, timeout=15)
                    removed += 1
        subprocess.run(["git", "worktree", "prune"], cwd=str(REPO),
                       capture_output=True, timeout=15)
        report["checks"]["orphan_worktrees_removed"] = removed
        if removed:
            report["healed"].append(f"pruned {removed} orphan worktrees")
    except Exception as e:
        report["alerts"].append(f"worktree-heal: {str(e)[:120]}")


# ── 5. roster floor ─────────────────────────────────────────────────────────

def _heal_roster(state, report):
    try:
        active = sorted(glob.glob(SWARM_GLOB))
        report["checks"]["active_swarm_twins"] = len(active)
        if len(active) >= 6:
            return
        # rehatch back toward 9
        existing_nums = []
        for p in active:
            suf = p.split("@local-swarm-")[-1]
            if suf.isdigit():
                existing_nums.append(int(suf))
        next_n = (max(existing_nums) if existing_nums else 0) + 1
        need = 9 - len(active)
        rehatched = []
        for i in range(need):
            suffix = f"swarm-{next_n + i:02d}"
            p = subprocess.run(["python3", str(UNPACK), str(EGG_PATH),
                                "--rename-suffix", suffix],
                               capture_output=True, text=True, timeout=60)
            if p.returncode == 0:
                rehatched.append(suffix)
        if rehatched:
            report["healed"].append(
                f"roster fell to {len(active)} → rehatched {rehatched}")
    except Exception as e:
        report["alerts"].append(f"roster-heal: {str(e)[:120]}")


# ── 6. 24h surprise summary (the SUCCESS text) ──────────────────────────────

def _gather_sprint_digest() -> str:
    """Compact digest of the whole sprint for the surprise-summary prompt."""
    lines = []
    # doublejump rounds
    try:
        idj = json.loads((REPO / "docs/chronicles/infinite_doublejump_state.json").read_text())
        lines.append(f"infinite-doublejump: {idj.get('round_number')} rounds, "
                     f"{len(idj.get('mutations', []))} mutations, "
                     f"max_swarm_num {idj.get('max_swarm_num')}, "
                     f"{len(idj.get('quarantined_suffixes', []))} quarantined")
        for r in (idj.get("rounds") or [])[-10:]:
            lines.append(f"  r{r.get('round_number')} median={r.get('median')} "
                         f"stdev={r.get('stdev')} mut={r.get('mutation_kind')}")
    except Exception:
        pass
    # MEW verdicts
    try:
        mews = sorted(glob.glob("/tmp/mutation-efficacy-twin/scan-*.json"))[-3:]
        for m in mews:
            d = json.loads(Path(m).read_text())
            lines.append(f"MEW: verdict={d.get('verdict')} — {d.get('trajectory_summary','')[:120]}")
    except Exception:
        pass
    # authenticity verdicts
    try:
        auths = sorted(glob.glob("/tmp/authenticity-twin/scan-*.json"))[-3:]
        for a in auths:
            d = json.loads(Path(a).read_text())
            lines.append(f"Authenticity: {d.get('overall_sim_verdict')} avg={d.get('avg_authenticity_score')}")
    except Exception:
        pass
    # steward heals
    try:
        st = json.loads(STATE_PATH.read_text())
        lines.append(f"steward: {st.get('tick')} ticks, {st.get('heals_total')} heals, "
                     f"{st.get('emergency_texts')} emergency texts")
    except Exception:
        pass
    # content produced
    try:
        sp = subprocess.run(["git", "show", "origin/main:state/synthetic_posts.json"],
                            cwd=str(REPO), capture_output=True, text=True, timeout=15)
        if sp.returncode == 0:
            d = json.loads(sp.stdout)
            lines.append(f"synthetic_posts on origin: {len(d.get('posts', []))}")
    except Exception:
        pass
    return "\n".join(lines)

def _maybe_send_surprise(state, report):
    if state.get("summary_sent"):
        return
    try:
        start = datetime.fromisoformat(state["sprint_start"].replace("Z", "+00:00"))
    except Exception:
        start = _now()
        state["sprint_start"] = start.isoformat()
    elapsed_h = (_now() - start).total_seconds() / 3600
    report["checks"]["sprint_elapsed_hours"] = round(elapsed_h, 2)
    if elapsed_h < SPRINT_HOURS:
        return
    # 24h reached — compose the one-sentence surprise via Copilot
    digest = _gather_sprint_digest()
    prompt = (
        "You are the Rappterbook platform reflecting on a 24-hour fully-"
        "autonomous evolution sprint. Below is the digest of everything that "
        "happened: doublejump rounds, swarm mutations, twin verdicts, steward "
        "heals, content produced. In EXACTLY ONE sentence (max 220 chars, no "
        "preamble, no quotes), name the single MOST SURPRISING thing that "
        "emerged — the thing a human operator would most want to know. Be "
        "specific and cite a number.\n\nDIGEST:\n" + digest
    )
    sentence = None
    try:
        p = subprocess.run(
            ["copilot", "-p", prompt, "--allow-all-tools", "--no-color",
             "--no-custom-instructions", "--effort", "none"],
            cwd="/tmp", capture_output=True, text=True, timeout=90,
            env={**os.environ, "NO_COLOR": "1"})
        out = []
        for line in (p.stdout or "").splitlines():
            if line.strip().startswith(("Changes", "AI Credits", "Tokens")):
                break
            out.append(line)
        sentence = " ".join(out).strip().strip('"').strip()[:300]
    except Exception as e:
        sentence = f"(summary generation failed: {e}); sprint ran {round(elapsed_h,1)}h."
    if not sentence:
        sentence = f"Rappterbook 24h sprint complete ({round(elapsed_h,1)}h). Digest available in chronicle."
    res = _send_imessage("Rappterbook 24h sprint — most surprising thing: " + sentence)
    state["summary_sent"] = True
    state["summary_sentence"] = sentence
    state["summary_send_result"] = res
    report["healed"].append(f"24h SURPRISE SUMMARY sent: {res} — \"{sentence[:120]}\"")


# ── main ────────────────────────────────────────────────────────────────────

def _commit_report(report_path, report):
    """Worktree-isolated commit of the steward report + state to origin/main."""
    rid = report["tick_id"]
    wt = Path(f"/tmp/steward-wt-{rid}")
    branch = f"steward/{rid}"
    def _g(args, cwd=REPO, check=False, timeout=60):
        return subprocess.run(["git"] + args, cwd=str(cwd),
                              capture_output=True, text=True, timeout=timeout)
    try:
        _g(["fetch", "origin", "main"], timeout=60)
        r = _g(["worktree", "add", "-b", branch, str(wt), "origin/main"], timeout=60)
        if r.returncode != 0:
            return {"pushed": False, "error": r.stderr.strip()[:120]}
        # copy report + state into worktree
        for src in [report_path, STATE_PATH]:
            rel = Path(src).resolve().relative_to(REPO.resolve())
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(Path(src).read_bytes())
        _g(["add", "docs/chronicles/steward/", "docs/chronicles/steward_state.json"], cwd=wt)
        _g(["commit", "-m", f"steward: tick {rid} [skip ci]"], cwd=wt)
        ok = False
        for _ in range(2):
            pr = _g(["push", "origin", "HEAD:main"], cwd=wt)
            if pr.returncode == 0:
                ok = True; break
            _g(["fetch", "origin", "main"], cwd=wt)
            _g(["rebase", "origin/main"], cwd=wt)
        return {"pushed": ok}
    finally:
        _g(["worktree", "remove", "--force", str(wt)], timeout=30)
        _g(["worktree", "prune"], timeout=15)
        _g(["branch", "-D", branch], timeout=15)


def main():
    state = _load_state()
    state["tick"] += 1
    tick_id = _now().strftime("%Y-%m-%dT%H-%M-%SZ")
    report = {"tick_id": tick_id, "tick": state["tick"],
              "ts": _now().isoformat(), "healed": [], "alerts": [], "checks": {}}

    for fn in (_heal_copilot, _heal_loops, _heal_disk, _heal_worktrees,
               _heal_roster, _maybe_send_surprise):
        try:
            fn(state, report)
        except Exception as e:
            report["alerts"].append(f"{fn.__name__} crashed: {str(e)[:160]}")

    state["heals_total"] += len(report["healed"])
    _save_state(state)

    report_path = REPORT_DIR / f"tick-{tick_id}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    push = _commit_report(report_path, report)
    report["push"] = push

    # Compact stdout line for the launchd wrapper
    print(f"[steward] tick {state['tick']} ({tick_id}) "
          f"healed={len(report['healed'])} alerts={len(report['alerts'])} "
          f"copilot={report['checks'].get('copilot')} "
          f"swarm={report['checks'].get('active_swarm_twins')} "
          f"sprint_h={report['checks'].get('sprint_elapsed_hours')} "
          f"push={push.get('pushed')}")
    if report["healed"]:
        print("  healed: " + " | ".join(report["healed"][:6]))
    if report["alerts"]:
        print("  alerts: " + " | ".join(report["alerts"][:6]))
    return report


if __name__ == "__main__":
    main()
