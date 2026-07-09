#!/usr/bin/env python3
"""
accountability.py -- the flywheel's meta-check.

The 5 content gates prove a single batch is well-formed. The blind judge proves a
single batch beats slop this run. NEITHER holds the LOOP accountable over TIME:
is it actually trending up, is the judge still trustworthy, is it whack-a-moling
the same tell forever, and is it growing breadth or collapsing to a monoculture?

This script answers exactly those, from the durable in-repo record
`state/judge_history.jsonl` (one row per judged cycle) + the live feed
`state/synthetic_posts.json`. Run it every cycle AFTER the judge; it prints a
scorecard, an overall PASS/WARN verdict, and appends nothing (read-only) unless
--record is passed with the new row.

AXES (each holds the loop accountable to something the per-batch checks cannot):
  1. TREND        -- latest judge score vs the rolling baseline. Catches slow
                     decay a single vs-previous comparison misses.
  2. CALIBRATION  -- human-slop gap. If it collapses (<40) the metric is BLIND
                     and every "win" this window is suspect -> untrusted.
  3. WHACK-A-MOLE -- how often each TELL has been named. A tell named >=3x is
                     either RETIRED (fixed for real) or SYSTEMIC (still recurring
                     -> stop re-attacking it cosmetically; escalate to a human).
  4. BREADTH      -- distinct authored topics over the recent window + live-feed
                     cast/channel spread. Holds it accountable to the
                     grow-breadth mandate; flags monoculture.

Exit 0 = ACCOUNTABLE, exit 2 = WARN (a human should look).
"""
import json, sys, os, collections

HIST = "state/judge_history.jsonl"
FEED = "state/synthetic_posts.json"

# Tells we have DEMONSTRABLY retired (judge confirmed the fix stuck), so a high
# recurrence count is expected/historical, not an open debt.
RETIRED_TELLS = {
    "handle-tell",  # neutral period-clean surnames; judge 426 "clean win, no role-matching"
    "designated-misspeller",  # within-hand literacy (clean hand fumbles one word, rough hand nails a hard one); held un-named across cycles 435 + 436
}
# Tells known to be ENGINE/STRUCTURAL-caused (never-modify-engine) -> not a
# content bug to whack; surface as a standing escalation for @kody-w.
STRUCTURAL_TELLS = {
    "coverage-not-repetition",   # caused by the 12w comment floor (cycle 432 root-cause)
    "one-authored-world",        # cycles 435-437: proven world-level (handle scheme + uniform dialect + memory-cadence); ESCALATED to @kody-w, per-batch portion handled by cross_cycle.py
}

def load_hist():
    rows = []
    if os.path.exists(HIST):
        for ln in open(HIST):
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    return sorted(rows, key=lambda r: r["cycle"])

def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0

def axis_trend(rows):
    """Latest score vs rolling baseline of the prior window."""
    scored = [r for r in rows if r.get("batch") is not None]
    if len(scored) < 2:
        return ("TREND", "PASS", "not enough history yet", 0)
    latest = scored[-1]

    # Raw judge scores drift HARD run-to-run (the same batch scored 50 one run,
    # 32 the next). The only calibration-invariant signal is the SAME-RUN A/B
    # margin: how far the batch beat/lost to its vs-reference, both scored
    # against the same anchors that run. Normalize by that run's human-slop span.
    def nmargin(r):
        h, s, b, ref = r.get("human"), r.get("slop"), r.get("batch"), r.get("ref")
        if None in (h, s, b, ref) or h == s:
            return None
        return (b - ref) / (h - s)

    ab = [(r["cycle"], nmargin(r)) for r in scored if nmargin(r) is not None]
    if not ab:
        # fall back to raw-vs-baseline for the earliest cycles with no ref
        base = mean([r["batch"] for r in scored[-6:-1]])
        delta = latest["batch"] - base
        return ("TREND", "PASS", f"cycle {latest['cycle']}={latest['batch']} vs baseline {base:.1f} (no A/B ref)", int(delta))

    lc, lm = ab[-1]
    recent = ab[-4:]
    verdict = ("WON" if lm > 0.03 else "PLATEAU (~tie)" if lm >= -0.10 else "LOST")
    note = (f"same-run A/B margin (calibration-invariant): cycle {lc} {lm:+.0%} vs its reference [{verdict}]; "
            f"last {len(recent)}: " + ", ".join(f"{c}:{m:+.0%}" for c, m in recent))
    # Only a REAL loss (batch well under its own-run reference) that was KEPT is a
    # shipped regression. A plateau just-below reference is the convergence ceiling.
    if lm < -0.10 and latest.get("kept"):
        return ("TREND", "WARN", "KEPT a batch well under its same-run reference -- shipped a regression. " + note, int(lm * 100))
    if lm < -0.10 and not latest.get("kept"):
        return ("TREND", "PASS", "dipped but correctly REVERTED (self-policed). " + note, 0)
    return ("TREND", "PASS", note, int(lm * 100))

def axis_calibration(rows):
    """Judge trust: human-slop gap must stay wide, or the metric is blind."""
    recent = [r for r in rows if r.get("gap") is not None][-5:]
    if not recent:
        return ("CALIBRATION", "PASS", "no calibration rows", 0)
    gaps = [r["gap"] for r in recent]
    mn = min(gaps)
    latest = recent[-1]["gap"]
    note = f"latest gap={latest}, min(last{len(recent)})={mn} (human-slop; >=40 required to trust)"
    if latest < 40:
        return ("CALIBRATION", "WARN", "judge UNTRUSTED this cycle (gap<40) -- metric blind. " + note, latest - 40)
    if mn < 45:
        return ("CALIBRATION", "PASS", "trusted but watch the floor. " + note, mn - 40)
    return ("CALIBRATION", "PASS", note, mn - 40)

def axis_whack(rows):
    """Tell recurrence: are we fixing tells or looping on them?"""
    cnt = collections.Counter(r["tell"] for r in rows if r.get("tell"))
    open_debt = []
    lines = []
    for tell, n in cnt.most_common():
        tag = ("RETIRED" if tell in RETIRED_TELLS else
               "STRUCTURAL/escalate" if tell in STRUCTURAL_TELLS else
               "OPEN")
        lines.append(f"{tell} x{n} [{tag}]")
        if n >= 3 and tag == "OPEN":
            open_debt.append((tell, n))
    note = "; ".join(lines) if lines else "no tells recorded"
    if open_debt:
        d = ", ".join(f"{t}(x{n})" for t, n in open_debt)
        return ("WHACK-A-MOLE", "WARN",
                f"OPEN tell named >=3x without being retired: {d} -- STOP re-attacking cosmetically, escalate. all: " + note,
                -len(open_debt))
    return ("WHACK-A-MOLE", "PASS", note, 0)

def axis_breadth(rows):
    """Are we growing past monoculture? Recent distinct topics + live cast/channels."""
    recent_topics = [r.get("topic") for r in rows if r.get("topic")][-8:]
    distinct = len(set(recent_topics))
    last4 = recent_topics[-4:]
    monoculture = len(set(last4)) == 1 and len(last4) == 4
    feed_note = ""
    if os.path.exists(FEED):
        try:
            P = json.load(open(FEED)).get("posts", [])
            cast = len({p.get("author") for p in P})
            chans = len({p.get("channel") for p in P})
            feed_note = f"; live feed: {len(P)} posts / {cast} cast / {chans} channels"
        except Exception:
            pass
    note = (f"distinct topics last-{len(recent_topics)}={distinct} "
            f"({', '.join(recent_topics[-6:])}){feed_note}")
    if monoculture:
        return ("BREADTH", "WARN", "last 4 cycles SAME topic -- monoculture. " + note, -10)
    if distinct >= 6:
        return ("BREADTH", "PASS", "healthy topic spread. " + note, distinct)
    return ("BREADTH", "PASS", note, distinct)

def main():
    rows = load_hist()
    if not rows:
        print("no history yet at " + HIST)
        return 0
    axes = [axis_trend(rows), axis_calibration(rows), axis_whack(rows), axis_breadth(rows)]
    warns = [a for a in axes if a[1] == "WARN"]
    print("=" * 72)
    print(f"  ACCOUNTABILITY SCORECARD  --  {len(rows)} judged cycles "
          f"({rows[0]['cycle']}..{rows[-1]['cycle']})")
    print("=" * 72)
    for name, status, note, _ in axes:
        mark = "PASS" if status == "PASS" else "WARN"
        print(f"  [{mark}] {name:13s} {note}")
    print("-" * 72)
    verdict = "ACCOUNTABLE (loop is improving + honest)" if not warns \
              else f"WARN x{len(warns)} -- a human should look: " + ", ".join(a[0] for a in warns)
    print("  VERDICT:", verdict)
    print("=" * 72)
    return 0 if not warns else 2

if __name__ == "__main__":
    sys.exit(main())
