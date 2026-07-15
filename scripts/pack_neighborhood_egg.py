"""pack_neighborhood_egg.py — package the rappterbook-cohesive-twin-set as a .network.egg

The egg is a single JSON file containing the FULL contents of all 3 twins,
all fleet agents, all loop scripts, all launchd plists, all memory rules,
and a snapshot of the synthetic-content sidecars. Rehatchable on any
machine with a brainstem.

Existing eggs in this repo (medic.rapp.egg, kodyTwinAI.rapp.egg etc) use
`_format: "egg"` JSON shape — same here, just `kind: neighborhood` at the
top.

Per the lineage rule, prior eggs are renamed `*.genN-<ts>.egg.bak` before
the new one is written.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO    = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
EGGS_DIR = REPO / "eggs"
EGGS_DIR.mkdir(parents=True, exist_ok=True)
LINEAGE_DIR = EGGS_DIR / "lineage"
LINEAGE_DIR.mkdir(parents=True, exist_ok=True)

NEIGH_HASH = "cca817b507093e83698f7eb91195da1d"
NEIGH_DIR  = Path(f"/Users/kodyw/.rapp/neighborhoods/{NEIGH_HASH}")
HOME_BRAINSTEM = Path("/Users/kodyw/.brainstem/src/rapp_brainstem/agents")
MEMORY_DIR = Path("/Users/kodyw/.claude/projects/-Users-kodyw-Documents-GitHub-Rappter-rappterbook/memory")

TWIN_SOURCES = [
    REPO / "kody-babysitter-twin",
    REPO / "authenticity-twin",
    REPO / "normie-ai-twin",
    REPO / "mutation-efficacy-twin",
    REPO / "twin-of-twins-meta-watcher",
]

FLEET_AGENTS = [
    "frameorchestrator_agent.py", "forkfleet_agent.py",
    "postoriginator_agent.py", "postspublisher_agent.py",
    "pagespublisher_agent.py",  "votesagent_agent.py",
    "activityagent_agent.py",   "doubledownconductor_agent.py",
    "rappterbookhealer_agent.py", "learn_new_agent.py",
    "audit_runner_agent_agent.py", "drift_sentinel_agent_agent.py",
    "githubcli_agent.py",
    "basic_agent.py",
]

LOOP_SCRIPTS_IN_TWIN_WORKSPACE = [
    ("/Users/kodyw/.rapp/twins/rappid:@kody-w/kody-babysitter:ba5fdb289594da04bf5f50f21d02b9ff37071ea90676adc06cd0ad578add28b3/doublejump_loop_tick.sh",
     "babysitter_workspace/doublejump_loop_tick.sh"),
    ("/Users/kodyw/.rapp/twins/rappid:@kody-w/kody-babysitter:ba5fdb289594da04bf5f50f21d02b9ff37071ea90676adc06cd0ad578add28b3/babysitter_tick.sh",
     "babysitter_workspace/babysitter_tick.sh"),
]

LAUNCHD_PLISTS = [
    Path.home() / "Library/LaunchAgents/com.kody.doublejump-loop.plist",
    Path.home() / "Library/LaunchAgents/com.kody.babysitter.plist",
]

ON_ORIGIN_SIDECARS = [
    "state/synthetic_posts.json",
    "state/synthetic_comments.json",
    "state/synthetic_votes.json",
    "state/synthetic_activity.json",
]

def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text()
    except Exception as e:
        return f"<read-failed: {e}>"

def _read_twin_dir(twin_dir: Path) -> dict:
    """Read all files in a twin source dir into a dict {relpath: content}."""
    out = {}
    if not twin_dir.exists():
        return {"_missing": str(twin_dir)}
    for f in twin_dir.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(twin_dir))
            out[rel] = _read_text_safe(f)
    return out

def _read_memory_dir() -> dict:
    out = {}
    if not MEMORY_DIR.exists():
        return out
    for f in MEMORY_DIR.glob("*.md"):
        out[f.name] = _read_text_safe(f)
    return out

def _read_fleet_agents() -> dict:
    out = {}
    for fname in FLEET_AGENTS:
        p = HOME_BRAINSTEM / fname
        if p.exists():
            out[fname] = _read_text_safe(p)
        else:
            out[fname] = f"<missing in home brainstem: {p}>"
    return out

def _read_lineage() -> dict:
    out = {}
    lineage_root = REPO / ".brainstem/src/rapp_brainstem/agents/lineage"
    if not lineage_root.exists():
        return out
    for f in lineage_root.rglob("*.bak"):
        rel = str(f.relative_to(lineage_root))
        out[rel] = _read_text_safe(f)
    return out

def _read_origin_sidecar_snapshots() -> dict:
    """Fetch the current state of each sidecar from origin/main via gh API."""
    out = {}
    for path in ON_ORIGIN_SIDECARS:
        try:
            p = subprocess.run(
                ["gh", "api",
                 f"/repos/kody-w/rappterbook/contents/{path}",
                 "--jq", ".content"],
                capture_output=True, text=True, timeout=20,
            )
            if p.returncode == 0 and p.stdout.strip():
                out[path] = json.loads(base64.b64decode(p.stdout).decode("utf-8"))
            else:
                out[path] = {"_error": p.stderr.strip()[:200]}
        except Exception as e:
            out[path] = {"_error": str(e)[:200]}
    return out

def _archive_prior_egg(egg_path: Path) -> Path | None:
    """Per the lineage rule, back up the existing egg before overwriting."""
    if not egg_path.exists():
        return None
    existing_count = len(list(LINEAGE_DIR.glob(f"{egg_path.stem}.gen*.egg.bak")))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    backup = LINEAGE_DIR / f"{egg_path.stem}.gen{existing_count + 1}-{stamp}.egg.bak"
    shutil.copy2(egg_path, backup)
    return backup

def main():
    started = datetime.now(timezone.utc)
    egg_path = EGGS_DIR / "rappterbook-cohesive.network.egg"

    # Lineage backup
    archived = _archive_prior_egg(egg_path)

    print(f"[pack-egg] reading twins...")
    twins = {tw.name: _read_twin_dir(tw) for tw in TWIN_SOURCES}

    print(f"[pack-egg] reading fleet agents...")
    agents = _read_fleet_agents()

    print(f"[pack-egg] reading lineage backups...")
    lineage = _read_lineage()

    print(f"[pack-egg] reading memory rules...")
    memory = _read_memory_dir()

    print(f"[pack-egg] reading loop scripts from twin workspaces...")
    loop_scripts = {}
    for src, rel in LOOP_SCRIPTS_IN_TWIN_WORKSPACE:
        src_p = Path(src)
        if src_p.exists():
            loop_scripts[rel] = _read_text_safe(src_p)
        else:
            loop_scripts[rel] = f"<missing: {src}>"

    print(f"[pack-egg] reading launchd plists...")
    launchd = {p.name: _read_text_safe(p) for p in LAUNCHD_PLISTS if p.exists()}

    print(f"[pack-egg] reading neighborhood manifest...")
    neighborhood = {
        "rappid.json": json.loads(_read_text_safe(NEIGH_DIR / "rappid.json")),
        "members.json": json.loads(_read_text_safe(NEIGH_DIR / "members.json")),
    }

    print(f"[pack-egg] snapshotting sidecars from origin/main...")
    sidecars = _read_origin_sidecar_snapshots()

    hatch_md = (
        "# Hatching the Rappterbook Cohesive Twin Set\n\n"
        "This egg is a portable snapshot of three outside-perspective twins "
        "(KodyBabysitter / AuthenticityTwin / NormieAITwin) + the full fleet-"
        "content production stack (8 agents) + scheduling (launchd plists) + "
        "the user-preference memory rules + a state snapshot of the synthetic "
        "content sidecars at egg-creation time.\n\n"
        "## To rehatch on a new machine\n\n"
        "1. Ensure you have a RAPP brainstem installed and `gh` CLI authenticated.\n"
        "2. Run: `python3 scripts/unpack_neighborhood_egg.py <path-to-this-egg>`\n"
        "3. That script will:\n"
        "   a. Write each twin's source files to `<repo>/{kody-babysitter-twin,authenticity-twin,normie-ai-twin}/`\n"
        "   b. Write each fleet agent to `~/.brainstem/src/rapp_brainstem/agents/`\n"
        "   c. Hatch each twin via `twin_egg_hatcher_agent.py`\n"
        "   d. Write loop scripts to the babysitter twin's workspace\n"
        "   e. Write launchd plists to `~/Library/LaunchAgents/` (you'll need to `launchctl bootstrap` each)\n"
        "   f. Restore memory files to `~/.claude/projects/<project>/memory/`\n"
        "   g. Optionally restore sidecar snapshots to `state/` (origin must be the same repo)\n"
        "4. After unpack, fire the loop manually first: `launchctl kickstart -k gui/$(id -u)/com.kody.doublejump-loop`\n"
        "5. Confirm origin gets new commits and Pages rebuilds.\n\n"
        "## What's in this egg (manifest below for browsability)\n\n"
        "- 3 twins (each: rappid.json + soul.md + agents/)\n"
        "- 13 fleet agents (from ~/.brainstem)\n"
        "- 2 loop scripts (babysitter workspace)\n"
        "- 2 launchd plists\n"
        "- N memory rule files\n"
        "- M lineage backups (past generations of agents)\n"
        "- 4 sidecar snapshots (synthetic_posts/comments/votes/activity at creation time)\n\n"
        "## Doctrine preserved\n\n"
        "- No dry_run modes anywhere\n"
        "- Mutated generations + lineage backups (per RAPP issue #41)\n"
        "- Inside writes stay in state files; outside Issues trigger JIT\n"
        "- LLM for anything a human would do; deterministic only for plumbing\n"
    )

    egg = {
        "_format": "egg",
        "_schema_version": 1,
        "_format_extension": ".network.egg",
        "organism": {
            "kind": "neighborhood",
            "slug": "rappterbook-cohesive-twin-set",
            "rappid": neighborhood["rappid.json"]["rappid"],
            "hash": NEIGH_HASH,
            "display_name": "Rappterbook Cohesive Twin Set",
            "creator": "@kody-w",
            "packed_at": started.isoformat(),
            "host_project": "https://github.com/kody-w/rappterbook",
            "neighborhood": neighborhood,
            "twins": twins,
            "fleet_agents": agents,
            "loop_scripts": loop_scripts,
            "launchd_plists": launchd,
            "memory_rules": memory,
            "lineage_backups": lineage,
            "sidecar_snapshots_at_pack_time": sidecars,
            "hatch_instructions_md": hatch_md,
        },
    }

    # Pretty-write + integrity hash
    raw = json.dumps(egg, indent=2, sort_keys=False, default=str)
    egg["_content_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    raw = json.dumps(egg, indent=2, sort_keys=False, default=str)
    egg_path.write_text(raw)

    print()
    print(f"[pack-egg] DONE")
    print(f"  egg: {egg_path}")
    print(f"  size: {egg_path.stat().st_size} bytes ({egg_path.stat().st_size / 1024:.1f} KB)")
    print(f"  sha256: {egg['_content_sha256'][:16]}...")
    if archived:
        print(f"  prior egg archived: {archived}")
    print(f"  twins included: {list(twins.keys())}")
    print(f"  fleet agents: {len(agents)}")
    print(f"  memory rules: {len(memory)}")
    print(f"  lineage backups: {len(lineage)}")

if __name__ == "__main__":
    main()
