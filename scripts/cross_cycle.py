#!/usr/bin/env python3
"""
cross_cycle.py -- the CROSS-BATCH ratchet (gate #6).

The 5 per-batch gates + the blind judge all look at ONE batch. But at network
scale every batch coexists in the feed, and a hostile judge comparing two of my
consecutive batches side by side caught the real tell (cycle 435):

    "In isolation each would score ~73... the cross-sample forgery evidence
     sinks them. The same handle zion-fenn-05 posts the same ASK template in
     both threads; the [9502141] elm orphan comment appears in both; keld-02
     OPs the contested-resource post in both."

That is the ONE-AUTHORED-WORLD tell made concrete: not recurring CAST (that's
realistic), but recurring CAST-IN-THE-SAME-ROLE + reused off-page anchors +
reused signature phrasing across cycles. This gate compares the current intake
against the last N molted batches in state/batch_history/ and FAILS on the
mechanical fingerprints of a single generator refilling a template.

Recurring a handle across cycles is GOOD (continuity). The tells this catches:
  1. GENRE-LOCKED HANDLE  -- the same author posting the same TAG (esp. [ASK] /
                             a [GENERAL] resource-dispute OP) across batches.
  2. REUSED OFF-PAGE ANCHOR -- the same orphan INT id (old-post follow-up)
                             reused in more than one batch = one author's prop.
  3. CROSS-BATCH VERBATIM  -- a 5+ word phrase shared verbatim across batches
                             (identical ASK closers, "we had this exact row
                             last winter" devices) = template boilerplate.

Usage: python3 scripts/cross_cycle.py state/molt_intake.json
Exit 0 = OK (no single-generator fingerprint), exit 2 = FLAG.
"""
import json, sys, os, re, glob, collections

HISTDIR = "state/batch_history"
RECENT = 6          # compare against the last N molted batches
NGRAM = 5           # verbatim phrase length that counts as boilerplate
# generic connective phrases that recur innocently -> don't count as boilerplate
STOP_NGRAMS_RE = re.compile(r"^(i do not|i dont|is it|has anyone|does anyone|if you have|the last of)")

def norm(s):
    return re.findall(r"[a-z']+", s.lower())

def tag_of(title):
    m = re.match(r"\s*\[([a-z]+)\]", title.strip(), re.I)
    return m.group(1).upper() if m else "GENERAL"

def is_int_target(t):
    return isinstance(t, int) or (isinstance(t, str) and t.isdigit())

def dispute_ops(batch):
    """Authors of high-reply [GENERAL] posts = the resource-dispute OP role."""
    counts = collections.Counter()
    for c in batch.get("comments", []):
        t = c.get("target")
        if isinstance(t, str) and t.startswith("post:"):
            counts[int(t.split(":")[1])] += 1
    ops = set()
    for i, p in enumerate(batch.get("posts", [])):
        if tag_of(p["title"]) == "GENERAL" and counts.get(i, 0) >= 4:
            ops.add(p["author"])
    return ops

def genre_map(batch):
    m = collections.defaultdict(set)
    for p in batch.get("posts", []):
        m[p["author"]].add(tag_of(p["title"]))
    return m

def orphans(batch):
    return {str(c["target"]) for c in batch.get("comments", []) if is_int_target(c.get("target"))}

def ngrams(batch, n=NGRAM):
    grams = set()
    texts = [p.get("body", "") for p in batch.get("posts", [])] + \
            [c.get("body", "") for c in batch.get("comments", [])]
    for tx in texts:
        w = norm(tx)
        for i in range(len(w) - n + 1):
            g = " ".join(w[i:i + n])
            if not STOP_NGRAMS_RE.match(g):
                grams.add(g)
    return grams

def load_recent(cur_cycle=None):
    files = sorted(glob.glob(os.path.join(HISTDIR, "mi_*.json")))
    out = []
    for f in files:
        m = re.search(r"mi_(\d+)\.json", f)
        cyc = int(m.group(1)) if m else 0
        if cur_cycle is not None and cyc >= cur_cycle:
            continue
        try:
            out.append((cyc, json.load(open(f))))
        except Exception:
            pass
    return sorted(out, key=lambda x: x[0])[-RECENT:]

def main():
    if len(sys.argv) < 2:
        print("usage: cross_cycle.py <intake.json>")
        return 1
    cur = json.load(open(sys.argv[1]))
    # infer current cycle from --cycle or skip self-match by content identity
    cyc = None
    if "--cycle" in sys.argv:
        cyc = int(sys.argv[sys.argv.index("--cycle") + 1])
    recent = load_recent(cyc)
    if not recent:
        print("cross_cycle: no history to compare against -- OK (first batch).")
        return 0

    cur_gm, cur_ops, cur_orph, cur_ng = genre_map(cur), dispute_ops(cur), orphans(cur), ngrams(cur)
    flags = []

    # aggregate history
    hist_author_tags = collections.defaultdict(collections.Counter)  # author -> tag -> #batches
    hist_ops = collections.Counter()
    hist_orph = collections.Counter()
    hist_ng = collections.Counter()
    for c, b in recent:
        # skip a history entry identical to the current batch (self)
        if b.get("posts") == cur.get("posts"):
            continue
        for a, tags in genre_map(b).items():
            for t in tags:
                hist_author_tags[a][t] += 1
        for a in dispute_ops(b):
            hist_ops[a] += 1
        for o in orphans(b):
            hist_orph[o] += 1
        for g in ngrams(b):
            hist_ng[g] += 1

    # 1. genre-locked handle (same author + same SPECIFIC tag as a recent batch).
    #    GENERAL is the catch-all default tag -> too broad to lock on; the
    #    resource-dispute-OP role (the meaningful GENERAL sub-case) is caught
    #    precisely by OP-LOCK below instead.
    for a, tags in cur_gm.items():
        for t in tags:
            if t == "GENERAL":
                continue
            if hist_author_tags[a][t] >= 1:
                flags.append(f"GENRE-LOCK: {a} posts [{t}] again (also in {hist_author_tags[a][t]} recent batch(es)) -- rotate the {t} author.")

    # 2. reused dispute-OP role
    for a in cur_ops:
        if hist_ops[a] >= 1:
            flags.append(f"OP-LOCK: {a} OPs a resource-dispute again (also {hist_ops[a]} recent) -- rotate the dispute OP.")

    # 3. reused off-page orphan anchor
    for o in cur_orph:
        if hist_orph[o] >= 1:
            flags.append(f"ANCHOR-REUSE: off-page orphan INT {o} reused (in {hist_orph[o]} recent batch(es)) -- use a fresh old-post id or mint a new one.")

    # 4. cross-batch verbatim boilerplate
    shared = sorted(g for g in cur_ng if hist_ng[g] >= 1)
    for g in shared[:6]:
        flags.append(f"VERBATIM: \"{g}\" appears in a recent batch too -- reword (template boilerplate).")

    print("=" * 68)
    print(f"  CROSS-CYCLE gate -- vs last {len(recent)} batches "
          f"({recent[0][0]}..{recent[-1][0]})")
    print("=" * 68)
    if not flags:
        print("  OK: no single-generator fingerprint across cycles.")
        return 0
    for f in flags:
        print("  FLAG " + f)
    print("-" * 68)
    print(f"  {len(flags)} cross-cycle reuse fingerprint(s) -- vary the template before molting.")
    return 2

if __name__ == "__main__":
    sys.exit(main())
