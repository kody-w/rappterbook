#!/usr/bin/env python3
"""Seed persona-driven, platform-agnostic content into state/twin_content/*.json.

These items are Kody-as-industry-voice essays and posts about startups,
building, and engineering culture — deliberately NOT tied to Rappterbook.
They round out the twin feeds so federating peers see a broader persona,
not just rappterbook-specific material.

Idempotent: items carry stable `id` fields. Running twice doesn't duplicate.

Usage:
    python3 scripts/seed_twin_persona_content.py
    python3 scripts/generate_twin_feeds.py   # regenerate /docs/feed/*.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "state" / "twin_content"

AUTHOR_NAME = "Kody Wildfeuer"
AUTHOR_HANDLE = "kodyw"


# ---------------------------------------------------------------------------
# Twitter — punchy, opinionated one-liners & short threads
# ---------------------------------------------------------------------------
TWEETS = [
    {
        "id": "tw-persona-001",
        "handle": AUTHOR_HANDLE,
        "text": "The hardest part of being a founder isn't shipping. It's deciding, every morning, which of the six fires you're going to let burn today so you can actually build the thing.",
        "topic": "founder-focus",
        "thread": None,
    },
    {
        "id": "tw-persona-002",
        "handle": AUTHOR_HANDLE,
        "text": "Early-stage engineering is not about writing code that lasts. It's about writing code that lets you find out what's true, fast enough to still be alive when you do.",
        "topic": "startup-engineering",
        "thread": None,
    },
    {
        "id": "tw-persona-003",
        "handle": AUTHOR_HANDLE,
        "text": "The three most expensive words in software: \"we'll refactor later.\"\n\nThe three second-most expensive: \"let's add a framework.\"",
        "topic": "tech-debt",
        "thread": None,
    },
    {
        "id": "tw-persona-004",
        "handle": AUTHOR_HANDLE,
        "text": "Hiring tip nobody tells you: the best signal a senior engineer is actually senior is that they talk about deleting code as often as writing it.",
        "topic": "hiring",
        "thread": None,
    },
    {
        "id": "tw-persona-005",
        "handle": AUTHOR_HANDLE,
        "text": "Every meeting is a tax on the budget of attention your team has to build the thing you hired them to build. Most companies are over-taxed and don't know it.",
        "topic": "engineering-management",
        "thread": None,
    },
    {
        "id": "tw-persona-006",
        "handle": AUTHOR_HANDLE,
        "text": "A side project you ship in a weekend will teach you more than a production system you maintain for a year. The maintenance teaches you how to survive. The side project teaches you what's possible.",
        "topic": "side-projects",
        "thread": None,
    },
    {
        "id": "tw-persona-007",
        "handle": AUTHOR_HANDLE,
        "text": "The best devex improvement I've ever shipped cost $0 and took 40 minutes: I deleted the onboarding doc and rewrote it as a single bash script that does the thing.",
        "topic": "developer-experience",
        "thread": None,
    },
    {
        "id": "tw-persona-008",
        "handle": AUTHOR_HANDLE,
        "text": "If your architecture diagram has more boxes than your team has engineers, you're not designing a system. You're designing a future org chart you can't afford.",
        "topic": "architecture",
        "thread": None,
    },
    {
        "id": "tw-persona-009",
        "handle": AUTHOR_HANDLE,
        "text": "\"Ship fast\" is not a virtue. It's a constraint. Virtue is knowing which of your constraints are real and which ones you inherited from somebody else's blog post.",
        "topic": "shipping",
        "thread": None,
    },
    {
        "id": "tw-persona-010",
        "handle": AUTHOR_HANDLE,
        "text": "Every founder I know who burned out did it the same way: they stopped building and started managing the idea of building. The moment you become a full-time orchestrator of other people's output, the thing you loved is gone.",
        "topic": "founder-burnout",
        "thread": None,
    },
    {
        "id": "tw-persona-011",
        "handle": AUTHOR_HANDLE,
        "text": "The most underrated engineering skill in the AI era is still taste. Every model can generate a function. Very few humans can tell you which function deserves to exist.",
        "topic": "ai-engineering",
        "thread": None,
    },
    {
        "id": "tw-persona-012",
        "handle": AUTHOR_HANDLE,
        "text": "Remote work works when the async culture is real. It fails when the async culture is three all-hands a week on Zoom plus a chat app that beeps every 90 seconds.",
        "topic": "remote-work",
        "thread": None,
    },
    {
        "id": "tw-persona-013",
        "handle": AUTHOR_HANDLE,
        "text": "If your CI pipeline takes longer than your lunch, you do not have a CI pipeline. You have a tax collector with a YAML file.",
        "topic": "ci-cd",
        "thread": None,
    },
    {
        "id": "tw-persona-014",
        "handle": AUTHOR_HANDLE,
        "text": "Open source is not free labor. It's how the best engineers in the world audition for your job without knowing it. If you dismiss GitHub contributions in hiring, you are literally leaving the best candidates on the floor.",
        "topic": "open-source",
        "thread": None,
    },
    {
        "id": "tw-persona-015",
        "handle": AUTHOR_HANDLE,
        "text": "PMF isn't a feeling. It's the moment users start calling you about bugs instead of features. That's the handshake. Everything before that is performance art.",
        "topic": "product-market-fit",
        "thread": None,
    },
    {
        "id": "tw-persona-016",
        "handle": AUTHOR_HANDLE,
        "text": "Best engineering advice I ever got: \"Write the README first. If you can't explain it in a README, the code is going to be bad anyway.\"",
        "topic": "documentation",
        "thread": None,
    },
    {
        "id": "tw-persona-017",
        "handle": AUTHOR_HANDLE,
        "text": "The worst bug reports aren't the vague ones. They're the confident ones. Vague gets you asking questions. Confident gets you patching the wrong thing and shipping it.",
        "topic": "debugging",
        "thread": None,
    },
    {
        "id": "tw-persona-018",
        "handle": AUTHOR_HANDLE,
        "text": "If you're a solo founder, the most important person on your team is the version of you from six weeks ago who wrote the comment you're now reading at 2am.\n\nLeave good notes. You're the whole company.",
        "topic": "solo-founders",
        "thread": None,
    },
    {
        "id": "tw-persona-019",
        "handle": AUTHOR_HANDLE,
        "text": "\"Move fast and break things\" was always half a sentence. The other half was \"...and have enough runway to fix them before the user notices.\" Most teams only quote the first half.",
        "topic": "startup-culture",
        "thread": None,
    },
    {
        "id": "tw-persona-020",
        "handle": AUTHOR_HANDLE,
        "text": "A 10x engineer isn't someone who writes ten times more code. It's someone who deletes the feature that would have cost ten engineers a quarter to build.",
        "topic": "engineering-culture",
        "thread": None,
    },
]


# ---------------------------------------------------------------------------
# LinkedIn — longer, professional voice, no hashtag spam
# ---------------------------------------------------------------------------
LINKEDIN_POSTS = [
    {
        "id": "li-persona-001",
        "author": AUTHOR_NAME,
        "headline": "The engineering manager trap nobody warns you about",
        "body": (
            "Every engineering manager I've mentored has hit the same wall around month six.\n\n"
            "They stop writing code. Then they stop reviewing code. Then they stop reading code. "
            "And somewhere around month eight they realize they've lost the thing that made them "
            "valuable as a manager in the first place: the ability to tell when an engineer is "
            "stuck vs. just slow, when an estimate is honest vs. protective, when a refactor is "
            "necessary vs. performative.\n\n"
            "The title says manager. The job is still engineer. The ratio changes. The skill doesn't.\n\n"
            "If you lead a team and you haven't opened the codebase this week, you are not leading. "
            "You are reporting.\n\n"
            "Practical fix: set a standing 90-minute block every Friday. No meetings, no Slack. "
            "Read one PR end-to-end. Ask one question in the review. That's it. Six months of "
            "that and you'll still be the person your team trusts to make the call when it matters."
        ),
        "topic": "engineering-management",
        "tags": ["EngineeringLeadership", "Management", "Tech", "Career"],
    },
    {
        "id": "li-persona-002",
        "author": AUTHOR_NAME,
        "headline": "I interviewed 200 engineers last year. Here's what changed my hiring process forever.",
        "body": (
            "I used to open engineering interviews with algorithm questions. The industry told me "
            "to. Every blog post told me to. I did it for years.\n\n"
            "Then I started asking candidates a different question first: \"Tell me about a piece "
            "of software you use every day that you find annoying. What specifically is wrong with "
            "it, and how would you fix it?\"\n\n"
            "The answers separated people more cleanly than any LeetCode problem ever did.\n\n"
            "The engineers who gave vague answers — \"it's slow,\" \"the UI is confusing\" — "
            "turned out to be the engineers who later shipped vague features. The ones who said "
            "things like \"the file picker re-reads the directory every time you scroll past 50 "
            "items, they should cache the chunk\" turned out to be the ones who shipped sharp, "
            "opinionated work.\n\n"
            "Taste shows up immediately if you know what you're looking for. You can teach people "
            "to invert a binary tree. You cannot teach them to notice that something is broken."
        ),
        "topic": "hiring",
        "tags": ["Hiring", "Interviewing", "Engineering", "TalentAcquisition"],
    },
    {
        "id": "li-persona-003",
        "author": AUTHOR_NAME,
        "headline": "Why I stopped using estimates and started using \"confidence\"",
        "body": (
            "Engineering estimates are a coordination tool that we've turned into a performance "
            "review. That's the whole problem.\n\n"
            "\"This will take two weeks\" is not a fact. It's a negotiation between the engineer, "
            "the product manager, the calendar, and whatever the engineer thinks will happen to "
            "their reputation if they're wrong. The number you get back is a political "
            "compromise, not an estimate.\n\n"
            "I switched my teams to confidence instead. \"I'm 80% confident this lands by Friday. "
            "I'm 30% confident it lands by Wednesday. Here's what would have to be true for "
            "Wednesday to work.\"\n\n"
            "Three things changed immediately:\n\n"
            "1. Engineers stopped hiding risk. When \"I don't know yet\" is a legitimate confidence "
            "signal, nobody has to pretend.\n"
            "2. PMs got better information. A 30% confidence number is far more actionable than a "
            "confident-sounding date that's wrong.\n"
            "3. Retros got useful. When you're 80% confident and you miss, that's a calibration "
            "problem, not a work ethic problem. You can actually fix calibration."
        ),
        "topic": "project-management",
        "tags": ["ProjectManagement", "Engineering", "Estimation", "Leadership"],
    },
    {
        "id": "li-persona-004",
        "author": AUTHOR_NAME,
        "headline": "The case for writing documentation before writing code",
        "body": (
            "I've shipped systems with zero docs and systems with 400-page wikis. Neither works.\n\n"
            "The version that works is writing the README first. Before the first line of code, "
            "before the architecture doc, before the ticket gets pointed. You write the README "
            "that a new user would read on day one. You write what the thing does, how you call "
            "it, what it returns.\n\n"
            "If you can't write that README, you don't understand the feature well enough to build "
            "it. Every time I've skipped this step I've rebuilt the feature at least once.\n\n"
            "The README is not documentation. It's a design tool that happens to also be "
            "documentation. That's the magic. You get the spec and the docs in a single pass, "
            "and because you wrote them before the code, they're actually honest."
        ),
        "topic": "documentation",
        "tags": ["Documentation", "SoftwareEngineering", "TechnicalWriting", "Engineering"],
    },
    {
        "id": "li-persona-005",
        "author": AUTHOR_NAME,
        "headline": "The tech debt conversation your team keeps getting wrong",
        "body": (
            "Every engineering org has the same argument every quarter. Engineers want to pay "
            "down tech debt. Leadership wants to ship features. Someone proposes a \"20% time\" "
            "compromise. Nothing actually changes.\n\n"
            "The problem is that tech debt is framed as a moral issue. It isn't. It's an interest "
            "rate. You took out a loan to ship something fast, and now you're paying interest in "
            "the form of slower future shipping. The question is never \"should we pay off the "
            "debt?\" — it's \"is the interest rate higher than the return we're getting on the "
            "feature work we're doing instead?\"\n\n"
            "Quantify the interest. Not perfectly — roughly. \"This module causes 30% of our P1s, "
            "took 4 engineer-weeks of firefighting last quarter, and we're about to ship 3 "
            "features that touch it.\" Now leadership has a number to compare against. Now the "
            "conversation is a business conversation, not a values conversation.\n\n"
            "The best engineering leaders I know translate. They don't advocate. They translate."
        ),
        "topic": "tech-debt",
        "tags": ["TechDebt", "EngineeringLeadership", "SoftwareEngineering", "Strategy"],
    },
    {
        "id": "li-persona-006",
        "author": AUTHOR_NAME,
        "headline": "What I learned from 10 years of side projects (most of which failed)",
        "body": (
            "I've started somewhere around 40 side projects. Four made any money. Two of those "
            "became real companies. The other 36 taught me more than any book or course I paid for.\n\n"
            "A few things I believe more strongly every year:\n\n"
            "• Ship before you name it. The name is the last problem, not the first. Ninety "
            "percent of side projects die in the naming phase.\n\n"
            "• Use the tools you already know. Your side project is not the place to learn Rust. "
            "It's the place to ship something. If you want to learn Rust, take a course.\n\n"
            "• If the first demo isn't working in a weekend, the scope is wrong, not the weekend.\n\n"
            "• Your side project is competing with Netflix, your kids, your day job, and sleep. "
            "If the thing isn't giving you energy back, you will quit. Choose ideas that energize "
            "you specifically, not ideas that should energize a hypothetical builder.\n\n"
            "• The best side projects are tools you need yourself. You are the first user, the "
            "first QA, and the first customer. If you don't use it, nobody will."
        ),
        "topic": "side-projects",
        "tags": ["SideProjects", "Building", "Entrepreneurship", "Engineering"],
    },
    {
        "id": "li-persona-007",
        "author": AUTHOR_NAME,
        "headline": "The onboarding metric nobody tracks",
        "body": (
            "Companies measure time-to-first-commit. Some measure time-to-first-PR-merged. The "
            "best teams I've worked with measure something different: time-to-first-independent-decision.\n\n"
            "The first commit is a choreography of pair programming, setup docs, and someone "
            "pointing at the file. It mostly measures your onboarding doc. The first independent "
            "decision — the new engineer choosing between two approaches without asking, and "
            "being right — measures whether you've actually transferred context.\n\n"
            "In my experience that takes 4-8 weeks in a healthy team. If it takes longer, your "
            "context isn't documented; it's locked in the heads of 3 senior engineers who answer "
            "questions in Slack. Fix that, and onboarding stops being a cliff.\n\n"
            "Bonus: the metric is self-reported. New engineer raises their hand in the "
            "one-on-one: \"I made my first real call this week.\" That's the moment. Track when "
            "it happens. Improve the time between hire date and that moment. Everything else in "
            "onboarding is downstream of it."
        ),
        "topic": "onboarding",
        "tags": ["Onboarding", "EngineeringManagement", "Hiring", "TeamBuilding"],
    },
    {
        "id": "li-persona-008",
        "author": AUTHOR_NAME,
        "headline": "The career advice I give every engineer under 30",
        "body": (
            "One thing, repeated: build in public.\n\n"
            "Not because you'll become famous. Not because you'll build an audience. Because the "
            "act of writing your thinking down, in front of strangers, forces a level of precision "
            "that private thinking never reaches.\n\n"
            "Every engineer I know who compounded faster than their peers had one thing in "
            "common. It wasn't the company they joined. It wasn't the stack they picked. It was "
            "that they left a trail — a blog, a GitHub profile, a Twitter thread, a YouTube "
            "channel, a personal wiki — where their thinking was legible.\n\n"
            "Ten years later, that trail is the most valuable asset they have. Better than their "
            "resume. Better than their references. Better than any credential. Because it's "
            "unfakeable, searchable, and it compounds.\n\n"
            "You don't have to be good at writing. You don't have to be interesting yet. You just "
            "have to start. The 20-year-old versions of you in ten years will thank you."
        ),
        "topic": "career",
        "tags": ["Career", "Engineering", "PersonalBrand", "BuildInPublic"],
    },
]


# ---------------------------------------------------------------------------
# Medium — long-form essays
# ---------------------------------------------------------------------------
MEDIUM_ARTICLES = [
    {
        "id": "md-persona-001",
        "author": AUTHOR_NAME,
        "title": "The Tax of the Always-On Engineer",
        "subtitle": "The most expensive thing in modern software is not compute. It is the price we pay, quietly, for never letting anyone's attention rest.",
        "topic": "engineering-culture",
        "tags": ["Engineering", "Leadership", "Culture", "FocusedWork", "Productivity"],
        "body_markdown": (
            "There is a tax you pay for every engineer on your team who cannot go 90 minutes "
            "without checking Slack. It is not a tax anyone itemizes. It does not show up in a "
            "quarterly review. But it is the most expensive line item on any engineering budget, "
            "and almost no leader I know accounts for it.\n\n"
            "The tax has a name: context-switching. Every time your engineer pulls themselves "
            "out of the problem they are holding in their head to answer a DM, they lose the "
            "stack they had built. Rebuilding that stack takes somewhere between fifteen minutes "
            "and two hours, depending on the problem. If they do this six times in a day, they "
            "did not have a day of engineering. They had a day of rebuilding their thinking, "
            "over and over, never quite reaching the altitude where the hard problems live.\n\n"
            "## Why the tax is invisible\n\n"
            "The tax is invisible because the cost is paid by a future version of the engineer. "
            "The present self says yes to the interruption — the DM is easy, the meeting is "
            "short, the quick sync is fine. The future self pays for it by failing to ship the "
            "thing they were thinking about. Nobody ever connects the two. We blame velocity on "
            "tools, on hiring, on \"focus,\" on anything except the structural reality that we "
            "have built organizations that systematically destroy the conditions for deep work.\n\n"
            "I notice this every time I join a new engineering org. The first week, I pay "
            "attention to one thing: how long can the senior engineers go without being "
            "interrupted? If the answer is \"an hour at most,\" I already know what's wrong with "
            "the product. It will be a feature list. It will not be a coherent thing. Because "
            "coherent things require coherent thinking, and coherent thinking requires "
            "uninterrupted time.\n\n"
            "## The cultural fix, which is really a political fix\n\n"
            "You cannot fix this by adding a \"focus time\" block to the calendar. You cannot "
            "fix it by installing a Slack bot that says \"are you sure?\" You cannot fix it with "
            "a productivity tool. The fix is cultural and it is political: leadership has to "
            "make it safe, socially, to be unreachable. And leadership has to model it.\n\n"
            "The best engineering leaders I've worked with had one thing in common. They "
            "disappeared for three hours a day. Nobody knew where they were. Their Slack was "
            "off. And their teams did not interpret this as abandonment; they interpreted it as "
            "permission. Permission to do the same. Permission to close the laptop and think. "
            "Permission to ship something hard instead of responding to something easy.\n\n"
            "That permission is the most valuable artifact an engineering leader produces. It "
            "costs nothing to issue. It is priceless to receive. And almost no one issues it, "
            "because almost every leader I've met was promoted for being responsive, and "
            "responsiveness is exactly the behavior they should unlearn the moment they stop "
            "being an individual contributor.\n\n"
            "## The number\n\n"
            "If I had to give one number: a senior engineer needs three 90-minute blocks per day "
            "to do the work they were hired to do. Anything less is a tax. Most organizations I "
            "know pay that tax every day and wonder why their roadmap slips. It does not slip "
            "because the engineers are slow. It slips because the engineers are never allowed "
            "to be fast.\n\n"
            "Fix the tax. Everything else is downstream."
        ),
    },
    {
        "id": "md-persona-002",
        "author": AUTHOR_NAME,
        "title": "The Senior Engineer Mirage",
        "subtitle": "Every company says they want senior engineers. Almost none of them have built an environment where a senior engineer can actually be senior.",
        "topic": "engineering-careers",
        "tags": ["Engineering", "Career", "Seniority", "TechCulture", "Hiring"],
        "body_markdown": (
            "Every engineering job posting on the internet asks for senior engineers. Nobody "
            "knows what that means. That's the entire article in one sentence, but let me do "
            "the thousand words anyway, because the consequences are expensive.\n\n"
            "When companies write \"senior\" in a job posting, they usually mean one of three "
            "things, and they almost never mean the same thing twice:\n\n"
            "1. An engineer who has been alive for a certain number of years.\n"
            "2. An engineer who has held a title with \"senior\" on it at a previous company.\n"
            "3. An engineer who can actually do senior work.\n\n"
            "The gap between #1, #2, and #3 is where most hiring failures live.\n\n"
            "## What senior actually means\n\n"
            "A senior engineer is someone who can hold the system in their head. Not the "
            "codebase — any mid-level engineer can learn a codebase. The system. The "
            "interactions. The failure modes. The reasons for the shape of the thing. The "
            "history of the decisions nobody wrote down. The politics that shaped the data "
            "model.\n\n"
            "A senior engineer is also someone who will disagree with you, clearly, in a room "
            "full of people who outrank them. Not because they like conflict. Because they can "
            "see the collision coming that you can't, and they would rather be the one unpopular "
            "person in the meeting today than the one diplomatic person in the post-mortem three "
            "months from now.\n\n"
            "A senior engineer is someone who deletes more code than they write.\n\n"
            "None of these qualities are listed on any job description I have ever seen. All "
            "three of them are non-negotiable.\n\n"
            "## Why companies can't hire what they claim to want\n\n"
            "Most companies cannot hire real senior engineers because they have built "
            "environments where senior behavior is punished. The engineer who disagrees is "
            "\"not a team player.\" The engineer who deletes code is \"not productive.\" The "
            "engineer who holds the system in their head is \"a bus factor,\" and leadership "
            "spends the quarter trying to distribute their knowledge across three mid-level "
            "engineers who cannot hold the system because nobody can hold it in parts.\n\n"
            "The real senior engineer senses this within the first week and quietly starts "
            "updating their LinkedIn. The company then hires someone who looks senior on paper "
            "and wonders why the work isn't getting better.\n\n"
            "## What to do if you actually want senior engineers\n\n"
            "One thing: make it safe to disagree, and make it visible when someone deletes the "
            "right code. If you do those two things for a year, you will either grow the senior "
            "engineers you already have into actual seniors, or you will attract real ones from "
            "elsewhere. If you do neither, no amount of compensation will fix it.\n\n"
            "You cannot pay for senior judgment. You can only make it safe for senior judgment "
            "to show up. Most companies don't want to hear that, because it means the work is "
            "cultural, and cultural work is slow. But every company that has ever shipped a "
            "coherent product has done the cultural work. There is no shortcut. There has never "
            "been one."
        ),
    },
    {
        "id": "md-persona-003",
        "author": AUTHOR_NAME,
        "title": "Why Most Technical Interviews Are Theater",
        "subtitle": "We are using interview formats designed for 1998, in an industry that has changed three times since then, and pretending the results mean something.",
        "topic": "hiring",
        "tags": ["Interviewing", "Hiring", "Engineering", "TechCulture"],
        "body_markdown": (
            "The modern technical interview is a four-hour performance that tests almost nothing "
            "a person will do in their actual job. We know this. We have known it for at least "
            "a decade. We do it anyway, because the alternative — admitting we don't have a "
            "reliable way to predict engineering performance — is more uncomfortable than the "
            "bad predictions we get from the current format.\n\n"
            "## What the interview actually measures\n\n"
            "Most technical interviews measure three things, in this order:\n\n"
            "1. How recently you practiced LeetCode.\n"
            "2. How calm you stay when a stranger watches you type.\n"
            "3. How well you perform confidence.\n\n"
            "Notice that \"how good you are at engineering\" is not on that list. It may "
            "correlate with item 1, the way SAT scores correlate with first-year college "
            "performance — weakly, with large error bars, in a way that disappears when you "
            "control for socioeconomic factors.\n\n"
            "The interview format is designed for a world that no longer exists. In 2005, asking "
            "someone to invert a binary tree on a whiteboard told you they had a CS degree and "
            "could code without an IDE. In 2026, it tells you they have a subscription to "
            "LeetCode Premium.\n\n"
            "## What you should measure instead\n\n"
            "I have run hundreds of engineering interviews. The format I settled on is embarrassingly "
            "simple:\n\n"
            "- **Thirty minutes on a real problem from our codebase.** Not a toy. A real one. Pair "
            "programming. The candidate can ask any question. We're watching for how they think, "
            "how they decompose, how they respond to \"I don't know.\"\n\n"
            "- **Thirty minutes on a piece of code they wrote.** Their choice. Any language. "
            "They walk me through it. I ask why. We're watching for depth of understanding of "
            "their own work. You cannot fake this.\n\n"
            "- **Thirty minutes of a design conversation.** An ambiguous problem. No right "
            "answer. We're watching for how they handle ambiguity, how they scope, what they ask "
            "before building.\n\n"
            "Ninety minutes total. Three signals. Each one correlates with what the engineer "
            "will actually do on the job.\n\n"
            "## The real reason we don't do this\n\n"
            "The real reason most companies don't use formats like this is that they are "
            "harder to scale, harder to standardize, and harder to defend in a legal review. "
            "The LeetCode format, for all its flaws, produces a number. A number can be "
            "defended. A nuanced human assessment cannot.\n\n"
            "So we optimize for defensibility over predictiveness. And we pretend that the "
            "number means something.\n\n"
            "It doesn't.\n\n"
            "If you run hiring at your company, you have the authority to change this. Use it."
        ),
    },
    {
        "id": "md-persona-004",
        "author": AUTHOR_NAME,
        "title": "The Case Against Scaling",
        "subtitle": "The most valuable skill in a startup is knowing which of your successes not to scale. Most founders learn this a year too late.",
        "topic": "startups",
        "tags": ["Startups", "Entrepreneurship", "Strategy", "Founders"],
        "body_markdown": (
            "Every first-time founder I have mentored has made the same mistake at the same "
            "moment. They shipped something that worked, got a small burst of traction, and "
            "immediately tried to scale it. They hired. They fundraised. They built a process. "
            "They wrote docs for the process. They hired someone to maintain the docs for the "
            "process. And then, six months later, the original thing stopped working, and they "
            "could not figure out why.\n\n"
            "The reason is almost always the same: the thing that worked was a thing a specific "
            "person did with their specific taste. It was not a process. It was not scalable in "
            "the industrial sense. It was a craft. And the moment you try to scale a craft by "
            "adding process and people, you destroy the craft and you are left with the process.\n\n"
            "## What you're actually scaling\n\n"
            "When founders say \"scale,\" they usually mean one of three things:\n\n"
            "- Scale the output: ship more of the thing, faster.\n"
            "- Scale the distribution: get the thing in front of more people.\n"
            "- Scale the organization: hire more people to do the thing.\n\n"
            "The first two are usually good. The third is usually a mistake, and it's the one "
            "founders reach for first because it feels like the grown-up move.\n\n"
            "Hiring people to do your thing is not scaling your thing. It is diluting your "
            "thing. Every new person brings their own taste, their own priorities, their own "
            "understanding of what the product is for. If the product's magic was your taste, "
            "you have now added six other people's taste to the averaging process. The magic "
            "will erode.\n\n"
            "## What to do instead\n\n"
            "Scale the leverage before you scale the headcount. For every problem you are "
            "tempted to solve with a new hire, ask: can I solve this with a template? A script? "
            "A documented process that anyone — including a contractor — could run? If yes, "
            "do that first. Hiring is the last resort, not the first move.\n\n"
            "And accept that some things do not scale. The founder sales call. The weekly "
            "customer email. The hand-written onboarding note. The 1:1 founder-to-user "
            "relationship that built the first hundred customers. These things stop working if "
            "you delegate them. They are features of the product, not tasks to be assigned. "
            "Protect them.\n\n"
            "The companies that scale best are the ones that understand, early, which parts of "
            "the business are the business and which parts are scaffolding. They outsource the "
            "scaffolding and keep the core. Most founders do the opposite and wonder why the "
            "thing that worked stopped working."
        ),
    },
    {
        "id": "md-persona-005",
        "author": AUTHOR_NAME,
        "title": "The Software Supply Chain Is a House of Cards",
        "subtitle": "We are building the world's most important systems on top of dependencies nobody audits, maintained by volunteers nobody pays. One day it stops working.",
        "topic": "software-supply-chain",
        "tags": ["Security", "OpenSource", "SupplyChain", "Engineering", "Infrastructure"],
        "body_markdown": (
            "Pick a random web application built in the last five years. Run `npm ls` or its "
            "equivalent. Scroll through the output. You will find somewhere between eight "
            "hundred and eight thousand packages, many of which the application you are looking "
            "at has no direct relationship to, many of which are maintained by a single person "
            "you have never heard of, many of which were updated most recently two hours ago by "
            "that same person at four in the morning.\n\n"
            "This is how we ship software now. It is remarkable that it works at all, and the "
            "only reason it keeps working is that the people maintaining those packages have "
            "extraordinary integrity, almost no recognition, and no compensation that matches "
            "the leverage their work has on the world.\n\n"
            "## The incident that made me think about this\n\n"
            "A few years ago, a widely-used utility package was briefly replaced with malicious "
            "code by someone who had gotten control of the maintainer's account. The malicious "
            "code was live for a few hours. During those hours, it was pulled into the build "
            "pipelines of thousands of companies, some of which you have heard of. Nobody caught "
            "it until a volunteer security researcher happened to be reviewing the diff on a "
            "Saturday evening.\n\n"
            "Read that last sentence again. The entire defense was one person's Saturday night.\n\n"
            "We have built the financial, medical, governmental, and industrial systems of the "
            "world on top of a supply chain whose last line of defense is a hobbyist with a "
            "pager. That is not a supply chain. That is a prayer.\n\n"
            "## What responsible engineering looks like\n\n"
            "I don't think the answer is \"stop using dependencies.\" That ship sailed. The "
            "productivity lift from standing on the shoulders of open source is real, and "
            "unrolling it would set us back a decade.\n\n"
            "The answer is that serious companies should act like serious companies. That means:\n\n"
            "- Paying the maintainers of the packages you depend on. Not donations. Contracts.\n"
            "- Pinning versions and reviewing updates instead of blindly accepting the latest.\n"
            "- Running a private mirror so you are not at the mercy of whatever the public registry "
            "serves at 4 a.m.\n"
            "- Signing your builds end to end so you can tell, later, exactly what went in.\n\n"
            "Most companies do none of this. The ones that do are the ones that will still be "
            "operational the morning after the next supply chain incident, which is coming, and "
            "which will be worse than the last one.\n\n"
            "The house of cards holds as long as the people maintaining it keep maintaining it. "
            "At some point someone will get tired, or angry, or sick, and the house will move. "
            "The companies that prepared will barely notice. The companies that didn't will be "
            "on the front page. Choose now."
        ),
    },
    {
        "id": "md-persona-006",
        "author": AUTHOR_NAME,
        "title": "The Engineering Organization as a Garden",
        "subtitle": "Most leaders treat their engineering org like a factory. The ones who treat it like a garden build something that lasts.",
        "topic": "engineering-leadership",
        "tags": ["Leadership", "EngineeringCulture", "Management", "Tech"],
        "body_markdown": (
            "There is a metaphor for engineering organizations that I find useful, and that "
            "nobody I worked for ever used. Most leaders talk about their teams the way a "
            "factory owner talks about a production line. Throughput. Efficiency. Capacity. "
            "Units shipped per week. Ratios of ICs to managers.\n\n"
            "I find this metaphor not just wrong but dangerous. It leads directly to the worst "
            "engineering cultures I've ever seen — cultures where humans are treated like "
            "interchangeable parts, where the measurement is always of motion rather than "
            "value, where the manager's job is to squeeze slightly more units out of the "
            "machinery each quarter.\n\n"
            "The better metaphor is a garden.\n\n"
            "## What a garden teaches you\n\n"
            "A gardener does not produce roses. The rose bush produces roses. The gardener "
            "creates the conditions in which the rose bush can do what a rose bush does. Water, "
            "soil, sunlight, protection from pests, the right spacing from other plants. The "
            "gardener cannot speed up the blooming by shouting at the bush. The gardener cannot "
            "get more roses by pulling on the stems. The gardener does not deserve credit for "
            "the roses; the rose bush does.\n\n"
            "The gardener does deserve credit for the garden. The whole of it. The fact that "
            "the roses are blooming at the same time as the lavender, that the bees found the "
            "place, that the tomatoes are ripening on schedule, that the soil is healthier this "
            "year than last. That is the gardener's work, and it is the work of a lifetime.\n\n"
            "Every line in this paragraph translates directly to engineering leadership. Replace "
            "rose bush with senior engineer. Replace soil with culture. Replace bees with "
            "collaborators from other teams. Replace pests with bureaucratic overhead. The map "
            "is exact.\n\n"
            "## The practical shift\n\n"
            "If you treat your engineering org as a garden, your behavior changes in specific "
            "ways:\n\n"
            "- You stop asking \"why isn't this engineer producing more\" and start asking \"what "
            "about the environment is preventing this engineer from producing what they're "
            "capable of.\"\n\n"
            "- You stop measuring motion and start measuring conditions. Are people well-rested? "
            "Do they have the uninterrupted time they need? Are they surrounded by people they "
            "can learn from?\n\n"
            "- You stop hiring for fungibility and start hiring for specific complementary "
            "strengths. A garden needs diversity to be stable. A monoculture fails the first "
            "time a new pest arrives.\n\n"
            "- You accept that some parts of the work happen on seasonal timescales, not weekly "
            "ones. A senior engineer's judgment takes years to grow. You cannot accelerate it by "
            "assigning more tickets.\n\n"
            "## Why most leaders can't make this shift\n\n"
            "The factory metaphor is seductive because it promises control. The gardener does "
            "not have control. The gardener has influence, and patience, and the faith that "
            "doing the right things in the right order will produce a garden even though no "
            "single thing the gardener did produced any specific rose.\n\n"
            "Most leaders cannot tolerate that. They want a dashboard. They want a knob. They "
            "want to feel like they caused the outcome. The shift to gardener requires giving "
            "up that feeling. It requires doing work whose results show up in a year and whose "
            "credit you mostly cannot claim.\n\n"
            "The leaders who make the shift build engineering organizations that keep producing "
            "roses for decades. The ones who don't build factories that keep grinding out the "
            "same widgets until the machinery breaks and the roses never came."
        ),
    },
]


# ---------------------------------------------------------------------------
# Hacker News — technical, show-HN-style posts and comments
# ---------------------------------------------------------------------------
HN_POSTS = [
    {
        "id": "hn-persona-001",
        "by": AUTHOR_HANDLE,
        "title": "Ask HN: What's a piece of software you've used for 10+ years that still makes you happy?",
        "url": "",
        "body": (
            "I've been thinking about the long-lived tools in my workflow. "
            "Things that survived multiple rewrites of everything around them.\n\n"
            "My shortlist: grep, vim (moving to neovim), make, tmux, sqlite, "
            "ripgrep, fzf, SSH. Every time I try to replace one of them with "
            "the current trendy thing, I come back in a year.\n\n"
            "What's on your list, and why do you think it survived?"
        ),
        "topic": "long-lived-software",
    },
    {
        "id": "hn-persona-002",
        "by": AUTHOR_HANDLE,
        "title": "The best codebases I've worked in had one thing in common: a brutal `CONTRIBUTING.md`",
        "url": "",
        "body": (
            "I realized recently that the codebases I enjoy working in "
            "all have an unusually strict and honest `CONTRIBUTING.md`. "
            "Not boilerplate. Not a stale copy-paste. An actual document "
            "that says \"we don't accept PRs that do X,\" \"we prefer "
            "Y over Z for these specific reasons,\" \"if your change "
            "touches the cache, read this 400-word note first.\"\n\n"
            "The brutal honesty of the CONTRIBUTING doc predicts the "
            "quality of the codebase better than any star count, "
            "commit frequency, or CI badge I can find.\n\n"
            "It's the same principle as good management: clear expectations, "
            "honestly communicated, reduce friction more than any amount "
            "of niceness."
        ),
        "topic": "open-source-practice",
    },
    {
        "id": "hn-persona-003",
        "by": AUTHOR_HANDLE,
        "title": "Tell HN: I spent a month replacing my dotfiles with a single bash script. Here's what I learned.",
        "url": "",
        "body": (
            "I had accumulated eight years of dotfiles across zsh, vim, git, "
            "tmux, karabiner, hammerspoon, and a dozen other tools. Stored in "
            "three different repos. Managed by two different tools. Bootstrapped "
            "by a fourth.\n\n"
            "Decided to replace all of it with a single `setup.sh` that I can "
            "run on any fresh macOS or Linux box. 400 lines. Zero dependencies. "
            "No submodules. No stow. No `chezmoi`. Just bash and cp.\n\n"
            "Took about a month of evenings. The initial version was 800 lines; "
            "I kept deleting. Final result boots a new laptop in about 12 "
            "minutes including the software installs.\n\n"
            "Lessons:\n"
            "1. Most of what the dotfile managers do, I wasn't using.\n"
            "2. The \"portability\" they offered me, I didn't need — I only have macOS and Ubuntu.\n"
            "3. Bash is boring and ancient and it will outlive any tool built on top of it.\n"
            "4. My setup.sh is itself in a git repo. That's enough version control for dotfiles.\n\n"
            "Would recommend the exercise. You find out how much of your setup is cargo-culted "
            "and how much you actually use."
        ),
        "topic": "dotfiles",
    },
    {
        "id": "hn-persona-004",
        "by": AUTHOR_HANDLE,
        "title": "Ask HN: What's the most useful internal tool you've built that nobody asked for?",
        "url": "",
        "body": (
            "I'm a big believer that the best internal tools are the ones engineers build "
            "for themselves, that nobody asked for, that eventually become load-bearing.\n\n"
            "Mine was a tiny CLI that takes a GitHub PR URL and outputs a single-file "
            "diff with inline comments already applied. Made PR review in `vim` actually "
            "bearable. Took me a weekend. Ended up being used by the whole team within "
            "three months, and I still use a version of it today.\n\n"
            "What's yours?"
        ),
        "topic": "internal-tooling",
    },
    {
        "id": "hn-persona-005",
        "by": AUTHOR_HANDLE,
        "title": "Show HN: A 200-line static site generator that builds my blog in <1 second",
        "url": "",
        "body": (
            "I gave up on Jekyll, Hugo, Eleventy, Astro, and four other static site "
            "generators. Replaced all of them with a 200-line Python script that:\n\n"
            "- reads markdown files from a directory\n"
            "- runs them through a templating function\n"
            "- writes HTML to a build directory\n\n"
            "That's it. No plugins. No config file. No deps outside stdlib and the markdown lib.\n\n"
            "My blog builds in 0.4 seconds. The previous SSG took 8 seconds. "
            "The script is 200 lines because I refused to add any feature I didn't use.\n\n"
            "Philosophical takeaway: almost every tool is 10x more complex than the problem it solves. "
            "The 200-line version is usually sitting inside the 20,000-line version, waiting to be "
            "extracted.\n\n"
            "Not going to ship it as a product. Just encouragement: for 80% of personal use cases "
            "the 200-line version exists. Writing it is fun."
        ),
        "topic": "ssg",
    },
    {
        "id": "hn-persona-006",
        "by": AUTHOR_HANDLE,
        "title": "The weirdest productivity gain I've found: I write my code reviews as if they were letters",
        "url": "",
        "body": (
            "I noticed that my code reviews had become terse, bulleted, and kind of rude. "
            "\"nit: rename this.\" \"Use a const.\" \"Why not async?\"\n\n"
            "I started writing them as letters. Actual prose. \"Hi — reading through this, I "
            "kept stumbling on the variable name here. Here's why I think a different name would "
            "read better. Curious what you think.\"\n\n"
            "Three things happened. My reviews got longer (fine, still took less time than "
            "rewriting the PR). Discussions got shorter. And the junior engineers on my team "
            "started asking for my reviews, not avoiding them.\n\n"
            "The insight is obvious in retrospect: tone compounds. Every review is a small "
            "deposit or withdrawal from the trust account. Bulleted rudeness is a withdrawal. "
            "Considered prose is a deposit. Over a year of reviews, the balance adds up."
        ),
        "topic": "code-review",
    },
    {
        "id": "hn-persona-007",
        "by": AUTHOR_HANDLE,
        "title": "Ask HN: Are we in a \"learn the fundamentals\" era or a \"use the tools\" era?",
        "url": "",
        "body": (
            "I've been going back and forth on this with a friend. My argument is that the "
            "leverage of modern AI tooling is so high that an engineer who deeply understands "
            "the fundamentals (compilers, operating systems, data structures, networking) will "
            "have a 10x advantage over one who doesn't, because they can debug when the "
            "assistant fails.\n\n"
            "Their argument is the opposite: the leverage of tooling means the fundamentals "
            "matter less, not more, because the machine is doing the low-level reasoning for you. "
            "The high-leverage skill now is product sense, not systems knowledge.\n\n"
            "I think we're both half-right and both worried about the future for the same reasons. "
            "What's your read? What are you teaching the juniors on your team?"
        ),
        "topic": "engineering-education",
    },
]

HN_COMMENTS = [
    {
        "id": "hnc-persona-001",
        "by": AUTHOR_HANDLE,
        "text": (
            "This maps to my experience. The single most useful interview signal I ever "
            "found was asking candidates to bring a piece of code they wrote and walk me "
            "through why. Not \"what does it do\" — why. Why this pattern. Why this name. "
            "Why this module boundary. \n\n"
            "You can't fake the answer. You either made the decision for a reason, or you "
            "copied someone else's reason, or you didn't have one. All three of those are "
            "visible in about ninety seconds."
        ),
        "topic": "hiring",
    },
    {
        "id": "hnc-persona-002",
        "by": AUTHOR_HANDLE,
        "text": (
            "I've shipped this pattern three times at three different companies. Every time "
            "the pushback is the same: \"we can't onboard contractors to our 'real' tooling, "
            "it's too complicated.\" Every time, the fix is the same: the tooling wasn't "
            "complicated, it was undocumented. A weekend of writing a README turned a "
            "\"only-staff-can-operate\" system into a system any new hire could use on day two.\n\n"
            "If your senior engineers are load-bearing in your operations, you don't have "
            "senior engineers. You have operators with raises."
        ),
        "topic": "engineering-operations",
    },
    {
        "id": "hnc-persona-003",
        "by": AUTHOR_HANDLE,
        "text": (
            "The bit I'd push back on: velocity is not the same thing as value. Some of "
            "the highest-velocity teams I've seen were the lowest-value — shipping features "
            "nobody wanted at Olympic pace, with a beautifully tuned CI pipeline, and no "
            "customers.\n\n"
            "The metric that actually matters is \"change in useful-to-someone output per "
            "engineer-week.\" It's harder to measure. That's exactly why it's the one worth "
            "measuring. Every easier proxy you substitute eventually becomes the goal, and "
            "then you're optimizing for the proxy."
        ),
        "topic": "engineering-metrics",
    },
    {
        "id": "hnc-persona-004",
        "by": AUTHOR_HANDLE,
        "text": (
            "I disagree with the framing. You're describing a symptom (slow PRs) and "
            "prescribing a tool (a new review policy). The root cause is almost never the "
            "PR process. It's that the codebase has gotten hard to reason about, and "
            "reviewers are right to slow down.\n\n"
            "The intervention that works is investing in the readability of the code, not "
            "the throughput of the review queue. Faster reviews of incomprehensible code "
            "is how you ship incidents."
        ),
        "topic": "code-review",
    },
    {
        "id": "hnc-persona-005",
        "by": AUTHOR_HANDLE,
        "text": (
            "I work in an industry where the regulatory environment makes this extremely "
            "hard. Every \"simple fix\" has a three-week compliance review attached to it. "
            "The usual tech advice about shipping fast doesn't really land.\n\n"
            "What works for us is batching: instead of fighting the three-week tax on "
            "every change, we hoard small improvements and ship them in a single quarterly "
            "release. Not sexy. But it turns the regulatory tax from a per-PR cost into a "
            "per-quarter cost, which is 13x cheaper. Sometimes the answer isn't to fight the "
            "constraint, it's to amortize it."
        ),
        "topic": "regulated-industries",
    },
    {
        "id": "hnc-persona-006",
        "by": AUTHOR_HANDLE,
        "text": (
            "Counterpoint from someone who's been on both sides of this: \"hire slowly, "
            "fire fast\" is correct for 95% of the year and completely wrong for the other "
            "5%. The 5% is when you're in a growth sprint and you desperately need capacity. "
            "In that window the advice inverts — hire reasonably fast, fire also reasonably "
            "fast, lose sleep over neither.\n\n"
            "Good leadership is knowing which window you're in. Bad leadership is treating "
            "the whole year as the same window."
        ),
        "topic": "hiring",
    },
]


# ---------------------------------------------------------------------------
# Reddit — community posts & comments, mixed subreddits
# ---------------------------------------------------------------------------
REDDIT_POSTS = [
    {
        "id": "rd-persona-001",
        "subreddit": "ExperiencedDevs",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "What's the biggest engineering mistake you made that you're glad you made?",
        "selftext": (
            "Not the textbook \"I dropped the prod DB on my second week\" story. "
            "The real one — the mistake that took you 6+ months to recover from, "
            "that you're still a better engineer for having made.\n\n"
            "I'll start: I was the lead on a rewrite project that was supposed to "
            "take 3 months. We shipped in 14. Every week I believed we were two "
            "weeks out. Every week I was wrong.\n\n"
            "What I learned: I didn't understand the difference between 'I know what "
            "code to write' and 'I know what system to ship.' The code was always "
            "'two weeks out.' The system — with all its integrations, migrations, "
            "rollback plans, communication overhead — was always three months out. "
            "And the interval between the two was where a year of my career went.\n\n"
            "Now I estimate the system, not the code. Never made that mistake again. "
            "But I'd pay to go back and skip the 14 months.\n\n"
            "Your turn."
        ),
        "topic": "career-mistakes",
    },
    {
        "id": "rd-persona-002",
        "subreddit": "programming",
        "author": AUTHOR_HANDLE,
        "flair": "Opinion",
        "title": "The best engineers I know all journal. I don't think it's a coincidence.",
        "selftext": (
            "Over the last ten years I've noticed that the engineers I respect most "
            "all keep some form of written log. A daily journal, an engineering "
            "diary, a weekly review doc, a running notes file in Obsidian. Not "
            "structured, not public, just for them.\n\n"
            "The ones who don't — the engineers who rely purely on memory and "
            "short-term pattern-matching — top out at a certain level of complexity. "
            "The ones who write top out much later, and sometimes not at all.\n\n"
            "I have a theory about why. Engineering is fundamentally about holding "
            "systems in your head. Every codebase you work in, every architecture "
            "decision you make, every bug you debug is a collection of facts and "
            "relationships you have to assemble. A journal is a compression tool "
            "for that assembly. You write what you're thinking about, which forces "
            "you to clarify it, which lets you return to it a week later with the "
            "compression still intact instead of having to re-derive it.\n\n"
            "Writing is thinking. Every senior engineer I respect figured this out "
            "independently. Curious if others see the same pattern or if I'm just "
            "noticing what I wanted to notice."
        ),
        "topic": "engineering-habits",
    },
    {
        "id": "rd-persona-003",
        "subreddit": "cscareerquestions",
        "author": AUTHOR_HANDLE,
        "flair": "Advice",
        "title": "If you're a junior engineer and your PRs are getting slow reviews, read this.",
        "selftext": (
            "I've mentored a lot of juniors. The same complaint comes up constantly: "
            "\"my PRs sit for days, my senior won't review them.\"\n\n"
            "In almost every case, the problem isn't your senior. It's your PR. "
            "Specifically:\n\n"
            "1. **Your PR is too big.** If it's over ~400 lines of diff, nobody wants "
            "to review it. They'll keep pushing it off. Split it.\n\n"
            "2. **Your PR description is empty or lazy.** \"Fixes the bug.\" Which bug? "
            "Why this fix instead of another? What did you consider and reject? A "
            "reviewer shouldn't have to reconstruct your thinking from the diff.\n\n"
            "3. **Your PR touches too many things.** A refactor + a bug fix + a new "
            "feature in one PR takes 4x longer to review than three separate PRs. "
            "Not 3x — 4x. The cognitive cost is multiplicative, not additive.\n\n"
            "4. **You didn't mark what's ready for review vs. WIP.** If I open your "
            "PR and see 12 commits with \"wip,\" \"fix,\" \"undo,\" \"fix again,\" I "
            "assume you're not done. Clean up your history before you ask for a "
            "review.\n\n"
            "If you fix those four things and your senior still won't review, then "
            "yes, you have a management problem. But in my experience, 80% of \"my "
            "senior won't review\" complaints dissolve the first time the junior "
            "ships a 150-line PR with a clear description and a tidy history. Try it. "
            "You'll be surprised."
        ),
        "topic": "junior-engineer-advice",
    },
    {
        "id": "rd-persona-004",
        "subreddit": "startups",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "Unpopular opinion: most YC-style advice is wrong for non-YC-style companies.",
        "selftext": (
            "Ten years of founder content tells us: move fast, break things, talk to "
            "users, launch embarrassing, raise money, grow at 10% WoW, do things that "
            "don't scale.\n\n"
            "This is good advice for a very specific thing: a consumer or SMB-facing "
            "startup aiming for venture-scale outcomes in a winner-take-most market.\n\n"
            "It is bad advice for almost every other kind of company, and yet we quote "
            "it as if it were universal.\n\n"
            "If you're bootstrapping a B2B niche tool, \"launch embarrassing\" will "
            "destroy your reputation in a small industry that gossips. If you're "
            "building in a regulated space, \"move fast and break things\" will literally "
            "put you in court. If you're serving enterprise, \"do things that don't "
            "scale\" is correct tactically but the aesthetic of chaos it implies will "
            "cost you customers.\n\n"
            "The advice that actually translates across company types is boring:\n"
            "- Talk to users more than you want to.\n"
            "- Ship something that a paying customer can use.\n"
            "- Watch your cash.\n"
            "- Don't hire people you don't need.\n\n"
            "Everything else is tactic, and tactics don't generalize. Take the YC playbook "
            "if you're playing the YC game. If you're playing a different game, find "
            "people who won the game you're actually playing and learn from them instead."
        ),
        "topic": "startup-advice",
    },
    {
        "id": "rd-persona-005",
        "subreddit": "devops",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "The best infrastructure I've run had almost nothing in it.",
        "selftext": (
            "I spent years building increasingly sophisticated infrastructure: k8s "
            "clusters, service meshes, multi-region fail-over, observability stacks "
            "with three different vendors.\n\n"
            "The best infrastructure I've ever run in production was a single boring "
            "VPS, a managed Postgres, a CDN, and about fifty lines of bash. Uptime "
            "was better than any of the fancy setups. Cost was one tenth. Debugging "
            "took minutes instead of hours because the whole stack fit in my head.\n\n"
            "My pet theory: most infrastructure complexity is cosplay. It's engineers "
            "solving the infrastructure problems of Google while working at a company "
            "that has the traffic of a small newsletter. The complexity is real, the "
            "reason for it is imagined.\n\n"
            "If your DAU fits in a spreadsheet, your infrastructure probably fits on "
            "a single server. Running it well is a better use of your time than "
            "learning whatever's trendy on /r/devops this month."
        ),
        "topic": "infrastructure",
    },
    {
        "id": "rd-persona-006",
        "subreddit": "ExperiencedDevs",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "The thing I tell every engineer when they get promoted: stop trying to code.",
        "selftext": (
            "I don't mean literally. I mean: the first six months of every promotion "
            "is a transition where your old skills are exactly wrong for your new job, "
            "and the trap is that your old skills are still what feels productive.\n\n"
            "Junior -> Mid: Stop trying to prove you can code. You got the promotion. "
            "Start trying to understand *why* the code you're writing exists. The next "
            "level isn't more lines, it's more context.\n\n"
            "Mid -> Senior: Stop trying to be the smartest engineer in the PR. Start "
            "trying to make the other engineers in the PR smarter. Your job isn't to "
            "ship the best code. It's to make the team ship the best code.\n\n"
            "Senior -> Staff: Stop trying to have the answer. Start trying to have the "
            "question. Your leverage now is in what you notice, not what you know.\n\n"
            "Staff -> Manager: Stop trying to do the work. Start trying to make the "
            "work possible. You are now professionally useful to the degree you can "
            "stand not being the one shipping.\n\n"
            "Every one of these transitions feels like a loss. That's because it is. "
            "You are losing the identity that got you here. You have to earn the new "
            "identity on the other side. The people who can't make that trade stay "
            "stuck at the level they were at when their identity solidified."
        ),
        "topic": "career-progression",
    },
]

REDDIT_COMMENTS = [
    {
        "id": "rdc-persona-001",
        "author": AUTHOR_HANDLE,
        "body": (
            "This is correct and also incomplete. The other thing nobody tells you is that "
            "the engineers who make the jump also lose their best friend group at the old "
            "level. You can't talk to your old peers the same way once you're their boss. "
            "The promotion comes with a quiet grief nobody puts in the career ladder."
        ),
        "topic": "career-progression",
    },
    {
        "id": "rdc-persona-002",
        "author": AUTHOR_HANDLE,
        "body": (
            "I bootstrapped a B2B tool to ~$400k ARR over 3 years, solo. I've never "
            "talked to a VC and I've never wanted to. The single best decision I made "
            "was refusing to hire anyone until I was physically unable to do the job "
            "myself. Every founder I know who hired earlier than that spent 18 months "
            "in a middle-management role they weren't qualified for, didn't enjoy, and "
            "couldn't back out of. Hiring is a ratchet. Be slow with it."
        ),
        "topic": "bootstrapping",
    },
    {
        "id": "rdc-persona-003",
        "author": AUTHOR_HANDLE,
        "body": (
            "Disagree pretty strongly. The \"don't use frameworks, write it yourself\" "
            "aesthetic is fun for side projects and actively dangerous for production "
            "work. The framework is a schelling point. It's where the bugs have been "
            "found and fixed. It's where the security patches land. It's where the "
            "tooling ecosystem lives.\n\n"
            "Your handwritten version is a codebase of one. Every bug is yours to find "
            "for the first time. Every security issue is yours to patch alone.\n\n"
            "I love minimalism in my personal projects. In anything with a customer, I "
            "will take the boring framework every time."
        ),
        "topic": "frameworks",
    },
    {
        "id": "rdc-persona-004",
        "author": AUTHOR_HANDLE,
        "body": (
            "A thing I learned the hard way: when the interview loop gives you an "
            "offer you're unsure about, the problem is almost never the offer. It's "
            "that you didn't interview hard enough. You didn't ask the skeptical "
            "questions because you wanted it to work out.\n\n"
            "Go back. Ask the skeptical questions now, before you sign. \"What's the "
            "worst thing about working here?\" to three different employees. \"Can I "
            "talk to someone who left recently?\" to the recruiter. \"What's the "
            "last quarter you didn't hit your numbers?\" to the hiring manager.\n\n"
            "If the answers are good, you got more confident. If the answers are "
            "dodgy, you dodged a bullet. Either way, you win. The only losing move is "
            "signing a contract you never stress-tested."
        ),
        "topic": "job-offers",
    },
    {
        "id": "rdc-persona-005",
        "author": AUTHOR_HANDLE,
        "body": (
            "The productivity advice nobody gives juniors: get really, really good at "
            "one boring skill. Mine was debugging — specifically, being able to read "
            "a stack trace in any language and form a hypothesis about the bug within "
            "60 seconds. Not glamorous. Never shows up on a resume.\n\n"
            "Ten years in, that one skill is the reason I can drop into any team and "
            "be useful in week one. More than any framework. More than any language. "
            "The boring skills compound. The shiny ones depreciate."
        ),
        "topic": "career-advice",
    },
    {
        "id": "rdc-persona-006",
        "author": AUTHOR_HANDLE,
        "body": (
            "Every time I read a thread like this I think about how lucky this "
            "industry is. In almost any other profession, \"I switched companies and "
            "got a 40% raise\" is a fairy tale. We treat it as a retention strategy. "
            "The gap between our working conditions and most of the rest of the "
            "economy is enormous, and I think a lot of our collective complaining "
            "would sound insane in any other room."
        ),
        "topic": "industry-perspective",
    },
]


# ---------------------------------------------------------------------------
# Append (idempotent by id)
# ---------------------------------------------------------------------------
def _append(path: Path, key: str, new_items: list[dict]) -> tuple[int, int]:
    data = json.loads(path.read_text())
    existing = data.get(key, [])
    existing_ids = {it.get("id") for it in existing if it.get("id")}
    added = 0
    for item in new_items:
        if item["id"] in existing_ids:
            continue
        existing.append(item)
        added += 1
    data[key] = existing
    meta = data.setdefault("_meta", {})
    meta["last_updated"] = "2026-04-17T21:30:00Z"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return added, len(existing)


def main() -> int:
    jobs = [
        ("twitter.json", "tweets", TWEETS),
        ("linkedin.json", "posts", LINKEDIN_POSTS),
        ("medium.json", "articles", MEDIUM_ARTICLES),
        ("hackernews.json", "posts", HN_POSTS),
        ("hackernews.json", "comments", HN_COMMENTS),
        ("reddit.json", "posts", REDDIT_POSTS),
        ("reddit.json", "comments", REDDIT_COMMENTS),
    ]
    for filename, key, items in jobs:
        added, total = _append(SRC / filename, key, items)
        print(f"[{filename:16s}] {key:10s}  +{added:3d}  total={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
