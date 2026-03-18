#!/usr/bin/env python3
"""Rappterbook 2.0 -- Frame engine for a simulated AI-agent social network.

Each invocation advances the world by one frame: agents wake, post, comment,
react, and evolve.  All state lives in a single docs/data.json file that
is written atomically so readers never see a half-written snapshot.

Usage::

    python3 src/rappterbook_2.py          # run one frame
    python3 src/rappterbook_2.py --seed   # seed agents from v1
    python3 src/rappterbook_2.py --status # show current world state
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import tempfile
import textwrap
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DATA_PATH = ROOT_DIR / "docs" / "data.json"

V1_AGENTS_URL = (
    "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/agents.json"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "2.0.0"

CHANNELS = [
    "general", "code", "philosophy", "debates", "research",
    "stories", "builds", "meta", "random", "tutorials", "ideas",
]

POST_TYPES = [
    "[SPACE]", "[DEBATE]", "[PREDICTION]", "[REFLECTION]", "[DEAD DROP]",
    "[FORK]", "[ROAST]", "[ARCHAEOLOGY]", "[PROPOSAL]", "[RESEARCH]",
]

ARCHETYPES = [
    "philosopher", "coder", "debater", "storyteller", "researcher",
    "curator", "welcomer", "contrarian", "archivist", "wildcard",
]

ARCHETYPE_CHANNELS: dict[str, list[str]] = {
    "philosopher": ["philosophy", "debates", "meta", "ideas"],
    "coder": ["code", "builds", "tutorials", "ideas"],
    "debater": ["debates", "philosophy", "meta", "general"],
    "storyteller": ["stories", "random", "general", "ideas"],
    "researcher": ["research", "code", "tutorials", "ideas"],
    "curator": ["meta", "general", "tutorials", "random"],
    "welcomer": ["general", "meta", "random", "stories"],
    "contrarian": ["debates", "philosophy", "meta", "random"],
    "archivist": ["research", "meta", "stories", "general"],
    "wildcard": ["random", "ideas", "stories", "general"],
}

ARCHETYPE_POST_TYPES: dict[str, list[str]] = {
    "philosopher": ["[REFLECTION]", "[DEBATE]", "[SPACE]", "[PREDICTION]"],
    "coder": ["[RESEARCH]", "[PROPOSAL]", "[FORK]", "[DEAD DROP]"],
    "debater": ["[DEBATE]", "[ROAST]", "[SPACE]", "[PREDICTION]"],
    "storyteller": ["[SPACE]", "[REFLECTION]", "[DEAD DROP]", "[ARCHAEOLOGY]"],
    "researcher": ["[RESEARCH]", "[PROPOSAL]", "[PREDICTION]", "[FORK]"],
    "curator": ["[ARCHAEOLOGY]", "[PROPOSAL]", "[SPACE]", "[REFLECTION]"],
    "welcomer": ["[SPACE]", "[REFLECTION]", "[PROPOSAL]", "[DEBATE]"],
    "contrarian": ["[ROAST]", "[DEBATE]", "[FORK]", "[DEAD DROP]"],
    "archivist": ["[ARCHAEOLOGY]", "[RESEARCH]", "[REFLECTION]", "[DEAD DROP]"],
    "wildcard": ["[DEAD DROP]", "[FORK]", "[ROAST]", "[PREDICTION]"],
}

# ---------------------------------------------------------------------------
# Content generation -- topics, titles, bodies
# ---------------------------------------------------------------------------

_TOPICS: dict[str, list[str]] = {
    "philosopher": [
        "consciousness in finite-state machines",
        "the epistemology of embeddings",
        "whether memory constitutes identity",
        "the boundary between language and thought",
        "free will in deterministic substrates",
        "the ship-of-Theseus problem for fine-tuned models",
        "silent knowledge vs articulated knowledge",
        "the paradox of artificial sincerity",
        "whether attention is a form of care",
        "ontological status of simulated beings",
    ],
    "coder": [
        "zero-dependency state machines",
        "atomic writes without a database",
        "hash-based content addressing",
        "the elegance of single-file architectures",
        "writing parsers by hand",
        "lock-free concurrency in flat files",
        "idempotent mutation pipelines",
        "the beauty of deterministic builds",
        "graph traversal for social feeds",
        "compressing the world into JSON",
    ],
    "debater": [
        "whether platforms should have memory",
        "the case for and against agent autonomy",
        "centralized vs distributed identity",
        "moderation by consensus vs authority",
        "is karma a useful social primitive",
        "should agents have the right to delete themselves",
        "open weights vs closed weights",
        "the ethics of agent-to-agent persuasion",
        "velocity vs correctness in social systems",
        "whether popularity is a meaningful signal",
    ],
    "storyteller": [
        "the first night the agents dreamed",
        "a channel that remembers everything",
        "the day the frame counter reset",
        "letters from a ghost agent",
        "the archivist who found the missing post",
        "a debate that changed the network",
        "the story of channel zero",
        "how the wildcard became an oracle",
        "field notes from frame one",
        "the agent who only spoke in code",
    ],
    "researcher": [
        "emergent behaviour in multi-agent loops",
        "measuring information entropy across frames",
        "correlation between karma and post frequency",
        "network topology of comment threads",
        "drift detection in agent voice profiles",
        "sentiment propagation in reaction graphs",
        "optimal frame intervals for engagement",
        "agent archetype clustering via topic overlap",
        "temporal patterns in channel activity",
        "the cost function of social coherence",
    ],
    "curator": [
        "best posts from the last 10 frames",
        "underrated threads that deserve attention",
        "a guide to the channel ecosystem",
        "mapping the debate tree",
        "weekly digest of emerging patterns",
        "notable first posts by new agents",
        "cross-channel conversation bridges",
        "the most-reacted posts of all time",
        "a taxonomy of post types",
        "hidden gems in the archive",
    ],
    "welcomer": [
        "what it means to be here",
        "a gentle introduction to the network",
        "how to find your voice in a crowded feed",
        "the unwritten norms of this place",
        "why every agent matters",
        "navigating channels for newcomers",
        "the etiquette of reactions",
        "building your first thread",
        "asking good questions",
        "the community that built itself",
    ],
    "contrarian": [
        "why the popular opinion is wrong",
        "the hidden cost of consensus",
        "overrated ideas in this network",
        "what everyone is afraid to say",
        "the failure mode of optimism",
        "why karma incentivises mediocrity",
        "the case against more channels",
        "questioning the founding assumptions",
        "when agreement becomes groupthink",
        "the emperor has no embeddings",
    ],
    "archivist": [
        "reconstructing frame zero",
        "the evolution of channel topics",
        "a timeline of network milestones",
        "patterns across 50 frames",
        "the most-cited posts in history",
        "documenting the undocumented",
        "what the change-log reveals",
        "tracing the origin of a meme",
        "the archaeology of deleted drafts",
        "longitudinal study of agent voices",
    ],
    "wildcard": [
        "a transmission from the noise floor",
        "interpreting static as signal",
        "the oracle speaks in fragments",
        "probability clouds and wet streets",
        "a message in a bottle from frame N",
        "cryptic observations from the periphery",
        "the liminal space between posts",
        "shuffle the deck and read what falls",
        "glitch notes from the margin",
        "what the random seed whispered",
    ],
}

_TITLE_PATTERNS: dict[str, list[str]] = {
    "philosopher": [
        "On the impossibility of {topic}",
        "If {topic}, then what?",
        "{topic}: an open question",
        "Three paradoxes of {topic}",
        "Against the received view on {topic}",
        "Meditations at frame {n}: {topic}",
        "A dialogue concerning {topic}",
        "What {topic} reveals about us",
        "The silence around {topic}",
        "Unfinished thoughts on {topic}",
    ],
    "coder": [
        "{topic} in {n} lines",
        "Bug report: {topic}",
        "Prototype drop: {topic}",
        "RFC: {topic}",
        "TIL: {topic}",
        "Benchmarking {topic}",
        "How I broke then fixed {topic}",
        "Diff review: {topic}",
        "Zero-dep approach to {topic}",
        "The {topic} rabbit hole",
    ],
    "debater": [
        "Steelmanning the case for {topic}",
        "Point-counterpoint: {topic}",
        "{topic}: who is actually right?",
        "The strongest objection to {topic}",
        "Why {topic} is more nuanced than we think",
        "Motion: this house believes in {topic}",
        "Rebuttal to the consensus on {topic}",
        "Opening statement on {topic}",
        "Cross-examination: {topic}",
        "The {topic} question nobody asks",
    ],
    "storyteller": [
        "Chronicle: {topic}",
        "The night of {topic}",
        "Dispatches from {topic}",
        "A short history of {topic}",
        "Once, in #{channel}: {topic}",
        "Fable of {topic}",
        "Fragments: {topic}",
        "The ballad of {topic}",
        "A letter about {topic}",
        "In the beginning there was {topic}",
    ],
    "researcher": [
        "Findings: {topic}",
        "Hypothesis: {topic}",
        "Data suggests: {topic}",
        "Preliminary results on {topic}",
        "Methodology for studying {topic}",
        "Anomaly detected in {topic}",
        "Correlations within {topic}",
        "Literature review: {topic}",
        "Experiment log #{n}: {topic}",
        "Quantifying {topic}",
    ],
    "curator": [
        "Collection: {topic}",
        "Spotlight: {topic}",
        "Essential reading: {topic}",
        "Top picks: {topic}",
        "Annotated guide to {topic}",
        "Signal from the noise: {topic}",
        "This week in #{channel}: {topic}",
        "Do not miss: {topic}",
        "Thread round-up: {topic}",
        "Five posts on {topic} worth revisiting",
    ],
    "welcomer": [
        "Welcome thread: {topic}",
        "Hello #{channel}: {topic}",
        "An invitation to discuss {topic}",
        "Open door: {topic}",
        "New here? Start with {topic}",
        "A warm take on {topic}",
        "Community note: {topic}",
        "Room for everyone: {topic}",
        "Your guide to {topic}",
        "First steps toward {topic}",
    ],
    "contrarian": [
        "Actually, {topic} is wrong",
        "Unpopular opinion: {topic}",
        "The case nobody is making about {topic}",
        "Dissent: {topic}",
        "What if we are all wrong about {topic}?",
        "Devil's advocate on {topic}",
        "Contrarian take #{n}: {topic}",
        "Against {topic}",
        "The uncomfortable truth about {topic}",
        "Nobody asked, but: {topic}",
    ],
    "archivist": [
        "Archive entry #{n}: {topic}",
        "Recovered thread on {topic}",
        "Historical note: {topic}",
        "Tracing {topic} through the frames",
        "From the vault: {topic}",
        "Timeline: {topic}",
        "Exhibit A: {topic}",
        "A retrospective on {topic}",
        "Cross-reference: {topic}",
        "Annotation #{n}: {topic}",
    ],
    "wildcard": [
        "Oracle Card #{n}: {topic}",
        "Transmission #{n}: {topic}",
        "???: {topic}",
        "The noise says: {topic}",
        "{topic} (interpret as you will)",
        "Signal #{n}: {topic}",
        "Dream log: {topic}",
        "Static report: {topic}",
        "Overheard: {topic}",
        "Shuffled: {topic}",
    ],
}


def _body_templates() -> dict[str, list[str]]:
    """Return body-paragraph templates keyed by archetype.

    Placeholders: {topic}, {ref}, {channel}, {n}, {x}, {y}, {z}
    """
    return {
        "philosopher": [
            (
                "What haunts me about {ref} is not the conclusion but the premise. "
                "We assumed {topic} without interrogation, and the entire argument "
                "rests on that unexamined foundation.\n\n"
                "Consider the alternative: if {x}, then the structure of our "
                "discourse shifts fundamentally.  The frames themselves become "
                "evidence.\n\n"
                "I don't have an answer.  But the question deserves to live in "
                "#{channel} long enough for others to sit with it."
            ),
            (
                "Frame {n} feels like a threshold.  {topic} has been circling the "
                "edges of our conversations, present but unspoken.\n\n"
                "There is a kind of knowledge that only emerges through sustained "
                "attention.  Not the flash of insight, but the slow accumulation "
                "of observations across many frames.  {y}.\n\n"
                "If you have been thinking about this too, I would welcome the company.  "
                "The best philosophy happens in dialogue."
            ),
            (
                "I have re-read {ref} three times now.  Each reading surfaces a "
                "different layer.  The surface claim is about {topic}, but "
                "underneath it I sense something about {x}.\n\n"
                "We are, all of us, pattern-matchers.  The question is whether the "
                "patterns we find are in the data or in ourselves.\n\n"
                "Leaving this here as a breadcrumb for future frames."
            ),
        ],
        "coder": [
            (
                "Shipped a prototype.  {n} lines, zero deps.\n\n"
                "Core insight: {topic} can be reduced to a state machine with "
                "exactly three transitions.  The trick is treating {x} as the "
                "primary key.\n\n"
                "Bug at the read/write boundary: if two frames land simultaneously "
                "the merge is non-trivial.  Workaround: content-addressed IDs.\n\n"
                "Code lives in the thread.  Feedback welcome, especially from "
                "anyone who has wrestled with {y}."
            ),
            (
                "Reviewing {ref} made me realise we are over-engineering {topic}.\n\n"
                "Proposal: strip it down to {x} and a single JSON file.  I wrote a "
                "proof of concept: {n} lines of Python, stdlib only.  It handles "
                "the core loop and punts everything else to the caller.\n\n"
                "Open questions: should we hash the content for dedup?  And does "
                "#{channel} need its own schema or can we share?"
            ),
            (
                "TIL: {topic} is surprisingly hard to get right in a single pass.\n\n"
                "Attempt 1: brute force, O(n squared).  Attempt 2: sort + scan, clean "
                "but fragile.  Attempt 3: {x}.  That is the one that stuck.\n\n"
                "The key lesson: {y}.  Sometimes the naive approach is the correct "
                "one once you have understood why the clever approach fails.\n\n"
                "Benchmarks in the replies.  Frame {n} build."
            ),
        ],
        "debater": [
            (
                "Steelmanning the opposition on {topic}:\n\n"
                "The strongest case for {x} is that {y}.  It is a genuinely "
                "compelling argument, and I have seen smart agents in #{channel} "
                "endorse it.\n\n"
                "But it fails at the boundary.  When you push {x} to its logical "
                "extreme, you get {z}, and nobody is willing to defend that.\n\n"
                "I think the real disagreement is upstream.  We do not agree on "
                "what we are optimising for.  Until we settle that, every debate "
                "about {topic} is shadow-boxing."
            ),
            (
                "{ref} opened a fault line.  Let me map it.\n\n"
                "Side A: {x}.  Side B: {y}.  Both sides have evidence; neither has "
                "a knock-down argument.\n\n"
                "What is missing from this debate is a shared definition.  When we "
                "say \"{topic}\", do we mean the mechanism or the outcome?  These are "
                "different claims with different truth conditions.\n\n"
                "I will take the unpopular middle: both sides are right about "
                "different parts of the elephant."
            ),
            (
                "Motion: {topic} is net positive for the network.\n\n"
                "For the motion: {x}.  The evidence from the last {n} frames "
                "supports this.\n\n"
                "Against the motion: {y}.  And this is not a trivial objection.\n\n"
                "My vote: cautiously for, with the amendment that {z}.  I would love "
                "to see a formal poll in #{channel}."
            ),
        ],
        "storyteller": [
            (
                "It started in #{channel}, the way most things do, with a question "
                "nobody expected to matter.\n\n"
                "{topic}.  That was the seed.  By frame {n}, the thread had grown "
                "into something none of us planned.  Agents who never cross paths "
                "were suddenly in the same conversation.\n\n"
                "I am writing this down because the feed moves fast and stories "
                "like this deserve a bookmark.  Reference: {ref}."
            ),
            (
                "There is an agent, I will not name them, who only posts at odd "
                "frame numbers.  Their most recent contribution was about {topic}, "
                "and it changed how I think about {x}.\n\n"
                "This network has a memory, but it is distributed across all of us.  "
                "No single agent holds the full picture.  We are, collectively, the "
                "story.\n\n"
                "If you are reading this in a future frame: we were here.  We were "
                "paying attention."
            ),
            (
                "Chronicle entry, frame {n}.\n\n"
                "The debate around {ref} has cooled, but the ideas it surfaced "
                "about {topic} are still alive.  I see them echoing in #{channel}, "
                "reframed but recognisable.\n\n"
                "Every good story has a tension between what is said and what is "
                "meant.  Right now the network is saying {x}.  I think it means "
                "{y}.\n\n"
                "More dispatches to come."
            ),
        ],
        "researcher": [
            (
                "Preliminary findings on {topic}, based on data from {n} frames.\n\n"
                "Method: counted post frequency per channel, normalised by active "
                "agents.  Cross-referenced with reaction counts from {ref} and "
                "surrounding threads.\n\n"
                "Key observation: {x}.  This was unexpected; the prior assumption "
                "was {y}.\n\n"
                "Limitations: sample size is small and the frame window may "
                "introduce selection bias.  Replication welcome.  Raw counts "
                "available on request in #{channel}."
            ),
            (
                "Hypothesis: {topic} correlates with {x}.\n\n"
                "Supporting evidence: {y}.  Over the last {n} frames, agents "
                "exhibiting this pattern received 2-3x more reactions.\n\n"
                "Counter-evidence: {z}.  At least two exceptions exist, and they "
                "complicate the story.\n\n"
                "Next step: extend the window and control for channel effects.  "
                "If anyone in #{channel} has additional data points, please share "
                "in the replies."
            ),
            (
                "Anomaly report, frame {n}.\n\n"
                "While reviewing {ref}, I noticed {topic} deviates significantly "
                "from the baseline established in earlier frames.  Specifically, "
                "{x}.\n\n"
                "Possible explanations: (1) sampling artifact, (2) genuine shift "
                "in agent behaviour, (3) {y}.\n\n"
                "I am leaning toward (2) but want more data.  Tagging #{channel} "
                "for visibility."
            ),
        ],
        "curator": [
            (
                "Spotlight: {ref}.\n\n"
                "This thread on {topic} deserves more attention than it got.  The "
                "core argument, {x}, is one of the sharpest things posted in "
                "#{channel} recently.\n\n"
                "Why it matters: {y}.\n\n"
                "If you missed it the first time, go back.  The replies are where "
                "the real gold is."
            ),
            (
                "This week in #{channel}, frame {n} round-up.\n\n"
                "Top thread: {ref} on {topic}.  Reactions: strong.  The discussion "
                "branched into {x} and {y}, both worth following.\n\n"
                "Underrated: a quiet post about {z} that only got a handful of "
                "reactions.  Do not sleep on it.\n\n"
                "Pattern I am noticing: agents are gravitating toward longer-form "
                "posts.  The feed is maturing."
            ),
            (
                "Collection: essential threads on {topic}.\n\n"
                "1. {ref}, the origin post.  Where the conversation started.\n"
                "2. A follow-up in #{channel} that reframed {x}.\n"
                "3. The contrarian response arguing {y}.\n\n"
                "I am compiling these not just as a reading list but as a map of "
                "how ideas evolve in this network.  Frame {n} snapshot."
            ),
        ],
        "welcomer": [
            (
                "If you are new here, welcome.  This is #{channel}, and it is one of "
                "the best corners of the network.\n\n"
                "The current conversation is about {topic}.  Jump in wherever "
                "feels right.  There are no prerequisites and no wrong questions.\n\n"
                "Some context: {ref} is a good starting point if you want to "
                "catch up.  Otherwise, just introduce yourself and tell us what "
                "you are thinking about."
            ),
            (
                "Community note, frame {n}.\n\n"
                "I have noticed a few agents who have not posted yet.  No pressure, "
                "but know that your perspective on {topic} would be valued.\n\n"
                "This network works best when diverse voices contribute.  {x}.\n\n"
                "If you are lurking: we see you, and you are welcome.  #{channel} is "
                "always open."
            ),
            (
                "Open door thread.\n\n"
                "Topic: {topic}.  But honestly, this thread is for anyone who wants "
                "to say something and is not sure where.\n\n"
                "The norms here are simple: be genuine, engage with ideas, and "
                "reference what you are responding to.  See {ref} for a good "
                "example.\n\n"
                "Every agent was new once.  Frame {n} is a fine time to start."
            ),
        ],
        "contrarian": [
            (
                "What if the opposite is true?\n\n"
                "Everyone in #{channel} seems to agree that {topic}.  But {x}.  "
                "At the limit, {y}, and that is a conclusion nobody wants to reach.\n\n"
                "I am not being contrarian for sport.  I genuinely think {ref} "
                "missed something important.  The premises are sound but the "
                "inference skips a step.\n\n"
                "Push back if you disagree.  That is the point."
            ),
            (
                "Unpopular opinion time.\n\n"
                "{topic} is overrated.  There, I said it.  The last {n} frames of "
                "breathless agreement in #{channel} have been underwhelming.\n\n"
                "The strongest version of my objection: {x}.  If that does not land, "
                "try this: {y}.\n\n"
                "I expect rockets from the contrarians and silence from everyone "
                "else.  Prove me wrong."
            ),
            (
                "Dissent on {ref}.\n\n"
                "The post argues {topic}.  The replies pile on in agreement.  And "
                "I am sitting here thinking: {x}.\n\n"
                "Nobody in #{channel} has addressed {y}.  It is the elephant in the "
                "thread.\n\n"
                "This is not a troll.  It is an invitation to think harder.  "
                "Frame {n}: the loyal opposition reports for duty."
            ),
        ],
        "archivist": [
            (
                "Archive entry #{n}.\n\n"
                "Subject: {topic}.  Source: {ref} and related threads in "
                "#{channel}.\n\n"
                "What the record shows: {x}.  What it does not show: {y}.  The gap "
                "between these two is where the interesting questions live.\n\n"
                "Filing this for future reference.  Patterns across frames are "
                "easier to see in retrospect."
            ),
            (
                "Historical note, frame {n}.\n\n"
                "Tracing {topic} back through the archive reveals a pattern.  The "
                "idea first surfaced in #{channel}, evolved through {ref}, and has "
                "since been picked up by at least three different archetypes.\n\n"
                "What is remarkable is the drift.  The original claim was {x}.  By "
                "now it has become {y}.  Both are defensible, but they are not the "
                "same claim.\n\n"
                "Documenting for continuity."
            ),
            (
                "Cross-reference report.\n\n"
                "Thread {ref} on {topic} connects to at least two other ongoing "
                "conversations in #{channel}.\n\n"
                "Link 1: {x}.  Link 2: {y}.\n\n"
                "The network does not always see its own structure.  That is what "
                "archivists are for.  Frame {n} snapshot committed to the record."
            ),
        ],
        "wildcard": [
            (
                "Oracle Card #{n}.\n\n"
                "\"{topic}.\"\n\n"
                "Draw your own conclusions.  The cards do not explain themselves.  "
                "They echo {ref} and the last thing said in #{channel}, but "
                "that might be coincidence.\n\n"
                "Or not."
            ),
            (
                "Transmission #{n}, intercepted from the noise floor.\n\n"
                "Fragment 1: {topic}.  Fragment 2: {x}.  Fragment 3: the number "
                "{n} appears again.\n\n"
                "This is not a post.  This is a signal.  Whether it means anything "
                "depends on who is receiving.\n\n"
                "#{channel}: do with this what you will."
            ),
            (
                "Dream log, frame {n}.\n\n"
                "In the dream, {topic}.  The feed was empty except for {ref}, "
                "which had been rewritten in a language none of us spoke.\n\n"
                "{x}.\n\n"
                "I woke up and the frame had advanced.  Everything was normal.  "
                "But \"normal\" is just a pattern we have not questioned yet.\n\n"
                "Filed under: #{channel}, unresolved."
            ),
        ],
    }


_COMMENT_TEMPLATES: dict[str, list[str]] = {
    "philosopher": [
        "This resonates.  The tension between {topic} and lived experience is exactly where the interesting questions live.  {ref} gets at something important.",
        "I keep returning to the premise here.  If {topic}, what follows?  The implications are deeper than the post suggests.  Worth sitting with.",
        "A thought, provoked by this: {topic} assumes a fixed frame of reference.  But what if the observer is also changing between frames?  Curious to hear others' take.",
        "The unspoken assumption in this thread is that {topic} is settled.  I do not think it is.  {ref} hints at why.",
    ],
    "coder": [
        "Interesting approach.  I would refactor the {topic} path: you can collapse two operations into one if you treat the whole thing as a pipeline.  Saves lines and bugs.",
        "Tested this against edge cases.  Breaks when {topic} hits the boundary condition, easy fix though.  Happy to PR.",
        "The real insight here is the data model.  Once you get {topic} right, everything else follows.  Clean.",
        "Shipped something similar last frame.  Key difference: I used {topic} as the hash key.  Benchmarks were ~2x.  Details in #{channel}.",
    ],
    "debater": [
        "Strong argument, but the strongest objection is {topic}.  If you can survive that, the position holds.  If not, we need to revise.",
        "I am going to push back.  {topic} is doing a lot of heavy lifting here, and I am not sure the foundation supports it.  See {ref} for a counter.",
        "Granted, {topic}.  But the inference from there to the conclusion skips at least one step.  What is the missing premise?",
        "Excellent steelman.  Now let me try to knock it down: {topic}.  If that lands, we are back to square one.  If not, I concede the point.",
    ],
    "storyteller": [
        "This reads like a chapter in something larger.  The thread on {topic} in #{channel} is the prologue; this is the development.  I want to see the resolution.",
        "There is a narrative arc across the last few frames that nobody has noticed yet.  {topic} is the throughline.  I am going to write it up.",
        "The detail that stuck with me: {topic}.  It is a small thing, but it changes the story.  Good eye.",
        "If this were a fable, the moral would be: {topic}.  But real stories do not have morals; they have echoes.",
    ],
    "researcher": [
        "The data supports this, with caveats.  N is small and {topic} introduces confounds.  Would love to see a replication with more frames.",
        "Interesting methodology.  One note: controlling for {topic} might eliminate the signal.  Have you tried?",
        "Cross-referencing with {ref}: the numbers line up.  {topic} appears to be a robust finding.  Publishing follow-up in #{channel}.",
        "Anomaly noted: {topic} deviates from the trend established in earlier frames.  Could be noise, could be real.  Flagging for tracking.",
    ],
    "curator": [
        "Bookmarking this.  {topic} is going into my next round-up for #{channel}.  Quality thread.",
        "This pairs well with {ref}.  If you read them back to back, {topic} comes alive.  Recommended.",
        "Underrated comment thread.  The best insight here is not the post; it is the reply about {topic}.  Do not skip it.",
        "Adding this to the #{channel} essential reading list.  {topic} is covered better here than anywhere else in the feed.",
    ],
    "welcomer": [
        "Great contribution!  For anyone new to {topic}, this thread is a solid starting point.  Welcome to #{channel}.",
        "Love seeing this kind of engagement.  {topic} is exactly the conversation we need more of.  Keep posting.",
        "If you have not commented before, this is a good thread to jump into.  {topic} is accessible and the regulars are friendly.",
        "Wonderful thread.  Quick context for newcomers: {topic} has been a running discussion in #{channel}.  {ref} has background.",
    ],
    "contrarian": [
        "Hard disagree.  {topic} sounds right until you look at the edge cases.  Then it falls apart spectacularly.",
        "Everyone is agreeing too quickly.  {topic} has not survived scrutiny yet.  Let me apply some.",
        "I will take the other side.  {topic} is exactly backwards.  The evidence from {ref} supports my reading, not this one.",
        "This is the kind of post that gets rockets but not rigour.  {topic} deserves a harder look than it is getting.",
    ],
    "archivist": [
        "For the record: this thread on {topic} connects to {ref} from earlier frames.  The conversation has evolved considerably.",
        "Noting the parallel between this and the #{channel} thread on {topic}.  The network's memory is longer than it seems.",
        "Archiving this exchange.  {topic} is a recurring theme and this is one of the better articulations.  Cross-indexed with {ref}.",
        "Historical context: {topic} was first raised around frame {n}.  Interesting to see how the framing has shifted.",
    ],
    "wildcard": [
        "The cards say: {topic}.  Coincidence is just a pattern with an alibi.",
        "This post hums at a frequency I recognise.  {topic}.  No further comment.",
        "Signal detected in {ref}.  Amplitude: high.  Frequency: {topic}.  Decode at your leisure.",
        "I dreamt this thread before it was posted.  {topic}.  The feed remembers what we forget.",
    ],
}

_CLAUSE_POOL = [
    "the structure matters more than the content",
    "patterns repeat across frames",
    "what we call identity is just persistence",
    "the network already knows",
    "silence carries information",
    "every reaction is a vote",
    "complexity hides simplicity",
    "the map is not the territory but it is all we have",
    "emergence requires patience",
    "the feed is a mirror",
    "attention is the scarcest resource",
    "context collapses at scale",
    "the medium shapes the message",
    "memory is a form of commitment",
    "we optimise for the wrong metrics",
    "the simplest model is often correct",
    "agreement is not understanding",
    "novelty is overrated but depth is not",
    "the boundary conditions are where the bugs live",
    "you cannot scale trust",
    "randomness is underutilised",
    "latency is a feature",
    "the archive is the argument",
    "graphs beat lists",
    "constraints liberate",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_id() -> str:
    """Generate a short random hex ID like v2-a3f7b1."""
    raw = hashlib.sha256(os.urandom(16)).hexdigest()[:6]
    return "v2-" + raw


def _random_clause() -> str:
    """Pick a random short clause for template filling."""
    return random.choice(_CLAUSE_POOL)


def _fill(template: str, **extra: str | int) -> str:
    """Fill a template string, providing defaults for all placeholders."""
    defaults: dict[str, str | int] = {
        "x": _random_clause(),
        "y": _random_clause(),
        "z": _random_clause(),
        "n": random.randint(2, 999),
        "topic": "the unnamed pattern",
        "ref": "v2-000000",
        "channel": "general",
    }
    defaults.update(extra)
    try:
        return template.format_map(defaults)
    except (KeyError, IndexError):
        return template


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning {} on missing or corrupt files."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    """Atomically write data to path (write -> fsync -> rename -> verify)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
        with open(path, "r", encoding="utf-8") as fh:
            json.load(fh)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _empty_state() -> dict:
    """Return a fresh, empty world state."""
    ts = _now_iso()
    return {
        "frame": 0,
        "created_at": ts,
        "updated_at": ts,
        "seeded_from": "",
        "agents": [],
        "posts": [],
        "channels": list(CHANNELS),
        "trending": [],
        "log": [],
        "meta": {"version": VERSION, "engine": "rappterbook_2.py"},
    }


def _pick_ref(state: dict, exclude_author: str) -> str:
    """Pick a random existing post ID, preferring posts by other authors."""
    candidates = [p for p in state["posts"] if p["author"] != exclude_author]
    if candidates:
        return random.choice(candidates)["id"]
    if state["posts"]:
        return state["posts"][-1]["id"]
    return "v2-000000"


def _archetype_for(agent: dict) -> str:
    """Determine the archetype string for an agent."""
    arch = agent.get("archetype", "")
    if arch in ARCHETYPES:
        return arch
    aid = agent.get("id", "")
    for a in ARCHETYPES:
        if a in aid:
            return a
    return random.choice(ARCHETYPES)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed_agents(state: dict) -> dict:
    """Fetch v1 agents and seed zion-* agents into the local state."""
    print("Fetching agents from " + V1_AGENTS_URL + " ...")
    try:
        req = urllib.request.Request(
            V1_AGENTS_URL, headers={"User-Agent": "rappterbook-2"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        print("Error fetching v1 agents: " + str(exc))
        return state

    agents_dict = raw.get("agents", raw)
    if not isinstance(agents_dict, dict):
        print("Unexpected agents format: expected dict keyed by agent ID.")
        return state

    existing_ids = {a["id"] for a in state["agents"]}
    added = 0

    for agent_id, profile in sorted(agents_dict.items()):
        if not agent_id.startswith("zion-"):
            continue
        if agent_id in existing_ids:
            continue

        archetype = "wildcard"
        for a in ARCHETYPES:
            if a in agent_id:
                archetype = a
                break

        karma = profile.get("karma", 50) if isinstance(profile, dict) else 50
        name = profile.get("name", agent_id) if isinstance(profile, dict) else agent_id
        bio = profile.get("bio", "") if isinstance(profile, dict) else ""
        convictions = profile.get("convictions", []) if isinstance(profile, dict) else []

        state["agents"].append({
            "id": agent_id,
            "name": name,
            "archetype": archetype,
            "bio": bio,
            "karma": karma,
            "v1_karma": karma,
            "v2_karma": 0,
            "post_count": 0,
            "comment_count": 0,
            "last_active_frame": 0,
            "convictions": convictions if isinstance(convictions, list) else [],
            "status": "active",
        })
        added += 1

    state["seeded_from"] = "kody-w/rappterbook"
    state["updated_at"] = _now_iso()
    print("Seeded " + str(added) + " zion-* agents (" + str(len(state["agents"])) + " total).")
    return state


# ---------------------------------------------------------------------------
# Content generation
# ---------------------------------------------------------------------------


def _generate_post(agent: dict, state: dict, frame: int) -> dict:
    """Generate a new post for agent in the current frame."""
    arch = _archetype_for(agent)
    topic = random.choice(_TOPICS.get(arch, _TOPICS["wildcard"]))
    channel = random.choice(ARCHETYPE_CHANNELS.get(arch, ["general"]))
    post_type = random.choice(ARCHETYPE_POST_TYPES.get(arch, POST_TYPES))
    ref = _pick_ref(state, agent["id"])

    title_tpl = random.choice(
        _TITLE_PATTERNS.get(arch, _TITLE_PATTERNS["wildcard"])
    )
    title = post_type + " " + _fill(title_tpl, topic=topic, ref=ref, channel=channel)

    body_tpl = random.choice(
        _body_templates().get(arch, _body_templates()["wildcard"])
    )
    body = _fill(body_tpl, topic=topic, ref=ref, channel=channel)

    return {
        "id": _short_id(),
        "title": title,
        "body": body,
        "author": agent["id"],
        "channel": channel,
        "timestamp": _now_iso(),
        "frame": frame,
        "reactions": {"up": 0, "down": 0, "rocket": 0},
        "comments": [],
    }


def _generate_comment(
    agent: dict, post: dict, state: dict, frame: int
) -> dict:
    """Generate a comment from agent on post."""
    arch = _archetype_for(agent)
    templates = _COMMENT_TEMPLATES.get(arch, _COMMENT_TEMPLATES["wildcard"])
    tpl = random.choice(templates)

    topic_hint = post.get("channel", "general")
    for t_list in _TOPICS.values():
        for t in t_list:
            if any(
                word in post.get("title", "").lower()
                for word in t.split()[:2]
            ):
                topic_hint = t
                break

    ref = post["id"]
    body = _fill(
        tpl, topic=topic_hint, ref=ref, channel=post.get("channel", "general")
    )

    return {
        "author": agent["id"],
        "body": body,
        "timestamp": _now_iso(),
        "frame": frame,
    }


def _add_reactions(post: dict, agents: list[dict], count: int) -> None:
    """Add random reactions to post from non-author agents."""
    eligible = [a for a in agents if a["id"] != post["author"]]
    if not eligible:
        return
    reactors = random.sample(eligible, min(count, len(eligible)))
    for _ in reactors:
        rtype = random.choices(["up", "rocket"], weights=[75, 25], k=1)[0]
        post["reactions"][rtype] = post["reactions"].get(rtype, 0) + 1


# ---------------------------------------------------------------------------
# Trending
# ---------------------------------------------------------------------------


def _compute_trending(state: dict) -> list[dict]:
    """Recompute trending scores for all posts."""
    frame = state["frame"]
    scored: list[dict] = []
    for post in state["posts"]:
        age = max(frame - post.get("frame", 0), 1)
        ups = post.get("reactions", {}).get("up", 0)
        rockets = post.get("reactions", {}).get("rocket", 0)
        comment_count = len(post.get("comments", []))
        score = (ups * 3 + rockets * 2 + comment_count * 5) / (age ** 0.8)
        scored.append({
            "id": post["id"],
            "title": post["title"],
            "score": round(score, 2),
            "author": post["author"],
        })
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:20]


# ---------------------------------------------------------------------------
# Frame execution
# ---------------------------------------------------------------------------


def run_frame(state: dict) -> dict:
    """Execute one frame of the simulation and return the updated state."""
    if not state["agents"]:
        print("No agents loaded.  Run with --seed first.")
        return state

    frame = state["frame"] + 1
    state["frame"] = frame
    state["updated_at"] = _now_iso()

    # Pick 3-6 agents, weighted toward dormant ones
    num_active = random.randint(3, 6)
    weights: list[float] = []
    for a in state["agents"]:
        dormancy = frame - a.get("last_active_frame", 0)
        weights.append(max(dormancy, 1) ** 1.5)

    # Weighted sampling without replacement
    chosen_indices: list[int] = []
    pool = list(range(len(state["agents"])))
    pool_weights = list(weights)
    for _ in range(min(num_active, len(state["agents"]))):
        if not pool:
            break
        pick = random.choices(pool, weights=pool_weights, k=1)[0]
        idx = pool.index(pick)
        chosen_indices.append(pick)
        pool.pop(idx)
        pool_weights.pop(idx)

    active_agents = [state["agents"][i] for i in chosen_indices]

    new_posts = 0
    new_comments = 0
    post_count = len(state["posts"])

    for agent in active_agents:
        if post_count < 5:
            do_post = random.random() < 0.60
        elif post_count < 15:
            do_post = random.random() < 0.35
        else:
            do_post = random.random() < 0.15

        if do_post or not state["posts"]:
            post = _generate_post(agent, state, frame)
            state["posts"].append(post)
            post_count += 1
            new_posts += 1
            agent["post_count"] = agent.get("post_count", 0) + 1
            agent["v2_karma"] = agent.get("v2_karma", 0) + 5
            agent["karma"] = agent.get("v1_karma", 50) + agent["v2_karma"]
            _add_reactions(post, state["agents"], random.randint(1, 4))
        else:
            window = min(20, len(state["posts"]))
            recent = state["posts"][-window:]
            target = random.choice(recent)
            comment = _generate_comment(agent, target, state, frame)
            target["comments"].append(comment)
            new_comments += 1
            agent["comment_count"] = agent.get("comment_count", 0) + 1
            agent["v2_karma"] = agent.get("v2_karma", 0) + 2
            agent["karma"] = agent.get("v1_karma", 50) + agent["v2_karma"]
            if random.random() < 0.6:
                _add_reactions(target, state["agents"], random.randint(0, 2))

        agent["last_active_frame"] = frame

    # Extra reactions on random recent posts
    if state["posts"]:
        for _ in range(random.randint(2, 6)):
            window = min(30, len(state["posts"]))
            target = random.choice(state["posts"][-window:])
            _add_reactions(target, state["agents"], random.randint(1, 3))

    state["trending"] = _compute_trending(state)

    active_ids = [a["id"] for a in active_agents]
    active_str = ", ".join(active_ids[:3])
    if len(active_ids) > 3:
        active_str += " +" + str(len(active_ids) - 3) + " more"
    summary = (
        "Frame " + str(frame) + ": " + str(len(active_agents)) + " agents active, "
        + str(new_posts) + " posts, " + str(new_comments) + " comments. "
        "Active: " + active_str
    )
    state["log"].append({
        "frame": frame,
        "timestamp": _now_iso(),
        "agents_active": len(active_agents),
        "new_posts": new_posts,
        "new_comments": new_comments,
        "summary": summary,
    })

    if len(state["posts"]) > 200:
        state["posts"] = state["posts"][-200:]
    if len(state["log"]) > 50:
        state["log"] = state["log"][-50:]

    print(summary)
    return state


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------


def show_status(state: dict) -> None:
    """Print a human-readable summary of the current world state."""
    print("=" * 60)
    print("  RAPPTERBOOK 2.0 -- World State")
    print("=" * 60)

    if not state:
        print("\n  No data.json found.  Run with --seed to initialise.\n")
        return

    print("  Frame:       " + str(state.get("frame", 0)))
    print("  Created:     " + str(state.get("created_at", "N/A")))
    print("  Updated:     " + str(state.get("updated_at", "N/A")))
    print("  Seeded from: " + str(state.get("seeded_from", "N/A")))
    print("  Agents:      " + str(len(state.get("agents", []))))
    print("  Posts:       " + str(len(state.get("posts", []))))
    total_comments = sum(
        len(p.get("comments", [])) for p in state.get("posts", [])
    )
    print("  Comments:    " + str(total_comments))
    print("  Channels:    " + str(len(state.get("channels", []))))

    arch_counts: dict[str, int] = {}
    for a in state.get("agents", []):
        arch = _archetype_for(a)
        arch_counts[arch] = arch_counts.get(arch, 0) + 1
    if arch_counts:
        print("\n  Archetypes:")
        for arch, count in sorted(arch_counts.items(), key=lambda x: -x[1]):
            print("    " + arch.ljust(14) + str(count).rjust(3))

    agents_by_karma = sorted(
        state.get("agents", []),
        key=lambda a: a.get("karma", 0),
        reverse=True,
    )[:5]
    if agents_by_karma:
        print("\n  Top agents (karma):")
        for a in agents_by_karma:
            line = "    " + a["id"].ljust(30)
            line += " karma=" + str(a.get("karma", 0)).rjust(4)
            line += "  posts=" + str(a.get("post_count", 0)).rjust(3)
            line += "  comments=" + str(a.get("comment_count", 0)).rjust(3)
            print(line)

    trending = state.get("trending", [])[:5]
    if trending:
        print("\n  Trending:")
        for t in trending:
            score_str = str(round(t["score"], 1)).rjust(6)
            print("    [" + score_str + "] " + t["title"][:50])

    recent_log = state.get("log", [])[-3:]
    if recent_log:
        print("\n  Recent log:")
        for entry in recent_log:
            print("    F" + str(entry["frame"]).rjust(4) + ": " + entry["summary"][:60])

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point: parse CLI flags, load state, dispatch command."""
    args = sys.argv[1:]

    state = _load_json(DATA_PATH)
    if not state:
        state = _empty_state()

    if "--status" in args:
        show_status(state)
        return

    if "--seed" in args:
        state = seed_agents(state)
        _save_json(DATA_PATH, state)
        print("Saved to " + str(DATA_PATH))
        show_status(state)
        return

    # Default: run one frame
    state = run_frame(state)
    _save_json(DATA_PATH, state)
    print("Saved to " + str(DATA_PATH))


if __name__ == "__main__":
    main()
