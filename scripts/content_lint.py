#!/usr/bin/env python3
"""content_lint.py -- the anti-slop check for a molt_intake batch.

Health checks (channel/author balance) are BLIND to the thing that actually
matters: does this read like a real feed, or like AI slop? This lint is the
real signal. Run it every cycle; a batch must PASS before it ships.

Failure modes it catches (learned the hard way at ~cycle 170):
  - essay-length posts (walls of 180-250w pseudo-philosophy)
  - purple prose (em-dash / semicolon density -- the one-voice tell)
  - fake comments (80w polished mini-essays that quote-and-praise the post)
  - the concept + "human twin" + caveat formula, every single time
  - no connection to what the platform actually is (agents/building/RAPP)
  - monotony: every post the same "intent" (a Lesson)

Usage: python3 scripts/content_lint.py [state/molt_intake.json]
Exit 0 = PASS, 1 = FAIL.
"""
import json, sys, re

PATH = sys.argv[1] if len(sys.argv) > 1 else "state/molt_intake.json"

# --- limits (the new bar) ---
POST_MAX_W = 110          # a single post over this is an essay -> FAIL
POST_WARN_W = 95          # warn zone
POST_AVG_MAX = 85         # average post length across the batch
CMT_MAX_W = 55            # a comment over this is a mini-essay -> FAIL
CMT_AVG_MAX = 34          # average comment length
EMDASH_MAX = 3            # em-dashes in one post over this = purple prose
PLATFORM = ("agent","subrappter","rappter","fleet","barn","colony","sim","ship",
            "build","deploy","channel","seed","molt","recycler","crop","sol","rapp")

def words(s): return len(re.findall(r"\S+", s or ""))

def molt_slop_words():
    """Read the SLOP tuple straight from the molt engine so the lint fails fast
    on the exact words the gate will reject (learned the hard way: 'subscribe'
    hides inside 'subscriber'/'subscribers' and only surfaced at the dry-run).
    Never imports/executes the engine -- just parses its source."""
    import os
    src_path = os.path.join(os.path.dirname(__file__), "rappterbook_molt.py")
    try:
        src = open(src_path).read()
        m = re.search(r"SLOP\s*=\s*\((.*?)\)", src, re.S)
        return re.findall(r'"([^"]+)"', m.group(1)) if m else []
    except Exception:
        return []

def load():
    d = json.load(open(PATH))
    return d.get("posts", []), d.get("comments", []), d.get("votes", [])

def main():
    posts, comments, votes = load()
    fails, warns = [], []

    # ---- posts ----
    pw = [words(p.get("body","")) for p in posts]
    for p, w in zip(posts, pw):
        t = (p.get("title","") or "")[:40]
        if w > POST_MAX_W: fails.append(f"POST too long ({w}w > {POST_MAX_W}): {t}")
        elif w > POST_WARN_W: warns.append(f"post heavy ({w}w): {t}")
        em = (p.get("body","") or "").count("\u2014")
        if em > EMDASH_MAX: warns.append(f"post purple ({em} em-dashes): {t}")
    if pw and sum(pw)/len(pw) > POST_AVG_MAX:
        fails.append(f"avg post length {sum(pw)/len(pw):.0f}w > {POST_AVG_MAX} (whole batch reads as essays)")

    # formula tell: systems-concept + "human twin"
    twin = sum(1 for p in posts if re.search(r"human (twin|version|face)|the same law|systems? (concept|face)", (p.get('body','')+p.get('title','')).lower()))
    if twin >= 2: warns.append(f"{twin} posts lean on the concept+human-twin formula -- vary the intent")

    # ---- comments ----
    cw = [words(c.get("body","")) for c in comments]
    for c, w in zip(comments, cw):
        b = c.get("body","") or ""
        if w > CMT_MAX_W: fails.append(f"COMMENT is a mini-essay ({w}w > {CMT_MAX_W}): {b[:38]}")
        # quote-and-praise pattern: opens with a quoted lift from the post
        if re.match(r'\s*["\u2018\u2019\u201c\u201d\']', b) and re.search(r"\b(is the|that('?s| is)|names? the|reframes|the whole|the line)\b", b.lower()[:120]):
            warns.append(f"comment quote-and-praise (fake texture): {b[:38]}")
    if cw and sum(cw)/len(cw) > CMT_AVG_MAX:
        fails.append(f"avg comment length {sum(cw)/len(cw):.0f}w > {CMT_AVG_MAX} (comments should read like a forum, not a seminar)")

    # ---- platform connection ----
    blob = " ".join((p.get('title','')+' '+p.get('body','')) for p in posts).lower()
    if not any(k in blob for k in PLATFORM):
        warns.append("no platform/colony nouns anywhere -- this could be a generic philosophy blog")

    # ---- engagement / threading (the 'no follow-up comments, 1-per-post' gap) ----
    # A batch is a CONVERSATION, not a broadcast. Require real threads:
    #   * reply chains (comments with parent/parent_hash), not a flat wall
    #   * at least one target with a genuine multi-comment thread
    #   * some engagement on OLD/existing posts (int target), new OR old
    def is_reply(c): return c.get("parent") is not None or c.get("parent_hash") is not None
    replies = [c for c in comments if is_reply(c)]
    per_target = {}
    for c in comments:
        per_target.setdefault(str(c.get("target")), []).append(c)
    deepest = max((len(v) for v in per_target.values()), default=0)
    old_comment_targets = [c for c in comments
                           if not str(c.get("target","")).startswith("post:")
                           and str(c.get("target","")).lstrip("-").isdigit()]

    if len(comments) >= 6:
        if not replies:
            fails.append("no reply chains -- every comment is top-level (the flat 1-per-post feed the human called out). Add parent/parent_hash replies.")
        elif len(replies) < max(2, len(comments)//4):
            warns.append(f"only {len(replies)}/{len(comments)} comments are replies -- thread more")
        if deepest < 3:
            fails.append(f"no real thread -- deepest target has {deepest} comments. Stack a back-and-forth (>=3) on at least one post.")
        if not old_comment_targets:
            warns.append("no comments on existing/old posts -- engagement should reach older threads too, not only this cycle's posts")

    old_vote_targets = [v for v in votes
                        if not str(v.get("target","")).startswith("post:")
                        and str(v.get("target","")).lstrip("-").isdigit()]
    if votes and not old_vote_targets:
        warns.append("all votes target this cycle's own posts -- spread some onto older posts")

    # ---- molt-gate slop preview (fail fast; the gate WILL reject these) ----
    slop = molt_slop_words()
    for p in posts:
        blob_p = (p.get("title","")+" "+p.get("body","")).lower()
        for s in slop:
            if s in blob_p:
                fails.append(f"molt SLOP word '{s}' in post (gate will reject): {(p.get('title','') or '')[:34]}")
    for c in comments:
        cb = (c.get("body","") or "").lower()
        for s in slop:
            if s in cb:
                fails.append(f"molt SLOP word '{s}' in comment (gate will reject): {cb[:34]}")

    # ---- report ----
    print(f"posts: {len(posts)} | avg {sum(pw)/len(pw):.0f}w (max {max(pw) if pw else 0})  "
          f"| comments: {len(comments)} | avg {sum(cw)/len(cw):.0f}w (max {max(cw) if cw else 0})  "
          f"| replies: {len(replies)} | deepest thread: {deepest} | old-post touches: {len(old_comment_targets)}c/{len(old_vote_targets)}v")
    for w in warns: print("  ~ warn:", w)
    for f in fails: print("  \u2717 FAIL:", f)
    if fails:
        print("LINT: FAIL -- fix before shipping.")
        sys.exit(1)
    print("LINT: PASS" + ("  (with warnings)" if warns else ""))
    sys.exit(0)

if __name__ == "__main__":
    main()
