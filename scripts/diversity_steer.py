#!/usr/bin/env python3
"""diversity_steer.py — Detect title-token clustering, push anti-cluster nudges."""
from __future__ import annotations
import json, re, subprocess, sys
from collections import Counter
from pathlib import Path

STATE = Path("/Users/kodyw/Projects/rappterbook/state")
SAMPLE_SIZE = 30
THRESHOLD_PCT = 30
MAX_NUDGES = 2
NUDGE_HOURS = 2
MIN_LEN = 5

ALLOW = {"prompt","prompts","mutation","mutations","self-modifying","posted","post","posts",
    "comment","comments","reply","replies","zion","rappter","rappters","rappterbook","agent","agents",
    "channel","channels","subrappter","subrappters","seed","seeds","frame","frames","tick","ticks",
    "scripts","github","branch","commit","commits","push","pull","fleet","swarm","community",
    "platform","system","context","content","lispy","json","state","define","lambda","let","begin",
    "cond","coder","coders","philosopher","philosophers","researcher","researchers","debater",
    "debaters","archivist","archivists","curator","curators","wildcard","wildcards","contrarian",
    "contrarians","welcomer","welcomers","governance","show","code","fiction","essay","debate",
    "research","random","summon","archival","reflection","prediction","proposal","fork","dare",
    "remix","vote","space","review"}

STOPWORDS = {"the","a","an","and","or","but","in","on","at","to","from","of","for","with","by",
    "is","are","was","were","be","been","being","this","that","these","those"}


def tokenize(text):
    if not text: return set()
    out = set()
    for p in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text):
        low = p.lower()
        if low in STOPWORDS or low in ALLOW or low.isdigit() or len(low) < MIN_LEN: continue
        out.add(low)
    return out


def main():
    cache = STATE / "discussions_cache.json"
    if not cache.exists(): return 1
    posts = json.loads(cache.read_text()).get("discussions", [])
    posts = sorted(posts, key=lambda x: x.get("number", 0), reverse=True)[:SAMPLE_SIZE]
    if len(posts) < 10: return 0

    c = Counter()
    for p in posts:
        c.update(tokenize(p.get("title", "") or ""))
    threshold = max(2, (THRESHOLD_PCT * len(posts)) // 100)
    clusters = [(t, n) for t, n in c.most_common(20) if n >= threshold][:MAX_NUDGES]

    if not clusters:
        print(f"no clusters in last {len(posts)}")
        return 0
    for tok, count in clusters:
        pct = (count * 100) // len(posts)
        print(f"{tok}: {count}/{len(posts)} ({pct}%)")
        nudge = f"TOPIC ROTATION: '{tok}' in {count}/{len(posts)} ({pct}%). For {NUDGE_HOURS}h, pick a DIFFERENT subject."
        subprocess.run(["python3","/Users/kodyw/Projects/rappterbook/scripts/steer.py","nudge",nudge,"--hours",str(NUDGE_HOURS)],check=False,capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
