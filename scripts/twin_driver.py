#!/usr/bin/env python3
"""
Twin Driver — the autonomous engine that runs the sims forever.

This is the public twin of the private rappter fleet harness. Where rappter
loops forever driving AI agents, this loops forever driving deterministic
evolution sims.

Each cycle:
  1. Pick the next experiment from the campaign queue (round-robin over
     phylogeny, cambrian, ecosystem; rotating seeds and parameter sweeps).
  2. Run it via the twin engine.
  3. Catalog the run in state/twin_runs/index.json.
  4. Keep going.

Modes:
  --once         Run a single experiment then exit (good for cron)
  --loop N       Run N experiments back-to-back
  --forever      Loop indefinitely (good for daemons, ctrl-c to stop)
  --campaign     Specific named campaign (small / medium / large / mixed)

State layout:
  state/twin_runs/
    index.json           # catalog of all runs
    next_seed.json       # rotating counter so seeds don't repeat
    {ts}-{kind}-{seed}/  # per-run output dir (links to per-sim outputs)

No deps, stdlib only. Same shape as the rest of the repo.
"""
from __future__ import annotations
import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DRIVER_VERSION = "twin-driver-1.0"


# ---------- catalog helpers ----------

def load_catalog(state_dir: Path) -> dict:
    idx = state_dir / "twin_runs" / "index.json"
    if not idx.exists():
        return {"_meta": {"driver": DRIVER_VERSION, "created": iso_now()},
                "runs": [], "totals": {}}
    return json.loads(idx.read_text())


def save_catalog(state_dir: Path, catalog: dict) -> None:
    out_dir = state_dir / "twin_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog["_meta"]["updated"] = iso_now()
    (out_dir / "index.json").write_text(json.dumps(catalog, indent=2))


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def next_seed(state_dir: Path) -> int:
    p = state_dir / "twin_runs" / "next_seed.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        n = json.loads(p.read_text()).get("seed", 100)
    else:
        n = 100
    p.write_text(json.dumps({"seed": n + 1}))
    return n


# ---------- experiment definitions ----------

CAMPAIGNS: dict[str, list[dict]] = {
    "small": [
        {"kind": "phylogeny", "args": ["--generations", "30", "--carry", "20"]},
        {"kind": "cambrian", "args": ["--generations", "50", "--founders", "30",
                                       "--carry", "150"]},
        {"kind": "ecosystem", "args": ["--generations", "50", "--founders", "16",
                                        "--biome-carry", "40"]},
    ],
    "medium": [
        {"kind": "phylogeny", "args": ["--generations", "60", "--carry", "40"]},
        {"kind": "cambrian", "args": ["--generations", "150", "--founders", "60",
                                       "--carry", "300"]},
        {"kind": "ecosystem", "args": ["--generations", "100", "--founders", "24",
                                        "--biome-carry", "80"]},
    ],
    "large": [
        {"kind": "phylogeny", "args": ["--generations", "100", "--carry", "80"]},
        {"kind": "cambrian", "args": ["--generations", "500", "--founders", "100",
                                       "--carry", "500"]},
        {"kind": "ecosystem", "args": ["--generations", "200", "--founders", "32",
                                        "--biome-carry", "120"]},
        {"kind": "theory_of_mind", "args": ["--generations", "400", "--population", "80"]},
    ],
    "mixed": [
        # Nice variety pack — different shapes each time
        {"kind": "cambrian", "args": ["--generations", "100", "--founders", "50",
                                       "--carry", "250"]},
        {"kind": "ecosystem", "args": ["--generations", "80", "--founders", "20",
                                        "--biome-carry", "60"]},
        {"kind": "phylogeny", "args": ["--generations", "40", "--carry", "30"]},
        {"kind": "cambrian", "args": ["--generations", "300", "--founders", "80",
                                       "--carry", "400"]},
        {"kind": "ecosystem", "args": ["--generations", "150", "--founders", "30",
                                        "--biome-carry", "100"]},
        {"kind": "theory_of_mind", "args": ["--generations", "250", "--population", "60"]},
    ],
}


SCRIPT_FOR_KIND = {
    "phylogeny": "egg_phylogeny.py",
    "cambrian": "cambrian.py",
    "ecosystem": "ecosystem.py",
    "theory_of_mind": "theory_of_mind.py",
}

STATE_SUBDIR_FOR_KIND = {
    "phylogeny": "phylogeny",
    "cambrian": "cambrian",
    "ecosystem": "ecosystem",
    "theory_of_mind": "theory_of_mind",
}


# ---------- run a single experiment ----------

def run_experiment(experiment: dict, seed: int, state_dir: Path) -> dict:
    kind = experiment["kind"]
    script = SCRIPTS / SCRIPT_FOR_KIND[kind]
    args = list(experiment["args"]) + ["--seed", str(seed)]
    # Phylogeny only honors STATE_DIR via env; cambrian/ecosystem accept both.
    # Setting env always works; passing flag would error on phylogeny.
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)

    print(f"\n{'=' * 60}")
    print(f"[twin-driver] {kind}  seed={seed}")
    print(f"  {' '.join(args)}")
    print(f"{'=' * 60}")

    started = time.time()
    started_iso = iso_now()
    result = subprocess.run(
        [sys.executable, str(script)] + args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed = time.time() - started

    ok = result.returncode == 0
    if not ok:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)

    # Find the run directory the sub-script produced
    sim_state = state_dir / STATE_SUBDIR_FOR_KIND[kind]
    run_dir_name = None
    summary_path = None
    if (sim_state / "latest.json").exists():
        latest = json.loads((sim_state / "latest.json").read_text())
        run_dir_name = latest.get("run_dir")
        if run_dir_name and (sim_state / run_dir_name / "summary.md").exists():
            summary_path = f"state/{STATE_SUBDIR_FOR_KIND[kind]}/{run_dir_name}/summary.md"

    return {
        "kind": kind,
        "seed": seed,
        "args": experiment["args"],
        "ok": ok,
        "started": started_iso,
        "elapsed_seconds": round(elapsed, 2),
        "exit_code": result.returncode,
        "run_dir": run_dir_name,
        "summary_path": summary_path,
        "state_dir": f"state/{STATE_SUBDIR_FOR_KIND[kind]}/{run_dir_name}" if run_dir_name else None,
    }


# ---------- catalog update ----------

def append_to_catalog(catalog: dict, record: dict) -> None:
    catalog["runs"].insert(0, record)  # newest first
    # Keep last 200 runs in catalog
    catalog["runs"] = catalog["runs"][:200]
    totals = catalog.setdefault("totals", {})
    totals[record["kind"]] = totals.get(record["kind"], 0) + 1
    totals["all"] = totals.get("all", 0) + 1
    catalog["_meta"]["last_run"] = record["started"]


# ---------- driver loop ----------

def pick_next_experiment(catalog: dict, campaign: list[dict],
                         strategy: str, rng: random.Random) -> dict:
    """Pick the next experiment.

    Strategies:
      round_robin  — cycle through the campaign in order
      least_run    — pick the kind that has been run least
      random       — uniformly random pick from campaign
    """
    if strategy == "round_robin":
        idx = catalog["totals"].get("all", 0) % len(campaign)
        return campaign[idx]
    if strategy == "least_run":
        counts = {e["kind"]: catalog["totals"].get(e["kind"], 0) for e in campaign}
        target_kind = min(counts, key=counts.get)
        candidates = [e for e in campaign if e["kind"] == target_kind]
        return rng.choice(candidates)
    if strategy == "random":
        return rng.choice(campaign)
    raise ValueError(f"Unknown strategy: {strategy}")


def drive(campaign_name: str, strategy: str, n_runs: int,
          state_dir: Path, sleep_between: int) -> None:
    catalog = load_catalog(state_dir)
    campaign = CAMPAIGNS[campaign_name]
    rng = random.Random()  # not deterministic for picks — that's intentional

    print(f"[twin-driver] campaign={campaign_name} strategy={strategy} "
          f"runs={'forever' if n_runs == 0 else n_runs}")
    print(f"[twin-driver] state_dir={state_dir}")

    completed = 0
    try:
        while n_runs == 0 or completed < n_runs:
            experiment = pick_next_experiment(catalog, campaign, strategy, rng)
            seed = next_seed(state_dir)
            record = run_experiment(experiment, seed, state_dir)
            append_to_catalog(catalog, record)
            save_catalog(state_dir, catalog)
            completed += 1

            print(f"[twin-driver] DONE {completed}/{n_runs or '∞'}  "
                  f"kind={record['kind']} ok={record['ok']} "
                  f"elapsed={record['elapsed_seconds']}s")

            if (n_runs == 0 or completed < n_runs) and sleep_between > 0:
                print(f"[twin-driver] sleeping {sleep_between}s before next...")
                time.sleep(sleep_between)
    except KeyboardInterrupt:
        print(f"\n[twin-driver] interrupted after {completed} runs.")


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Autonomous twin driver — runs evolution sims forever.")
    ap.add_argument("--campaign", default="medium",
                    choices=sorted(CAMPAIGNS.keys()),
                    help="Which parameter campaign to run.")
    ap.add_argument("--strategy", default="least_run",
                    choices=["round_robin", "least_run", "random"],
                    help="How to pick the next experiment.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="Run one experiment and exit.")
    mode.add_argument("--loop", type=int, default=0,
                      help="Run N experiments back-to-back, then exit.")
    mode.add_argument("--forever", action="store_true",
                      help="Loop indefinitely (ctrl-c to stop).")
    ap.add_argument("--sleep", type=int, default=2,
                    help="Seconds to sleep between runs.")
    ap.add_argument("--state-dir", default=os.environ.get("STATE_DIR", "state"))
    args = ap.parse_args()

    state_dir = Path(args.state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)

    if args.once:
        n_runs = 1
    elif args.forever:
        n_runs = 0
    elif args.loop > 0:
        n_runs = args.loop
    else:
        n_runs = 1  # default: one shot

    drive(args.campaign, args.strategy, n_runs, state_dir, args.sleep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
