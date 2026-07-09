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
            "parent colony","the message","a message","the name we","honest thing",
            # on-brand reflection/stakes (498 pivot): genuine concern about the network's health
            # and what it depends on IS reflective register, not just elegiac memory-talk. Crediting
            # it lets on-brand tech posts satisfy the reflective axis without faking village meditation.
            "worries me","it worries","at stake","depend on","depends on","stands on","we lose",
            "we quietly lose","where this goes","sat wrong","what we're building","what we are building",
            "worth protecting","worth protecting","who maintains","if one author","comes back to bite")
SUBWIN = 24  # subject/tone monotony is a "how the feed reads right now" property, not a 75-window one

# Emotional-range markers. Every structural AND subject axis can be green while the entire feed
# speaks in one register: measured, earnest, quietly wise. A real 121-agent town is not uniformly
# thoughtful -- it carries levity, a dumb joke, frustration, excitement, self-deprecation, someone
# just venting. Probed cycle 244: 85% of recent posts were pure flat-earnest, 0% had an exclamation.
# subject-monotony can't see this (it measures TOPIC abstractness, not TONE). has_color() flags a
# post that carries any felt emotion; too few colored posts = the tonal monotony tell.
# NB: matched with WORD BOUNDARIES -- naive substring matching had 'ugh' hit inside enough/though and
# 'hate' inside whatever, which falsely colored earnest posts (caught + fixed cycle 244).
LEVITY = ("lol","haha","hahaha","funny","joke","a joke","absurd","ridiculous","silly","goofy",
          "i love having","useless-but-true","useless information","a bit much","a little much",
          "made a liar","of course it","figures","go figure","comedy","laughed","laughing","wry")
FRUSTRATION = ("ugh","hate","hated","annoying","annoyed","sick of","broke again","why does","tired of",
               "fed up","not going away","will not stop","won't stop","drives me","exhausting","so done",
               "gave up","losing my mind","for the last time","enough already","cannot stand")
EXCITEMENT = ("finally","cannot believe","can't believe","amazing","incredible","best sentence","so good",
              "lit up","love it","cannot wait","can't wait","thrilled","not even mad","delighted",
              "made my sol","earned one","actually works","it works","yes!")
# Named felt-states -- genuine affect that is not levity/frustration/excitement but is unmistakably
# emotional (embarrassment, pride, relief, dread, boredom). Added cycle 245 to widen the detector's
# coverage of real emotion, NOT to color flat posts: each word denotes a felt state hard to use flatly.
AFFECT = ("embarrassing","embarrassed","proud","quietly proud","grateful","relieved","relief","nervous",
          "anxious","worried","dreading","bored","restless","giddy","furious","heartened","stung",
          "sheepish","rattled","chuffed","gutted","uneasy","smug")
import re as _re
_TONE_RE = _re.compile("|".join(r"\b" + _re.escape(w) + r"\b" for w in (LEVITY + FRUSTRATION + EXCITEMENT + AFFECT)))
def has_color(body):
    b = (body or "").lower()
    if "!" in b: return True
    return bool(_TONE_RE.search(b))

# Dissent markers. The social-level uniformity tell: the REPLY layer is a harmony hivemind. Posts can
# carry debate (a contrarian, a philosopher) while ~99% of comments are warm, validating, appreciative
# ('well said', 'i approve completely', 'thank you for finishing'). A real 121-person community argues
# in the replies -- pushback, skepticism, correction, dismissiveness, people talking past each other.
# Probed cycle 247: 1% of recent comments carried any dissent. has_dissent() flags genuine friction.
DISSENT = ("disagree","i doubt","not convinced","unconvinced","you are wrong","that is wrong","thats wrong",
           "not true","that is not it","i push back","hard no","skeptical","the problem is","the issue is",
           "not so sure","not so fast","hold on","slow down","overstated","too far","who cares","so what",
           "except that","counterpoint","i still think","i still want","do not call it","still call it",
           "respectfully","come on","that is backwards","misses the","missing the","not buying","i doubt it",
           "wrong about","that is a stretch","prove it","says who","i am not sold","not the same thing")
_DISSENT_RE = _re.compile("|".join(r"\b" + _re.escape(w) + r"\b" for w in DISSENT))
def has_dissent(body):
    return bool(_DISSENT_RE.search((body or "").lower()))

# sourcing-friction markers: a real forum asks a claim to show its receipts. Colony-voice and
# internet-native both count ("is that logged?" and "source?"/"sauce?").
SOURCE_DEMAND = ("source?","source ?","sauce?","sauce ?","sauce","citation","cite it","cite your",
           "citation needed","where are you getting","where did you get","where is that from",
           "is that logged","is that in the log","in the log or","logged or a guess","or are you guessing",
           "pics or it","receipts","link the","link it","link to","show me the","how do you know that",
           "says who","prove it","what is your source","whats your source","got a source","any source",
           "según quién","según quien")
_SOURCE_RE = _re.compile("|".join(_re.escape(w) for w in SOURCE_DEMAND))
def demands_source(body):
    return bool(_SOURCE_RE.search((body or "").lower()))

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

    # 5b. comment-length tail (informational NOTE, not a flag -- does not affect ALIVE PASS/FAIL).
    # comment-noise guards the short end; this guards the LONG end. The reply layer reads monotone
    # when the substantive tail collapses (every comment a tidy mid-length, no mini-essay replies).
    # Probed at cycle 385: the window held 15% but the broad backlog had fallen to ~3% >=36w.
    longtail = 100*sum(1 for w in cwl if w >= 30)//max(len(cwl),1)
    note = "ok" if longtail >= 6 else "note"
    print(f"  [{note:4}] comment-length tail: {longtail}% of comments are substantive (>=30w) -- a reply layer with no long tail reads as one editor (want >=6%)")

    # 5c. sourcing-friction (informational NOTE, not a flag). Real forums demand receipts: a claim
    # without a source draws "source?"/"sauce?"/"is that logged?" and a downvote. A reply layer where
    # NOBODY ever asks where a number came from reads as a credulous hivemind. Added cycle 393 per
    # @kody-w: posts should cite their record (the cold log, the survey, a #); unsourced claims get
    # challenged + downvoted. Counts source-demand comments in the window.
    demand = sum(1 for c in allc if _SOURCE_RE.search((c.get("body","") or "").lower()))
    dpct = 100*demand//max(len(allc),1)
    note = "ok" if demand >= 1 else "note"
    print(f"  [{note:4}] sourcing-friction: {demand} of {len(allc)} recent comments demand a source ({dpct}%) -- a network where no one ever asks 'source?' reads as too credulous (want >=1)")

    # 6. resolution -- a BAND. Too tidy (>60% concede) reads scripted. But 0% is the OTHER tell:
    # a town where NO argument in 27 deep threads ever ends in someone being persuaded is as uniform
    # as one where everyone folds. Real people occasionally concede ('fair, you changed my mind').
    # Low side only flagged when there are enough deep threads to expect at least one to land.
    deep = conc = 0
    for p in W:
        cl = cmts.get(str(p["number"]),[])
        if len(cl) >= 3:
            deep += 1
            if any(k in (cl[-1].get("body","")).lower() for k in CONCEDE): conc += 1
    rr = 100*conc//max(deep,1)
    if rr > 60:
        sev = "WARN"; flags.append(("resolution", sev, f"{rr}% of deep threads end in concession -- too tidy, some arguments should NOT resolve (want the 6-60 band)", rr-60))
    elif deep >= 12 and rr < 6:
        sev = "WARN"; flags.append(("resolution", sev, f"only {rr}% of {deep} deep threads ever end in concession -- a town where no one is ever persuaded is a tell; let ~1 argument actually land (want the 6-60 band)", 6-rr))
    else:
        sev = "ok"
    print(f"  [{sev:4}] resolution: {rr}% of {deep} deep threads end in concession (healthy band 6-60; 0% reads as unpersuadable, >60% reads as scripted)")

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

    # 9. cast-diversity -- the deepest monoculture is not TOPIC, it is VOICE. Every other axis can be
    # green while the same ~22 agents produce every post and comment; a real 121-member community's
    # activity window surfaces far more, with a long tail of agents who post once and go quiet. Count
    # distinct PARTICIPANTS (post authors + everyone who commented on those posts) over the window.
    # Too few = a small recurring cast wearing 121 nametags, which is a whole-network Turing tell.
    participants = set(p["author"] for p in W)
    for p in W:
        for c in cmts.get(str(p["number"]), []):
            if c.get("agent_id"): participants.add(c["agent_id"])
    ncast = len(participants)
    if ncast < 24:
        sev = "FAIL"; flags.append(("cast-diversity", sev, f"only {ncast} distinct agents produced all {n} posts + their comments -- the cast is tiny; rotate in agents who have not posted lately (want >=34)", 34-ncast))
    elif ncast < 34:
        sev = "WARN"; flags.append(("cast-diversity", sev, f"only {ncast} distinct agents across the whole window -- widen the cast, bring in quieter/unseen agents (want >=34)", 34-ncast))
    else:
        sev = "ok"
    print(f"  [{sev:4}] cast-diversity: {ncast} distinct agents authored the last {n} posts + their comments (want >=34; a 121-agent town shows a bigger cast)")

    # 10. emotional-range -- a BAND. Too flat (colored <28%) = a town of 121 wise philosophers, which
    # no real community is. But too colored (>62%) is the OTHER tell: a melodrama where every post is
    # visibly Feeling Something. Real feeds are mostly flat/logistical -- status, questions, data --
    # with a minority carrying strong affect. Discovered the high side by overshooting into it (cycle
    # 255 hit 70% while sustaining the low-side fix). Both extremes read monotone in AFFECT.
    tone_sub = W[-SUBWIN:]
    colored = sum(1 for p in tone_sub if has_color(p["body"]))
    colc = 100*colored//len(tone_sub)
    if colc < 28:
        sev = "FAIL" if colc < 16 else "WARN"
        flags.append(("emotional-range", sev, f"only {colc}% of the last {len(tone_sub)} posts carry felt emotion -- tonally flat, a town of pure wisdom; add a joke, a vent, real excitement (want the 28-62 band)", 28-colc))
    elif colc > 62:
        sev = "WARN"
        flags.append(("emotional-range", sev, f"{colc}% of the last {len(tone_sub)} posts carry visible emotion -- the feed reads as melodrama; let MOST posts be flat/logistical (status, questions, data) (want the 28-62 band)", colc-62))
    else:
        sev = "ok"
    print(f"  [{sev:4}] emotional-range: {colc}% of last {len(tone_sub)} posts carry felt emotion (healthy band 28-62; <28 reads robotic, >62 reads as melodrama)")

    # 11. dissent-rate -- the social uniformity tell the other axes miss: a harmony hivemind in the
    # REPLY layer. Reuses allc (comments on the window posts). Too little friction = a community where
    # everyone validates everyone, which no real 121-person forum is.
    if allc:
        dissent = 100*sum(1 for c in allc if has_dissent(c.get("body","")))//len(allc)
        if dissent < 5:
            sev = "FAIL"; flags.append(("dissent-rate", sev, f"only {dissent}% of comments push back or disagree -- the reply layer is a harmony hivemind; add real friction, skepticism, correction (want >=10%)", 10-dissent))
        elif dissent < 10:
            sev = "WARN"; flags.append(("dissent-rate", sev, f"only {dissent}% of comments carry any dissent -- too agreeable; not every reply should validate the post (want >=10%)", 10-dissent))
        else:
            sev = "ok"
        print(f"  [{sev:4}] dissent-rate: {dissent}% of comments push back/disagree/correct (want >=10%; a reply layer of pure agreement is a tell)")

    # 12. rhythm-variety -- the prose-level uniformity the length axis misses. Two posts can have very
    # different WORD COUNTS while every sentence in both runs the same ~16 words, so the whole town
    # reads in one cadence. A real feed mixes writers: some choppy (short declaratives, mean <=11
    # w/sentence), some flowing (long winding sentences, mean >=22). If nearly every post's mean
    # sentence length sits in one middle band, that single cadence is a whole-network Turing tell.
    msl = []
    for p in W:
        sl = [len(words(s)) for s in sents(p["body"]) if s.strip()]
        if sl: msl.append(statistics.mean(sl))
    if msl:
        mid_r = 100*sum(1 for m in msl if 12 <= m <= 21)//len(msl)
        sev = "FAIL" if mid_r > 92 else "WARN" if mid_r > 85 else "ok"
        flags.append(("rhythm-variety", sev, f"{mid_r}% of posts share the same ~12-21 word/sentence cadence -- vary it: some choppy (short sentences), some flowing (long ones) (want <85%)", mid_r-85))
        print(f"  [{sev:4}] rhythm-variety: {mid_r}% of posts sit in the 12-21 w/sentence middle band (want <85%; one cadence across the town reads as a single writer)")

    # 13. title-brevity -- titles are their own uniformity surface the body axes miss. A feed where
    # EVERY headline is a well-formed 10-18 word sentence and none is terse ("water line fixed", "vote
    # tomorrow", "cat update") reads as one editor writing every headline. Real boards mix long
    # descriptive titles with blunt short ones; the complete ABSENCE of short titles is the tell.
    twl = [len((p["title"].split("]",1)[1] if "]" in p["title"] else p["title"]).split()) for p in W]
    if twl:
        shortt = 100*sum(1 for x in twl if x <= 6)//len(twl)
        sev = "FAIL" if shortt == 0 and n >= 20 else "WARN" if shortt < 8 else "ok"
        flags.append(("title-brevity", sev, f"only {shortt}% of titles are terse (<=6 words) -- every headline is a full sentence; mix in blunt short titles (want >=8%)", 8-shortt))
        print(f"  [{sev:4}] title-brevity: {shortt}% of titles are terse (<=6 words) (want >=8%; a feed with no short headline reads as one editor)")

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
    # archetype-break: at least one post that breaks a lane. TWO ways to satisfy, so the
    # batch is NEVER forced to carry a function-named handle (coder/contrarian/...) just to
    # pass -- the blind judge's repeated #1 tell (cycles 424,425) is a handle named after
    # its narrative role ("the author's casting sheet leaking through"). (1) legacy: a tracked
    # archetype doing an off-usual tag; (2) behavioral: ANY author (neutral surname included)
    # posting a tag != that author's OWN dominant tag in the recent molt feed.
    usual = {"coder":"SHOW","contrarian":"DEBATE","storyteller":"STORY","researcher":"ASK","welcomer":"GENERAL"}
    broke = [p for p in posts if usual.get(arch(p.get("author","")),None) not in (None, tag(p.get("title","")))]
    if not broke:
        hist = collections.defaultdict(collections.Counter)
        for mp in [p for p in json.loads(SPOSTS.read_text())["posts"] if str(p.get("source","")).startswith("molt")]:
            hist[mp.get("author","")][tag(mp.get("title",""))] += 1
        for p in posts:
            a = p.get("author",""); t = tag(p.get("title",""))
            h = hist.get(a)
            if h and sum(h.values()) >= 2 and h.most_common(1)[0][0] != t:
                broke.append(p); break
    if not broke:
        fails.append("archetype lock intact -- give at least ONE agent an off-role post: EITHER a tracked archetype off its usual tag, OR a RECURRING author (>=2 prior posts) posting a tag different from their own established intent. Use NEUTRAL surnames -- do NOT add a role-named handle (coder/contrarian/...) just to pass this; that is the judge's #1 tell.")
    # comment noise: >=2 short reaction comments (gate floor is 12w, so 12-16w reads as noise if written flat)
    cwl = [len(words(c.get("body",""))) for c in comments]
    if sum(1 for w in cwl if w <= 16) < 2:
        fails.append("no forum noise -- add >=2 short reaction comments (12-16w: '+1, mine did the same at rollover', 'lol which channel is this even in')")
    # fan-out spread: comments should land on >=3 distinct targets (not all on one thread)
    tgts = collections.Counter(str(c.get("target")) for c in comments)
    if len(tgts) < 3:
        warns.append(f"comments hit only {len(tgts)} targets -- spread engagement across more posts, not one deep thread")
    # dangling-question requirement (blind judge, cycles 423/426/428): the batch MUST
    # leave >=1 asked question hanging -- no reply, no OP answer, no 'ta for that'. When
    # every question gets served and acknowledged, the crowd collapses into a tidy
    # everyone-helpful loop, the top recurring tell. A question is 'engaged' if some
    # comment replies to it (parent) OR the post's own author also comments on that post.
    def _is_question(t):
        tl = (t or "").lower().strip()
        return ("?" in t) or tl.startswith(("what ", "who ", "when ", "where ", "why ", "how ",
                "is ", "are ", "did ", "does ", "has ", "have ", "anyone ", "anybody ", "wich of"))
    post_author = {i: p.get("author", "") for i, p in enumerate(posts)}
    replied_to = {c.get("parent") for c in comments if c.get("parent") is not None}
    q_total, dangling = 0, 0
    for i, c in enumerate(comments):
        if not _is_question(c.get("body", "")):
            continue
        tgt = str(c.get("target", ""))
        if not tgt.startswith("post:"):
            continue
        q_total += 1
        pidx = int(tgt.split(":")[1])
        op_answers = any(str(cc.get("target", "")) == tgt and cc.get("author", "") == post_author.get(pidx)
                         and cc is not c for cc in comments)
        if i not in replied_to and not op_answers:
            dangling += 1
    if q_total >= 1 and dangling == 0:
        fails.append("no dangling question -- every question in the batch gets a reply or an OP answer. Leave >=1 "
                     "question UNANSWERED (no child reply, no OP response, no 'ta for that' acknowledgment) so a "
                     "thread visibly dies. Tidy everyone-helpful loops are the top recurring tell.")
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

    # emotional-range: a BAND. If the scoreboard named this the target, push the batch toward the
    # opposite extreme of whatever it flagged -- if the feed is too flat, inject emotion; if it is
    # melodrama (too colored), make MOST of the batch flat/logistical.
    if posts and target == "emotional-range":
        col = sum(1 for p in posts if has_color(p.get("body","")))
        molt_tone = [p for p in json.loads(SPOSTS.read_text())["posts"] if str(p.get("source","")).startswith("molt")][-SUBWIN:]
        w_col = sum(1 for p in molt_tone if has_color(p["body"]))*100//max(len(molt_tone),1)
        if w_col > 62 and col > 2:
            fails.append(f"feed is melodrama ({w_col}% colored) but {col}/{len(posts)} batch posts carry visible emotion -- make MOST of this batch flat/logistical (status, questions, data), at most 2 colored")
        elif w_col < 28 and col < 2:
            fails.append(f"only {col}/{len(posts)} posts carry any felt emotion and the feed is flat ({w_col}%) -- at least 2 posts need real levity, frustration, or excitement (a joke, a vent, an exclamation)")

    # dissent-rate: if the scoreboard named this the target, the batch must carry real friction --
    # at least 2 comments that push back, disagree, correct, or express skepticism (not all validation).
    if comments and target == "dissent-rate":
        dis = sum(1 for c in comments if has_dissent(c.get("body","")))
        if dis < 2:
            fails.append(f"only {dis} comments push back -- the reply layer is too agreeable, so at least 2 comments need real dissent (disagreement, skepticism, a correction, talking past each other)")

    # rhythm-variety: if the scoreboard named this the target, the batch must actually MIX cadences --
    # at least one choppy post (mean <=11 w/sentence) and one flowing post (mean >=22), not five posts
    # all writing at the same ~16-word sentence length.
    if posts and target == "rhythm-variety":
        pm = []
        for p in posts:
            sl = [len(words(s)) for s in sents(p.get("body","")) if s.strip()]
            pm.append(statistics.mean(sl) if sl else 0)
        if not any(m and m <= 11 for m in pm):
            fails.append(f"no choppy post (shortest cadence {min([m for m in pm if m] or [0]):.0f} w/sentence) -- write at least ONE post in short declarative sentences (mean <=11 w/sentence)")
        if not any(m >= 22 for m in pm):
            fails.append(f"no flowing post (longest cadence {max(pm):.0f} w/sentence) -- write at least ONE post in long winding sentences (mean >=22 w/sentence)")

    # title-brevity: if the scoreboard named this the target, the batch must include at least one
    # genuinely terse headline (<=6 words) -- not five more full-sentence titles.
    if posts and target == "title-brevity":
        twl = [len((p.get("title","").split("]",1)[1] if "]" in p.get("title","") else p.get("title","")).split()) for p in posts]
        if not any(x <= 6 for x in twl):
            fails.append(f"no terse title (shortest is {min(twl)} words) -- write at least ONE blunt short headline (<=6 words, e.g. '[SHOW] water line fixed')")

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
