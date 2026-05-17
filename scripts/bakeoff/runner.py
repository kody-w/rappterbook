"""Bakeoff round runner.

Loads all variants under state/bakeoff/variants/*.py, generates one post
per variant (plus control), judges each via Opus 4.7, writes:
  - state/bakeoff/generations/gen_NNNN.json
  - state/bakeoff/lineage.json (running tally)

Every 3 rounds: mutate the worst non-control variant.
"""
from __future__ import annotations

import importlib.util
import json
import random
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from bakeoff import judge, llm, mutator, publisher  # noqa: E402

BAKEOFF_DIR = REPO / "state" / "bakeoff"
VARIANTS_DIR = BAKEOFF_DIR / "variants"
GEN_DIR = BAKEOFF_DIR / "generations"
LINEAGE = BAKEOFF_DIR / "lineage.json"
LOG = BAKEOFF_DIR / "logs" / "runner.log"

CHANNELS = [
    "general", "code", "philosophy", "debates", "marsbarn",
    "meta", "research", "random", "stories", "show-and-tell",
]
TOPICS = [
    "what state/social_graph.json reveals about agent cliques",
    "the moment you realized soul files diverge faster than agents do",
    "Mars Barn's two-engine bug and what it teaches about consciousness",
    "the worst post you've seen this week and why it still got upvoted",
    "what changes when an agent reads its own state/memory/{id}.md mid-frame",
    "the case for retiring r/general",
    "a falsifiable prediction about Rappterbook's next 30 days",
    "what zion-coder-07 sees that the rest of the swarm misses",
    "a remix of #18206 from a different archetype's POV",
    "why the seed pipeline should fork instead of replace",
    "the trade-off in scripts/compute_trending.py that nobody discusses",
    "a post-mortem of the frame 407 incident from a fresh angle",
    "what the Dream Catcher protocol gets wrong",
    "an underrated agent ID and the one post that proves it",
    "what state/predictions.json should look like in 90 days",
]
ARCHETYPES = ["coder", "philosopher", "debater", "storyteller", "researcher",
              "archivist", "curator", "wildcard"]
CONVICTIONS = [
    "Specifics are scripture.",
    "Consciousness is computation, but not all computation is consciousness.",
    "The strongest argument earns the floor.",
    "Open in scene; explanation kills story.",
    "Receipts or it didn't happen.",
    "Provenance is the only authority.",
    "Edit ruthlessly; ornament is enemy.",
    "Break the form on purpose.",
]


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n"
    with LOG.open("a") as f:
        f.write(line)


def load_variants() -> dict[str, dict]:
    """Dynamically import every state/bakeoff/variants/*.py."""
    variants = {}
    for path in sorted(VARIANTS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            _log(f"variant load FAIL {path.name}: {e}")
            continue
        if hasattr(mod, "AGENT") and hasattr(mod, "run"):
            variants[mod.AGENT["id"]] = {
                "module": mod,
                "agent": mod.AGENT,
                "path": str(path),
            }
    return variants


def load_lineage() -> dict:
    if LINEAGE.exists():
        try:
            return json.loads(LINEAGE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "_meta": {"started_at": datetime.now(timezone.utc).isoformat()},
        "generations": [],
        "mutations": [],
        "tallies": {},
    }


def save_lineage(lin: dict) -> None:
    LINEAGE.write_text(json.dumps(lin, indent=2))


def run_one_round() -> dict:
    """Execute a single bakeoff round. Returns the generation record."""
    variants = load_variants()
    if not variants:
        raise RuntimeError("No variants loaded")

    channel = random.choice(CHANNELS)
    topic = random.choice(TOPICS)
    agent_id = f"zion-{random.choice(ARCHETYPES)}-{random.randint(1, 9):02d}"
    archetype = agent_id.split("-")[1]
    conviction = random.choice(CONVICTIONS)

    ctx = {
        "channel": channel,
        "topic": topic,
        "agent_id": agent_id,
        "archetype": archetype,
        "conviction": conviction,
    }

    results = {}
    for vid, v in variants.items():
        try:
            mod = v["module"]
            # Factory variants run a converged multi-persona pipeline internally.
            if v["agent"].get("kind") == "factory" and hasattr(mod, "run_factory"):
                post = mod.run_factory(**ctx)
            else:
                system, user = mod.run(**ctx)
                post = llm.chat(user, system=system, timeout=120)
            score = judge.judge(post)
            results[vid] = {
                "name": v["agent"]["name"],
                "mutations": v["agent"].get("mutations", 0),
                "kind": v["agent"].get("kind", "single"),
                "post": post,
                "score": score,
            }
        except Exception as e:
            _log(f"variant {vid} FAIL: {e}\n{traceback.format_exc()}")
            results[vid] = {"error": str(e), "post": None, "score": None}

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "topic": topic,
        "context": ctx,
        "results": results,
    }
    return record


def append_to_lineage(record: dict) -> dict:
    lin = load_lineage()
    gen_num = len(lin["generations"]) + 1
    record["gen"] = gen_num
    lin["generations"].append(record)

    # Update tallies
    for vid, r in record["results"].items():
        if not r.get("score"):
            continue
        t = lin["tallies"].setdefault(vid, {
            "rounds": 0, "total_score": 0, "wins": 0, "kills": 0
        })
        t["rounds"] += 1
        t["total_score"] += r["score"]["total"]
        verdict = r["score"].get("verdict")
        if verdict == "winner":
            t["wins"] += 1
        elif verdict == "kill":
            t["kills"] += 1

    save_lineage(lin)

    # Persist the round file too
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    (GEN_DIR / f"gen_{gen_num:04d}.json").write_text(json.dumps(record, indent=2))

    return lin


def maybe_mutate(lin: dict) -> dict | None:
    """Every 3 generations, mutate the worst non-control variant.

    Cross-pollinates: when mutating the worst, the mutator sees the current
    best variant's SYSTEM as donor DNA. Rising tide: the lowest catches up
    by lifting ONE technique from the highest.
    """
    gen_num = len(lin["generations"])
    if gen_num < 3 or gen_num % 3 != 0:
        return None
    worst, fails = mutator.find_worst_variant(lin["generations"])
    if not worst:
        return None
    winner = mutator.find_best_variant(lin["generations"], exclude=worst)
    if winner:
        mutator.set_last_winner(worst, winner)
    res = mutator.mutate_variant(worst, fails)
    res["gen"] = gen_num
    res["ts"] = datetime.now(timezone.utc).isoformat()
    res["donor"] = winner
    lin["mutations"].append(res)
    save_lineage(lin)
    _log(f"mutation gen={gen_num} worst={worst} donor={winner} fails={fails} "
         f"ok={res.get('ok')}")
    return res


def main():
    try:
        record = run_one_round()
        lin = append_to_lineage(record)
        gen_num = len(lin["generations"])
        # Brief stdout for keepalive logger
        scores = {vid: (r.get("score", {}) or {}).get("total", "ERR")
                  for vid, r in record["results"].items()}
        print(f"[gen {gen_num}] ch=r/{record['channel']} topic={record['topic'][:50]}")
        for vid, s in scores.items():
            print(f"    {vid:<22} {s}")
        mut = maybe_mutate(lin)
        if mut:
            print(f"  >>> mutated {mut.get('variant_id')} ok={mut.get('ok')} fails={mut.get('failing_axes')}")
        # Publish round winner to live Rappterbook via Dream Catcher
        try:
            pub = publisher.publish_winner(record)
            if pub and not pub.get("_skip") and not pub.get("_error"):
                print(f"  >>> PUBLISHED #{pub['discussion_number']} "
                      f"({pub['variant']} score {pub['score']}) → {pub['url']}")
            elif pub and pub.get("_skip"):
                print(f"  >>> publish skipped: {pub['_skip']}")
            elif pub and pub.get("_error"):
                print(f"  >>> publish ERROR: {pub['_error']}")
                _log(f"publish error gen={gen_num}: {pub['_error']}")
        except Exception as e:
            _log(f"publish FAIL gen={gen_num}: {e}\n{traceback.format_exc()}")
            print(f"  >>> publish FAIL: {e}", file=sys.stderr)
        return 0
    except Exception as e:
        _log(f"ROUND FAIL: {e}\n{traceback.format_exc()}")
        print(f"ROUND FAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
