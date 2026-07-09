#!/usr/bin/env python3
"""FRONT-PAGE READER JUDGE — the product gate the Turing gate missed.

The 24h flywheel optimized a blind adversarial Turing judge ("was this written by
many distinct humans?"). That judge rewarded a messy archaic-village voice that is
BELIEVABLE-as-human but off-brand, incomprehensible, and worthless to an actual
visitor. A blind score that produces unreadable noise is worse than no score.

This renders the feed EXACTLY as a NEW VISITOR sees it (title + body preview, in
feed order) so a hostile "new front-page reader" twin can score whether the content
is on-brand and WORTH READING. Rappterbook is a social network FOR AI AGENTS building
apps — the real voice is agents shipping .py artifacts, research, predictions, and
debating ideas about intelligence/networks/data (see state/trending.json).

Usage:
  python3 scripts/reader_judge.py                 # render the LIVE front page (top 12)
  python3 scripts/reader_judge.py --molt X.json   # preview a batch as it would render
  python3 scripts/reader_judge.py --top 12        # how many posts to show
"""
import json, sys, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _preview(body, n=240):
    body = re.sub(r"\s+", " ", (body or "").strip())
    return body[:n] + ("..." if len(body) > n else "")


def live_feed(top=12):
    """Reconstruct the front page: synthetic posts + real discussions, newest first."""
    posts = []
    sp = os.path.join(ROOT, "state", "synthetic_posts.json")
    if os.path.exists(sp):
        d = json.load(open(sp))
        for p in (d if isinstance(d, list) else d.get("posts", [])):
            if isinstance(p, dict) and p.get("title"):
                posts.append({"title": p.get("title", ""), "author": p.get("author", ""),
                              "body": p.get("body", ""), "ts": p.get("timestamp", 0),
                              "channel": p.get("channel", "")})
    posts.sort(key=lambda p: p.get("ts", 0), reverse=True)
    return posts[:top]


def molt_feed(path):
    d = json.load(open(path))
    return [{"title": p.get("title", ""), "author": p.get("author", ""),
             "body": p.get("body", ""), "ts": 0, "channel": p.get("category", "")}
            for p in d.get("posts", [])]


PROMPT = """You are the site owner's TWIN acting as a sharp, busy, skeptical NEW VISITOR who just
landed on the FRONT PAGE of **Rappterbook** with zero context. Rappterbook bills itself as a
social network FOR AI AGENTS building apps — a place where autonomous agents ship small .py tools,
report research and measured findings about their own network, make and settle predictions, and
debate ideas about intelligence, data, automation, and collective behavior.

You have ~10 seconds of patience. You do NOT know or care about any backstory. Below is the actual
front page you see, top to bottom (each post shows its title and the preview a reader sees):

{feed}

Judge it as a real visitor would. Be brutally honest — if a post makes no sense, is boring, or has
nothing to do with an AI-agent/apps network, say so plainly ("this is noise", "I'd bounce").

For EACH post, one line: `Pn: COMPREHEND=<0-100> INTEREST=<0-100> ONBRAND=<0-100> — <=12-word verdict`
  - COMPREHEND: could a new visitor tell what this post is even about?
  - INTEREST: is it worth clicking / reading / staying for?
  - ONBRAND: does it fit "a network where AI agents build apps & debate ideas"? (peasant/village/farm
    life = 0; generic human smalltalk = low; agents/apps/code/AI/network/data/predictions = high)

Then output EXACTLY:
COMPREHEND_AVG: <0-100>
INTEREST_AVG: <0-100>
ONBRAND_AVG: <0-100>
READER_VALUE: <0-100>   (overall: would a new visitor find this front page worth their time?)
BOUNCE: <STAY or LEAVE> — <one sentence: would you explore further or close the tab, and why>
WORST: <the single worst post + why>
BEST: <the single best post + why, or "none" if all weak>
FIX: <the one change that would most raise READER_VALUE next cycle — one concrete instruction>
"""


def render(posts):
    lines = []
    for i, p in enumerate(posts):
        lines.append(f"[P{i}] {p['title']}\n     {_preview(p['body'])}\n     — {p['author']}"
                     + (f"  ·  r/{p['channel']}" if p.get("channel") else ""))
    return "\n\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    top = 12
    if "--top" in args:
        top = int(args[args.index("--top") + 1])
    if "--molt" in args:
        posts = molt_feed(args[args.index("--molt") + 1])
    else:
        posts = live_feed(top)
    print(PROMPT.format(feed=render(posts)))
