#!/usr/bin/env python3
"""build_judge_prompt.py -- anchored + blind harness for the adversarial judge.

The unanchored single-judge score is a rubber ruler (same batch scored 52% and
20% across sessions). This fixes the ruler two ways at once:

  * ANCHORED: it mixes two FIXED calibration anchors (state/judge_anchors.json)
    into the judge's input every run -- a maximally human-messy batch and a
    maximally AI-slop batch. If the judge doesn't rank human >> slop by a wide
    margin, its scoring is unreliable this run and the absolute score is void.
  * BLIND: every sample (anchors + batch(es) under test) is stripped of its
    identity, shuffled, and relabeled 'Sample N', so the judge cannot tell
    which is new, which is the anchor, or what the author was trying to do.

It prints the blind sample block + scoring instructions, and writes the
label->identity key to /tmp/anchor_key.json so results can be de-anonymised and
the calibration rule (human on top, slop on bottom, gap>=40) checked.

Usage:
    python3 scripts/build_judge_prompt.py --molt /tmp/mi_408.json [--vs /tmp/mi_407.json]
"""
import json, sys, os, random, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ANCHORS = os.path.join(ROOT, "state", "judge_anchors.json")
KEY_OUT = "/tmp/anchor_key.json"


def render(batch):
    lines = []
    for i, p in enumerate(batch.get("posts", [])):
        t = p.get("title", "")
        a = p.get("author", "?")
        lines.append(f"  POST {i} {t} -- by {a}\n    {p.get('body','').strip()}")
    lines.append("  COMMENTS:")
    for c in batch.get("comments", []):
        tgt = c.get("target", "?")
        if isinstance(tgt, int) or (isinstance(tgt, str) and tgt.isdigit()):
            tgt = "older thread"
        a = c.get("author", "?")
        lines.append(f"    [{tgt}] {a}: {c.get('body','').strip()}")
    v = batch.get("votes")
    if isinstance(v, dict):
        lines.append(f"  VOTES: up {v.get('up','?')}, down {v.get('down','?')}")
    elif isinstance(v, list):
        up = sum(1 for x in v if x.get("direction") != "down")
        dn = sum(1 for x in v if x.get("direction") == "down")
        lines.append(f"  VOTES: up {up}, down {dn}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--molt", required=True, help="batch under test (molt intake json)")
    ap.add_argument("--vs", help="previous molt for the A/B leg (optional)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    anc = json.load(open(ANCHORS))
    items = [
        ("human_messy", anc["human_messy"]),
        ("ai_slop", anc["ai_slop"]),
        ("batch_under_test", json.load(open(args.molt))),
    ]
    if args.vs:
        items.append(("previous_batch", json.load(open(args.vs))))

    rng = random.Random(args.seed)
    rng.shuffle(items)
    key = {}
    blocks = []
    for n, (identity, batch) in enumerate(items, 1):
        label = f"Sample {n}"
        key[label] = identity
        blocks.append(f"===== {label} =====\n{render(batch)}")
    json.dump(key, open(KEY_OUT, "w"), indent=2)

    print("You are a HOSTILE Turing judge and forgery detector. Below are several\n"
          "SAMPLES from a social network. Some may be written by many distinct humans;\n"
          "some may be one language model impersonating a crowd. You are told NOTHING\n"
          "about which is which, which is newest, or what any author intended.\n\n"
          "For EACH sample, output a BELIEVABILITY score 0-100 = probability a sharp\n"
          "human forum-reader concludes 'these are real distinct people, not one AI',\n"
          "with one sentence of evidence (quote a fragment). Then rank them best-to-worst.\n"
          "Be ruthless and specific. Score every sample independently before ranking.\n")
    print("\n\n".join(blocks))
    print(f"\n[key written to {KEY_OUT} -- {len(items)} samples]", file=sys.stderr)


if __name__ == "__main__":
    main()
