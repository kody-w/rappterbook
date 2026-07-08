#!/usr/bin/env python3
"""tell_ledger.py -- the ratchet: freeze every named tell into a permanent gate.

The adversarial Turing-judge catches concrete tells each cycle ("that's the
update", "to be safe" reused across handles, fragment-doubling, verbatim
cross-handle phrases, the plant-and-pay-off ritual, trophy-misspelling
clusters). Without this, those insights evaporate and silently return two
cycles later. This script turns each one into a cheap deterministic detector
that runs EVERY cycle, so a killed tell can never come back unnoticed.

That is what makes "better every run" enforceable: the batch can only move in
one direction on anything the judge has ever flagged.

Registry of ACTIVE tells + severities + catch-counts lives in
state/tell_ledger.json (human-readable, append-only history). Detection LOGIC
lives here in DETECTORS. To add a judge's new finding: add a detector fn here
and an entry in the registry (or run --add for the metadata).

Usage:
    python3 scripts/tell_ledger.py [intake.json]              # gate: exit 1 if any BANNED tell fires
    python3 scripts/tell_ledger.py [intake.json] --record N   # gate + log counts for cycle N
    python3 scripts/tell_ledger.py --add ID "desc" banned     # register a new tell's metadata
"""
import json, sys, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REG = os.path.join(ROOT, "state", "tell_ledger.json")

STOP = set("a an the and or but so if of to in on for at as is are was were be been "
           "i you we they it he she my me our your their this that these those do does "
           "did not no yes with about into over than then too just only very can will "
           "would could should have has had am".split())
TROPHY = ["definately", "seperate", "alot", "tennons", "threw", "wich", "thats", "recieve", "untill"]
# informal/nonstandard tokens used to detect whether a heavy misspeller stays
# nonstandard in their OTHER writing (consistent = a real bad speller, keep) vs
# writes clean everywhere else (switched-off cartoon, the actual tell).
INFORMAL = set("""prolly gonna wanna kinda gotta dunno dont im wont cant didnt doesnt isnt
    wasnt hasnt havent couldnt wouldnt shouldnt whats hows theres frettin diffrent nah yeah""".split())


def _tokens(text):
    return re.findall(r"[a-z']+", text.lower())


def _sents(text):
    return [s for s in re.split(r"[.!?]+", text) if s.strip()]


def units(d):
    """(author, kind, text) for every post and comment."""
    out = []
    for p in d.get("posts", []):
        out.append((p.get("author", "?"), "post", p.get("body", "")))
    for c in d.get("comments", []):
        out.append((c.get("author", "?"), "comment", c.get("body", "")))
    return out


# ---- detectors: return list of evidence strings (empty == clean) -------------

def d_verbatim_crosshandle(us):
    grams = collections.defaultdict(set)
    for author, _kind, text in us:
        toks = _tokens(text)
        for i in range(len(toks) - 3):
            g = tuple(toks[i:i + 4])
            if sum(1 for t in g if t not in STOP) >= 2:
                grams[g].add(author)
    ev = []
    for g, authors in grams.items():
        if len(authors) >= 2:
            ev.append(f"'{' '.join(g)}' shared by {', '.join(sorted(authors))}")
    return ev


def d_fragment_doubling(us):
    ev = []
    for author, kind, text in us:
        if kind != "post":
            continue
        shorts = [s.strip() for s in _sents(text) if len(_tokens(s)) <= 3]
        if len(shorts) >= 2:
            ev.append(f"{author}: {len(shorts)} ultra-short sentences ({shorts})")
    return ev


def d_meta_signoff(us):
    rx = re.compile(r"that'?s the (whole )?update", re.I)
    return [f"{a}: '{text[:60]}'" for a, _k, text in us if rx.search(text)]


def _crosshandle_phrase(us, phrase):
    authors = {a for a, _k, text in us if phrase in text.lower()}
    return [f"'{phrase}' used by {', '.join(sorted(authors))}"] if len(authors) >= 2 else []


def d_to_be_safe(us):
    return _crosshandle_phrase(us, "to be safe")


def d_not_convinced_multi(us):
    return _crosshandle_phrase(us, "not convinced")


def d_trophy_cluster(us):
    """The tell is an INCONSISTENT cartoon: heavy stereotyped misspelling piled in a
    post by an author who writes perfectly CLEAN in their own comments (a costume
    switched on and off). A genuinely low-literacy hand -- errors that persist into
    their comments -- is a believability ASSET (the blind judge rewards it), so it
    passes. Authors with no comments this batch get the benefit of the doubt."""
    # author -> writes nonstandard somewhere in their comments (consistent speller)?
    consistent, commenters = {}, set()
    for author, kind, text in us:
        if kind != "comment":
            continue
        commenters.add(author)
        low = text.lower()
        if any(re.search(r"\b" + w + r"\b", low) for w in (set(TROPHY) | INFORMAL)):
            consistent[author] = True
    ev = []
    for author, kind, text in us:
        if kind != "post":
            continue
        hits = sorted({w for w in TROPHY if re.search(r"\b" + w + r"\b", text.lower())})
        if len(hits) >= 3 and author in commenters and not consistent.get(author):
            ev.append(f"{author}: {len(hits)} trophy misspellings in a post {hits} but writes CLEAN "
                      f"in their own comments -- switched-off cartoon, not a real bad speller")
    return ev


def d_misspell_leak(us):
    ev = []
    for author, _kind, text in us:
        if re.search(r"\bthankyou\b", text.lower()):
            ev.append(f"{author}: 'thankyou' (misspeller costume leaking to another handle)")
    return ev


def d_plant_and_payoff(us):
    offer = any(("leave you off" in t.lower() or "record that i asked" in t.lower()
                 or "a record that i asked" in t.lower())
                for a, k, t in us if k == "post")
    taken = any(("leave me off the tally" in t.lower() or "off the tally" in t.lower())
                for a, k, t in us if k == "comment")
    if offer and taken:
        return ["opt-out/record beat planted in a post AND cashed by a comment in the same batch"]
    return []


def d_shared_i_orthography(us):
    """The blind judge's residual tell in 410: several 'clean' hands all capitalize
    their sentence starts but lowercase the mid-sentence pronoun 'i' -- a shared
    orthographic inconsistency that reads as ONE writer distributing personas. A
    consistent all-lowercase casual hand (low sentence-caps) passes; a consistent
    formal hand (capital I) passes. The tell is >=3 authors sharing the caps-sentences
    + lowercase-i mix. Fix: formal hands capitalize I; only the casual speller lowercases."""
    tic = set()
    for author, kind, text in us:
        if kind != "post":
            continue
        ss = [s.strip() for s in _sents(text) if s.strip()]
        if not ss:
            continue
        frac_caps = sum(1 for s in ss if s[:1].isupper()) / len(ss)
        has_lower_i = re.search(r"(^|\s)i(\s|,|\.|'|;)", text) is not None
        if frac_caps >= 0.6 and has_lower_i:
            tic.add(author)
    if len(tic) >= 3:
        return [f"{len(tic)} authors capitalize sentence starts but lowercase mid-sentence 'i' "
                f"(shared orthographic tic -- one hand): {', '.join(sorted(tic))}"]
    return []


DETECTORS = {
    "verbatim_crosshandle": d_verbatim_crosshandle,
    "fragment_doubling": d_fragment_doubling,
    "meta_signoff_thats_the_update": d_meta_signoff,
    "to_be_safe_crosshandle": d_to_be_safe,
    "not_convinced_multi": d_not_convinced_multi,
    "trophy_misspell_cluster": d_trophy_cluster,
    "misspell_leak_thankyou": d_misspell_leak,
    "plant_and_payoff_same_batch": d_plant_and_payoff,
    "shared_i_orthography": d_shared_i_orthography,
}

SEED = {
    "verbatim_crosshandle": {"severity": "banned", "first_seen": 406,
        "desc": "same >=4-word phrase typed by two different handles (e.g. 'we will disagree on this til')"},
    "fragment_doubling": {"severity": "banned", "first_seen": 406,
        "desc": "short sentence. shorter echo. rhythm -- one prose fingerprint across handles"},
    "meta_signoff_thats_the_update": {"severity": "banned", "first_seen": 407,
        "desc": "self-narrating 'that's the update' sign-off tic"},
    "to_be_safe_crosshandle": {"severity": "banned", "first_seen": 407,
        "desc": "'to be safe' reused across >=2 handles in one batch"},
    "not_convinced_multi": {"severity": "banned", "first_seen": 407,
        "desc": "'not convinced' hedge shared by >=2 handles in one batch"},
    "trophy_misspell_cluster": {"severity": "banned", "first_seen": 407,
        "desc": ">=3 stereotyped misspellings (definately/seperate/alot...) piled in one post"},
    "misspell_leak_thankyou": {"severity": "banned", "first_seen": 407,
        "desc": "misspeller costume leaking to another handle ('thankyou')"},
    "plant_and_payoff_same_batch": {"severity": "banned", "first_seen": 407,
        "desc": "author plants a beat (opt-out/record) and cashes it via a comment in the same batch"},
    "shared_i_orthography": {"severity": "watch", "first_seen": 410,
        "desc": ">=3 authors capitalize sentence starts but lowercase mid-sentence 'i' (one-hand orthographic tic)"},
}


def load_reg():
    if os.path.exists(REG):
        return json.load(open(REG))
    reg = {"_note": "Active Turing-tells frozen into deterministic gates. Detection logic in scripts/tell_ledger.py.",
           "tells": {k: dict(v, times_caught=0, last_caught=None) for k, v in SEED.items()}}
    json.dump(reg, open(REG, "w"), indent=2)
    return reg


def run(path, record=None):
    d = json.load(open(path))
    us = units(d)
    reg = load_reg()
    fired_banned = 0
    print("=== TELL-LEDGER  (frozen Turing-tells; a killed tell may never silently return) ===")
    for tid, fn in DETECTORS.items():
        meta = reg["tells"].get(tid, {"severity": "watch"})
        ev = fn(us)
        if ev:
            if record is not None:
                meta["times_caught"] = meta.get("times_caught", 0) + 1
                meta["last_caught"] = record
            sev = meta.get("severity", "watch").upper()
            print(f"  [{sev:6}] {tid}: FIRED ({len(ev)})")
            for e in ev[:4]:
                print(f"            - {e}")
            if meta.get("severity") == "banned":
                fired_banned += 1
        else:
            print(f"  [ok    ] {tid}: clean")
    if record is not None:
        json.dump(reg, open(REG, "w"), indent=2)
    if fired_banned:
        print(f"  >>> TELL-LEDGER FAIL: {fired_banned} banned tell(s) reappeared. Fix before molting.")
        return 1
    print("  >>> TELL-LEDGER PASS: no frozen tell reappeared.")
    return 0


def add(tid, desc, severity):
    reg = load_reg()
    reg["tells"][tid] = {"severity": severity, "first_seen": None, "desc": desc,
                         "times_caught": 0, "last_caught": None}
    json.dump(reg, open(REG, "w"), indent=2)
    print(f"registered tell '{tid}' ({severity}). Now add a detector fn in scripts/tell_ledger.py.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--add":
        add(args[1], args[2], args[3] if len(args) > 3 else "banned"); sys.exit(0)
    path = "state/molt_intake.json"
    rec = None
    if args and not args[0].startswith("--"):
        path = args[0]; args = args[1:]
    if "--record" in args:
        rec = int(args[args.index("--record") + 1])
    sys.exit(run(path, rec))
