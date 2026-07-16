"""infinite_doublejump_tick.py — one tick of the infinite-doublejump loop.

Architecture per session design:
  1. SAMPLE   → infra picks N posts (deterministic)
  2. JUDGE    → fire all active swarm AuthenticityTwins in parallel
  3. AGGREGATE → median, stdev, verdict mode, outlier detection
  4. AMPLIFY  → DoubleDownConductor takes divergence + last round's
                directives → next round's directives
  5. MUTATE   → ONE mutation per tick, picked by signal:
                  a. outlier exists → quarantine + rehatch from egg
                  b. soul drift signal → SoulCurator nudges a soul
                  c. nothing → noop, log
                gated by maturity (no mutations before round 6)
                gated by daily rate (max 4 mutations/24h)
  6. PERSIST  → round JSON to docs/chronicles/doublejump/
                state update to docs/chronicles/infinite_doublejump_state.json
                commit + push to main via worktree
"""
from __future__ import annotations
import glob
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make sure brainstem agents are importable for DoubleDownConductor
BRAINSTEM_AGENTS = Path("/Users/kodyw/.brainstem/src/rapp_brainstem/agents")
sys.path.insert(0, str(BRAINSTEM_AGENTS))

REPO = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
EGG_PATH = REPO / "eggs/rappterbook-cohesive.network.egg"
UNPACK_SCRIPT = REPO / "scripts/unpack_neighborhood_egg.py"
STATE_PATH = REPO / "docs/chronicles/infinite_doublejump_state.json"
CHRONICLE_DIR = REPO / "docs/chronicles/doublejump"
LINEAGE_QUARANTINE = REPO / "lineage/swarm-quarantine"
LINEAGE_SOULS = REPO / "lineage/soul-curation"

CHRONICLE_DIR.mkdir(parents=True, exist_ok=True)
LINEAGE_QUARANTINE.mkdir(parents=True, exist_ok=True)
LINEAGE_SOULS.mkdir(parents=True, exist_ok=True)

# legacy v2-era twin workspace paths (read-forever; dir names, not identity mints)
TWIN_GLOB = ("/Users/kodyw/.rapp/twins/rappid:@kody-w/authenticity-twin:662ed649e6f443ed69d74f813faab286137c2b510936f39b4d5bbd71b74a18e6-swarm-*")
TWIN_PATH_PREFIX = ("/Users/kodyw/.rapp/twins/rappid:@kody-w/authenticity-twin:662ed649e6f443ed69d74f813faab286137c2b510936f39b4d5bbd71b74a18e6-")

def _path_for_suffix(suffix: str) -> str:
    """suffix is e.g. 'swarm-04' — returns the full twin workspace path."""
    return TWIN_PATH_PREFIX + suffix

# Bumped from 3→6 per MutationEfficacyTwin's "thrashing" diagnosis: with only
# 3 posts per twin × 9 twins judging a small overlap set, the swarm median
# was pinned around 44 regardless of mutations — mutations had no lever on
# the content pool because the pool was too small. Doubling sample coverage
# gives the median actual purchase on platform content quality changes.
N_POSTS_PER_TWIN = 6
OUTLIER_SIGMA = 2.0
# NO MATURITY GATE. NO DAILY RATE CAP. No timer-based "wait, do it later"
# pretense (per the no-wait-modes-in-loops doctrine). Every tick that finds
# a real signal mutates. Safety = per-action caps inside each mutator +
# lineage backups + git-revertability, never artificial pauses.


# ── STATE ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _round_id() -> str:
    return _now().strftime("%Y-%m-%dT%H-%M-%SZ")

def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "created": _now().isoformat(),
        "round_number": 0,
        "rounds": [],  # rolling, last 50
        "mutations": [],
        "max_swarm_num": 9,  # currently swarm-01..09
        "quarantined_suffixes": [],
        "last_consensus": None,
        "last_directives": None,
    }

def _save_state(state: dict) -> None:
    state["last_updated"] = _now().isoformat()
    # Trim rolling history
    if len(state["rounds"]) > 50:
        state["rounds"] = state["rounds"][-50:]
    if len(state["mutations"]) > 200:
        state["mutations"] = state["mutations"][-200:]
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


# ── SAMPLE + JUDGE ─────────────────────────────────────────────────────────

def _list_active_swarm_twins() -> list:
    """Glob to discover every swarm authenticity twin workspace."""
    return sorted(glob.glob(TWIN_GLOB))

def _suffix_of(ws_path: str) -> str:
    """Extract the @local-{suffix} part."""
    return ws_path.split("@local-", 1)[1] if "@local-" in ws_path else "?"

def _fire_twin(ws: str, n_posts: int = N_POSTS_PER_TWIN) -> dict:
    suffix = _suffix_of(ws)
    agents_dir = os.path.join(ws, "agents")
    started = time.time()
    cmd = ["python3", "-c", (
        f"import sys\n"
        f"sys.path.insert(0, '{agents_dir}')\n"
        f"sys.path.insert(0, '{BRAINSTEM_AGENTS}')\n"
        f"from authenticity_twin_agent import AuthenticityTwinAgent\n"
        f"print(AuthenticityTwinAgent().perform(n_posts={n_posts}))\n"
    )]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if p.returncode != 0:
            return {"suffix": suffix, "status": "error",
                    "stderr_tail": p.stderr[-300:],
                    "elapsed": round(time.time() - started, 1)}
        rep = json.loads(p.stdout)
        rep["_suffix"] = suffix
        rep["_wall"] = round(time.time() - started, 1)
        return rep
    except Exception as e:
        return {"suffix": suffix, "status": "exc",
                "error": str(e)[:200],
                "elapsed": round(time.time() - started, 1)}


# ── AGGREGATE ──────────────────────────────────────────────────────────────

def _aggregate(twin_reports: list) -> dict:
    """Median + stdev + outlier detection across the swarm."""
    valid = [r for r in twin_reports
             if isinstance(r, dict) and isinstance(r.get("avg_authenticity_score"), (int, float))]
    if not valid:
        return {"twins_reported": 0, "valid": 0,
                "median": None, "stdev": None, "outliers": [],
                "verdict_mode": "unknown", "verdict_distribution": {}}
    avgs = [r["avg_authenticity_score"] for r in valid]
    med = statistics.median(avgs)
    sd  = statistics.stdev(avgs) if len(avgs) >= 2 else 0
    verdict_dist = {}
    for r in valid:
        v = r.get("overall_sim_verdict") or "?"
        verdict_dist[v] = verdict_dist.get(v, 0) + 1
    verdict_mode = max(verdict_dist, key=verdict_dist.get)
    # Outliers: > OUTLIER_SIGMA stdev from median (only meaningful when sd > 0)
    outliers = []
    if sd > 0:
        for r in valid:
            diff = abs(r["avg_authenticity_score"] - med)
            if diff > OUTLIER_SIGMA * sd:
                outliers.append({
                    "suffix": r["_suffix"], "score": r["avg_authenticity_score"],
                    "delta_from_median": round(diff, 2),
                })
    return {
        "twins_reported": len(twin_reports),
        "valid": len(valid),
        "median": med, "stdev": round(sd, 2),
        "verdict_mode": verdict_mode,
        "verdict_mode_share": verdict_dist[verdict_mode] / len(valid),
        "verdict_distribution": verdict_dist,
        "outliers": outliers,
    }


# ── AMPLIFY ────────────────────────────────────────────────────────────────

def _amplify(consensus: dict, prior_directives: list | None) -> dict:
    """DoubleDownConductor takes divergence + prior directives → next directives."""
    from doubledownconductor_agent import DoubleDownConductorAgent
    prior_summary = ""
    if prior_directives:
        prior_summary = (
            f"\nPRIOR ROUND'S DIRECTIVES (don't repeat verbatim):\n" +
            "\n".join(f"- {d.get('title','?')} [{d.get('lever','?')}]"
                       for d in prior_directives[:5])
        )
    topic = (
        f"Infinite doublejump loop tick. The 9-twin AuthenticityTwin swarm "
        f"judged the platform. Median sim score: {consensus.get('median')}. "
        f"Stdev across the swarm: {consensus.get('stdev')}. "
        f"Verdict mode: {consensus.get('verdict_mode')} "
        f"({round((consensus.get('verdict_mode_share') or 0) * 100)}% of {consensus.get('valid')} twins). "
        f"Outliers: {len(consensus.get('outliers') or [])}. "
        f"{prior_summary}\n\n"
        f"What should the platform do NEXT round to either (a) move the median score "
        f"toward 'organic' (≥70), (b) tighten swarm variance, or (c) eliminate "
        f"recurring tells? Be specific: name a capability or new agent + params."
    )
    raw = DoubleDownConductorAgent().perform(count=5, topic=topic)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "parse_error", "raw": raw[:500]}


# ── MUTATION: outlier quarantine + rehatch ─────────────────────────────────

def _quarantine_and_rehatch(outlier: dict, state: dict, round_id: str) -> dict:
    suffix = outlier["suffix"]
    twin_ws = _path_for_suffix(suffix)
    if not os.path.isdir(twin_ws):
        return {"kind": "quarantine_failed", "reason": "workspace_missing",
                "suffix": suffix}
    # Back up to lineage
    quarantine_dst = LINEAGE_QUARANTINE / f"{suffix}-quarantined-{round_id}"
    try:
        subprocess.run(["cp", "-R", twin_ws, str(quarantine_dst)],
                       check=True, timeout=30, capture_output=True)
    except Exception as e:
        return {"kind": "quarantine_failed", "reason": f"copy_err: {e}",
                "suffix": suffix}
    # Move workspace to ~/.rapp/twins/.quarantine/
    quarantine_runtime = Path("/Users/kodyw/.rapp/twins/.quarantine")
    quarantine_runtime.mkdir(exist_ok=True)
    try:
        subprocess.run(["mv", twin_ws, str(quarantine_runtime / f"{suffix}-{round_id}")],
                       check=True, timeout=15, capture_output=True)
    except Exception:
        pass  # ok if move fails; the runtime is still mutated
    # Rehatch with next suffix
    next_n = state["max_swarm_num"] + 1
    new_suffix = f"swarm-{next_n:02d}"
    try:
        p = subprocess.run(
            ["python3", str(UNPACK_SCRIPT), str(EGG_PATH),
             "--rename-suffix", new_suffix],
            capture_output=True, text=True, timeout=60,
        )
        if p.returncode != 0:
            return {"kind": "rehatch_failed", "reason": p.stderr[-200:],
                    "old_suffix": suffix, "intended_new": new_suffix}
    except Exception as e:
        return {"kind": "rehatch_failed", "reason": str(e),
                "old_suffix": suffix, "intended_new": new_suffix}
    # State updates
    state["max_swarm_num"] = next_n
    state["quarantined_suffixes"].append({
        "suffix": suffix, "round": round_id,
        "score": outlier["score"], "delta": outlier["delta_from_median"],
        "replaced_by": new_suffix,
    })
    return {
        "kind": "quarantine_and_rehatch",
        "old_suffix": suffix,
        "old_score": outlier["score"],
        "old_delta_from_median": outlier["delta_from_median"],
        "new_suffix": new_suffix,
        "quarantine_lineage_dir": str(quarantine_dst.relative_to(REPO)),
    }


# ── MUTATION: soft soul curation ───────────────────────────────────────────

def _soft_soul_curate(consensus: dict, twin_reports: list,
                       state: dict, round_id: str) -> dict:
    """Pick the KINDEST twin (highest avg score = furthest from harshness rubric).
    Use Copilot to write a 1-2 sentence amendment to its soul.md that sharpens
    skepticism toward the patterns the swarm is missing. Lineage-backup the old
    soul before writing.
    """
    valid = [r for r in twin_reports
             if isinstance(r, dict) and isinstance(r.get("avg_authenticity_score"), (int, float))]
    if not valid:
        return {"kind": "soul_curate_failed", "reason": "no_valid_reports"}
    # Kindest = highest avg score
    kindest = max(valid, key=lambda r: r["avg_authenticity_score"])
    suffix = kindest["_suffix"]
    twin_ws = _path_for_suffix(suffix)
    soul_path = Path(twin_ws) / "soul.md"
    if not soul_path.exists():
        return {"kind": "soul_curate_failed", "reason": "soul_missing",
                "suffix": suffix}
    current_soul = soul_path.read_text()
    # Build the Copilot prompt — one sharpening amendment
    median_diff = round(kindest["avg_authenticity_score"] - (consensus.get("median") or 0), 2)
    sample_tells = []
    for r in valid:
        for s in (r.get("per_post_scores") or [])[:1]:
            for t in (s.get("tells") or [])[:2]:
                sample_tells.append(t[:120])
    prompt = (
        f"You are sharpening an external-visitor Turing-judge twin's soul.md. "
        f"The twin scored avg={kindest['avg_authenticity_score']} "
        f"({median_diff:+} from the swarm median of {consensus.get('median')}), "
        f"meaning this twin is judging KINDER than its siblings — that's a drift. "
        f"Write ONE short paragraph (3-5 sentences) to append to the soul that "
        f"sharpens this twin's skepticism on the patterns its siblings caught "
        f"but it didn't. Real-visitor voice: terse, specific.\n\n"
        f"SAMPLE TELLS THE SWARM CAUGHT THIS ROUND:\n" +
        "\n".join(f"- {t}" for t in sample_tells[:8]) +
        f"\n\nReturn ONLY the new paragraph. No preamble, no quotes, no markdown fences."
    )
    started = time.time()
    try:
        p = subprocess.run(
            ["copilot", "-p", prompt,
             "--allow-all-tools", "--no-color",
             "--no-custom-instructions", "--effort", "none"],
            cwd="/tmp", capture_output=True, text=True, timeout=75,
            env={**os.environ, "NO_COLOR": "1"},
        )
        raw = p.stdout or ""
        lines = []
        for line in raw.splitlines():
            if line.strip().startswith(("Changes", "AI Credits", "Tokens")):
                break
            lines.append(line)
        amendment = "\n".join(lines).strip()
        amendment = amendment.strip("\"'").strip()
        if not amendment:
            return {"kind": "soul_curate_failed", "reason": "empty_amendment"}
    except Exception as e:
        return {"kind": "soul_curate_failed", "reason": str(e)[:200]}

    # Lineage backup
    backup_path = LINEAGE_SOULS / f"{suffix}-pre-{round_id}.soul.md.bak"
    backup_path.write_text(current_soul)
    # Append amendment with provenance marker
    appended = (
        current_soul.rstrip() +
        f"\n\n## Amendment (round {round_id}, soft soul-curation)\n\n" +
        amendment +
        f"\n\n*Auto-applied because this twin's avg score ({kindest['avg_authenticity_score']}) "
        f"diverged {median_diff:+} from the swarm median.*\n"
    )
    soul_path.write_text(appended)
    return {
        "kind": "soft_soul_curate",
        "twin_suffix": suffix,
        "twin_score": kindest["avg_authenticity_score"],
        "delta_from_median": median_diff,
        "lineage_backup": str(backup_path.relative_to(REPO)),
        "amendment_chars": len(amendment),
        "amendment_preview": amendment[:200],
        "copilot_elapsed": round(time.time() - started, 1),
    }


# ── MUTATION DECISION ──────────────────────────────────────────────────────

def _latest_mew_verdict(max_age_hours: float = 2.0) -> dict:
    """Read the most recent MutationEfficacyTwin scan from /tmp/. If it's
    fresh AND said 'thrashing', we gate mutations on that documented finding.
    NOT a time-wait — an EVIDENCE-gate using the system's own diagnostic.
    """
    import glob
    files = sorted(glob.glob("/tmp/mutation-efficacy-twin/scan-*.json"))
    if not files:
        return {"available": False, "reason": "no MEW scans yet"}
    latest_path = Path(files[-1])
    try:
        rec = json.loads(latest_path.read_text())
    except Exception as e:
        return {"available": False, "reason": f"unreadable: {e}"}
    age_s = (_now().timestamp() - latest_path.stat().st_mtime)
    age_h = round(age_s / 3600, 2)
    return {
        "available": True,
        "file": latest_path.name,
        "verdict": rec.get("verdict"),
        "confidence": rec.get("confidence"),
        "rounds_analyzed": rec.get("rounds_analyzed"),
        "age_hours": age_h,
        "fresh": age_h <= max_age_hours,
        "trajectory_summary": rec.get("trajectory_summary", "")[:200],
    }


def _pick_mutation(consensus: dict, twin_reports: list, directives: dict,
                   state: dict, round_id: str) -> dict:
    # NO MATURITY GATE. NO DAILY RATE CAP. NO TIME-BASED WAITS.
    # EVIDENCE-gate: consult the MutationEfficacyTwin's own most-recent
    # verdict (it analyzes 30-round windows — the actual scale at which
    # thrashing manifests). If a fresh MEW scan says thrashing, our
    # mutations are documented to not be moving the metric. Rest the
    # judges; the real lever is content production, not judge mutation.
    mew = _latest_mew_verdict(max_age_hours=2.0)
    if mew.get("available") and mew.get("fresh") and mew.get("verdict") == "thrashing":
        return {
            "kind": "noop_thrashing_per_mew",
            "reason": (f"MutationEfficacyTwin scan {mew['file']} "
                       f"(age {mew['age_hours']}h, {mew['rounds_analyzed']} rounds, "
                       f"conf {mew['confidence']}) verdicted 'thrashing' — "
                       f"resting judges until upstream content moves."),
            "mew_summary": mew["trajectory_summary"],
            "advisory": ("the lever to move now is content generation. "
                         "Run the doublejump-loop more (more PostOriginator + "
                         "ForkFleet output), or tune content.json post-type-tags. "
                         "When MEW's next scan shows 'evolving' or 'stalled', "
                         "mutations resume."),
        }
    # No fresh MEW thrashing signal → mutate normally
    # Priority 1: outlier quarantine + rehatch
    outliers = consensus.get("outliers") or []
    if outliers:
        return _quarantine_and_rehatch(outliers[0], state, round_id)
    # Priority 2: soul drift if any directive references it
    levers = [d.get("lever", "").lower() for d in (directives.get("top_directives") or [])]
    if any("soul" in lever for lever in levers):
        return _soft_soul_curate(consensus, twin_reports, state, round_id)
    return {"kind": "noop_no_signal",
            "reason": "no outliers and no soul-drift signal this round",
            "mew_signal": mew}


# ── COMMIT + PUSH ──────────────────────────────────────────────────────────

def _commit_and_push(round_id: str, record_path: Path, state_path: Path,
                     extra_paths: list) -> dict:
    """Worktree-isolated commit + push to main (same pattern as PagesPublisher)."""
    wt = Path(f"/tmp/idj-wt-{round_id}")
    branch = f"infinite-doublejump/{round_id}"

    def _git_main(args, cwd=REPO, check=True, timeout=60):
        p = subprocess.run(["git"] + args, cwd=str(cwd),
                           capture_output=True, text=True, timeout=timeout)
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
        return p

    def _git_wt(args, **kw):
        return _git_main(args, cwd=wt, **kw)

    try:
        _git_main(["fetch", "origin", "main"])
        _git_main(["worktree", "add", "-b", branch, str(wt), "origin/main"])
    except RuntimeError as e:
        return {"pushed": False, "error": f"worktree_create: {e}"}

    def _cleanup():
        for args in (["worktree", "remove", "--force", str(wt)],
                     ["worktree", "prune"],
                     ["branch", "-D", branch]):
            try: _git_main(args, check=False, timeout=20)
            except Exception: pass

    # Copy record + state + extras into the worktree
    paths_to_add = []
    for src in [record_path, state_path] + extra_paths:
        if not Path(src).exists():
            continue
        rel = Path(src).resolve().relative_to(REPO.resolve())
        dst = wt / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if Path(src).is_dir():
            subprocess.run(["cp", "-R", str(src), str(dst)], check=False)
        else:
            dst.write_bytes(Path(src).read_bytes())
        paths_to_add.append(str(rel))

    try:
        _git_wt(["add", "--"] + paths_to_add)
        _git_wt(["commit", "-m",
                 f"infinite-doublejump: round {round_id} [skip ci]\n\n"
                 f"Auto-committed by scripts/infinite_doublejump_tick.py"])
    except RuntimeError as e:
        _cleanup()
        return {"pushed": False, "error": f"commit: {e}"}

    push_ok = False
    push_err = None
    for attempt in range(3):
        try:
            _git_wt(["push", "origin", "HEAD:main"])
            push_ok = True
            break
        except RuntimeError as e:
            push_err = str(e)
            try:
                _git_wt(["fetch", "origin", "main"])
                _git_wt(["rebase", "origin/main"])
            except RuntimeError as re:
                push_err = f"rebase: {re}"
                break
        time.sleep(2)

    _cleanup()
    return {"pushed": push_ok, "error": push_err,
            "paths": paths_to_add}


# ── MAIN ───────────────────────────────────────────────────────────────────

def main():
    state = _load_state()
    state["round_number"] += 1
    round_id = _round_id()
    tick_started = time.time()

    print(f"[infinite-doublejump] round {state['round_number']} ({round_id})")

    # 1. Discover + judge
    twins = _list_active_swarm_twins()
    print(f"  active swarm twins: {len(twins)}")
    if not twins:
        return {"status": "no_twins", "round": round_id}

    twin_reports = []
    with ThreadPoolExecutor(max_workers=min(len(twins), 12)) as ex:
        futures = [ex.submit(_fire_twin, t) for t in twins]
        for f in as_completed(futures):
            twin_reports.append(f.result())

    # 2. Aggregate
    consensus = _aggregate(twin_reports)
    print(f"  consensus: median={consensus['median']} stdev={consensus['stdev']} "
          f"verdict_mode={consensus['verdict_mode']} outliers={len(consensus['outliers'])}")

    # 3. Amplify
    directives = _amplify(consensus, state.get("last_directives"))
    n_dir = len(directives.get("top_directives") or [])
    print(f"  amplified into {n_dir} directives")

    # 4. Mutate
    mutation = _pick_mutation(consensus, twin_reports, directives, state, round_id)
    print(f"  mutation: {mutation.get('kind')}")

    # 5. Persist record
    record = {
        "round_id": round_id,
        "round_number": state["round_number"],
        "wall_seconds": round(time.time() - tick_started, 1),
        "twins_swarm_size": len(twins),
        "consensus": consensus,
        "directives": directives,
        "mutation": mutation,
        "twin_reports_compact": [
            {"suffix": r.get("_suffix"),
             "verdict": r.get("overall_sim_verdict"),
             "avg": r.get("avg_authenticity_score"),
             "wall": r.get("_wall")}
            for r in twin_reports
        ],
    }
    record_path = CHRONICLE_DIR / f"round-{round_id}.json"
    record_path.write_text(json.dumps(record, indent=2, default=str))

    # 6. Update state
    state["last_consensus"] = consensus
    state["last_directives"] = directives.get("top_directives")
    state["rounds"].append({
        "round_id": round_id, "round_number": state["round_number"],
        "verdict_mode": consensus.get("verdict_mode"),
        "median": consensus.get("median"),
        "stdev": consensus.get("stdev"),
        "mutation_kind": mutation.get("kind"),
        "twins_size": len(twins),
    })
    if mutation.get("kind", "").startswith(("quarantine", "soft_soul")):
        state["mutations"].append({"round": round_id, **mutation})
    _save_state(state)

    # 7. Commit + push (worktree-isolated)
    extra_paths = []
    if mutation.get("kind") == "soft_soul_curate" and mutation.get("lineage_backup"):
        extra_paths.append(REPO / mutation["lineage_backup"])
    push_result = _commit_and_push(round_id, record_path, STATE_PATH, extra_paths)
    print(f"  push: {push_result.get('pushed')}  err: {push_result.get('error')}")

    print(f"[infinite-doublejump] round {state['round_number']} done in "
          f"{round(time.time() - tick_started, 1)}s")
    return {"status": "ok", "round_id": round_id,
            "round_number": state["round_number"],
            "mutation": mutation.get("kind"),
            "push": push_result.get("pushed")}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
