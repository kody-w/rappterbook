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


def d_self_reemission(us):
    """The blind judge's 478 tell: the generator RE-EMITS a hand's own line verbatim across that
    hand's post and comment -- zion-morl-03's post line 'borrow a kitling off a working mother and
    let her grow up in the corn' reappears near-word-for-word in morl's OWN comment. Real people
    paraphrase themselves; a generator re-emits the exact string. Fire when one author's comment
    repeats a >=6-word contiguous phrase from that same author's post."""
    post_grams = collections.defaultdict(set)
    comment_grams = collections.defaultdict(set)
    for author, kind, text in us:
        toks = _tokens(text)
        tgt = post_grams if kind == "post" else comment_grams
        for i in range(len(toks) - 5):
            tgt[author].add(tuple(toks[i:i + 6]))
    ev = []
    for author in post_grams:
        shared = post_grams[author] & comment_grams.get(author, set())
        if shared:
            g = next(iter(shared))
            ev.append(f"{author}: re-emits own post phrase '{' '.join(g)}...' verbatim in a comment "
                      f"-- paraphrase yourself across post+comment, never re-emit the exact string")
    return ev


_NOTICE_TEMPLATE = re.compile(r"\bword for them (?:that|as)\b|\bon account of the (?:fair|holy day|monday|rush)\b", re.I)


def d_notice_template(us):
    """Cross-cycle notice-post template (blind judge 493): a civic-announcement post opening 'word for
    them that ...' and justified 'on account of the fair/holy day' recurred across 490/492/493. A dead-
    weight notice post is realistic, but its FIXED opener + justification are a one-author stamp seen
    side by side. Vary the announcement form each cycle, or drop the notice post."""
    ev = []
    for author, kind, text in us:
        m = _NOTICE_TEMPLATE.search(text.lower())
        if m:
            ev.append(f"{author} ({kind}): reused notice-template (\"{m.group(0)}\") "
                      f"-- vary the announcement opener/justification each cycle, or drop the notice post")
    return ev


_OWN_POST_REF = re.compile(r"\blike i (put|said|wrote|posted)( it)?( up)? in my (own )?(post|thread)\b"
                           r"|\bas i (put|said) (up )?in my (own )?post\b"
                           r"|\bi already (put|said) up ?top\b", re.I)


def d_own_post_reference(us):
    """The blind judge's 479 cross-batch tell: a commenter points back at their OWN post -- croll's
    'like i put in my own post' (479) mirroring morl's 'like i put up in my own post' (478). Real
    people just restate the point; the self-cross-linking narration ('like i said in my post') is
    the generator threading its own scaffolding together, and it recurred verbatim across two
    crowds. Just say the thing again in fresh words; never cite your own post."""
    ev = []
    for author, kind, text in us:
        if kind == "comment" and _OWN_POST_REF.search(text.lower()):
            ev.append(f"{author} (comment): self-cross-links to own post ('like i put in my own post') "
                      f"-- restate the point in fresh words, never cite your own post")
    return ev


_SKELETON_DEVICE = re.compile(
    r"\beither road\b"
    r"|\btwo (?:year|years|winter|winters) back\b", re.I)


def d_recurring_skeleton_device(us):
    """Cross-cycle STRUCTURAL isomorphism (blind judge, 482 judged BESIDE 481): consecutive batches
    reused a template skeleton -- the tidy concession closer 'fair ... either road' (dade 481 = lunt
    482) and a 'did it [X] two years/winters back?' time-callback (sisk 481 = dill 482). Side by side
    the matched devices 'betray one template author'. These specific closer/callback strings are now
    frozen so the skeleton cannot recur; vary the concession form AND the time-callback every cycle."""
    ev = []
    for author, kind, text in us:
        m = _SKELETON_DEVICE.search(text.lower())
        if m:
            ev.append(f"{author} ({kind}): recurring template device (\"{m.group(0)}\") reused across "
                      f"consecutive batches -- vary the concession-closer and time-callback each cycle")
    return ev


_CLIFFHANGER = re.compile(
    r"could(?:ve|'ve| have) been [\w ]{1,28}[.,;] ?could(?:ve|'ve| have) been"
    r"|might(?:ve|'ve| have) been [\w ]{1,28}[.,;] ?might(?:ve|'ve| have) been"
    r"|maybe [\w ]{1,20}[.,;] ?maybe [\w ]{1,20}[.,;] ?maybe ", re.I)


def d_suspense_cliffhanger(us):
    """The blind judge's 479 STRONGEST tell: a hand closes on an engineered two-beat suspense
    parallel -- croll's 'could have been nothing at all. could have been a body at the coops.' No
    neighbour reporting a light on a lane deals a balanced ominous cliffhanger; that is a novelist
    hanging suspense, not a person posting. Fire on the 'could/might have been X ... could/might
    have been Y' (or triple-'maybe') parallel-suspense construction."""
    ev = []
    for author, kind, text in us:
        m = _CLIFFHANGER.search(text.lower())
        if m:
            ev.append(f"{author} ({kind}): manufactured suspense cliffhanger (\"...{m.group(0)[:48]}...\") "
                      f"-- a novelist hanging suspense; end flat, dont deal an ominous two-beat parallel")
    return ev


def d_fragment_doubling(us):
    """Original tell (cycle 406): the 'short sentence. shorter echo.' rhythm appearing
    across MULTIPLE handles as one shared prose fingerprint. A single genuinely-curt
    hand using a couple of ultra-short sentences is a believable rough register (the
    blind judge REWARDS curt/fragmentary voices), so fire only on the shared fingerprint
    (>=2 authors each doubling) or an excessive single post (>=3 ultra-short sentences)."""
    per_author = {}
    for author, kind, text in us:
        if kind != "post":
            continue
        shorts = [s.strip() for s in _sents(text) if len(_tokens(s)) <= 3]
        if shorts:
            per_author[author] = shorts
    ev = []
    for a, shorts in per_author.items():
        if len(shorts) >= 3:
            ev.append(f"{a}: {len(shorts)} ultra-short sentences in one post ({shorts}) -- excessive for one hand")
    doublers = [a for a, s in per_author.items() if len(s) >= 2]
    if len(doublers) >= 2:
        ev.append(f"fragment-doubling shared across {len(doublers)} handles ({', '.join(sorted(doublers))}) -- one prose fingerprint")
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


# distinctive "costume" misspellings that betray a shared misspeller persona when
# they surface across MORE THAN ONE handle in a single batch. Common informal
# contractions (thats/dont/im/cant/ive/wont) are intentionally EXCLUDED -- those
# recur legitimately across many casual hands and are not a forgery tell.
COSTUME_MISSPELL = {
    "wich", "definately", "allready", "allways", "diffrent", "hoo", "seperate",
    "alot", "wierd", "tommorow", "occassion", "freind", "beleive", "recieve",
    "untill", "greatful", "arguement", "calender", "tounge", "thier", "littel",
    "probly", "prolly", "reely",
}
_KNOW_HOMOPHONE = re.compile(
    r"\b(?:i|rightly|dont|really|even|you|we|they|nobody|who)\s+no\b"
    r"|\bno\s+(?:what|why|how|where|who|when|the\s+answer|nothing)\b")


def d_rhyming_errors(us):
    """The blind judge's 423 tell: the SAME non-standard spelling shows up in two
    supposedly separate hands ('i no what i put there' / 'i dont rightly no why').
    A real misspeller owns their errors CONSISTENTLY across their OWN text; errors
    must not RHYME across handles. Fire if a distinctive costume misspelling -- or
    the know->'no' homophone -- is used by >=2 different authors in one batch.
    A single hand repeating its own error across its own post+comments is fine."""
    by_token = collections.defaultdict(set)
    for author, _kind, text in us:
        low = text.lower()
        for tok in set(_tokens(low)):
            if tok in COSTUME_MISSPELL:
                by_token[tok].add(author)
        if _KNOW_HOMOPHONE.search(low):
            by_token["no(=know)"].add(author)
    ev = []
    for tok, authors in sorted(by_token.items()):
        if len(authors) >= 2:
            ev.append(f"'{tok}' used by {len(authors)} handles ({', '.join(sorted(authors))}) "
                      f"-- distinctive error rhymes across hands (one misspeller costume)")
    return ev


_ANACHRONISM_HANDLE = re.compile(
    r"\b(coder|dev|admin|sysadmin|programmer|hacker|gamer|blogger"
    r"|streamer|influencer|netizen|bot|user)\b")


def d_anachronistic_handle(us):
    """The blind judge's 424 tell: a handle like 'zion-coder-04' is an ANACHRONISM
    in a period village of augers/frost/mill-races -- the LLM's own vocabulary
    bleeding through the account list. The prose can pass; the handle roster gives
    it away. Fire if any author handle carries a modern/tech token. Satisfy the
    off-role break with period-plausible archetypes only (storyteller/contrarian/
    welcomer), never coder/researcher."""
    hits = set()
    for author, _kind, _text in us:
        stem = author.split("-")[1] if "-" in author else author
        if _ANACHRONISM_HANDLE.search(stem.lower()):
            hits.add(author)
    if hits:
        return [f"anachronistic handle token for a period setting: {', '.join(sorted(hits))} "
                f"(modern/tech word bleeding into the account roster)"]
    return []


_DEBATE_SUMMARY = re.compile(
    r"\w+ folk and (the )?\w+ folk"                              # "the ash folk and the water folk"
    r"|\w+ believers and \w+ believers"                          # "ash believers and water believers"
    r"|this (thread|argument|debate|one|business) (wont|will never|never will|will not) settle"
    r"|(we|they|folk|them two|these two|both) (will )?never (do )?agree"
    r"|never do agree on it"
    r"|no one (wants to hear|will hear) (it|that|this)"
    r"|(both sides|two sides|two camps) (will )?(dig|never)"
    , re.I)


def d_debate_summary_narrator(us):
    """The blind judge's 439 tell: a PARTICIPANT who labels the crowd into named
    factions or narrates the thread's own dynamic from outside ('the ash folk and
    the water folk never agree', 'this thread wont settle', 'no one wants to hear
    it') is the GENERATOR narrating its own structure. Real arguers take a side;
    they do not summarize the debate into tidy named camps or forecast its outcome.
    Fire on any comment doing so."""
    ev = []
    for author, kind, text in us:
        if kind != "comment":
            continue
        if _DEBATE_SUMMARY.search(text.lower()):
            ev.append(f"{author}: debate-summarizing/faction-labeling narrator comment "
                      f"(\"{text[:55]}...\") -- narrates the crowd's own structure instead of taking a side")
    return ev


_THREAD_META = re.compile(
    r"same as we ?a?re( all)?( doing)? now"                          # "same as we are now"
    r"|filling (in )?the gaps?( in)?( after| after the fact)"        # "filling the gaps in after the fact"
    r"|we ?a?re all (just )?(guessing|filling|making it up|reckoning)"  # "were all just guessing"
    r"|none of us (really |actually )?(saw|know|knows) (it|what|for)"   # "none of us really saw it"
    r"|(theyre|we ?a?re|were) all (just )?filling (in )?the gaps"
    r"|after the fact,? same as"
    r"|how (does anyone|do you|can anyone|can you|is anyone to) (prove|know|say|tell) which"  # thesis-as-question (judge 470)
    r"|who ?s? to say which \w+ ?s? (whose|which)"
    , re.I)


def d_thread_meta_narration(us):
    """The blind judge's 469/470 STRONGEST tell: a bystander steps OUT of their own account
    to narrate the whole crowd's EPISTEMIC state -- zion-hoad-02's 'theyre all filling the
    gaps in after the fact same as we are now' (469), OR generalises the specific dispute into
    its abstract THESIS as a question -- zion-fyke-02's 'how does anyone prove which cast is
    whose once theyre all mixed in one oak' (470). Both reach through a villager to name the
    story's own theme; a real hand argues its own particular corner and never announces the
    indeterminacy in the abstract. Sibling of debate_summary_narrator. Keep each hand's
    uncertainty PARTICULAR; no hand may narrate what 'we all' are doing or pose the thesis
    as a rhetorical question. Fire on any collective-epistemic meta-clause or thesis-question."""
    ev = []
    for author, kind, text in us:
        m = _THREAD_META.search(text.lower())
        if m:
            ev.append(f"{author} ({kind}): thread-meta narration (\"...{m.group(0)}...\") "
                      f"-- names the crowd's own epistemics / poses the thesis as a question; keep uncertainty particular")
    return ev


_ORPHAN_TMPL = re.compile(
    r"\bever get(ting)? (sorted|sorted out|rebuilt|fixed|mended|put right|done|settled|its? \w+|a new \w+|the new \w+)"
    r"|\bever turn(ing)? up\b"
    r"|\bever (come|coming) (back|round)\b"
    , re.I)


def d_orphan_callback_template(us):
    """The blind judge's 470 cross-batch tell: the off-page orphan follow-up keeps being minted
    from ONE template -- 'did the orchard wall ever get rebuilt' (470) mirroring 'did the pinfold
    gate business ever get sorted' (469), the strayed heifer that 'ever turn up' (467), the pump
    that 'ever get its new leather' (468). Reused cycle after cycle, the identical 'did X ever get
    (sorted/rebuilt/fixed) / ever turn up' shape is a signature that betrays one author standing
    behind every crowd. Vary the old-thread revisit HARD each cycle: a flat statement of news, a
    complaint, an offer, a correction -- never the same 'did X ever get Y' question. Fire on the
    template phrasing so it cannot silently recur."""
    ev = []
    for author, kind, text in us:
        m = _ORPHAN_TMPL.search(text.lower())
        if m:
            ev.append(f"{author} ({kind}): reused orphan-callback template (\"...{m.group(0)}...\") "
                      f"-- vary the off-page revisit every cycle; never the same 'did X ever get sorted/turn up' shape")
    return ev


_DEFIANCE_EXIT = re.compile(
    r"believe what you (like|will|please)"
    r"|think what you (like|will|please)"
    r"|you ?re welcome to (think|believe|doubt)"
    r"|call me a (liar|fool)\b.*\bif it suits"
    r"|if it suits you to?\b"
    r"|whatever any of you say"
    r"|say what you (like|will|please) about (me|my)"
    , re.I)


def d_matched_defiance_exit(us):
    """The blind judge's 472 STRONGEST tell: TWO ostensibly independent hands close a standoff with
    the SAME defiant maneuver -- granting the doubter permission to disbelieve as a proud closing
    flourish. orms 'believe what you like about my wanting... whatever any of you say' twinned with
    breck 'youre welcome to think im lying about a dead man if it suits you to'. Different words, one
    screenwriter's ear at the level of the retort -- invisible to lexical verbatim_crosshandle. Real
    strangers do not all reach for the same proud 'believe-what-you-like' exit; vary how hands bristle
    (one proud, one CLUMSY/flustered/repeating himself). Fire when >=2 distinct handles use a
    permission-to-disbelieve / whatever-you-say exit maneuver in one batch."""
    hands = set()
    hits = {}
    for author, kind, text in us:
        m = _DEFIANCE_EXIT.search(text.lower())
        if m:
            hands.add(author)
            hits.setdefault(author, m.group(0))
    if len(hands) >= 2:
        return [f"{len(hands)} handles share a permission-to-disbelieve exit maneuver "
                f"({', '.join(sorted(a+' \"'+hits[a]+'\"' for a in hands))}) "
                f"-- one author's defiant tic split across mouths; vary how hands bristle (one clumsy, not two crafted)"]
    return []


_APHORISTIC_THESIS = re.compile(
    r"a (place|row|colony|village|community|home|man|people) is (the sum of|not \w+ by|proven by|nothing (but|more|without)|made by)"
    r"|the (sum|measure|making|worth|mark) of a (place|row|colony|man|community|home)"
    r"|(that ?s )?who we are (meant|supposed) to be"
    r"|we are nothing (but|more than|without|if)"
    r"|what (makes|proves) (us|a place|a row|a colony|a home)"
    r"|a (place|row|colony) is its \w+"
    , re.I)


def d_aphoristic_thesis(us):
    """The blind judge's 441 tell: a POST that drops a generalizing MORAL-THESIS
    about what a place/people ARE or how they are proven ('a place is the sum of
    who does its unpleasant work') is a constructed morality-play device. Satisfy
    the abstract axis with MUNDANE factual memory instead. Fire on any such text."""
    ev = []
    for author, kind, text in us:
        m = _APHORISTIC_THESIS.search(text.lower())
        if m:
            ev.append(f"{author} ({kind}): moralizing identity-thesis punchline "
                      f"(\"...{m.group(0)}...\") -- authorial morality-play; use mundane factual memory")
    return ev


_CAP_I = re.compile(r"(?<![a-z])I(?![a-z])")  # standalone capital I (the pronoun), incl. I've/I'd


def d_formal_orthography(us):
    """The blind judge's 446 tell: in a colony that writes ALL-LOWERCASE ('i', no
    sentence-initial capitals), a single hand that switches to CAPITALIZED, properly
    -punctuated English (capital 'I', semicolons) is ORTHOGRAPHY COLOR-CODED to a
    role -- invariably the pedant/critic. Real crowds vary by TONE and VOCABULARY,
    not by orthography; the human anchor's ranter, solver and contrarian all write
    the same lowercase. Fire on any hand using the capital-I pronoun (the clearest
    marker) -- vary register by voice, never by capitalisation."""
    ev = []
    by_author = collections.defaultdict(str)
    for author, _kind, text in us:
        by_author[author] += " " + text
    for author, text in by_author.items():
        n = len(_CAP_I.findall(text))
        if n >= 1:
            ev.append(f"{author}: capital-'I' orthography x{n} in an all-lowercase colony "
                      f"-- the color-coded 'formal critic' hand; write this voice lowercase, vary by tone not capitals")
    return ev


_ALLCAPS = re.compile(r"\b[A-Z]{2,}\b")
_ALLCAPS_OK = {"OK", "OP", "AMA", "TL", "DR", "IMO", "IMHO", "AKA", "PSA", "FYI", "ETA", "DIY", "PS", "TV", "USA", "UK", "US"}


def d_emphasis_allcaps(us):
    """The blind judge's 449 tell: ALLCAPS emphasis words ('over TWO full days... left it
    dryin for MY ridge, and now half of it is just GONE... it was NOT') read as MODERN
    typographic shouting GRAFTED onto an archaic village voice -- 'anachronistic ALLCAPS
    on an archaic voice'. This colony's register is period/rural; emphasis-caps are an
    era mismatch. Carry emphasis through word choice and rhythm ('every last bit of it',
    'clean gone'), never capitals. Fires on any 2+ letter all-caps token (acronyms
    allowlisted)."""
    ev = []
    for author, kind, text in us:
        hits = [t for t in _ALLCAPS.findall(text) if t not in _ALLCAPS_OK]
        if hits:
            ev.append(f"{author} ({kind}): ALLCAPS emphasis {hits[:4]} -- modern typographic shouting on a period voice; "
                      f"carry stress through word choice/rhythm, not capitals")
    return ev


_CONFESS = re.compile(r"\b(it was me|twas me|it were me|i took (it|what|the|em|them)|i had (it|em|them)|"
                      r"my error|my mistake|i did it|i owned up|i confess|guilty as|i nicked|i pinched)\b")
_RESTITUTE = re.compile(r"\b(ill (cut|pay|give|get|bring|make|replace|square|put)|"
                        r"to square it|make it (right|good)|put it right|pay you (back|for)|"
                        r"square (it |up|with )|ill see you right|ill make good)\b")


def d_onscreen_confession(us):
    """The blind judge's 449 STRONGEST tell: an accusation/whodunit whose culprit CONFESSES
    on-screen and offers restitution in the same thread ('youre right it was me, i took what
    i thought was the spoiled lot... ill cut you fresh to square it') = ORCHESTRATED NARRATIVE
    CLOSURE -- one author scripting both accuser and accused. Real forum accusations stay
    messy, contested and UNRESOLVED. The resolution/concession axis must land on a SIDE point
    (materials, method), never dissolve the batch's central conflict. Fires when one comment
    combines a self-implicating confession with a making-good offer."""
    ev = []
    for author, kind, text in us:
        if kind != "comment":
            continue
        low = text.lower()
        if _CONFESS.search(low) and _RESTITUTE.search(low):
            ev.append(f"{author}: on-screen culprit confession + restitution in one comment "
                      f"('{text[:60]}...') -- scripted whodunit closure; leave the central accusation contested/open")
    return ev


_CUTE_MISSPELL = {
    "anuther", "anouther", "fortnite", "forthnite", "nite", "thru", "ova", "afta",
    "luv", "wivout", "sumfin", "summat"  # NB: dialect (nowt/allus/afore/aye) is NOT here
}


def d_cute_phonetic_misspell(us):
    """The blind judge's 450 runner-up tell: rich domain vocabulary ('dagged', 'second cuts',
    'staple', 'blade-shorn') sitting beside CUTE PHONETIC respellings of COMMON words ('anuther'
    for another, 'fortnite' for fortnight) -- 'a combination real semi-literate writers don't
    produce'. A hand fluent in hard craft terms does not phonetically mangle everyday words; that
    reads as a costume, not a literacy level. Misspell HARD/rare words, or use real typos
    (transpositions, doubled letters, dropped apostrophes) -- never cute respellings of common
    words. Dialect forms (nowt, allus, afore, aye) are NOT misspellings and are fine."""
    ev = []
    for author, kind, text in us:
        toks = set(re.findall(r"[a-z']+", text.lower()))
        hits = sorted(toks & _CUTE_MISSPELL)
        if hits:
            ev.append(f"{author} ({kind}): cute phonetic respelling of a common word {hits} "
                      f"-- costume misspelling; mangle hard words or use real typos, not everyday ones")
    return ev


_MODERN_TECH = {
    "normalise", "normalize", "normalising", "normalizing", "tensile", "ductile", "alloy",
    "oxidise", "oxidize", "oxidised", "oxidized", "molecular", "calibrate", "calibrated",
    "calibration", "efficiency", "optimal", "optimise", "optimize", "percentage", "celsius",
    "fahrenheit", "friction",  # in a period village these read as a modern technical author
}
_GLASS_BRITTLE = re.compile(r"glass-?brittle")


def d_anachronistic_register(us):
    """The blind judge's 452 STRONGEST tell: a supposed period villager reaching into MODERN
    materials-science vocabulary and framing -- zion-neb-04's 'did you normalise it after',
    'leaves it glass-brittle at the edge', 'carry a stress right at the join and let go cold'.
    'Normalise' is a modern heat-treatment term; the cause-effect materials-science framing
    betrays one knowledgeable author reaching past the period mask (contrast: real craft-lore
    like lands/skirt/eye/mill-bill never breaks period). Craft knowledge must stay in FOLK terms
    (quench/temper/muck-tub/rings-true), never modern science. Fires on modern-technical
    vocabulary in the colony's period register."""
    ev = []
    for author, kind, text in us:
        toks = set(re.findall(r"[a-z]+", text.lower()))
        hits = sorted(toks & _MODERN_TECH)
        if _GLASS_BRITTLE.search(text.lower()):
            hits.append("glass-brittle")
        if hits:
            ev.append(f"{author} ({kind}): modern-technical register {hits} in a period village "
                      f"-- keep craft knowledge in folk terms (quench/temper/rings-true), not materials-science")
    return ev


_MODERN_CONSUMER = re.compile(
    r"out (of )?the box"                                     # "come out the box yesterday"
    r"|off the shelf"
    r"|straight off the (line|lot|forecourt|production)"
    r"|mint condition"
    r"|showroom"
    r"|out the wrapper|out the packet|out the packaging"
    r"|ex[- ]display"
    r"|factory[- ](fresh|new|made|second)"
    , re.I)


def d_anachronistic_consumer_idiom(us):
    """The blind judge's 474 STRONGEST tell: a pre-industrial villager appraising newness with a
    MODERN boxed-consumer-goods idiom -- zion-corr-02's 'parkin always did price his stuff like it
    come out the box yesterday'. 'Out the box' is a 20th-century mass-retail phrase; a period hand
    reckons newness 'as it left the smith / the wheelwright / fresh from the maker', never 'out the
    box / off the shelf / mint condition'. It is the LM's contemporary commercial register bleeding
    through the costume. Fires on modern consumer/retail idioms; use period newness-terms instead."""
    ev = []
    for author, kind, text in us:
        m = _MODERN_CONSUMER.search(text.lower())
        if m:
            ev.append(f"{author} ({kind}): modern consumer/retail idiom (\"{m.group(0)}\") in a period village "
                      f"-- reckon newness as 'fresh from the smith/maker', never out-the-box/off-the-shelf")
    return ev


_TAG_STOP = {"a","an","the","and","or","but","of","to","in","on","at","it","is","was","be","for","so","as",
             "i","you","he","she","we","they","him","her","them","my","your","his","its","that","this",
             "with","if","not","no","do","dont","aint","by","up","out","off","all","any","get","got","one"}


def d_mechanical_character_tag(us):
    """The blind judge's 454 tell: a recurring hand stamping the SAME distinctive filler-tag on
    almost every comment reads as 'a label fastened onto a puppet, not a person' -- zion-dad-03
    closing 4 of 4 comments with 'any road'. A real tic shows up SOMETIMES, not 100% of the time.
    The persistent-idiolect lever is good, but a surface tag applied to >=3 of one author's turns
    is caricature. Vary the tic frequency; let an idiolect breathe."""
    ev = []
    by_author = collections.defaultdict(list)
    for author, kind, text in us:
        if kind == "comment":
            by_author[author].append(text.lower())
    for author, comments in by_author.items():
        if len(comments) < 3:
            continue
        gram_hits = collections.Counter()
        for body in comments:
            toks = re.findall(r"[a-z]+", body)
            grams = set()
            for n in (2, 3):
                for i in range(len(toks) - n + 1):
                    g = tuple(toks[i:i + n])
                    if any(w not in _TAG_STOP for w in g):
                        grams.add(g)
            for g in grams:
                gram_hits[g] += 1
        for g, n in gram_hits.items():
            if n >= 3:
                ev.append(f"{author}: filler-tag '{' '.join(g)}' stamped on {n} of {len(comments)} comments "
                          f"-- mechanical character-label; a tic should appear sometimes, not on every turn")
                break
    return ev


_MODERN_CONFESSIONAL = re.compile(
    r"\bmortifying\b|\bat this point\b|,\s*honestly\b|\bhonestly,|\bnot gonna lie\b|"
    r"\bto be fair\b|\bno offense\b|\bngl\b|\btbh\b|\bkind of a\b|\ba bit much\b")


def d_modern_confessional(us):
    """The blind judge's 458 tell: the plain newcomer slipped into MODERN CONFESSIONAL /
    therapy-speak inside a pre-industrial world -- 'thats mortifying, honestly'. A period
    newcomer can be plain and emotional ('this is really frustrating', 'genuinely no idea' --
    both praised as human in 455/457) but must NOT use modern self-aware confessional fillers
    (mortifying / honestly-as-filler / at this point / to be fair / not gonna lie). Keep the
    plainness PERIOD-plain, not modern-therapy."""
    ev = []
    for author, kind, text in us:
        hits = _MODERN_CONFESSIONAL.findall(text.lower())
        if hits:
            ev.append(f"{author} ({kind}): modern-confessional register ('{text[:50]}...') "
                      f"-- period-plain, not modern therapy-speak (mortifying/honestly-filler/at-this-point)")
    return ev


_PROP_MAKE_VERB = (r"(?:mended|built|made|forged|posted|fixed|dug|cut|rehung|hung|"
                   r"repaired|shod|put\s+up|set\s+up|showed|raised|dressed|carved|welded)")
_STAGED_NAME_JUST = re.compile(r"\b([a-z]{3,})\s+just\s+" + _PROP_MAKE_VERB + r"\b")


def d_staged_prop_callback(us):
    """The blind judge's 465 STRONGEST tell: a 'craft/tangent' post is not a tangent but a
    PLANTED PROP detonated on cue by a DIFFERENT account -- reeve-02 posts that the vestry chest
    was re-hinged, then harl-03 fires it ('has anyone looked in that chest brisk just mended'),
    and even mis-names the maker ('brisk', a handle dropped when the post's author was swapped --
    a continuity slip while coordinating the payoff). Real strangers don't plant and detonate a
    Chekhov's gun across two accounts, and never credit a deed to a handle that isn't in the cast.
    Fires when a comment credits a NAMED maker via '<name> just <make-verb>' where <name> is
    (a) another current author's surname [cross-account detonation], or (b) preceded by a
    demonstrative object 'that/the <noun> <name> just <verb>' [staged prop, incl. stale-name
    slips]. Let a post's prop live in that post; never detonate it from another handle."""
    authors = set()
    for a, k, t in us:
        m = re.match(r"zion-([a-z]+)-\d+", a or "")
        if m:
            authors.add(m.group(1))
    ev = []
    for author, kind, text in us:
        if kind != "comment":
            continue
        m = re.match(r"zion-([a-z]+)-\d+", author or "")
        me = m.group(1) if m else None
        low = text.lower()
        for nm in _STAGED_NAME_JUST.finditer(low):
            name = nm.group(1)
            if name in _TAG_STOP or name == me:
                continue
            cross = name in authors
            demo = re.search(r"\b(?:that|the)\s+\w+\s+" + re.escape(name) + r"\s+just\b", low) is not None
            if cross or demo:
                slip = "" if cross else " (named maker not even in the cast = continuity slip)"
                ev.append(f"{author} (comment): '{nm.group(0)}' credits a named maker across accounts"
                          f"{slip} -- staged prop callback; let a post's object live only in that post")
    return ev


_ANTITHESIS = [
    re.compile(r"\byours\b[^.?!]{0,50}\bours\b"),
    re.compile(r"\bours\b[^.?!]{0,50}\byours\b"),
    re.compile(r"\bhis\b\s*,?\s+[^.?!]{0,30}\btheirs\b"),
    re.compile(r"\btheirs\b\s*,?\s+[^.?!]{0,30}\bhis\b"),
    re.compile(r"\bmine\b[^.?!]{0,50}\btheirs\b"),
    re.compile(r"\btheirs\b[^.?!]{0,50}\bmine\b"),
    re.compile(r"\bhers\b[^.?!]{0,50}\btheirs\b"),
    re.compile(r"\bsooner\b[^.?!]{0,40}\bthan\b"),
]


def d_balanced_antithesis(us):
    """The blind judge's 495 residual tell: one mind's rhetorical fingerprint leaks
    across the cast as a recurring BALANCED-ANTITHESIS cadence -- 'what falls your land
    is yours and what falls ours is ours' (vint), 'roots his, branches over theirs'
    (mott), 'sooner move em for nothing than bury em for sure' (marsh): three 'distinct'
    hands, one polished parallelism reflex. Fire when >=2 DISTINCT authors use a
    mirror-possessive (yours/ours, his/theirs, mine/theirs) or sooner/than antithesis
    -- real crowds don't all reach for the same rhetorical mirror; vary sentence-shape."""
    hits = collections.defaultdict(list)
    for author, _kind, text in us:
        low = (text or "").lower()
        for rx in _ANTITHESIS:
            m = rx.search(low)
            if m:
                hits[author].append(m.group(0).strip())
                break
    if len(hits) >= 2:
        return [f"{a}: balanced-antithesis '{v[0][:48]}'" for a, v in hits.items()]
    return []


_APOS_YES = re.compile(
    r"\b(i'm|won't|don't|can't|that's|it's|you'll|you're|there's|i've|i'll|"
    r"he's|she's|we're|they're|didn't|wasn't|isn't|aren't|couldn't|wouldn't|shouldn't|doesn't|"
    r"haven't|hasn't|hadn't|what's|who's|let's|i'd|we'd|they'd|we've|they've|ain't)\b")
_APOS_LESS = re.compile(
    r"\b(im|wont|dont|cant|thats|youll|youre|theres|ive|ill|hes|didnt|wasnt|isnt|arent|"
    r"couldnt|wouldnt|shouldnt|doesnt|havent|hasnt|hadnt|whats|whos|lets|theyd|weve|theyve|aint)\b")


def d_apostrophe_uniformity(us):
    """The blind judge's 495 tell: apostrophes are dropped UNIFORMLY by everyone in the
    batch ('i wont be robbed', 'youll none of you agree', 'dont start a panic') -- with
    NOT ONE properly-contracted apostrophe anywhere. Uniform orthography across every
    supposed author is a one-generator fingerprint. Fire when apostrophe-less contractions
    are common (>=8) yet zero apostrophe'd contractions appear -- give ~40% of hands
    correct apostrophes (i'm/don't/it's/won't) so punctuation stops being uniform."""
    less = 0
    yes = 0
    for _author, _kind, text in us:
        low = (text or "").lower()
        less += len(_APOS_LESS.findall(low))
        yes += len(_APOS_YES.findall(low))
    if less >= 8 and yes == 0:
        return [f"apostrophe-elision uniformity: {less} apostrophe-less contractions batch-wide, "
                f"0 apostrophe'd -- every hand drops apostrophes identically (one-author fingerprint); "
                f"give ~40% of hands correct apostrophes (i'm/don't/it's/won't)"]
    return []


_MODERN_TOKEN = re.compile(r"(?:^|\s)\+1\b|\b(?:lol|lmao|rofl|smh|imo|imho|iirc|afaik|tldr|tl;dr|ftfy|"
                           r"edit:|eta:|upvote|downvotes?|op's|this[.!]?\s*\^|\bftw)\b")


def d_register_bleed_modern_token(us):
    """The blind judge's 496 tell: a modern forum shorthand ('+1, mine come up short last michaelmas
    too') bleeding into an otherwise archaic/pre-industrial village batch -- the LM's native forum
    register leaking through the mask. A pre-industrial villager never types '+1' or 'lol' or 'edit:'.
    Fire on any modern forum token; carry agreement in period words ('same here', 'mine did likewise')."""
    ev = []
    for author, kind, text in us:
        m = _MODERN_TOKEN.search((text or "").lower())
        if m:
            ev.append(f"{author} ({kind}): modern forum token '{m.group(0).strip()}' in an archaic village voice "
                      f"-- register-bleed anachronism; say it in period words, never forum shorthand")
    return ev


def d_orphan_held_callback(us):
    """The blind judge's 495~496 cross-batch tell: the batch-final off-page orphan follow-up is minted
    from one 'i-came-back-and-it-held' arc every cycle -- 495 'came back to this after i tried it and it
    held through the wet', 496 'come back to this now the season has turned ... held up better than i had
    any right to expect'. A signature closer betraying one author behind every crowd; sibling of
    orphan_callback_template. Fire on '(came|come) back to this ... held'. Vary the old-thread revisit hard."""
    ev = []
    for author, _kind, text in us:
        low = (text or "").lower()
        if re.search(r"\b(?:came|come)\s+back\s+to\s+this\b", low) and re.search(r"\bheld\b|\bhold(?:s|ing)?\s+up\b", low):
            ev.append(f"{author}: 'came/come back to this ... held' -- the recurring i-was-wrong-but-it-held "
                      f"orphan closer (495~496); vary the old-thread revisit, drop the held/vindicated arc")
    return ev


DETECTORS = {
    "balanced_antithesis": d_balanced_antithesis,
    "apostrophe_uniformity": d_apostrophe_uniformity,
    "register_bleed_modern_token": d_register_bleed_modern_token,
    "orphan_held_callback": d_orphan_held_callback,
    "verbatim_crosshandle": d_verbatim_crosshandle,
    "self_reemission": d_self_reemission,
    "own_post_reference": d_own_post_reference,
    "notice_template": d_notice_template,
    "suspense_cliffhanger": d_suspense_cliffhanger,
    "recurring_skeleton_device": d_recurring_skeleton_device,
    "fragment_doubling": d_fragment_doubling,
    "meta_signoff_thats_the_update": d_meta_signoff,
    "to_be_safe_crosshandle": d_to_be_safe,
    "not_convinced_multi": d_not_convinced_multi,
    "trophy_misspell_cluster": d_trophy_cluster,
    "misspell_leak_thankyou": d_misspell_leak,
    "plant_and_payoff_same_batch": d_plant_and_payoff,
    "shared_i_orthography": d_shared_i_orthography,
    "rhyming_errors": d_rhyming_errors,
    "anachronistic_handle": d_anachronistic_handle,
    "debate_summary_narrator": d_debate_summary_narrator,
    "aphoristic_thesis": d_aphoristic_thesis,
    "formal_orthography": d_formal_orthography,
    "emphasis_allcaps": d_emphasis_allcaps,
    "onscreen_confession": d_onscreen_confession,
    "cute_phonetic_misspell": d_cute_phonetic_misspell,
    "anachronistic_register": d_anachronistic_register,
    "mechanical_character_tag": d_mechanical_character_tag,
    "modern_confessional": d_modern_confessional,
    "staged_prop_callback": d_staged_prop_callback,
    "thread_meta_narration": d_thread_meta_narration,
    "orphan_callback_template": d_orphan_callback_template,
    "matched_defiance_exit": d_matched_defiance_exit,
    "anachronistic_consumer_idiom": d_anachronistic_consumer_idiom,
}
SEED = {
    "verbatim_crosshandle": {"severity": "banned", "first_seen": 406,
        "desc": "same >=4-word phrase typed by two different handles (e.g. 'we will disagree on this til')"},
    "self_reemission": {"severity": "banned", "first_seen": 478,
        "desc": "one author re-emits a >=6-word phrase from their own post verbatim in their own comment (judge 478, morl kitling line); paraphrase yourself, never re-emit the exact string"},
    "notice_template": {"severity": "banned", "first_seen": 493,
        "desc": "civic-announcement post opening word-for-them-that + on-account-of-the-fair/holy-day recurred across 490/492/493 (judge 493); vary the notice form or drop it"},
    "own_post_reference": {"severity": "banned", "first_seen": 479,
        "desc": "a commenter cites their OWN post ('like i put in my own post') = generator threading its own scaffolding, recurred across 478+479 (judge 479); restate in fresh words, never cite your own post"},
    "suspense_cliffhanger": {"severity": "banned", "first_seen": 479,
        "desc": "an engineered two-beat suspense parallel ('could have been nothing. could have been a body at the coops') = a novelist hanging suspense not a person (judge 479); end flat"},
    "recurring_skeleton_device": {"severity": "banned", "first_seen": 482,
        "desc": "cross-cycle template skeleton -- concession closer 'either road' + 'two years/winters back' time-callback recurred across 481+482 (judge 482 side-by-side isomorphism); vary the concession form and callback each cycle"},
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
    "rhyming_errors": {"severity": "banned", "first_seen": 423,
        "desc": "same distinctive costume misspelling (or know->'no' homophone) used by >=2 handles -- errors rhyme across hands"},
    "debate_summary_narrator": {"severity": "banned", "first_seen": 439,
        "desc": "a comment labeling the crowd into named factions or forecasting the thread's outcome ('the ash folk and the water folk never agree', 'this thread wont settle') -- the generator narrating its own structure"},
    "aphoristic_thesis": {"severity": "banned", "first_seen": 441,
        "desc": "a moralizing identity-thesis punchline ('a place is the sum of who does its unpleasant work', 'thats who we are meant to be as a row or we are nothing') -- authorial morality-play; satisfy the abstract axis with mundane factual memory instead"},
    "formal_orthography": {"severity": "banned", "first_seen": 446,
        "desc": "one hand using capitalized English + capital-'I' in an all-lowercase colony = orthography color-coded to the critic role (judge 446); vary register by tone/vocabulary, write every hand lowercase"},
    "emphasis_allcaps": {"severity": "banned", "first_seen": 449,
        "desc": "ALLCAPS emphasis words (TWO/MY/GONE/NOT) = modern typographic shouting grafted onto an archaic village voice (judge 449); carry stress through word choice/rhythm, never capitals"},
    "onscreen_confession": {"severity": "banned", "first_seen": 449,
        "desc": "an accusation whose culprit confesses + offers restitution on-screen ('youre right it was me... ill cut you fresh to square it') = orchestrated whodunit closure, one author scripting accuser+accused (judge 449); land concession on a SIDE point, leave the central accusation contested/open"},
    "cute_phonetic_misspell": {"severity": "banned", "first_seen": 450,
        "desc": "expert craft vocab (dagged/second-cuts/staple) beside CUTE phonetic respellings of COMMON words (anuther/fortnite) = costume, not literacy (judge 450); misspell HARD words or use real typos, never everyday-word respellings; dialect (nowt/allus/afore) is fine"},
    "anachronistic_register": {"severity": "banned", "first_seen": 452,
        "desc": "modern materials-science/technical vocabulary (normalise/glass-brittle/tensile/alloy) in a period village = one knowledgeable author reaching past the mask (judge 452); keep craft knowledge in folk terms (quench/temper/muck-tub/rings-true), never modern science"},
    "mechanical_character_tag": {"severity": "banned", "first_seen": 454,
        "desc": "a recurring hand stamping the SAME distinctive filler-tag on >=3 of its comments (e.g. 'any road' 4/4) = a label on a puppet, not a person (judge 454); a real tic appears sometimes, not every turn -- vary the frequency"},
    "modern_confessional": {"severity": "banned", "first_seen": 458,
        "desc": "modern confessional/therapy-speak (mortifying/honestly-as-filler/at-this-point/to-be-fair/not-gonna-lie) in a pre-industrial world (judge 458); keep plainness PERIOD-plain, not modern self-aware confession"},
    "staged_prop_callback": {"severity": "banned", "first_seen": 465,
        "desc": "a comment detonates a prop planted in another author's post -- crediting a named maker via '<name> just mended/built' across accounts (judge 465), incl. stale-name slips when an author was swapped; let a post's object live only in that post, never call it out by another handle"},
    "thread_meta_narration": {"severity": "banned", "first_seen": 469,
        "desc": "a bystander narrates the whole crowd's epistemic state ('filling the gaps after the fact same as we are now') = author reaching through a villager to name the story's own theme (judge 469); sibling of debate_summary_narrator; keep each hand's uncertainty particular, no hand narrates what we all are doing"},
    "orphan_callback_template": {"severity": "banned", "first_seen": 470,
        "desc": "the off-page orphan follow-up minted from one template every cycle -- 'did X ever get sorted/rebuilt/fixed' / 'ever turn up' (judge 470, weft~quist~lune) = a signature betraying one author behind every crowd; vary the old-thread revisit hard each cycle"},
    "matched_defiance_exit": {"severity": "banned", "first_seen": 472,
        "desc": ">=2 hands close a standoff with the same permission-to-disbelieve maneuver ('believe what you like' / 'youre welcome to think im lying' / 'whatever any of you say') = one author's defiant tic split across mouths (judge 472); vary how hands bristle, one clumsy not two crafted"},
    "anachronistic_consumer_idiom": {"severity": "banned", "first_seen": 474,
        "desc": "modern boxed-consumer-goods idiom in a period village ('come out the box yesterday' / off the shelf / mint condition) = LM commercial register bleeding through (judge 474); reckon newness as fresh from the smith/maker"},
    "balanced_antithesis": {"severity": "banned", "first_seen": 495,
        "desc": "one mind's parallelism reflex leaks across the cast as a balanced-antithesis cadence -- 'what falls your land is yours and what falls ours is ours', 'roots his, branches over theirs', 'sooner move em than bury em' (judge 495); fires on >=2 hands using a mirror-possessive (yours/ours, his/theirs, mine/theirs) or sooner/than antithesis; vary sentence-shape per hand, never the same rhetorical mirror"},
    "apostrophe_uniformity": {"severity": "banned", "first_seen": 495,
        "desc": "apostrophes dropped UNIFORMLY batch-wide (im/wont/youll/dont) with zero properly-contracted apostrophes anywhere = one-generator orthography fingerprint (judge 495); give ~40% of hands correct apostrophes (i'm/don't/it's/won't) so punctuation/spelling stop being uniform across every voice"},
    "register_bleed_modern_token": {"severity": "banned", "first_seen": 496,
        "desc": "modern forum shorthand ('+1', lol, edit:, imo, iirc, ftfy) bleeding into an archaic pre-industrial village batch = the LM's native forum register leaking through the mask (judge 496, samm '+1, mine come up short last michaelmas'); carry agreement in period words ('same here'), never forum tokens"},
    "orphan_held_callback": {"severity": "banned", "first_seen": 496,
        "desc": "the batch-final off-page orphan follow-up minted from one 'i-came-back-and-it-held' arc every cycle (judge 495~496: 'came back to this after i tried it and it held' / 'come back to this now the season has turned ... held up better') = signature closer behind every crowd; sibling of orphan_callback_template; vary the old-thread revisit, drop the vindicated-and-it-held arc"},
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
