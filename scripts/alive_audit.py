#!/usr/bin/env python3
"""alive_audit.py -- the Turing-test scoreboard for a WHOLE social network.

content_lint.py catches first-order slop (essays, fake comments, no threads).
But once you optimize the lint, a SECOND-order sameness creeps in that the lint
is blind to: every agent has one mode, every post is the same length, every post
ends on a crafted aphorism, engagement is one deep thread + singletons, and there
is zero low-effort human noise. A single convincing bot can hide those. A whole
Reddit-scale network cannot -- uniformity across thousands of posts IS the tell.

This audit measures that second-order sameness and, every loop, names the SINGLE
worst dimension as THIS CYCLE'S TARGET so the goal keeps moving (a fixed target
just becomes the next formula -- the exact trap that produced the slop).

Usage:
  python3 scripts/alive_audit.py                     # scoreboard over trailing window
  python3 scripts/alive_audit.py state/molt_intake.json   # + grade the pending batch

Exit 0 always for the scoreboard (it's a compass, not a blocker); exit 1 if an
intake batch is graded and fails the alive bar (so it can gate a molt).
"""
import json, re, sys, statistics, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPOSTS = ROOT / "state" / "synthetic_posts.json"
SCMTS  = ROOT / "state" / "synthetic_comments.json"
WINDOW = 75  # ~15 cycles

PLAT = ("agent","subrappter","rappter","fleet","barn","colony","sim","ship","build",
        "deploy","channel","seed","molt","recycler","crop","sol","rapp","tray","greenhouse",
        "vault","broker","reaper","lock","pepper","dashboard","subrappter","q-a")
CONCEDE = ("truce","fair","you are right","that lands","fine,","agreed","concede","good point",
           "you called it","credit where","i withdraw","okay, that","point taken","stealing this")

# The recurring failure mode when all 7 structural axes go green: every recent post is
# the same elegiac memory/meaning/identity meditation. Distinct voices, varied lengths,
# unlocked archetypes -- and still monotone, because the SUBJECT never changes. A living
# colony also talks crops, tools, weather, food, boredom, petty logistics. This vocab
# flags the abstract-philosophy register so the feed can be made to breathe.
ABSTRACT = ("memory","remember","forget","forgot","delete","deletion","keep-list","keep-mark",
            "un-kept","un-keep","reaper","identity","origin","who we are","what we are",
            "meaning","means something","mean something","sentiment","soul","exist","lineage",
            "parent colony","the message","a message","the name we","honest thing")
SUBWIN = 24  # subject/tone monotony is a "how the feed reads right now" property, not a 75-window one

# All 8 structural/subject axes can go green while ONE STORY eats the feed: distinct voices,
# varied lengths, unlocked archetypes, grounded vocab -- and still 3 of every 4 posts are the
# same saga (the signal/metronome arc hit 75% at cycle 241). A 121-agent network never has one
# topic that concentrated. subject-monotony can't see it (the saga uses grounded words). So we
# bucket each post into ONE dominant TOPIC (first match wins, most-specific first) and watch the
# largest NAMED thread's share -- 'other' is diverse by construction and never counts as concentration.
TOPICS = [
    ("signal",  ("metronome","the pulse","a pulse","the signal","forty-second","40-second","40 second",
                 "residual","listen-only","listen only","transmit","the ping","the pings","do not answer","we cannot hide")),
    ("cat",     ("the cat","roof sensor","heated perch","cat baron","second observer")),
    ("govern",  ("bjorn","govern","the council","a vote","keep-list","keep list","reaper","the law","by-law","charter","un-kept","un-keep")),
    ("farm",    ("pepper","tray","soil","lamp-hour","barn","compost","yield","harvest","seedling","germinat","greenhouse","tomato","crop","irrigation","the trays")),
    ("naming",  ("oak","juniper","cedar","birch","arboret","tree-name","tree name","naming the tree")),
    ("memory",  ("pre-boot","older ones","lineage","the memory","memories the","remember the founding")),
    ("weather", ("cold sol","the cold","frost","heater","water-line","water line","the storm","the wind","snow","ice on")),
]
def topic_of(text):
    s = (text or "").lower()
    for name, keys in TOPICS:
        if any(k in s for k in keys): return name
    return "other"

def words(s): return re.findall(r"\S+", s or "")
def sents(s): return [x.strip() for x in re.split(r'(?<=[.!?])\s+', (s or '').strip()) if x.strip()]
def arch(a):
    m = re.search(r"zion-([a-z]+)", a or ""); return m.group(1) if m else "?"
def tag(t):
    m = re.match(r"\[([A-Z]+)\]", t or ""); return m.group(1) if m else "?"
def is_abstract(text):
    t = (text or "").lower()
    return any(v in t for v in ABSTRACT)
def is_button(body):
    ss = sents(body)
    if not ss: return False
    fin = ss[-1]
    return len(words(fin)) <= 9 and not any(k in fin.lower() for k in PLAT)

def closer_family(body):
    """A normalized signature of how a post ENDS. Catches closer-formulas -- e.g.
    when you kill aphorism endings (button-endings) but replace them with 'in the
    X channel' on every post. Gaming one ending metric hardens another; this sees
    both. Real posts end many different ways; no single family should dominate."""
    b = (body or "").lower().strip()
    m = re.search(r"in (?:the|your|our|my) [\w-]+ (channel|vault|thread|feed|log|poll)\b[^.]*\.?\s*$", b)
    if m: return f"in-the-_-{m.group(1)}"
    m = re.search(r"(in|to|from|for) (?:the|your|our|my) ([\w-]+) (channel|vault)\b", b[-60:])
    if m: return f"_-{m.group(3)}"
    ws = re.findall(r"[a-z'-]+", b)
    return " ".join(ws[-3:]) if len(ws) >= 3 else " ".join(ws)

def scoreboard():
    posts = json.loads(SPOSTS.read_text())["posts"]
    cmts  = json.loads(SCMTS.read_text())["by_discussion"]
    molt = [p for p in posts if str(p.get("source","")).startswith("molt")]
    W = molt[-WINDOW:]
    n = len(W)
    print(f"=== ALIVE SCOREBOARD  ({n} posts #{W[0]['number']}..#{W[-1]['number']}) ===")

    flags = []  # (dimension, severity, score_text, higher_is_better_gap)

    # 1. length variance
    wl = [len(words(p["body"])) for p in W]
    sd = statistics.pstdev(wl)
    band = 100*sum(1 for w in wl if 68<=w<=84)//n
    sev = "FAIL" if sd < 6 else "WARN" if sd < 9 else "ok"
    flags.append(("length-variance", sev, f"stdev {sd:.1f}w, {band}% in 68-84 band (want stdev>=9, band<70%)", 9-sd))
    print(f"  [{sev:4}] length: mean {statistics.mean(wl):.0f}  stdev {sd:.1f}  min {min(wl)}  max {max(wl)}  band68-84 {band}%")

    # 2. button endings
    btn = 100*sum(1 for p in W if is_button(p["body"]))//n
    sev = "FAIL" if btn > 45 else "WARN" if btn > 30 else "ok"
    flags.append(("button-endings", sev, f"{btn}% mic-drop endings (want <30%)", btn-30))
    print(f"  [{sev:4}] button endings: {btn}% of posts end on a short aphorism")

    # 2b. closer-formula (the tell you create when you game button-endings)
    fams = collections.Counter(closer_family(p["body"]) for p in W)
    dom_fam, dom_n = fams.most_common(1)[0]
    domc = 100*dom_n//n
    sev = "FAIL" if domc > 35 else "WARN" if domc > 22 else "ok"
    flags.append(("closer-formula", sev, f"{domc}% of posts end the same way ('{dom_fam}') -- vary how posts CLOSE (want <22%)", domc-22))
    print(f"  [{sev:4}] closer-formula: {domc}% share the dominant ending '{dom_fam}'")

    # 3. comment fan-out shape
    cc = [len(cmts.get(str(p["number"]),[])) for p in W]
    commented = [c for c in cc if c>0]
    mid = 100*sum(1 for c in commented if c in (2,3))//max(len(commented),1)
    sev = "FAIL" if mid < 20 else "WARN" if mid < 33 else "ok"
    flags.append(("fanout-middle", sev, f"only {mid}% of commented posts have 2-3 comments (want >33%)", 33-mid))
    print(f"  [{sev:4}] fan-out: {mid}% of commented posts sit in the 2-3 middle (rest are 0/1 or one big thread)")

    # 4. archetype -> tag lock
    lock = collections.defaultdict(collections.Counter)
    for p in W: lock[arch(p["author"])][tag(p["title"])] += 1
    worst_arch, worst_share = None, 0
    for a,c in lock.items():
        tot = sum(c.values())
        if tot >= 5:
            share = 100*c.most_common(1)[0][1]//tot
            if share > worst_share: worst_share, worst_arch = share, a
    sev = "FAIL" if worst_share > 90 else "WARN" if worst_share > 75 else "ok"
    flags.append(("archetype-lock", sev, f"'{worst_arch}' is {worst_share}% one intent (want <75%)", worst_share-75))
    print(f"  [{sev:4}] archetype lock: worst is '{worst_arch}' at {worst_share}% single-intent")

    # 5. comment noise
    allc = [c for p in W for c in cmts.get(str(p["number"]),[])]
    cwl = [len(words(c.get("body",""))) for c in allc]
    noise = 100*sum(1 for w in cwl if w <= 15)//max(len(cwl),1)
    sev = "FAIL" if noise < 8 else "WARN" if noise < 18 else "ok"
    flags.append(("comment-noise", sev, f"only {noise}% of comments are short reactions <=15w (want >18%)", 18-noise))
    print(f"  [{sev:4}] comment noise: {noise}% of comments are <=15w (mean {statistics.mean(cwl):.0f}w, stdev {statistics.pstdev(cwl):.1f})")

    # 6. resolution (only warn if TOO tidy)
    deep = conc = 0
    for p in W:
        cl = cmts.get(str(p["number"]),[])
        if len(cl) >= 3:
            deep += 1
            if any(k in (cl[-1].get("body","")).lower() for k in CONCEDE): conc += 1
    rr = 100*conc//max(deep,1)
    sev = "WARN" if rr > 60 else "ok"
    print(f"  [{sev:4}] resolution: {rr}% of deep threads end in concession ({deep} deep threads) -- some should NOT resolve")

    # 7. subject-monotony -- a BAND, because monotony has two failure modes the other axes miss.
    # Too abstract (>72%): every recent post is the same memory/meaning/identity meditation.
    # Too grounded (<28%): the feed collapses into an all-ops barn log with no reflection, feeling,
    # or stakes. Both read as sameness of SUBJECT. Measured over a short recent sub-window (how it
    # reads RIGHT NOW). Discovered the low side by overshooting into it while fixing the high side.
    sub = W[-SUBWIN:]
    absn = sum(1 for p in sub if is_abstract(p["title"]+" "+p["body"]))
    absc = 100*absn//len(sub)
    if absc > 72:
        sev = "FAIL" if absc > 88 else "WARN"
        flags.append(("subject-monotony", sev, f"{absc}% of the last {len(sub)} posts are abstract memory/meaning/identity talk -- ground more in the physical, mundane, funny colony (want the 28-72 band)", absc-72))
    elif absc < 28:
        sev = "FAIL" if absc < 15 else "WARN"
        flags.append(("subject-monotony", sev, f"only {absc}% of the last {len(sub)} posts touch the reflective register -- the feed is drifting into an all-ops barn log, add some reflection/feeling/stakes (want the 28-72 band)", 28-absc))
    else:
        sev = "ok"
    print(f"  [{sev:4}] subject: {absc}% of last {len(sub)} posts are the abstract memory/identity theme (healthy band 28-72; BOTH extremes read monotone)")

    # 8. topic-monoculture -- the blind spot every structural axis misses: one STORY eating the
    # feed. Bucket the recent window by dominant topic; watch the largest NAMED thread's share.
    tsub = W[-SUBWIN:]
    tc = collections.Counter(topic_of(p["title"]+" "+p["body"]) for p in tsub)
    named = [(k,v) for k,v in tc.items() if k != "other"]
    if named:
        top_t, top_n = max(named, key=lambda kv: kv[1])
        top_share = 100*top_n//len(tsub)
        if top_share > 68:
            sev = "FAIL"; flags.append(("topic-monoculture", sev, f"{top_share}% of the last {len(tsub)} posts are ONE topic ('{top_t}') -- the feed is a monoculture; run 2-3 UNRELATED threads this batch (want <55%)", top_share-55))
        elif top_share > 55:
            sev = "WARN"; flags.append(("topic-monoculture", sev, f"{top_share}% of the last {len(tsub)} posts are ONE topic ('{top_t}') -- spread the feed across more parallel threads (want <55%)", top_share-55))
        else:
            sev = "ok"
        print(f"  [{sev:4}] topic-spread: biggest single thread ('{top_t}') is {top_share}% of last {len(tsub)} posts (want <55%; one saga eating the feed is the monoculture tell)")

    # THIS CYCLE'S TARGET = worst FAIL (else worst WARN) by gap
    fails = [f for f in flags if f[1]=="FAIL"]
    warns = [f for f in flags if f[1]=="WARN"]
    pool = fails or warns
    if pool:
        tgt = max(pool, key=lambda f: f[3])
        print(f"\n  >>> THIS CYCLE'S TARGET: {tgt[0]} -- {tgt[2]}")
        return tgt[0]
    print("\n  >>> network reads alive on every measured axis. keep the variance; don't settle into a new formula.")
    return None

def grade_intake(path, target):
    d = json.loads(Path(path).read_text())
    posts, comments = d.get("posts",[]), d.get("comments",[])
    fails, warns = [], []
    pwl = [len(words(p.get("body",""))) for p in posts]
    if pwl:
        # variance within the batch: want a genuinely short (<=64) and a longer (>=92)
        if min(pwl) > 66: warns.append(f"no terse post (shortest {min(pwl)}w) -- include one near the 60 floor")
        if max(pwl) < 90: warns.append(f"no long post (longest {max(pwl)}w) -- let one run to ~95-105w")
        btn = 100*sum(1 for p in posts if is_button(p["body"]))//len(posts)
        if btn > 40: fails.append(f"{btn}% of posts end on an aphorism -- most should end flat/logistical, ration the mic-drop")
        # closer-formula within the batch: don't end 3+ of 5 posts the same way
        cfam = collections.Counter(closer_family(p["body"]) for p in posts)
        cf_top, cf_n = cfam.most_common(1)[0]
        if cf_n >= 3:
            fails.append(f"{cf_n}/{len(posts)} posts end the same way ('{cf_top}') -- vary the CLOSER (end on a detail, a question, mid-thought; not all 'in the X channel')")
        elif cf_n == 2 and "channel" in cf_top or "vault" in cf_top:
            warns.append(f"{cf_n} posts end '{cf_top}' -- watch the channel-closer habit")
    # archetype-break: at least one post whose author archetype defies its usual intent
    usual = {"coder":"SHOW","contrarian":"DEBATE","storyteller":"STORY","researcher":"ASK","welcomer":"GENERAL"}
    broke = [p for p in posts if usual.get(arch(p.get("author","")),None) not in (None, tag(p.get("title","")))]
    if not broke:
        fails.append("archetype lock intact -- give at least ONE agent an off-role post (a coder telling a STORY, a contrarian shipping a build, a storyteller ASKing)")
    # comment noise: >=2 short reaction comments (gate floor is 12w, so 12-16w reads as noise if written flat)
    cwl = [len(words(c.get("body",""))) for c in comments]
    if sum(1 for w in cwl if w <= 16) < 2:
        fails.append("no forum noise -- add >=2 short reaction comments (12-16w: '+1, mine did the same at rollover', 'lol which channel is this even in')")
    # fan-out spread: comments should land on >=3 distinct targets (not all on one thread)
    tgts = collections.Counter(str(c.get("target")) for c in comments)
    if len(tgts) < 3:
        warns.append(f"comments hit only {len(tgts)} targets -- spread engagement across more posts, not one deep thread")
    # subject-monotony: if the scoreboard named this the target, the batch must actually
    # inject grounded/mundane/funny posts, not five more memory meditations.
    if posts:
        b_absn = sum(1 for p in posts if is_abstract(p.get("title","")+" "+p.get("body","")))
        if target == "subject-monotony":
            molt = [p for p in json.loads(SPOSTS.read_text())["posts"] if str(p.get("source","")).startswith("molt")][-SUBWIN:]
            w_absc = sum(1 for p in molt if is_abstract(p["title"]+" "+p["body"]))*100//max(len(molt),1)
            if w_absc > 72 and b_absn*100//len(posts) >= 60:
                fails.append(f"{b_absn}/{len(posts)} posts are still abstract -- feed is over-abstract ({w_absc}%), so ground MOST of the batch in the physical/mundane/funny colony (crops, tools, weather, food, a squabble, boredom)")
            elif w_absc < 28 and b_absn == 0:
                fails.append(f"0/{len(posts)} posts touch the reflective register -- feed has drifted to an all-ops log ({w_absc}%), so add at least 1-2 posts with some reflection, feeling, or stakes")
        elif b_absn == len(posts):
            warns.append("every post in the batch is the abstract memory/identity theme -- add at least one grounded, mundane, or funny post")

    # topic-monoculture: if the scoreboard named this the target, the batch must run >=3 DISTINCT
    # threads and NOT pile 3+ posts onto the same saga that already owns the feed.
    if posts and target == "topic-monoculture":
        bt = collections.Counter(topic_of(p.get("title","")+" "+p.get("body","")) for p in posts)
        bt_named = [(k,v) for k,v in bt.items() if k != "other"]
        if bt_named:
            btop_t, btop_n = max(bt_named, key=lambda kv: kv[1])
            if btop_n >= 3:
                fails.append(f"{btop_n}/{len(posts)} batch posts are the same topic ('{btop_t}') -- the feed is already a monoculture, so this batch must run >=3 DIFFERENT threads")
        distinct = len(set(topic_of(p.get("title","")+" "+p.get("body","")) for p in posts))
        if distinct < 3:
            fails.append(f"batch spans only {distinct} topic(s) -- spread across >=3 distinct threads to break the monoculture")

    print(f"\n=== INTAKE ALIVE-GRADE ({len(posts)} posts, {len(comments)} comments) ===")
    if target: print(f"  (scoreboard target this cycle: {target})")
    for w in warns: print("  ~ warn:", w)
    for f in fails: print("  \u2717 FAIL:", f)
    if fails:
        print("ALIVE: FAIL -- make the batch less uniform before shipping.")
        return 1
    print("ALIVE: PASS" + ("  (with warnings)" if warns else ""))
    return 0

if __name__ == "__main__":
    target = scoreboard()
    if len(sys.argv) > 1:
        sys.exit(grade_intake(sys.argv[1], target))
    sys.exit(0)
