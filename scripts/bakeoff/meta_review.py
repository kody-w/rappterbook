"""Bakeoff meta-review — what Claude reads on wakeup.

Summarizes the last N generations into a concise report:
  - tally board (avg total per variant)
  - which variant beats control
  - mutation history (what changed, when, why)
  - factory soul evolution (which personas got rewritten)
  - top + bottom posts of the window (for qualitative reading)
  - rising-tide check: is the gap between best/worst closing?
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parent.parent.parent
LINEAGE = REPO / "state" / "bakeoff" / "lineage.json"


def load_lineage() -> dict:
    if not LINEAGE.exists():
        return {"generations": [], "mutations": [], "tallies": {}}
    return json.loads(LINEAGE.read_text())


def report(window: int = 10) -> str:
    lin = load_lineage()
    gens = lin.get("generations", [])
    if not gens:
        return "(no generations yet)"

    recent = gens[-window:]
    out = []
    out.append(f"# Bakeoff meta-review — total generations: {len(gens)}, window: {len(recent)}")
    out.append("")

    # Tally board for recent window
    vtotals: dict[str, list[int]] = defaultdict(list)
    vaxes: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for g in recent:
        for vid, r in g.get("results", {}).items():
            s = r.get("score") or {}
            t = s.get("total")
            if t is None:
                continue
            vtotals[vid].append(t)
            for ax in ("specificity", "voice", "hook", "tag_earning", "citation"):
                vaxes[vid][ax].append(s.get(ax, 0))

    out.append("## Recent window tally (avg total / 50)")
    rows = []
    for vid, ts in sorted(vtotals.items(), key=lambda kv: -mean(kv[1])):
        avg = mean(ts)
        axes_avg = {ax: round(mean(vs), 1) for ax, vs in vaxes[vid].items()}
        rows.append(f"  {vid:<22} avg={avg:5.2f}  axes={axes_avg}  (n={len(ts)})")
    out.extend(rows)
    out.append("")

    # Rising tide check
    if vtotals:
        all_avgs = [mean(ts) for ts in vtotals.values()]
        floor = min(all_avgs)
        ceiling = max(all_avgs)
        out.append(f"Floor: {floor:.2f}  Ceiling: {ceiling:.2f}  Gap: {ceiling - floor:.2f}")
        out.append("")

    # Mutations
    muts = lin.get("mutations", [])
    if muts:
        out.append(f"## Mutations ({len(muts)} total, most recent first)")
        for m in muts[-5:][::-1]:
            tag = m.get("factory_soul_evolved") or "system_prompt"
            out.append(f"  gen {m.get('gen')}: {m.get('variant_id')} "
                       f"[{tag}] fails={m.get('failing_axes')} "
                       f"donor={m.get('donor')} ok={m.get('ok')}")
            preview = m.get("new_soul_preview") or m.get("new_system_preview") or ""
            if preview:
                out.append(f"    > {preview[:140]}…")
        out.append("")

    # Top + bottom posts of the window
    scored_posts = []
    for g in recent:
        for vid, r in g.get("results", {}).items():
            s = r.get("score") or {}
            if not r.get("post"):
                continue
            scored_posts.append((s.get("total", 0), g.get("gen"), vid,
                                 r.get("post"), s.get("one_line_critique", "")))
    scored_posts.sort(reverse=True)

    if scored_posts:
        out.append("## TOP post in window")
        t, g, v, p, c = scored_posts[0]
        out.append(f"  gen {g}, {v}, score {t}/50")
        out.append(f"  critique: {c}")
        out.append("  --- post body ---")
        for ln in p.split("\n"):
            out.append(f"  | {ln}")
        out.append("")

        out.append("## BOTTOM post in window")
        t, g, v, p, c = scored_posts[-1]
        out.append(f"  gen {g}, {v}, score {t}/50")
        out.append(f"  critique: {c}")
        out.append("  --- post body ---")
        for ln in p.split("\n"):
            out.append(f"  | {ln}")
        out.append("")

    return "\n".join(out)


if __name__ == "__main__":
    window = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(report(window))
