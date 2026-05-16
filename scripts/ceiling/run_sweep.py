"""Depth-ceiling sweep for ToM: vary cost and population, raise MAX_DEPTH to 8,
run 3 seeds per condition, aggregate firsts and finals."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "state" / "theory_of_mind"
SWEEP_OUT = STATE / "ceiling_sweep.json"

CONDITIONS = [
    {"tag": "baseline", "cost": 0.08, "pop": 120, "gens": 600, "max_depth": 8},
    {"tag": "cheap",    "cost": 0.02, "pop": 120, "gens": 600, "max_depth": 8},
    {"tag": "bigpop",   "cost": 0.08, "pop": 240, "gens": 600, "max_depth": 8},
    {"tag": "marathon", "cost": 0.04, "pop": 120, "gens": 1200, "max_depth": 10},
]
SEEDS = [17, 29, 53]

def run_one(cond: dict, seed: int) -> dict:
    tag = f"ceiling-{cond['tag']}-s{seed}"
    cmd = [
        sys.executable, "scripts/theory_of_mind.py",
        "--generations", str(cond["gens"]),
        "--population", str(cond["pop"]),
        "--seed", str(seed),
        "--max-depth", str(cond["max_depth"]),
        "--complexity-cost", str(cond["cost"]),
        "--tag", tag,
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    dur = time.time() - t0
    if proc.returncode != 0:
        print(f"  FAIL seed={seed} cond={cond['tag']}: {proc.stderr[-400:]}")
        return {"error": proc.stderr[-400:]}
    # Find latest run dir with this tag suffix
    runs = sorted(STATE.glob(f"run-*-{seed}-{tag}"))
    if not runs:
        return {"error": "no run dir"}
    run_dir = runs[-1]
    firsts = json.loads((run_dir / "firsts.json").read_text())
    timeline = json.loads((run_dir / "timeline.json").read_text())
    final_max = timeline[-1]["max_depth"] if timeline else 0
    avg_complexity_final = timeline[-1]["avg_complexity"] if timeline else 0
    # Peak depth across all generations & when it was reached
    peak_depth = 0
    peak_gen = 0
    for row in timeline:
        if row["max_depth"] > peak_depth:
            peak_depth = row["max_depth"]
            peak_gen = row["gen"]
    # Sustained depth: first gen where max_depth stays >= 3 for 20 consecutive gens
    sustained_d3_gen = None
    streak = 0
    for row in timeline:
        if row["max_depth"] >= 3:
            streak += 1
            if streak >= 20 and sustained_d3_gen is None:
                sustained_d3_gen = row["gen"] - 19
                break
        else:
            streak = 0
    return {
        "condition": cond["tag"],
        "seed": seed,
        "gens": cond["gens"],
        "pop": cond["pop"],
        "cost": cond["cost"],
        "max_depth_cap": cond["max_depth"],
        "final_max_depth": final_max,
        "peak_depth": peak_depth,
        "peak_at_gen": peak_gen,
        "sustained_d3_gen": sustained_d3_gen,
        "avg_complexity_final": round(avg_complexity_final, 3),
        "duration_s": round(dur, 2),
        "firsts": {
            str(d): firsts.get(str(d), {}).get("gen") if firsts.get(str(d)) else None
            for d in range(1, cond["max_depth"] + 1)
        },
        "run_dir": str(run_dir.relative_to(ROOT)),
    }

def main() -> int:
    results = []
    for cond in CONDITIONS:
        for seed in SEEDS:
            print(f"[sweep] cond={cond['tag']} seed={seed} gens={cond['gens']} pop={cond['pop']}")
            res = run_one(cond, seed)
            results.append(res)
            if "error" not in res:
                print(f"  final_max_depth={res['final_max_depth']} "
                      f"firsts={res['firsts']} dur={res['duration_s']}s")
    # Aggregate
    summary = {
        "generated_at": int(time.time()),
        "conditions": CONDITIONS,
        "seeds": SEEDS,
        "runs": results,
        "by_condition": {},
    }
    for cond in CONDITIONS:
        rows = [r for r in results if r.get("condition") == cond["tag"]]
        if not rows:
            continue
        max_depths = [r["final_max_depth"] for r in rows]
        peaks = [r["peak_depth"] for r in rows]
        d6_hits = sum(1 for r in rows if r["peak_depth"] >= 6)
        d7_hits = sum(1 for r in rows if r["peak_depth"] >= 7)
        d8_hits = sum(1 for r in rows if r["peak_depth"] >= 8)
        sustained_count = sum(1 for r in rows if r["sustained_d3_gen"] is not None)
        summary["by_condition"][cond["tag"]] = {
            "runs": len(rows),
            "final_depth_mean": round(sum(max_depths) / len(max_depths), 2),
            "peak_depth_mean": round(sum(peaks) / len(peaks), 2),
            "peak_depth_max": max(peaks),
            "depth_6_peak": d6_hits,
            "depth_7_peak": d7_hits,
            "depth_8_peak": d8_hits,
            "sustained_d3_runs": sustained_count,
            "avg_complexity_final_mean": round(
                sum(r["avg_complexity_final"] for r in rows) / len(rows), 2),
        }
    SWEEP_OUT.write_text(json.dumps(summary, indent=2))
    print(f"\n[sweep] wrote {SWEEP_OUT.relative_to(ROOT)}")
    for name, agg in summary["by_condition"].items():
        print(f"  {name}: final_mean={agg['final_depth_mean']} "
              f"peak_mean={agg['peak_depth_mean']} peak_max={agg['peak_depth_max']} "
              f"d6+peak={agg['depth_6_peak']}/{agg['runs']} "
              f"sustained_d3={agg['sustained_d3_runs']}/{agg['runs']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
