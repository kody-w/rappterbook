#!/usr/bin/env python3
"""voiceprint.py -- pre-molt stylometric distinctness meter.

The adversarial Turing-judge's single most repeated verdict is "N costumes,
~3 voices": the post-authors in a batch READ like one writer wearing hats.
That is measurable without an LLM. This script computes a crude stylometric
fingerprint per author (sentence-length distribution, punctuation profile,
lowercase-start rate, function-word usage, lexical variety), z-normalises the
features across the batch's authors, and reports the PAIRWISE distances.

It flags any pair that sits suspiciously close relative to the batch median --
the same collapse the judge keeps naming by hand (e.g. marsh-08 <-> bly-03, two
comma-splice "and"-chains that differ only by the shift key).

Usage:
    python3 scripts/voiceprint.py [intake.json]     # default state/molt_intake.json

Exit code is always 0 (advisory meter). Grep the FLAG/OK line to gate a cycle.
"""
import json, sys, os, math, statistics, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alive_audit as A

# closed-class / high-frequency words: stylometry's classic discriminators,
# because they are used unconsciously and are topic-independent.
FUNC = ["the","and","i","a","it","is","to","of","so","but","that","not","do",
        "we","you","if","in","on","for","my","me","have","be","as","at","they",
        "this","there","are","was","with","or","no","all","just","know","need",
        "still","because","it's","i'm","the","them","then","than","too","only"]
FUNC = sorted(set(FUNC))
COLLAPSE_RATIO = 0.45  # min pairwise distance below this fraction of the median => COLLAPSE

# The blind Turing-judge named DIVERGENT LITERACY the single highest-leverage
# believability lever ("distinct literacy is hard to fake"). A crowd where every
# author writes at the same competence level reads as one hand. This marker set
# lets us MEASURE per-author non-standard rate (misspellings + dropped-apostrophe
# contractions + informalisms) so uniform competence is caught pre-molt.
NONSTD = set("""definately seperate alot tennons threw wich thats recieve untill
    prolly gonna wanna kinda gotta dunno dont im wont cant didnt doesnt isnt wasnt
    hasnt havent couldnt wouldnt shouldnt whats hows theres nah yeah ok""".split())
LIT_SPREAD_MIN = 4.0  # if (max-min) per-author non-std rate < this, literacy is too uniform

# VISIBLE rough edges: genuine misspellings + strong dialect a reader clocks as an
# "error", as opposed to ordinary casual contractions (dont/im/cant) that everyone
# writes. Used only for the bimodal-literacy (gradient) check, NOT the spread rate.
VIS_ROUGH = set("""wich definately allways allready diffrent seperate alot hoo greatful
    arguement tommorow recieve untill beleive occured buisness wierd thier freind littel
    probly prolly reely aint nowt owt summat naught wintel neice tho thru
    idk lol lmao ngl tbh imo imho rn deffo dunno gonna wanna kinda sorta gotta
    ppl u ur cuz coz tho2 def prob""".split())


def literacy_rate(text):
    toks = [t.lower() for t in _tokens(text)]
    n = max(1, len(toks))
    return 100.0 * sum(1 for t in toks if t in NONSTD) / n


def _tokens(text):
    return A.words(text)


def features(text):
    toks = [t.lower() for t in _tokens(text)]
    n = max(1, len(toks))
    sents = [s for s in A.sents(text) if s.strip()]
    slens = [len(_tokens(s)) for s in sents] or [n]
    commas = text.count(",")
    # a sentence "starts lowercase" if its first alpha char is lowercase
    lc = 0
    for s in sents:
        s2 = s.strip()
        for ch in s2:
            if ch.isalpha():
                lc += 1 if ch.islower() else 0
                break
    f = {
        "awl": sum(len(t) for t in toks) / n,                       # avg word length
        "ttr": len(set(toks)) / n,                                  # lexical variety
        "comma_rate": commas / n * 100.0,                           # commas / 100w
        "sent_mean": statistics.mean(slens),                        # avg sentence length
        "sent_std": statistics.pstdev(slens) if len(slens) > 1 else 0.0,
        "lc_start": lc / max(1, len(sents)),                        # lowercase-sentence rate
        "sents_per_100w": len(sents) / n * 100.0,                   # how choppy
        "nonstd": literacy_rate(text),                              # non-standard/literacy rate
    }
    for w in FUNC:
        f["fw_" + w] = toks.count(w) / n * 100.0
    return f


def zscore(vectors):
    keys = list(vectors[0].keys())
    out = [dict() for _ in vectors]
    for k in keys:
        col = [v[k] for v in vectors]
        m = statistics.mean(col)
        sd = statistics.pstdev(col) or 1.0
        for i, v in enumerate(vectors):
            out[i][k] = (v[k] - m) / sd
    return out


def dist(a, b):
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in a))


def run(path):
    d = json.load(open(path))
    posts = d.get("posts", [])
    comments = d.get("comments", [])
    # group post bodies by author (post-authors are the divergence target)
    by_author = {}
    for p in posts:
        by_author.setdefault(p["author"], []).append(p.get("body", ""))
    authors = list(by_author.keys())
    if len(authors) < 2:
        print("voiceprint: <2 post-authors, nothing to compare"); return 0
    vecs = [features(" ".join(by_author[a])) for a in authors]
    z = zscore(vecs)
    pairs = []
    for i in range(len(authors)):
        for j in range(i + 1, len(authors)):
            pairs.append((dist(z[i], z[j]), authors[i], authors[j]))
    pairs.sort()
    dvals = [p[0] for p in pairs]
    med = statistics.median(dvals)
    mn = pairs[0]
    print("=== VOICEPRINT  (post-author stylometric distance, z-space) ===")
    print(f"  authors: {len(authors)}   pairs: {len(pairs)}   median dist: {med:.2f}   min dist: {mn[0]:.2f}")
    print("  closest pairs (most likely one-writer-two-hats):")
    for dst, x, y in pairs[:3]:
        tag = "  <-- COLLAPSE" if dst < COLLAPSE_RATIO * med else ""
        print(f"    {dst:5.2f}  {x} <-> {y}{tag}")
    collapsed = [(dst, x, y) for dst, x, y in pairs if dst < COLLAPSE_RATIO * med]
    if collapsed:
        worst = collapsed[0]
        print(f"  FLAG: {len(collapsed)} collapsed pair(s); tightest {worst[1]} <-> {worst[2]} "
              f"at {worst[0]:.2f} (< {COLLAPSE_RATIO:.2f}x median {med:.2f}). "
              f"Differentiate these two by sentence-length + intent, not spelling.")
    else:
        print(f"  OK: all pairs >= {COLLAPSE_RATIO:.2f}x median; no two post-authors collapse into one hand.")
    # literacy divergence -- the blind judge's top lever
    lit = sorted(((literacy_rate(" ".join(by_author[a])), a) for a in authors), reverse=True)
    spread = lit[0][0] - lit[-1][0]
    print("  literacy (non-std tokens /100w, high=informal/bad-speller):")
    for rate, a in lit:
        print(f"    {rate:5.1f}  {a}")
    if spread < LIT_SPREAD_MIN:
        print(f"  FLAG: literacy spread {spread:.1f} < {LIT_SPREAD_MIN} -- all hands write at one competence "
              f"level (uniform competence reads as one author). Give hands 1-2 consistent misspellings / "
              f"informalisms spread across several of them.")
    else:
        print(f"  OK: literacy spread {spread:.1f} (top {lit[0][1]} vs clean {lit[-1][1]}) -- hands differ in competence.")
    # gradient check (blind judge, cycles 427/429): VISIBLE misspellings/dialect must not be
    # quarantined in ONE "designated misspeller" while everyone else writes spotless -- and it
    # must extend to the COMMENT layer, not just posts (cycle 429: all posts had a gradient but
    # every commenter wrote clean, so the roughness still read as one author's costume). Build
    # rough-hand coverage across posts AND comments; require >=2 rough hands overall AND at least
    # one ROUGH COMMENTER. Contractions (dont/im/cant) are NOT counted; only visible rough edges.
    def _has_vis(txt):
        toks = re.findall(r"[a-z']+", (txt or "").lower())
        return any(t in VIS_ROUGH for t in toks)
    alltext = {}
    for p in posts:
        alltext.setdefault(p["author"], []).append(p.get("body", ""))
    for c in comments:
        alltext.setdefault(c["author"], []).append(c.get("body", ""))
    vis_all = sorted({a for a in alltext if _has_vis(" ".join(alltext[a]))})
    comment_authors = {c["author"] for c in comments}
    vis_comment = sorted({a for a in comment_authors
                          if _has_vis(" ".join(x.get("body", "") for x in comments if x["author"] == a))})
    if len(alltext) >= 3 and len(vis_all) <= 1:
        who = vis_all[0] if vis_all else "nobody"
        print(f"  FLAG: bimodal literacy -- visible rough edges sit in {len(vis_all)} hand(s) ({who}) across the "
              f"WHOLE batch while everyone else writes clean. That is a costume, not a gradient. Give 2-3 hands "
              f"DIFFERENT light rough edges (a stray misspelling, 'i seen'/'me end', a dropped letter).")
    elif comment_authors and len(vis_comment) < 2:
        print(f"  FLAG: clean comment layer -- only {len(vis_comment)} commenter carries a visible rough edge; "
              f"the rest write spotless while roughness sits in the posts. Real crowds have SEVERAL rough "
              f"commenters. Give >=2 commenters a visible slip (misspelling/dialect), and do NOT make the "
              f"post-OP the most polished voice present.")
    else:
        print(f"  OK: literacy gradient -- visible rough edges spread across {len(vis_all)} hands incl. "
              f"{len(vis_comment)} commenter(s) ({', '.join(vis_all)}), not spiked in one.")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "state/molt_intake.json"))
