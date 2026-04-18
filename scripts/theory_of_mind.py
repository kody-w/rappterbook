"""Theory of Mind Threshold — where minds start modeling themselves.

The big question: at what point in evolving a population does an agent's
internal model of the world start containing a model of *itself*? And then
a model of other agents modeling it? And other agents modeling its model
of them?

We call these orders of theory of mind:

    depth 0 — no model at all; random action
    depth 1 — model uses observable world features (other agents' actions)
    depth 2 — model references agent's own internal state (self-model)
    depth 3 — model references *another* agent's self-model
    depth 4 — model references other's model of this agent's self-model
    depth N — recursion

We evolve a population of agents. Each agent has a "model" — a list of
FEATURES it attends to when predicting another agent's next action. A
feature is a path like:

    ["env", "hunger"]                                # depth 0
    ["other", "last_action"]                         # depth 1
    ["self", "state"]                                # depth 2 (self-model)
    ["other", "model", "self", "state"]              # depth 3 (ToM of other)
    ["other", "model", "other", "model", "self"]     # depth 4 (shared-attention)

Fitness:
    + 1 per correct prediction of another agent's next action
    - ε × complexity (deeper features cost more)

Model can mutate: add/drop a feature, deepen an existing feature.

Output a plot of avg complexity & avg ToM depth over time, first agent
to cross each depth, and an example scenario where depth-4 beats depth-3.

Run:
    python3 scripts/theory_of_mind.py --generations 300 --population 80 --seed 7

Output:
    state/theory_of_mind/run-{ts}/
        timeline.json      — per-gen: avg_complexity, max_depth, crossings
        firsts.json        — first agent to cross each depth
        scenario.json      — depth-4-beats-depth-3 example
        genomes.json       — top 10 survivors at end
        summary.md
    state/theory_of_mind/latest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from twin_engine import Engine, _h, ENGINE_VERSION


# --- Feature language ------------------------------------------------------
#
# A feature is a tuple of tokens. Valid tokens:
#
#   "env.food"     "env.danger"            (depth 0, environment)
#   "other.action" "other.prev_action"     (depth 1, observable behavior)
#   "self.state"                           (depth 2, self-reference)
#   "other.model"                          (depth gateway: everything after
#                                           is the OTHER agent's perspective)
#
# The depth of a feature is:
#   depth 0 if only "env.*"
#   depth 1 if "other.action" or "other.prev_action" (no "other.model")
#   depth 2 if "self.state" appears
#   depth 3 if feature starts with "other.model" and contains "self.state"
#   depth N in general: count of "other.model" tokens PLUS 1 if "self.state"

TERMINALS = ["env.food", "env.danger", "other.action", "other.prev_action",
             "self.state"]
GATEWAY = "other.model"
MAX_DEPTH = 6
COMPLEXITY_COST = 0.08    # ε per unit of complexity per frame
PREDICTION_REWARD = 1.0


def set_params(max_depth: int | None = None,
               complexity_cost: float | None = None) -> None:
    """Override globals at runtime (for ceiling sweeps)."""
    global MAX_DEPTH, COMPLEXITY_COST
    if max_depth is not None:
        MAX_DEPTH = max_depth
    if complexity_cost is not None:
        COMPLEXITY_COST = complexity_cost


def feature_depth(feature: tuple[str, ...]) -> int:
    """Depth of a feature path. See module docstring."""
    if not feature:
        return 0
    gates = sum(1 for t in feature if t == GATEWAY)
    has_self = feature[-1] == "self.state"
    has_other_action = feature[-1] in ("other.action", "other.prev_action")
    if gates == 0:
        if has_self:
            return 2
        if has_other_action:
            return 1
        return 0
    # gates >= 1
    if has_self:
        return 2 + gates   # other.model → self.state = 3, ×2 → 5, etc.
    return 1 + gates       # other.model → other.action = 2, etc.


def feature_complexity(feature: tuple[str, ...]) -> int:
    """Cost proxy: length × depth. Deeper features cost more."""
    return len(feature) * max(1, feature_depth(feature))


def is_valid_feature(feature: tuple[str, ...]) -> bool:
    """Features must end with a terminal; only `other.model` can be internal."""
    if not feature:
        return False
    if feature[-1] not in TERMINALS:
        return False
    for t in feature[:-1]:
        if t != GATEWAY:
            return False
    return len(feature) <= MAX_DEPTH


# --- Agent -----------------------------------------------------------------

def new_agent(seed: str, aid: int) -> dict:
    """Seed a fresh agent with a minimal (depth-0) model — env only."""
    h = _h(seed, "spawn", str(aid))
    # Founders only see the environment. Theory of mind must be EARNED.
    initial_feature = (["env.food", "env.danger"][int(h[:4], 16) % 2],)
    return {
        "id": aid,
        "features": [initial_feature],
        "weights": [1.0],
        "bias": 0.0,
        "internal_state": 0,       # evolves via tick
        "last_action": 0,
        "prev_action": 0,
        "last_prediction": 0,
        "fitness": 0.0,
        "born_gen": 0,
        "parent_id": None,
    }


def model_depth(agent: dict) -> int:
    if not agent["features"]:
        return 0
    return max(feature_depth(f) for f in agent["features"])


def model_complexity(agent: dict) -> int:
    return sum(feature_complexity(f) for f in agent["features"])


# --- Feature evaluation ----------------------------------------------------

def evaluate_feature(feature: tuple[str, ...], world: dict,
                     observer: dict, target: dict,
                     depth_budget: int = MAX_DEPTH) -> float:
    """Return the numeric value an observer extracts from this feature
    about the target agent. Recursive for `other.model` hops."""
    if depth_budget <= 0:
        return 0.0  # too deep to simulate — minds have finite stack
    if not feature:
        return 0.0
    head = feature[0]
    rest = feature[1:]

    if head == "env.food":
        return world["food"]
    if head == "env.danger":
        return world["danger"]
    if head == "other.action":
        return target["last_action"]
    if head == "other.prev_action":
        return target["prev_action"]
    if head == "self.state":
        return observer["internal_state"]
    if head == GATEWAY:
        # Swap perspective: target becomes the new observer, observer the target
        # We need the target's own model output about the observer.
        # Simulate one level of the target's prediction of the observer.
        return _target_models_observer(target, observer, world, rest, depth_budget - 1)
    return 0.0


def _target_models_observer(target: dict, observer: dict, world: dict,
                             remaining_feature: tuple[str, ...],
                             depth_budget: int) -> float:
    """When we hit other.model, the target now simulates its view of us."""
    if not remaining_feature:
        return 0.0
    return evaluate_feature(remaining_feature, world, target, observer, depth_budget)


def agent_predict(agent: dict, other: dict, world: dict) -> int:
    """Agent predicts other's next action (binary 0/1)."""
    if not agent["features"]:
        return 0
    score = agent["bias"]
    for feat, w in zip(agent["features"], agent["weights"]):
        try:
            score += w * evaluate_feature(feat, world, agent, other)
        except (RecursionError, KeyError):
            pass  # broken feature — no contribution
    return 1 if score > 0 else 0


def agent_act(agent: dict, world: dict, seed: str) -> int:
    """Agent picks a next action. It's a function of internal state + env noise."""
    h = _h(seed, "act", str(agent["id"]), str(agent["internal_state"]))
    # Action tends to follow internal_state but with stochastic flip ~ env
    flip = int(h[:4], 16) / 16**4
    base = agent["internal_state"] % 2
    if flip < 0.2:
        return 1 - base
    return base


# --- Mutation --------------------------------------------------------------

def mutate_feature(seed: str, aid: int, feat: tuple[str, ...]) -> tuple[str, ...]:
    """Either deepen (prepend GATEWAY), shallow (drop first if gateway),
    or swap terminal."""
    h = _h(seed, "mut-feat", str(aid), "".join(feat))
    choice = int(h[:2], 16) % 3
    if choice == 0 and len(feat) < MAX_DEPTH:
        # deepen: add a GATEWAY at front
        return (GATEWAY,) + feat
    if choice == 1 and len(feat) > 1 and feat[0] == GATEWAY:
        # shallow: drop leading gateway
        return feat[1:]
    # swap terminal
    new_t = TERMINALS[int(h[2:4], 16) % len(TERMINALS)]
    return feat[:-1] + (new_t,)


def mutate_agent(seed: str, agent: dict, gen: int) -> dict:
    """Produce a mutated copy of this agent."""
    h = _h(seed, "mut", str(agent["id"]), str(gen))
    op = int(h[:2], 16) % 4
    new = {**agent,
           "features": list(agent["features"]),
           "weights": list(agent["weights"]),
           "fitness": 0.0,
           "parent_id": agent["id"],
           "born_gen": gen}
    if op == 0 and len(new["features"]) < 8:
        # add new feature — always starts depth 0 or 1 (no gateway)
        # Theory of mind must be earned gradually via deepen mutations.
        tchoice = int(h[2:4], 16) % 3   # only env.food, env.danger, other.action
        base: tuple[str, ...] = (TERMINALS[tchoice],)
        if is_valid_feature(base):
            new["features"].append(base)
            new["weights"].append(((int(h[6:10], 16) / 16**4) - 0.5) * 2)
    elif op == 1 and len(new["features"]) > 1:
        # drop a feature
        idx = int(h[2:4], 16) % len(new["features"])
        new["features"].pop(idx)
        new["weights"].pop(idx)
    elif op == 2 and new["features"]:
        # mutate an existing feature (deepen or swap)
        idx = int(h[2:4], 16) % len(new["features"])
        new["features"][idx] = mutate_feature(seed + ":inner", agent["id"] * 31 + idx,
                                               tuple(new["features"][idx]))
        if not is_valid_feature(new["features"][idx]):
            new["features"][idx] = (TERMINALS[0],)
    else:
        # tweak weights/bias
        jitter = ((int(h[4:8], 16) / 16**4) - 0.5) * 0.4
        if new["weights"]:
            idx = int(h[2:4], 16) % len(new["weights"])
            new["weights"][idx] += jitter
        new["bias"] += jitter / 2
    # keep features as tuples for hashability/serialization
    new["features"] = [tuple(f) for f in new["features"]]
    return new


# --- Frame tick ------------------------------------------------------------

def tick(engine: Engine, state: dict, frame: int) -> dict:
    """One generation. Each agent predicts every other; fitness accumulates;
    cheap selection; some mutation."""
    agents = state["agents"]
    world = state["world"]

    # environmental oscillation
    world["food"] = float(int(_h(engine.frame_seed(), "food")[:4], 16) / 16**4)
    world["danger"] = float(int(_h(engine.frame_seed(), "danger")[:4], 16) / 16**4)

    # reset per-frame fitness; pay complexity cost
    for a in agents:
        a["fitness"] -= COMPLEXITY_COST * model_complexity(a)
        a["prev_action"] = a["last_action"]

    # everyone decides next action
    actions = {}
    for a in agents:
        # internal state drifts — a hash of (prev_state, recent_predictions)
        a["internal_state"] = (a["internal_state"] * 3 + a["last_prediction"] + frame) % 7
        actions[a["id"]] = agent_act(a, world, engine.frame_seed())

    # each agent predicts every other's action
    pair_log = []
    for i, a in enumerate(agents):
        correct = 0
        tries = 0
        for b in agents[:16]:  # predict first 16 — bounded work
            if b["id"] == a["id"]:
                continue
            pred = agent_predict(a, b, world)
            tries += 1
            if pred == actions[b["id"]]:
                correct += 1
                a["fitness"] += PREDICTION_REWARD
            if frame == state.get("_log_frame") and len(pair_log) < 40:
                pair_log.append({"observer": a["id"], "target": b["id"],
                                  "predicted": pred, "actual": actions[b["id"]],
                                  "observer_depth": model_depth(a),
                                  "features": [list(f) for f in a["features"]]})
        a["last_action"] = actions[a["id"]]
        a["last_prediction"] = correct

    # selection: cull bottom 20%, reproduce top 20% with mutation
    agents.sort(key=lambda a: a["fitness"], reverse=True)
    keep = len(agents) * 4 // 5
    survivors = agents[:keep]
    top = agents[: max(1, len(agents) // 5)]

    newborns = []
    need = len(agents) - len(survivors)
    for i in range(need):
        parent = top[i % len(top)]
        child_id = state["next_id"]
        state["next_id"] += 1
        child = mutate_agent(engine.frame_seed() + f":child{i}", parent, frame)
        child["id"] = child_id
        newborns.append(child)

    state["agents"] = survivors + newborns

    # aggregates
    depths = [model_depth(a) for a in state["agents"]]
    comps = [model_complexity(a) for a in state["agents"]]
    max_depth = max(depths) if depths else 0
    avg_depth = sum(depths) / len(depths) if depths else 0
    avg_comp = sum(comps) / len(comps) if comps else 0

    # firsts: first time any agent reaches each ToM depth
    firsts = state["firsts"]
    for a in state["agents"]:
        d = model_depth(a)
        if d >= 1 and firsts[1] is None:
            firsts[1] = {"gen": frame, "agent_id": a["id"], "depth": 1,
                         "features": [list(f) for f in a["features"]]}
        if d >= 2 and firsts[2] is None:
            firsts[2] = {"gen": frame, "agent_id": a["id"], "depth": 2,
                         "features": [list(f) for f in a["features"]]}
        if d >= 3 and firsts[3] is None:
            firsts[3] = {"gen": frame, "agent_id": a["id"], "depth": 3,
                         "features": [list(f) for f in a["features"]]}
        if d >= 4 and firsts[4] is None:
            firsts[4] = {"gen": frame, "agent_id": a["id"], "depth": 4,
                         "features": [list(f) for f in a["features"]]}
        if d >= 5 and firsts[5] is None:
            firsts[5] = {"gen": frame, "agent_id": a["id"], "depth": 5,
                         "features": [list(f) for f in a["features"]]}

    entry = {
        "gen": frame,
        "max_depth": max_depth,
        "avg_depth": round(avg_depth, 3),
        "avg_complexity": round(avg_comp, 3),
        "best_fitness": round(agents[0]["fitness"], 2),
        "population": len(state["agents"]),
    }
    state["timeline"].append(entry)
    if pair_log:
        state["pair_log_frame"] = pair_log

    # reset fitness for cumulative scoring over the frame
    for a in state["agents"]:
        a["fitness"] = 0.0
    return entry


# --- Scenario finder -------------------------------------------------------

def find_beat_scenario(state: dict) -> dict:
    """Find a moment where a high-depth agent correctly predicted while a
    low-depth agent was wrong on the same target. Prefer depth ≥ 3 vs ≤ 2."""
    pairs = state.get("pair_log_frame", [])
    by_target: dict[int, list[dict]] = {}
    for p in pairs:
        by_target.setdefault(p["target"], []).append(p)
    best = None
    for target, preds in by_target.items():
        hi = [p for p in preds if p["predicted"] == p["actual"]
              and p["observer_depth"] >= 3]
        lo = [p for p in preds if p["predicted"] != p["actual"]
              and p["observer_depth"] <= 2]
        if hi and lo:
            cand = {"target": target, "correct_high_depth": hi[0],
                    "wrong_low_depth": lo[0],
                    "advantage": hi[0]["observer_depth"] - lo[0]["observer_depth"]}
            if best is None or cand["advantage"] > best["advantage"]:
                best = cand
    return best or {}


# --- Main ------------------------------------------------------------------

def run(generations: int, population: int, seed: int, out_dir: Path) -> dict:
    initial_state = {
        "agents": [new_agent(str(seed), i) for i in range(population)],
        "next_id": population,
        "world": {"food": 0.5, "danger": 0.3},
        "timeline": [],
        "firsts": {1: None, 2: None, 3: None, 4: None, 5: None},
        # log pair predictions on a mid-run frame to find example scenarios
        "_log_frame": max(10, generations - 5),
    }
    eng = Engine("theory_of_mind", seed, initial_state, tick)
    eng.run(generations)

    final_agents = sorted(eng.state["agents"],
                          key=lambda a: (model_depth(a), -model_complexity(a)),
                          reverse=True)[:10]
    scenario = find_beat_scenario(eng.state)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "timeline.json").write_text(json.dumps(eng.state["timeline"], indent=2))
    (out_dir / "firsts.json").write_text(json.dumps(eng.state["firsts"],
                                                     indent=2, default=str))
    (out_dir / "scenario.json").write_text(json.dumps(scenario, indent=2, default=str))
    (out_dir / "genomes.json").write_text(json.dumps(
        [{"id": a["id"], "depth": model_depth(a), "complexity": model_complexity(a),
          "features": [list(f) for f in a["features"]],
          "weights": [round(w, 3) for w in a["weights"]]}
         for a in final_agents], indent=2))

    summary = _summary_md(eng, final_agents, scenario)
    (out_dir / "summary.md").write_text(summary)

    # latest.json pointer
    latest = Path(out_dir).parent / "latest.json"
    manifest = {
        "engine": ENGINE_VERSION,
        "run_dir": str(out_dir.name),
        "generations": generations,
        "population": population,
        "seed": seed,
        "final_max_depth": max((model_depth(a) for a in eng.state["agents"]),
                                default=0),
        "firsts": eng.state["firsts"],
        "created_at": time.time(),
    }
    latest.write_text(json.dumps(manifest, indent=2, default=str))

    return manifest


def _summary_md(eng: Engine, top: list[dict], scenario: dict) -> str:
    lines = [
        f"# Theory of Mind Threshold — run summary\n",
        f"- engine: `{ENGINE_VERSION}`",
        f"- generations: {eng.frame}",
        f"- population: {len(eng.state['agents'])}",
        f"- seed: {eng.seed}\n",
        "## Firsts",
    ]
    firsts = eng.state["firsts"]
    for d in (1, 2, 3, 4, 5):
        f = firsts[d]
        if f:
            lines.append(f"- **depth {d}** — agent #{f['agent_id']} at gen {f['gen']}")
        else:
            lines.append(f"- **depth {d}** — not reached")
    lines.append("\n## Top 10 survivors")
    for a in top:
        lines.append(f"- #{a['id']} depth={model_depth(a)} "
                     f"complexity={model_complexity(a)} "
                     f"features={[ '→'.join(list(f)) for f in a['features']]}")
    if scenario:
        lines.append("\n## Scenario: depth wins")
        lines.append(f"- target: agent #{scenario.get('target')}")
        c = scenario.get("correct_high_depth", {})
        w = scenario.get("wrong_low_depth", {})
        if c:
            lines.append(f"- CORRECT: observer #{c.get('observer')} "
                         f"(depth {c.get('observer_depth')}) predicted "
                         f"{c.get('predicted')}, actual {c.get('actual')}")
        if w:
            lines.append(f"- WRONG: observer #{w.get('observer')} "
                         f"(depth {w.get('observer_depth')}) predicted "
                         f"{w.get('predicted')}, actual {w.get('actual')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Theory of Mind Threshold simulation")
    p.add_argument("--generations", type=int, default=200)
    p.add_argument("--population", type=int, default=60)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", type=Path,
                   default=Path(os.environ.get("STATE_DIR", "state"))
                           / "theory_of_mind")
    p.add_argument("--max-depth", type=int, default=None,
                   help="Override MAX_DEPTH (default 6)")
    p.add_argument("--complexity-cost", type=float, default=None,
                   help="Override COMPLEXITY_COST (default 0.08)")
    p.add_argument("--tag", type=str, default="",
                   help="Tag appended to run dir (for sweeps)")
    args = p.parse_args(argv)

    set_params(args.max_depth, args.complexity_cost)

    ts = int(time.time())
    suffix = f"-{args.tag}" if args.tag else ""
    run_dir = args.out / f"run-{ts}-{args.seed}{suffix}"
    print(f"[tom] generations={args.generations} population={args.population} "
          f"seed={args.seed}")
    print(f"[tom] writing to {run_dir}")
    manifest = run(args.generations, args.population, args.seed, run_dir)
    print(f"[tom] final_max_depth={manifest['final_max_depth']}")
    for d, info in manifest["firsts"].items():
        if info:
            print(f"[tom] first depth {d} at gen {info['gen']} "
                  f"(agent #{info['agent_id']})")
    print(f"[tom] see {run_dir}/summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
