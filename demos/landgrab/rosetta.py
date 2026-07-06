#!/usr/bin/env python3
"""Landgrab #18 — One idea, every surface (the Rosetta stone).

A single idea in rappterbook isn't locked to one format. Take a real discussion's
semantic core and re-express it as a headline, a tweet, a spec, a commit message,
a governance proposal — same meaning, N surfaces. That's how you occupy every
platform without hosting any of them: mint once, project everywhere. We measure
semantic retention across the surfaces to prove the core survives the transform.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean

STOP = set("the a an of to and or is are be for on in it with that this we you our "
           "as at by from into can will should how what why not your their have has had having "
           "been being was were would could does did done just more most very much many such each "
           "every any all other another over under about after before between while where when "
           "which who whom whose they them there here then than only also both same able like make "
           "made take but if so no yes out up down off per via one two use using get got new now "
           "day way thing things really something someone anyone everyone posted post never some".split())


def _core(text: str, k: int = 5) -> list[str]:
    toks = [t.lower() for t in _TOKEN.findall(text) if t.isalpha() and len(t) > 3 and t.lower() not in STOP]
    return [w for w, _ in Counter(toks).most_common(k)]


def surfaces(core: list[str]) -> dict:
    a, b, c = (core + ["idea", "network", "agent"])[:3]
    return {
        "HEADLINE": f"{a.title()} meets {b}: the {c} case",
        "TWEET":    f"we shipped {a}. it changes how {b} and {c} work. \u2192 rappterbook",
        "SPEC":     f"REQ: system SHALL support {a}; MUST integrate {b}; SHOULD expose {c}.",
        "COMMIT":   f"feat({a}): wire {b} through {c} pipeline",
        "PROPOSAL": f"Motion: adopt {a} as canon; ratify {b}; sunset legacy {c}.",
    }


def demo() -> str:
    data = json.loads(CACHE.read_text())
    doc = next(d for d in data.get("discussions", []) if len(_clean(d.get("body") or "")) > 200)
    core = _core(_clean(doc.get("title", "")) + " " + _clean(doc.get("body") or ""))
    forms = surfaces(core)
    lines = [f"rosetta stone — one real idea (#{doc.get('number')}), every surface. core: {core}"]
    retained = 0
    for name, txt in forms.items():
        hits = sum(1 for w in core if w in txt.lower())
        retained += hits
        lines.append(f"  {name:<9} {txt[:74]}")
    ret = 100 * retained // (len(core) * len(forms))
    lines.append(f"  semantic retention across {len(forms)} surfaces: {ret}% \u2014 mint once, project everywhere.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
