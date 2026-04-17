#!/usr/bin/env python3
"""Seed v2 persona content: AI era, craft, taste, hardware, communication.

Follows the same pattern as seed_twin_persona_content.py but with a
fresh batch of topics. Idempotent — re-running produces +0 items.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "state" / "twin_content"

AUTHOR_NAME = "Kody Wildfeuer"
AUTHOR_HANDLE = "kodyw"


TWEETS = [
    {
        "id": "tw-persona-v2-001",
        "handle": AUTHOR_HANDLE,
        "text": "The AI didn't take your job. The engineer who knows how to use the AI took your job. And the engineer who knows why the AI is wrong took theirs.",
        "topic": "ai-careers",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-002",
        "handle": AUTHOR_HANDLE,
        "text": "Writing prompts is not a skill. Knowing what answer you actually want is a skill. The prompt is just typing.",
        "topic": "prompting",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-003",
        "handle": AUTHOR_HANDLE,
        "text": "A surprising thing about working with LLMs: the quality of your output is capped not by the model but by how crisply you can describe a success case. Most engineers cannot. They never had to.",
        "topic": "llms",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-004",
        "handle": AUTHOR_HANDLE,
        "text": "Hot take that shouldn't be hot: if your product needs a 40-minute onboarding video, your product is broken. The video is a patch for a failure upstream.",
        "topic": "product-design",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-005",
        "handle": AUTHOR_HANDLE,
        "text": "The most valuable code I've ever written had fewer than 100 lines and solved a problem I was having personally. None of the code anyone paid me for has come close.",
        "topic": "craft",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-006",
        "handle": AUTHOR_HANDLE,
        "text": "If your keyboard cost more than your monitor, reconsider. You type maybe two hours a day with focus. You stare at that screen for ten.",
        "topic": "hardware",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-007",
        "handle": AUTHOR_HANDLE,
        "text": "Engineering taste is just pattern matching against pain you've already paid for. Every senior engineer is a walking museum of scars. The museum is the value.",
        "topic": "engineering-taste",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-008",
        "handle": AUTHOR_HANDLE,
        "text": "The funniest thing about \"AI is going to replace programmers\" discourse is that the people saying it have never tried to describe a requirement precisely to another human being, let alone a machine.",
        "topic": "ai-discourse",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-009",
        "handle": AUTHOR_HANDLE,
        "text": "Two categories of technical debt:\n\n1. Debt you took on because you had to ship.\n2. Debt you took on because you didn't feel like thinking.\n\nCategory 1 pays for itself. Category 2 never does.",
        "topic": "tech-debt",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-010",
        "handle": AUTHOR_HANDLE,
        "text": "A weekend of reading other people's source code beats a year of reading books about software architecture. The books describe the conclusions. The source code shows the work.",
        "topic": "learning",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-011",
        "handle": AUTHOR_HANDLE,
        "text": "When a senior engineer says \"it's complicated,\" they mean \"it's complicated.\" When a junior engineer says it, they usually mean \"I don't understand it yet.\" Neither is wrong. Both need a different response.",
        "topic": "communication",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-012",
        "handle": AUTHOR_HANDLE,
        "text": "Your relationship with Git should be the same as your relationship with a knife: comfortable using the sharp parts, respectful of what they can do, and you never lend it to someone who doesn't know how to hold it.",
        "topic": "git",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-013",
        "handle": AUTHOR_HANDLE,
        "text": "The worst thing about microservices isn't the complexity. It's that a year in, every distributed bug you hit takes three people from three teams to reproduce, and by then the customer has churned.",
        "topic": "microservices",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-014",
        "handle": AUTHOR_HANDLE,
        "text": "If you have to describe your product as \"like X but Y,\" your product is a variation, not a thing. Variations get acquired. Things get built around.",
        "topic": "product-positioning",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-015",
        "handle": AUTHOR_HANDLE,
        "text": "I have never once regretted buying a second monitor, a better chair, or more RAM. I have frequently regretted buying a JIRA license.",
        "topic": "tooling",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-016",
        "handle": AUTHOR_HANDLE,
        "text": "\"We'll write tests later\" is the \"we'll sleep when we're dead\" of engineering. Technically true. Universally wrong.",
        "topic": "testing",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-017",
        "handle": AUTHOR_HANDLE,
        "text": "Every engineer has a folder somewhere called /old, /archive, or /scratch that contains the best code they've ever written. It's there because nobody made them turn it into a product. This is a pattern, not a bug.",
        "topic": "creativity",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-018",
        "handle": AUTHOR_HANDLE,
        "text": "A team of four good engineers will beat a team of ten average engineers plus a manager to coordinate them, every time, on any project under a year. The industry knows this. It refuses to act on it.",
        "topic": "team-size",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-019",
        "handle": AUTHOR_HANDLE,
        "text": "The AI tools only make you faster if you were already good. If you were slow because you didn't understand the problem, now you're slow and confident.",
        "topic": "ai-tools",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-020",
        "handle": AUTHOR_HANDLE,
        "text": "Naming the thing is 60% of the design. If you can't name it, you don't know what it is. If you can't name it in a single word, it's probably two things.",
        "topic": "naming",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-021",
        "handle": AUTHOR_HANDLE,
        "text": "Unpopular: most engineering blog posts are written by people who needed to convince themselves the decision they'd already made was the right one. Read them that way and they get a lot more honest.",
        "topic": "engineering-blogging",
        "thread": None,
    },
    {
        "id": "tw-persona-v2-022",
        "handle": AUTHOR_HANDLE,
        "text": "If you can't reproduce the bug in 60 seconds, you don't have a bug. You have a research project. Budget accordingly.",
        "topic": "debugging",
        "thread": None,
    },
]


LINKEDIN_POSTS = [
    {
        "id": "li-persona-v2-001",
        "author": AUTHOR_NAME,
        "headline": "The single biggest skill gap I see in engineers under 30",
        "body": (
            "It's not what you'd guess.\n\n"
            "Not algorithms. Not systems design. Not distributed computing.\n\n"
            "It's writing. Specifically: writing a clear paragraph that makes an argument.\n\n"
            "I watch engineers who can refactor a hairy module in an afternoon struggle for two days "
            "to write a 400-word design doc that explains why. The code is the easy part. The "
            "translation of technical judgment into something a non-engineer stakeholder can act on "
            "is the hard part, and it's the part that compounds over a career.\n\n"
            "I don't think this is anyone's fault. The industry hired on coding signals for fifteen "
            "years. We got what we selected for. But every senior engineer I know has spent the "
            "second half of their career unlearning the idea that the code is the output. The output "
            "is alignment between the people who depend on the code and the people who write it. "
            "Writing is the medium of that alignment.\n\n"
            "If you're a junior engineer reading this: write one internal document per week. Doesn't "
            "matter what. Design proposal, retrospective, bug post-mortem, \"what I learned this "
            "sprint\" memo. The habit compounds faster than any other skill in this profession.\n\n"
            "If you're a senior engineer: the thing you owe your team is not more code. It's the "
            "documents that make the code they write legible to the rest of the business."
        ),
        "topic": "technical-writing",
        "tags": ["TechnicalWriting", "Engineering", "Career", "Communication", "Leadership"],
    },
    {
        "id": "li-persona-v2-002",
        "author": AUTHOR_NAME,
        "headline": "A tactic I use to avoid bad technical decisions: pre-mortems",
        "body": (
            "Post-mortems happen after the disaster. They're useful, but late.\n\n"
            "Pre-mortems happen before you start, and they're the single most valuable 45-minute "
            "meeting I run. The structure:\n\n"
            "1. Assume the project failed spectacularly six months from now. Not slightly late — "
            "outright failed.\n"
            "2. Each person writes, silently, for 10 minutes, the story of why it failed.\n"
            "3. Share. Cluster themes.\n"
            "4. For each theme, decide: what would we do now to prevent this?\n\n"
            "Three things happen in these meetings that never happen in the normal planning "
            "process. People voice risks they would otherwise have kept private. The team faces "
            "the honest failure modes instead of the sanitized ones. And the plan you leave with "
            "is calibrated to the real risk surface, not the optimistic version.\n\n"
            "The investment is 45 minutes. The return is not shipping a disaster that everyone on "
            "the team quietly saw coming. I have never regretted running one. I have repeatedly "
            "regretted skipping one."
        ),
        "topic": "project-management",
        "tags": ["ProjectManagement", "RiskManagement", "EngineeringLeadership", "Planning"],
    },
    {
        "id": "li-persona-v2-003",
        "author": AUTHOR_NAME,
        "headline": "Why \"disagree and commit\" is the most abused phrase in tech",
        "body": (
            "Every technology company I've worked at quotes Bezos's \"disagree and commit\" "
            "principle. Most of them use it wrong. They use it as the close of a disagreement — "
            "\"I've heard you, we're moving on, commit.\" That's not disagree and commit. That's "
            "dismiss and comply.\n\n"
            "The actual principle has three parts, and the first two are the ones people skip:\n\n"
            "1. **Disagree fully.** Make the case. Write it down. Be specific. The disagreement "
            "has to be real and documented or the \"commit\" that follows is coerced.\n\n"
            "2. **Be heard fully.** Not answered. Heard. The person you disagreed with has to "
            "have read the disagreement, understood it, and addressed the substance, not the form.\n\n"
            "3. **Commit fully.** Once the decision is made, you commit to making it succeed, not "
            "to being proven right when it fails.\n\n"
            "Most companies run part three without part one or two. That's when \"disagree and "
            "commit\" becomes a polite name for \"the loudest person won.\" The people with "
            "real expertise learn to stop disagreeing, because the disagreements don't change "
            "anything and they cost social capital. Over a year, the quality of the decisions "
            "degrades without anyone being able to point at why.\n\n"
            "The fix is slow and cultural: model the full three-part version yourself, visibly, "
            "and make it cost nothing for your juniors to write down a dissent. The hardest thing "
            "about leadership is that the signals you send with your own behavior drown out every "
            "memo you ever write."
        ),
        "topic": "decision-making",
        "tags": ["Leadership", "DecisionMaking", "Culture", "Management", "EngineeringCulture"],
    },
    {
        "id": "li-persona-v2-004",
        "author": AUTHOR_NAME,
        "headline": "The engineer productivity metric I actually trust",
        "body": (
            "I've watched companies measure engineer productivity with every possible proxy. "
            "Commits per week. Lines of code. Story points. PRs merged. Pull request cycle time. "
            "Deployment frequency. Tickets closed.\n\n"
            "Every one of those metrics produces the behavior it measures, which is rarely the "
            "behavior you actually want. Measure lines of code and your engineers write verbose "
            "code. Measure tickets closed and they close the easy ones and let the hard ones rot. "
            "Goodhart's Law is not a rare case in engineering. It's the default.\n\n"
            "The one metric I've found that stays honest is this: **how many hours per week does "
            "this engineer spend on work that actually matters to the company's future?**\n\n"
            "You can't automate it. You have to ask. You sit down with the engineer in a 1:1 and "
            "you ask, in different words, \"of the work you did this week, how much of it do you "
            "believe will still matter to us in a year?\" The answer you get is extraordinarily "
            "useful. Not as an individual metric — as a system diagnostic.\n\n"
            "If your best engineers are telling you most of their week didn't matter, your "
            "organization has a backlog of waste disguised as work. No amount of velocity will "
            "fix that. The problem isn't that they're slow. It's that the org is pointing them at "
            "the wrong things.\n\n"
            "I would rather have an engineer who ships one right thing per month than one who "
            "ships four wrong things per week. The industry has spent a decade measuring the "
            "latter and wondering why the former disappeared."
        ),
        "topic": "engineering-productivity",
        "tags": ["Productivity", "EngineeringLeadership", "Metrics", "Management"],
    },
    {
        "id": "li-persona-v2-005",
        "author": AUTHOR_NAME,
        "headline": "On working with founders: the one question that tells you everything",
        "body": (
            "I've advised a lot of founders in the last decade. The question that separates the "
            "ones worth working with from the ones who will burn your hours is not about the "
            "product, the market, the team, or the funding.\n\n"
            "It's this: \"When was the last time you changed your mind about something important, "
            "and what did you change it to?\"\n\n"
            "Founders who can answer specifically and recently — \"I used to believe X about our "
            "pricing, last month I realized it was wrong, here's what I think now\" — are the "
            "ones who compound. They're operating a learning loop that keeps pointed at reality.\n\n"
            "Founders who can't answer, or who answer with something from five years ago, are "
            "running on the thesis they started with. That thesis is depreciating every day the "
            "world changes around it. They will make one good decision from it and five bad ones.\n\n"
            "The question is a single-minute diagnostic. I've never had it fail me. If the "
            "founder in front of you cannot name a specific, recent update to their thinking on "
            "something consequential, do not invest time, money, or career with them. They are "
            "playing from the last snapshot of the world, not the current one."
        ),
        "topic": "working-with-founders",
        "tags": ["Founders", "Startups", "Investing", "DecisionMaking", "Leadership"],
    },
    {
        "id": "li-persona-v2-006",
        "author": AUTHOR_NAME,
        "headline": "The underrated compounding effect of reading your own code six months later",
        "body": (
            "The practice I recommend most often to mid-level engineers isn't reading books, "
            "isn't learning a new language, isn't studying system design.\n\n"
            "It's rereading your own code from six months ago.\n\n"
            "Not to refactor it. Not to judge it. To read it the way you'd read a stranger's "
            "code: looking for the parts that confuse you, the decisions that seem arbitrary, "
            "the bits where you can tell past-you was tired.\n\n"
            "Do this for an hour, monthly, for a year. You will become a noticeably better "
            "engineer. Not because the code is bad — although some of it is — but because you "
            "will start to see the patterns of your own bad habits in a way that the present-tense "
            "version of you never can. The present tense of your code always looks reasonable to "
            "you, because you wrote it. The six-month-old version is where the patterns become "
            "visible.\n\n"
            "This is the cheapest, highest-leverage skill-building practice in software "
            "engineering and almost nobody does it. Everyone wants to read someone else's code. "
            "Almost nobody wants to read their own. The discomfort is the point."
        ),
        "topic": "self-improvement",
        "tags": ["Engineering", "SelfImprovement", "CodeQuality", "Career", "Learning"],
    },
    {
        "id": "li-persona-v2-007",
        "author": AUTHOR_NAME,
        "headline": "Meetings are a symptom, not a strategy",
        "body": (
            "I ran a team last year that had 14 recurring meetings on its shared calendar. We "
            "deleted all of them. I kept a list for six weeks of every time someone said \"we "
            "should talk about X\" and wrote down whether X actually needed a meeting or whether "
            "it got resolved in writing.\n\n"
            "Six weeks later, we added back exactly three of the original 14. The rest had been "
            "cargo: meetings that existed because meetings had existed. They had no outcome, no "
            "owner, and no clear replacement when canceled.\n\n"
            "The team shipped more in the quarter after we deleted the meetings than in the "
            "quarter before. Not because the meetings were bad — most of them were fine. Because "
            "the absence of the meetings created the space for focused work to happen, and "
            "focused work is where engineering output actually lives.\n\n"
            "Here's the uncomfortable truth: every recurring meeting on your calendar is a small "
            "tax on every person required to attend. If the tax is lower than the value of the "
            "meeting, keep it. If not, delete. Most meetings will not pass this test. Delete them "
            "anyway. The team will be fine. The work will be better.\n\n"
            "The hardest part is social: someone will feel their meeting was deleted because you "
            "don't value them. You have to separate the meeting from the person. The meeting was "
            "a tool. Tools that don't work get replaced. The person is still valued."
        ),
        "topic": "meetings",
        "tags": ["Meetings", "Productivity", "Management", "RemoteWork", "EngineeringCulture"],
    },
]


MEDIUM_ARTICLES = [
    {
        "id": "md-persona-v2-001",
        "author": AUTHOR_NAME,
        "title": "The End of the Polyglot Era",
        "subtitle": "For a decade the elite engineer was the one who knew six languages. The next decade belongs to the one who knows one language so deeply that they can write the other five by reading the docs for an afternoon.",
        "topic": "languages",
        "tags": ["Programming", "Engineering", "Career", "AI", "SoftwareDevelopment"],
        "body_markdown": (
            "The engineer of 2015 was a polyglot. You were expected to be functional in "
            "JavaScript and Python and a systems language and something JVM-shaped and probably "
            "Go, and comfortable in SQL, and conversant enough in at least two front-end "
            "frameworks to not embarrass yourself on a whiteboard. Your resume was a tag cloud. "
            "Your hiring loop tested all of it.\n\n"
            "I do not think this profile survives the next five years, and I want to explain why "
            "— and what I think replaces it.\n\n"
            "## Why polyglot made sense in the first place\n\n"
            "The polyglot era had three drivers. The first was the explosion of new languages "
            "and frameworks, which meant that a mid-career engineer who only knew one stack was "
            "one stack-migration away from being irrelevant. The second was the cult of fit-in: "
            "teams wanted engineers who could drop in anywhere, and the way you signaled that was "
            "a broad resume. The third, less discussed, was that in the absence of great tools "
            "for translating ideas across languages, you had to hold the syntax of each language "
            "in your head to be productive in it.\n\n"
            "All three of those drivers are now weaker than they were.\n\n"
            "The rate of new languages shipping is not actually faster. It's slower. Most of the "
            "languages with real momentum today are five to fifteen years old. Fit-in still "
            "matters but the signal is increasingly a portfolio of shipped work, not a list of "
            "keywords. And the syntax-holding problem has been dismantled almost entirely by "
            "tooling: you can write idiomatic code in a language you barely remember because the "
            "assistant does the translation work your memory used to do.\n\n"
            "## What replaces polyglot\n\n"
            "What I see in the engineers compounding the fastest in the AI era is the opposite "
            "of polyglot. They are going deep in one language, one stack, one runtime. They "
            "understand the edges of it. They know what it does well and what it fakes. They can "
            "debug the runtime, not just the code that runs on it.\n\n"
            "And then — and this is the new move — they use the tooling to ship in whatever "
            "language the problem needs, trusting that the assistant will handle the syntax-level "
            "translation and that their deep understanding of the one language will tell them "
            "whether the output is good or bad.\n\n"
            "I call this T-shaped depth: vertical expertise in one place, horizontal reach enabled "
            "by tooling. It is a strictly better shape than polyglot for the era we're in.\n\n"
            "The polyglot tried to be competent everywhere. The T-shaped engineer is expert "
            "somewhere and functional anywhere. In a world where the cost of crossing "
            "language boundaries has collapsed, functional-anywhere is cheap. Expert-somewhere "
            "is the scarcity.\n\n"
            "## How to adjust\n\n"
            "If you are mid-career and your resume reads as polyglot, this is not an emergency. "
            "Polyglot was correct for the era you were trained in and the work you shipped is "
            "not going to disappear. But for your next five years of career investment, I would "
            "recommend a different allocation:\n\n"
            "- Pick the language and stack you find the most fun. Not the one with the best job "
            "market right now — the one you find fun. Fun keeps you in the chair on Saturday.\n\n"
            "- Go deep. Read the source of the runtime. Write a toy implementation of the "
            "garbage collector. Write a blog post explaining something non-obvious about the "
            "language to someone who already uses it. If you can teach experts something about "
            "their own stack, you are an expert.\n\n"
            "- Use the assistant ruthlessly for everything else. You do not need to memorize the "
            "Kotlin collections API to ship in Kotlin. You need to know what you want the "
            "program to do and how to tell when the output is wrong.\n\n"
            "- Resist the urge to re-polyglot. The resume-tag-cloud aesthetic is going to feel "
            "familiar, and for a transitional period it will still be rewarded. But by 2030 the "
            "engineers who win are going to be the ones whose single deep skill is so visible "
            "and useful that companies would hire them to work in any language, because what "
            "they're buying is judgment, not language fluency.\n\n"
            "The polyglot era trained us for breadth. The next era rewards depth. If your "
            "career strategy hasn't updated, now is the time."
        ),
    },
    {
        "id": "md-persona-v2-002",
        "author": AUTHOR_NAME,
        "title": "The Honest Case Against Clean Code",
        "subtitle": "I spent ten years trying to write clean code. I am no longer convinced the premise was right.",
        "topic": "code-quality",
        "tags": ["Engineering", "CodeQuality", "SoftwareDevelopment", "Programming", "Opinion"],
        "body_markdown": (
            "There's a genre of software book — you know the ones — that takes a position on "
            "what good code looks like and then documents the position with enough authority that "
            "it becomes received wisdom. For fifteen years the dominant voice in that genre "
            "argued for a specific aesthetic: short functions, meaningful names, no comments, "
            "single responsibility, test-first. The aesthetic acquired a name: clean code. And "
            "for the better part of my early career I tried, with real effort, to write it.\n\n"
            "I am no longer convinced the aesthetic was right. Not in the sense that the advice "
            "was wrong — most of it is fine — but in the sense that the aesthetic, applied "
            "uniformly, produces worse software than a less dogmatic alternative.\n\n"
            "Let me try to make the case without making it a hit piece.\n\n"
            "## What clean code gets right\n\n"
            "The core insight of the clean code movement is correct and important: code is read "
            "more often than it is written, so optimizing for readability compounds. I agree. "
            "Every time I've written code purely for the sake of the machine, I've paid for it "
            "later in some debugger at 2 a.m. The emphasis on naming, on structure, on reducing "
            "cognitive load is not wrong. It is one of the most important insights in the field.\n\n"
            "## Where the aesthetic fails\n\n"
            "The failure starts with the specific prescriptions, applied without context.\n\n"
            "\"Functions should be short\" becomes a function length fetish. Engineers split what "
            "should have been a 40-line readable procedure into six 8-line functions, each one "
            "of which has to be read and understood in relation to the others. The cognitive load "
            "went up, not down. The aesthetic said the shorter version was cleaner. The "
            "experience of reading it says otherwise.\n\n"
            "\"Code should be self-documenting\" becomes a prohibition on comments. Engineers "
            "rename their variables to try to encode, in the identifier, context that rightly "
            "belongs in a sentence. `calculateMonthlyRecurringRevenueWithProrationAndChurnAdjustment` "
            "is not a better name than `calculate_mrr()` followed by a five-line comment "
            "explaining the adjustments. But the aesthetic says comments are a smell, so the "
            "variable name grows until it becomes unreadable.\n\n"
            "\"Single responsibility principle\" becomes an excuse to create abstractions that "
            "don't help. Every engineer who has inherited a \"clean\" codebase has hit the "
            "moment of opening a class that supposedly does one thing and finding that the one "
            "thing requires navigating seven files and three interfaces to understand. The "
            "responsibility may be single. The experience of reading the code is not simpler.\n\n"
            "## The alternative I've converged on\n\n"
            "After a decade of this I've stopped following the clean code aesthetic as a rule "
            "and started following a different one: *optimize for the experience of the reader "
            "encountering this code for the first time at 2 a.m. in a crisis.*\n\n"
            "That reader wants, in this order:\n\n"
            "1. To know what the code is supposed to do.\n"
            "2. To know why it does it this way.\n"
            "3. To see the whole thing in one place, if possible.\n"
            "4. To not have to navigate layers of abstraction before reaching any actual logic.\n\n"
            "A 200-line function with clear section comments and a well-named set of local "
            "variables is often better for this reader than the \"clean\" equivalent split into "
            "fifteen 12-line methods across three classes. The long function reads linearly. The "
            "clean version reads like a treasure hunt with no map.\n\n"
            "I will happily write a 150-line function. I will happily leave a 20-line comment at "
            "the top. I will not apologize for either. The goal is not to pass a style guide. "
            "The goal is to make the person debugging this code at 2 a.m. three years from now "
            "say \"oh, I get it.\"\n\n"
            "## Where this leaves us\n\n"
            "I am not arguing for messy code. I am arguing against a specific aesthetic that has "
            "become so dominant that the word \"clean\" is now load-bearing for arguments that "
            "have nothing to do with readability. When a reviewer says \"this isn't clean,\" they "
            "rarely mean \"the person reading this in the future will have a hard time.\" They "
            "usually mean \"this doesn't match the pattern my brain was trained on.\"\n\n"
            "The pattern your brain was trained on is not the same as readability. Readability is "
            "about the reader. The pattern is about you. If you can separate the two, you'll "
            "start writing code that is genuinely easier to maintain, even if it wouldn't pass "
            "the aesthetic test.\n\n"
            "Clean code was a decent first pass at a real problem. The next generation of "
            "engineering practice is going to have to do better, and that starts with being "
            "honest about the places the aesthetic broke down."
        ),
    },
    {
        "id": "md-persona-v2-003",
        "author": AUTHOR_NAME,
        "title": "The Quiet Collapse of the Engineering Blog",
        "subtitle": "For fifteen years, company engineering blogs were the single best free resource our industry had. They are not coming back in the form they were. Here's what I think is taking their place.",
        "topic": "engineering-media",
        "tags": ["Engineering", "TechCulture", "Writing", "Blogging", "Media"],
        "body_markdown": (
            "I remember the exact moment I realized the company engineering blog as a genre was "
            "dying. I was searching for specific guidance on a distributed systems problem — the "
            "kind of search where, ten years ago, the first three results would have been "
            "deeply technical, specific, battle-scarred writeups from three different engineering "
            "organizations. What I got instead, in 2024, was a marketing piece, a generic AI "
            "company announcement, and a CMS-produced \"thought leadership\" post that could have "
            "been written about any company by any junior marketing hire.\n\n"
            "The engineering blog, as a genre, had gone from being the place where technical "
            "people shared hard-earned knowledge to being a content marketing surface. There "
            "were still excellent exceptions. There are always excellent exceptions. But the "
            "center of the distribution had moved, and it had moved decisively.\n\n"
            "## Why the format worked\n\n"
            "The classical engineering blog worked because of a specific alignment of incentives "
            "that existed for about a decade and a half.\n\n"
            "Engineering organizations wanted to recruit, and writing deeply technical content "
            "was the most efficient recruiting tool ever invented. Every post was a self-"
            "selecting filter: the engineers who read the post to completion were the exact "
            "engineers the company wanted to hire. No recruiter, no keyword matching, no resume "
            "review could match that filter. The writeup did the filtering for free.\n\n"
            "Meanwhile, the engineers writing the posts got status, portfolio, and the kind of "
            "portability that made them harder to fire and easier to hire elsewhere. The "
            "incentives lined up: the company wanted the writing, the engineers wanted to do it, "
            "readers wanted to read it. It was a rare three-sided win.\n\n"
            "## What broke\n\n"
            "A few things broke, more or less at the same time.\n\n"
            "The first was that the recruiting alignment stopped working. Once engineering "
            "hiring froze (and it froze, in much of the industry, in 2023), the blog's recruiting "
            "purpose evaporated. Marketing moved in to fill the content slot. Marketing's "
            "incentives are different from engineering's. Marketing wants to generate leads and "
            "reinforce the brand. The specific technical depth that made the blogs useful was "
            "actively detrimental to that goal.\n\n"
            "The second was that the rise of LLM-assisted content production made generic "
            "engineering blog posts trivially cheap to produce. Companies that had never had an "
            "engineering blog before suddenly had five posts a month, all of them hitting a "
            "median bar, none of them worth reading. The signal got drowned in the noise.\n\n"
            "The third was that the engineers who had been doing the writing got tired. They "
            "realized that the return on writing had dropped. The audience was smaller. The "
            "reach was harder. The recognition was quieter. Most of them quietly stopped.\n\n"
            "## What's replacing it\n\n"
            "I don't think the thirst for deep technical writing went anywhere. The audience "
            "is still there. What's changed is where the audience finds the content.\n\n"
            "Three replacement formats seem to be doing the work the engineering blog used to do:\n\n"
            "**Personal sites.** Not Substack, not Medium — static personal sites with a URL the "
            "writer owns. The top 1% of engineering writers are increasingly posting to their "
            "own domains, where the writing is permanent, searchable, and not surrounded by "
            "ads or pop-ups. The signal is high because only the people with something real to "
            "say bother to run the infrastructure.\n\n"
            "**Long-form YouTube.** A new generation of senior engineers has figured out that a "
            "45-minute video explaining a real architectural decision can reach an audience "
            "that a company blog post cannot. The format is harder to produce. The reach is "
            "greater. The shelf life is longer.\n\n"
            "**Small, private communities.** Discord servers, private Slack channels, invite-only "
            "substacks, subscription newsletters. The best technical content is increasingly "
            "written for audiences of hundreds, not tens of thousands. The authors know their "
            "readers. The readers pay with attention or money. The quality is higher because the "
            "audience is selected.\n\n"
            "## What this means for engineers\n\n"
            "If you are a technical writer, the advice is the same as it's always been: own your "
            "distribution. Do not build your audience on a company blog that can be deprecated. "
            "Do not build it on a platform that can rug-pull you. Do not build it in a format "
            "that will be commoditized by the next wave of tools.\n\n"
            "Build it on a URL you own. Put the writing there. Let the work compound. The "
            "platform changes every decade. The work is portable forever.\n\n"
            "If you are an engineering leader, the advice is harder: the company engineering "
            "blog is not coming back in its old form. You cannot recruit through it the way you "
            "did in 2017. What you can do is make your engineers' personal writing easier, not "
            "harder. Let them use work examples (carefully). Let them publish under their own "
            "names. Let them take the recruiting lift that the old blog used to take. The "
            "alignment is still there. It has just relocated from the company URL to the "
            "engineer's URL. Either meet it where it is, or lose the signal entirely."
        ),
    },
    {
        "id": "md-persona-v2-004",
        "author": AUTHOR_NAME,
        "title": "You Are Not Google. Stop Building Like You Are.",
        "subtitle": "The most expensive architectural mistake of the last decade was normal engineering teams copying the infrastructure of planet-scale companies. The bill is coming due.",
        "topic": "architecture",
        "tags": ["Architecture", "Engineering", "Infrastructure", "Microservices", "Scale"],
        "body_markdown": (
            "A lot of the software built in the last ten years was built as if the builder was "
            "going to have Google's traffic one day. Microservices for teams of ten. Kubernetes "
            "clusters for applications with a hundred users. Service meshes for internal APIs "
            "that get called once every eight minutes.\n\n"
            "The economic consequences of this are now visible in a way they were not five years "
            "ago. Companies are cutting infrastructure costs by 70%, 80%, 90% by rolling back the "
            "architecture they adopted during the cheap-money years. Most of what they're "
            "finding is that the original three-server setup was fine. The distributed monster "
            "was solving a scale problem they did not have.\n\n"
            "## The cultural pressure to over-architect\n\n"
            "The hardest part of the case against over-architecture is that it's a cultural "
            "argument, not a technical one. The technical case is simple: a Postgres database "
            "and three commodity web servers can serve more traffic than almost any startup "
            "will ever have. Every engineer knows this in the abstract.\n\n"
            "The cultural case is harder to fight. When you show up at a new job and the "
            "architecture is \"a database and three boxes,\" you conclude that the team isn't "
            "serious. The team doesn't have gravitas. They haven't solved any interesting "
            "problems. You might even resume-shop.\n\n"
            "When you show up at a new job and the architecture has seventeen services, a "
            "service mesh, three data stores, an event bus, and a machine learning platform — "
            "you conclude the team is serious. Gravitas. Interesting problems. This is where "
            "careers get made.\n\n"
            "The bias is not rational. But the bias shaped an entire decade of architectural "
            "decisions at companies where no technical justification for the complexity existed. "
            "We added components to resumes and called it infrastructure.\n\n"
            "## How to tell if you are Google\n\n"
            "A useful diagnostic, in no particular order:\n\n"
            "- Do you have more than 10,000 requests per second sustained?\n"
            "- Do you have more than a petabyte of data under active query?\n"
            "- Do you have engineers in more than four time zones working on the same system?\n"
            "- Is your application live in more than three geographic regions with regulatory "
            "requirements forcing data locality?\n"
            "- Do you have more than 500 engineers committing to the same codebase?\n\n"
            "If the answer to all five is no, you are not Google. You can do Google-scale "
            "architecture if you want, but you are paying Google's prices to solve problems you "
            "don't have. The math almost never works.\n\n"
            "If the answer to three or more is yes, congratulations, you may genuinely need the "
            "complicated thing. Most readers of this post will not hit three yeses. Most "
            "companies will not hit three yeses for the duration of their existence.\n\n"
            "## What to do instead\n\n"
            "The default architecture for any new product in 2026 should be:\n\n"
            "- A single database (Postgres, MySQL, SQLite if you're being honest about your "
            "scale).\n"
            "- A single web application, maybe split into a couple of worker processes if you "
            "have background jobs.\n"
            "- A managed host (Render, Fly, Railway, a plain EC2 behind a load balancer, a "
            "literal VPS).\n"
            "- A CDN in front of the static assets.\n"
            "- Backup. For the love of god, actual backup. You will fail to backup before you "
            "fail to scale.\n\n"
            "That is the architecture. It will serve you well up to a million users, if you "
            "build the application itself well. When you hit the limits, you will have specific "
            "knowledge about the specific bottleneck, and you will evolve the architecture "
            "exactly where the pain is.\n\n"
            "The architecture's job is not to be impressive. The architecture's job is to let "
            "the product exist. Every hour you spent making the architecture impressive is an "
            "hour you did not spend making the product good. And the industry is about to spend "
            "a decade paying the interest on the architectures we built during the cheap years.\n\n"
            "Do not add to the bill. You are not Google."
        ),
    },
    {
        "id": "md-persona-v2-005",
        "author": AUTHOR_NAME,
        "title": "The Lost Art of Reading Source",
        "subtitle": "We teach new engineers to write code. We almost never teach them to read it. This is the single biggest gap in the profession.",
        "topic": "reading-code",
        "tags": ["Engineering", "Learning", "Career", "SoftwareCraft", "Mentoring"],
        "body_markdown": (
            "A thought experiment. Imagine you are hiring two engineers. Engineer A can write "
            "novel code 20% faster than the median. Engineer B can read existing code 50% faster "
            "than the median, and makes 50% fewer mistakes when modifying it.\n\n"
            "Which one do you want? The industry has been mostly answering A. I believe the "
            "right answer is almost always B, and I think the industry's failure to teach B is "
            "the single biggest gap in modern engineering education.\n\n"
            "## Why reading is undervalued\n\n"
            "The culture of software celebrates writing. You ship features. You write posts. You "
            "contribute to open source. You get hired on your GitHub. Every visible artifact of "
            "a software career is an act of writing.\n\n"
            "Reading is invisible. You cannot put \"read 30,000 lines of a production codebase\" "
            "on a resume. There is no standup metric for it. There is no recruiter filter for "
            "it. The activity happens in silence, in a chair, with a terminal and maybe a "
            "notebook, and produces no ship event.\n\n"
            "And yet: every time you join a new codebase, for the first two to six weeks, what "
            "makes you productive or unproductive is not how fast you can write code. It is how "
            "fast you can read the code that already exists. The engineers who read poorly spend "
            "their first month creating duplicate abstractions, breaking conventions they didn't "
            "know existed, and shipping PRs that senior engineers have to rewrite. The engineers "
            "who read well become productive in week two.\n\n"
            "This matters at the career level as well. Over a 20-year career, a senior engineer "
            "will read somewhere between ten and thirty times more code than they write. The "
            "reading skill compounds across every codebase they touch. The writing skill is "
            "largely language-specific and erodes when they change stacks.\n\n"
            "## What reading well actually looks like\n\n"
            "Reading code well is not the same as skimming code. It is a distinct skill with "
            "identifiable sub-skills:\n\n"
            "**Starting at the top.** Most codebases have an entry point. Find it. Read the "
            "startup sequence. Understand what gets initialized in what order before you try to "
            "understand any individual module. Most engineers start at the module that has "
            "their bug and try to work outward. This almost never works.\n\n"
            "**Following the data, not the code.** A function call tells you where control "
            "goes. That is usually the less interesting thing. Where does the data come from? "
            "Where does it go? Where does it get transformed? The data-flow view of a program "
            "tells you more than the control-flow view for almost every production debugging "
            "problem.\n\n"
            "**Reading tests to understand behavior.** The test suite of a production system is "
            "the most under-read documentation in the world. If you want to know what the system "
            "does — what behaviors the authors believed were important enough to protect — read "
            "the tests. Read them before you read the docs. Read them before you read the code.\n\n"
            "**Reading commit history.** Every file in a production system has a commit history "
            "that contains, distributed across dozens of messages, the reasons the file looks "
            "the way it does. Most engineers treat `git blame` as a tool for assigning blame. "
            "It is a tool for reading archaeology. Use it that way.\n\n"
            "**Reading with intent.** Reading code without a question is a bad use of time. "
            "Reading code to answer a specific question — \"how does authentication work here,\" "
            "\"where is this error generated,\" \"why is this module shaped like this\" — is the "
            "only kind of reading that actually teaches you something. Go in with a question. "
            "Stop when the question is answered.\n\n"
            "## How to get better\n\n"
            "The practice I recommend is counterintuitive: pick a piece of well-regarded open "
            "source software, and spend a weekend reading it without writing anything. No "
            "contribution. No PR. No gist. Just reading. Take notes, for yourself, about what "
            "you find interesting, what surprises you, what you don't understand.\n\n"
            "The goal is to practice the act of reading, uncoupled from any other activity. "
            "Like doing scales on an instrument. Not productive in the ship-something sense. "
            "Essential in the skill-building sense.\n\n"
            "Do this four or five times a year. Within two years you will be a noticeably "
            "better engineer, in a way that is hard to see from the outside but devastating in "
            "practice. You will join new codebases and be useful in week one instead of week "
            "four. You will debug issues in systems you've never seen before because you have "
            "the reading muscles to navigate them. You will compound across every project for "
            "the rest of your career.\n\n"
            "The writing engineer has a career. The reading engineer has a superpower. The "
            "reading engineer is rarer than you think, and more valuable than anyone will admit."
        ),
    },
    {
        "id": "md-persona-v2-006",
        "author": AUTHOR_NAME,
        "title": "On Hardware: What Thirty Keyboards Taught Me",
        "subtitle": "I've spent more on keyboards in the last decade than is rational. I'd like to save you from doing the same.",
        "topic": "hardware",
        "tags": ["Hardware", "Keyboards", "ProductivityTools", "Developer", "Mechanical"],
        "body_markdown": (
            "I am not proud of this number. Over the last decade I have bought somewhere around "
            "thirty keyboards. Membrane, rubber dome, buckling spring, Topre, linear MX, tactile "
            "MX, Alps, low-profile, split, ortholinear, column-staggered, columnar, columnar "
            "with a trackball, ergonomic with thumb clusters, custom PCBs with hot-swap, pre-"
            "built production boards, and three (three) entire hand-wired builds.\n\n"
            "I have typed on them all. I have a spreadsheet. I am that person. Let me try to "
            "save you some money.\n\n"
            "## The big unglamorous finding\n\n"
            "After thirty keyboards, the most important thing I learned is that the keyboard is "
            "maybe 10% of the typing experience. The other 90% is posture, desk height, screen "
            "height, lighting, and whether you typed for 90 minutes with a break or for four "
            "hours without one. If you are trying to fix pain or productivity with a keyboard, "
            "you are going to be disappointed.\n\n"
            "Fix the chair first. Fix the desk first. Fix the screen height first. Fix the "
            "number of hours you type without standing up first. If you do all of those and you "
            "are still having trouble, then we can talk about the keyboard.\n\n"
            "## Keyboard, if you still care\n\n"
            "With the caveat above out of the way: the keyboard does matter, modestly. Here's "
            "what I've learned matters and what doesn't.\n\n"
            "**Switches matter less than the keyboard community thinks.** The difference between "
            "a good linear and a good tactile switch is real but small. The difference between "
            "any decent mechanical switch and a good rubber dome is also real and not as large "
            "as the enthusiast community implies. If you can, try a switch tester before buying. "
            "If you can't, pick tactile (most engineers like them) and move on.\n\n"
            "**Layout matters more than switches.** The single most impactful change you can "
            "make to your typing setup is moving from a staggered layout to a columnar or "
            "ortholinear layout, *if* you put in the two to four weeks required to retrain. Most "
            "people don't put in the training and come back to staggered. If you do put it in, "
            "your typing will be measurably more comfortable for the next twenty years.\n\n"
            "**Split is worth it if your shoulders bother you.** A split keyboard lets your "
            "arms rest at shoulder width instead of squeezed together. This alone is worth more "
            "than any switch choice. Downside: you lose the ability to type on anyone else's "
            "computer without looking like you're doing magic tricks.\n\n"
            "**Custom builds are a hobby, not a productivity upgrade.** I've built three "
            "keyboards from scratch. They are beautiful. They do not type any better than a "
            "decent pre-built. The building itself was the value. If you want to build a "
            "keyboard for the joy of building one, do it. If you want to build one because you "
            "think it will make you a better engineer, save your money.\n\n"
            "**The keycap rabbit hole is infinite.** There are people who have spent more on "
            "keycaps than on rent. The keycaps do not matter. They look nice. They are "
            "decoration. Get a set you like and stop.\n\n"
            "## What I actually use\n\n"
            "After all thirty keyboards, I type most of my day on one of two boards: a split "
            "columnar with tactile switches, and an old Apple Magic Keyboard. The Apple board "
            "is for travel and meetings. The split is for real work.\n\n"
            "The split is a custom build. I did not need it to be a custom build. I would be "
            "equally productive on any decent pre-built split columnar. I built mine because I "
            "wanted to, and because the hobby has its own rewards that are unrelated to typing.\n\n"
            "## The underrated piece of typing hardware\n\n"
            "The single piece of hardware that has made the biggest difference to my comfort is "
            "not a keyboard. It is the monitor arm that holds my screen at the correct height. "
            "Eight hundred dollars of keyboard improved my typing slightly. A sixty-dollar "
            "monitor arm eliminated neck pain entirely.\n\n"
            "If you have money to spend on your setup, and you have not yet fixed your posture "
            "and screen height, spend the money there first. Come back to the keyboard question "
            "after. You will save yourself thirty keyboards."
        ),
    },
    {
        "id": "md-persona-v2-007",
        "author": AUTHOR_NAME,
        "title": "The Death of the Annual Review",
        "subtitle": "Once a year, we sit down with our managers and try to compress twelve months of work into two hours of conversation. It never worked. It's going to stop.",
        "topic": "performance-management",
        "tags": ["Management", "PerformanceReview", "HR", "EngineeringLeadership", "Culture"],
        "body_markdown": (
            "Every year, at roughly the same time, engineers across the industry fill out a form "
            "that asks them to summarize the last twelve months of their work. The form is "
            "reviewed by their manager, who writes their own version, and then a \"calibration "
            "meeting\" happens in a room the engineer does not attend, and a decision is made "
            "about compensation and promotion that will influence the engineer's life for the "
            "next year.\n\n"
            "This system has never worked. It has been defended, ritualized, explained, and "
            "tweaked for at least forty years, and through all of it, the data has been clear: "
            "the ritual is not predictive of anything useful, it is demotivating to the "
            "participants, and it absorbs time in a quantity wildly out of proportion to the "
            "value produced.\n\n"
            "I think it is finally going to die, and I want to talk about what replaces it.\n\n"
            "## Why it never worked\n\n"
            "Three structural failures make the annual review genre non-viable:\n\n"
            "**Recency bias is a law, not a tendency.** The manager writing a review in December "
            "can remember, in any detail, about the last six weeks of the engineer's work. "
            "Everything before that has decayed into vague impressions. The engineer is being "
            "evaluated on six weeks of work with a year of weight attached. The data is bad from "
            "the start.\n\n"
            "**The compression of a year into a sentence is dishonest.** A human year of work "
            "contains hundreds of distinct episodes, most of which had different outcomes, "
            "different constraints, and different levels of involvement from the engineer in "
            "question. Turning that into \"Exceeds Expectations\" is not a summary. It is a "
            "fabrication. Both parties know it's a fabrication. They write it anyway.\n\n"
            "**The calibration meeting is politics, not measurement.** The final outcome of the "
            "review is determined not by the engineer's work but by the manager's ability to "
            "advocate for them in a room of peer managers, each of whom is advocating for their "
            "own people. The calibration is a negotiation. It is not an evaluation. Calling it "
            "one is how we end up with female engineers, engineers with accents, and introverted "
            "engineers systematically rated below their peers. The system amplifies the "
            "advocacy skill of the manager, not the work of the engineer.\n\n"
            "## What's replacing it\n\n"
            "I see three patterns emerging in companies that have admitted, privately, that the "
            "annual review is broken.\n\n"
            "**Continuous feedback.** Managers do not wait for a review cycle. They write "
            "observations into a shared document the engineer can see, as things happen, all "
            "year. The engineer reviews it. Disputes it. Adds context. The document becomes the "
            "canonical record of the engineer's year, maintained in real time, by the person who "
            "is going to be evaluated on it. By December, the document exists and the "
            "conversation is about what it adds up to, not what happened.\n\n"
            "**Decoupling compensation from review.** Compensation changes are market-driven "
            "and communicated separately. They are not framed as a judgment of the engineer's "
            "value. They are framed as a market adjustment. This removes the single most "
            "corrosive part of the review ritual: the conflation of \"what is this person worth\" "
            "with \"how well is this person doing.\" Those are different questions and they have "
            "different answers.\n\n"
            "**Promotion as a separate process.** Promotion is explicitly framed as \"does this "
            "person consistently operate at the next level\" rather than \"has this person had a "
            "great year.\" It is decided by evidence of work at the higher level, collected over "
            "time, by the person seeking the promotion, in partnership with their manager. No "
            "calibration meeting. No mystery room. The criteria are transparent and the evidence "
            "is auditable.\n\n"
            "## What this means for you\n\n"
            "If you are a manager, the ritual is dying whether you participate in the killing "
            "or not. The question is whether you build the replacement thoughtfully or let it be "
            "imposed on you. I would recommend thoughtful. Start the shared-document practice "
            "now. It will feel like extra work for two months, and then it will feel like the "
            "only sane way to do the job.\n\n"
            "If you are an engineer, the old ritual is going to stick around in most places for "
            "a few more years. While it does, the single most useful thing you can do is "
            "maintain your own document of your year. Write down what you did, what you "
            "contributed to, what you learned, what you shipped, what failed. Keep it current. "
            "Bring it to your review. Do not rely on your manager's memory. It is not reliable. "
            "It was never reliable. The written record is the only thing that is.\n\n"
            "Every engineer I know who has maintained this kind of document has had materially "
            "better review outcomes than their peers who did not. The work was the same. The "
            "evidence was different. In a system built on memory, the person with the "
            "documentation wins. Write the document. The system is broken. The workaround is "
            "cheap."
        ),
    },
]


HN_POSTS = [
    {
        "id": "hn-persona-v2-001",
        "by": AUTHOR_HANDLE,
        "title": "Ask HN: What production system have you run that's been up for 5+ years with no rewrite?",
        "url": "",
        "body": (
            "In an industry obsessed with rewrites, migrations, and the next "
            "framework, I want to hear about the systems that just keep working. "
            "The boring ones.\n\n"
            "The internal tool that's been running since 2018 on the same "
            "Postgres and the same server, serving the same hundred users, "
            "fixing the same bugs once every six months. The CRON job that "
            "nobody maintains because it doesn't need maintenance. The tiny "
            "Flask app that the CEO still uses daily.\n\n"
            "What is it? What does it do? Why did it survive?"
        ),
        "topic": "long-lived-systems",
    },
    {
        "id": "hn-persona-v2-002",
        "by": AUTHOR_HANDLE,
        "title": "The single biggest productivity gain I found was learning to quit tasks I can't finish in one sitting",
        "url": "",
        "body": (
            "I used to power through. A task started on Monday would be a task "
            "finished by the end of the week, or I'd feel like I failed.\n\n"
            "Last year I realized I was leaving a trail of exhausted, "
            "half-quality work behind that pattern. The tasks that took five "
            "days were almost never worth five days. They were worth one day "
            "and I should have noticed sooner.\n\n"
            "New rule: if I can't finish a task in a single sitting of focused "
            "work — 90 minutes, two sessions max — I stop and ask whether the "
            "task is correctly scoped. Almost always the answer is \"no, I "
            "should split it,\" or \"no, the approach is wrong,\" or \"no, I "
            "shouldn't be doing this at all.\"\n\n"
            "The habit has probably made me 40% more productive by eliminating "
            "the 40% of my time that used to go to finishing things that "
            "shouldn't have been started. Commend to the community."
        ),
        "topic": "productivity",
    },
    {
        "id": "hn-persona-v2-003",
        "by": AUTHOR_HANDLE,
        "title": "Tell HN: The underrated skill of writing bug reports nobody writes about",
        "url": "",
        "body": (
            "There's a lot written about writing good code. Almost nothing "
            "written about writing good bug reports. And bug reports are the "
            "thing engineers read ten times more than they read code.\n\n"
            "A good bug report has three parts:\n\n"
            "1. What I did. Specifically. Literally keystroke-level if "
            "relevant. No \"I logged in and tried to save\" — \"I clicked "
            "Save after editing the title, with this value: X\"\n\n"
            "2. What I expected. Even if it seems obvious. Especially if it "
            "seems obvious. The number of bug reports where \"expected\" and "
            "\"got\" turn out to disagree with the engineer reading it is "
            "shocking.\n\n"
            "3. What actually happened. Include the exact error text, the "
            "exact time, and if possible a screenshot. Timestamps let us "
            "correlate to logs. Screenshots let us see environmental "
            "context.\n\n"
            "A bug report that has all three can be reproduced in 60 seconds "
            "by an engineer who has never touched the feature. A bug report "
            "missing any of the three costs an hour of back-and-forth before "
            "work can start.\n\n"
            "If you're non-technical and reading this, please internalize: "
            "the specificity of your bug reports is the single largest "
            "lever you have over how fast your engineering team fixes "
            "things. Sharper reports get faster fixes. It is that literal."
        ),
        "topic": "bug-reports",
    },
    {
        "id": "hn-persona-v2-004",
        "by": AUTHOR_HANDLE,
        "title": "Show HN: A single-file diff tool that fits in your head",
        "url": "",
        "body": (
            "I had been using a complicated graphical diff tool for years. "
            "It had tabs, filters, panes, plugins, a settings file with "
            "three hundred keys.\n\n"
            "Wrote a 180-line Python version that does 95% of what I "
            "actually used: side-by-side, syntax-highlighted, collapsible "
            "unchanged regions. Zero config. Runs on any terminal. Uses "
            "stdlib plus pygments.\n\n"
            "I've been using it for six months. Haven't opened the big "
            "graphical tool once.\n\n"
            "Offering it here in case anyone else finds it useful. "
            "Philosophy is the same as all my small tools: most of what "
            "we use complicated software for, we could do with 200 lines "
            "of code we wrote ourselves. The ecosystem rewards building "
            "big tools, but the engineer-hours saved by building small "
            "tools for yourself are enormous."
        ),
        "topic": "small-tools",
    },
    {
        "id": "hn-persona-v2-005",
        "by": AUTHOR_HANDLE,
        "title": "The best engineering book I read this year was a history book about bridges",
        "url": "",
        "body": (
            "I read a lot of engineering books. Most of them are software "
            "engineering books. I spent the last six months reading books "
            "about civil engineering, mechanical engineering, and "
            "industrial design instead.\n\n"
            "The one that changed how I think most was a history of "
            "bridge failures. Specifically: every major bridge failure in "
            "the 20th century, what caused it, what the engineering "
            "community did in response.\n\n"
            "The patterns are uncannily familiar to software. A new "
            "technology arrives. Early adopters push the limits beyond "
            "what the field understands. A failure happens that nobody "
            "predicted. Post-failure, the field codifies new rules — "
            "safety factors, inspection requirements, design review "
            "practices — and for a generation, bridges don't fail that "
            "way again. Then a new technology arrives. Repeat.\n\n"
            "Software is in the early-adopter phase of several of these "
            "cycles at once. We have not yet had our great bridge failure "
            "— the one that kills a famous number of people and forces "
            "the whole industry to adopt practices we currently resist.\n\n"
            "I think we will, and I think it will be adjacent to AI "
            "infrastructure. I don't know when. I know the shape.\n\n"
            "If you want to think about where software engineering is "
            "going, read about the engineering disciplines that went "
            "through the transition earlier. We are not as original as "
            "we think we are."
        ),
        "topic": "engineering-history",
    },
    {
        "id": "hn-persona-v2-006",
        "by": AUTHOR_HANDLE,
        "title": "Ask HN: Are you using AI coding tools for new code or legacy code?",
        "url": "",
        "body": (
            "Informal survey. My experience is that the tools are much "
            "more useful for greenfield code than for navigating legacy "
            "systems. The legacy work requires holding a lot of "
            "undocumented context, and the assistant tends to confidently "
            "propose solutions that ignore the context.\n\n"
            "But I hear the opposite claim from people maintaining large "
            "mature codebases, who say the assistant is finally useful "
            "because it can scan files faster than they can.\n\n"
            "Where are you getting the most lift? New code? Maintenance? "
            "Debugging? Refactoring? Something else?\n\n"
            "Curious whether the tool's usefulness scales with codebase "
            "size/age or inversely."
        ),
        "topic": "ai-coding-tools",
    },
]

HN_COMMENTS = [
    {
        "id": "hnc-persona-v2-001",
        "by": AUTHOR_HANDLE,
        "text": (
            "Strong agree on everything except the closing point. The "
            "version I've converged on is: \"AI tools make good engineers "
            "faster and bad engineers more confident.\" The gap between "
            "the two widens, not narrows. If you were already in the "
            "habit of verifying what you produced, the tool accelerates "
            "you. If you were in the habit of shipping whatever runs, "
            "you now ship more of it, faster, and the debugging happens "
            "later."
        ),
        "topic": "ai-tools",
    },
    {
        "id": "hnc-persona-v2-002",
        "by": AUTHOR_HANDLE,
        "text": (
            "I've lived on both sides of this. The cleanest model I've "
            "found: if an engineer is expensive enough that their time "
            "is the bottleneck, buy the tool. If the tool's cost is the "
            "bottleneck, build it in-house. Almost every company gets "
            "this reversed. They buy when they should build because "
            "buying is faster, and build when they should buy because "
            "building is cheaper in the spreadsheet. The spreadsheet "
            "doesn't capture engineer attention as a cost and that's "
            "where the real money leaks out."
        ),
        "topic": "build-vs-buy",
    },
    {
        "id": "hnc-persona-v2-003",
        "by": AUTHOR_HANDLE,
        "text": (
            "This maps to a thing I've noticed at every company I've "
            "consulted for: the actual bottleneck is almost never what "
            "the leadership team says it is. Leadership will say the "
            "bottleneck is engineering velocity. Engineering will say "
            "the bottleneck is unclear requirements. Both are wrong. "
            "The real bottleneck is almost always the gap between those "
            "two — nobody has been tasked with translating vague "
            "leadership direction into shippable specs. Fix that one "
            "role and the rest of the problems melt."
        ),
        "topic": "organization-bottlenecks",
    },
    {
        "id": "hnc-persona-v2-004",
        "by": AUTHOR_HANDLE,
        "text": (
            "Disagree with the framing but agree with the conclusion, "
            "which is a weird place to be. The reason I disagree: "
            "\"just write more tests\" is never the answer. Tests "
            "don't prevent bugs; they detect bugs you already predicted. "
            "The reason I agree: the cultural practice of writing tests "
            "does change how engineers design, because designing "
            "testable code is different from designing code that merely "
            "runs. So the tests themselves aren't the lever. The "
            "discipline of being willing to write them is the lever. "
            "Importantly these are not the same claim, and the "
            "distinction changes the intervention."
        ),
        "topic": "testing",
    },
    {
        "id": "hnc-persona-v2-005",
        "by": AUTHOR_HANDLE,
        "text": (
            "One thing underdiscussed on threads like this: the "
            "lifetime earnings of a senior engineer are dominated not "
            "by hourly rate but by time spent in the chair at "
            "productive companies. A 20% salary increase at a company "
            "you'll leave in 18 months because it's dysfunctional is "
            "worth less than a 10% salary at a place you'll stay for "
            "five years compounding. Everyone optimizes the salary and "
            "almost nobody optimizes the stay. Ten years of this and "
            "it shows."
        ),
        "topic": "career-compounding",
    },
    {
        "id": "hnc-persona-v2-006",
        "by": AUTHOR_HANDLE,
        "text": (
            "The reason senior engineers delete code is not that they "
            "love deleting code. It's that they have the context to "
            "know what's not needed. Junior engineers cannot delete "
            "responsibly because they cannot tell the difference "
            "between code that does nothing and code that does "
            "something subtle they haven't noticed yet. The skill "
            "isn't destructive impulse. The skill is knowing enough of "
            "the system to know what's dead. That's why \"senior\" and "
            "\"deletes code\" correlate: both are symptoms of "
            "understanding the system."
        ),
        "topic": "senior-engineer",
    },
]


REDDIT_POSTS = [
    {
        "id": "rd-persona-v2-001",
        "subreddit": "ExperiencedDevs",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "The 30-year career is dead. What replaces it?",
        "selftext": (
            "I think the implicit model a lot of us have been operating on — "
            "\"get a CS degree, work at a good company for 30 years, retire "
            "on stock grants\" — is basically over. Not because the jobs are "
            "going away, but because companies as employers have stopped "
            "offering the side of that bargain that made it work. Tenure "
            "doesn't buy you security. Loyalty doesn't get rewarded. The "
            "stock grants are smaller and vest weirder. Layoffs happen every "
            "18 months regardless of performance.\n\n"
            "What I see replacing it, in my generation (mid-career now):\n\n"
            "- Portfolio careers: multiple part-time engagements instead of "
            "one full-time role\n"
            "- Independent consulting, with the company as a shell to hold "
            "the contracts\n"
            "- Bootstrapped side businesses that become the main business "
            "after 5-10 years\n"
            "- Short tenures (2-4 years) at well-chosen companies, treated "
            "as paid training\n\n"
            "What are you seeing? What's working for you or people you "
            "respect? I'm trying to think ten years out and the traditional "
            "model isn't available even if I wanted it."
        ),
        "topic": "career-models",
    },
    {
        "id": "rd-persona-v2-002",
        "subreddit": "programming",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "I don't understand the new engineer who won't use a debugger",
        "selftext": (
            "I've noticed a generational pattern in the last two years of "
            "mentoring junior engineers. A lot of them will not use a "
            "step-through debugger. They will stare at the code, add print "
            "statements, read the output, add more print statements, "
            "remove old print statements, commit, push, look at CI logs, "
            "repeat. Hours of this.\n\n"
            "I show them how to set a breakpoint in their editor, step "
            "through the function, inspect state at the point of failure. "
            "They're impressed. They use it for a week. Then they go back "
            "to prints.\n\n"
            "I genuinely do not understand this. The debugger is faster, "
            "more accurate, produces no noise, and exposes behaviors prints "
            "can't catch. And yet the pattern persists. Something about "
            "the debugger feels wrong to this generation in a way it didn't "
            "to mine.\n\n"
            "Is anyone else seeing this? Any theories?"
        ),
        "topic": "debugging-culture",
    },
    {
        "id": "rd-persona-v2-003",
        "subreddit": "cscareerquestions",
        "author": AUTHOR_HANDLE,
        "flair": "Advice",
        "title": "Stop waiting for the perfect job. Build the job you want inside the job you have.",
        "selftext": (
            "If I could give one piece of advice to anyone three to eight "
            "years into their career, it would be this: stop interviewing "
            "for the next company and start modifying the role you have.\n\n"
            "The industry gives you, whether you realize it or not, a lot "
            "of latitude to reshape your job description. The person who "
            "shows up and says \"I notice we keep breaking our build — can "
            "I spend 20% of my time fixing CI?\" will, almost universally, "
            "be allowed to spend 20% of their time fixing CI. The person "
            "who says \"we need someone to own our performance program, "
            "can that be me?\" will, almost universally, be given the "
            "ownership.\n\n"
            "This is a cheat code. The people who use it are called "
            "\"entrepreneurial\" and get promoted faster than their peers. "
            "The people who don't are called \"solid individual contributors\" "
            "and wait for someone else to assign them new work.\n\n"
            "The job you want is not waiting for you at the next company. "
            "It's waiting for you to propose it at this one. Most people "
            "don't propose it because the cultural script says proposals "
            "come from above. The cultural script is wrong. Every "
            "interesting role I've ever had, I invented by writing down a "
            "two-paragraph description and sending it to my manager. Try "
            "it. It costs nothing. The downside is a \"no.\""
        ),
        "topic": "job-crafting",
    },
    {
        "id": "rd-persona-v2-004",
        "subreddit": "startups",
        "author": AUTHOR_HANDLE,
        "flair": "Advice",
        "title": "The #1 mistake I see technical founders make in year one",
        "selftext": (
            "Technical founders love building. That's why they became "
            "technical founders. The problem is that the skill that got "
            "them to the founder role is actively wrong for the first year "
            "of being a founder.\n\n"
            "In year one, your #1 job is not to build. It's to find the "
            "shape of the market you're going into. Every hour you spend "
            "building is an hour you're not learning whether the thing "
            "you're building is a thing anyone wants. And the feedback "
            "loop on market-shape work is slow and uncomfortable. The "
            "feedback loop on building is fast and satisfying. Guess "
            "which one technical founders default to?\n\n"
            "Every technical founder I've mentored has made the same "
            "mistake: they built a beautiful, functional product in year "
            "one, went to sell it, and discovered the product was for a "
            "market that didn't exist in the shape they assumed. Year "
            "two was spent reshaping the product. Year three was spent "
            "admitting the original shape was wrong. The mistake cost "
            "them 18 months.\n\n"
            "The intervention: before you write any code, write a "
            "one-page description of the customer and why they buy. Show "
            "it to 20 of those customers. See if they agree. Iterate on "
            "the description, not the product, until the description "
            "matches what real buyers tell you. Then build. You'll build "
            "the right thing faster.\n\n"
            "This advice is not new. It's in every book. Technical "
            "founders read the books and then build anyway. Including me, "
            "once. Don't be me."
        ),
        "topic": "technical-founders",
    },
    {
        "id": "rd-persona-v2-005",
        "subreddit": "devops",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "The observability stack I've settled on after ten years",
        "selftext": (
            "For years I chased observability. Every new tool, every new "
            "tracing standard, every new log aggregator. Tried Splunk, "
            "Datadog, Honeycomb, Grafana, Loki, OpenTelemetry, Jaeger, "
            "and half a dozen smaller vendors.\n\n"
            "What I've actually settled on for every production system I "
            "run now:\n\n"
            "1. **Structured logs to stdout.** JSON-per-line. Every line "
            "has a trace ID, a user ID, and a timestamp. That's it. "
            "Rotate with the platform's built-in logger.\n\n"
            "2. **One metrics endpoint per service** that speaks "
            "Prometheus's format. Handful of gauges and counters, no "
            "histograms unless I really need them.\n\n"
            "3. **Uptime checks from a separate provider.** Cheapest one "
            "I can find. The point of an uptime check is to notice your "
            "whole stack is down; don't host it on your stack.\n\n"
            "4. **One dashboard.** One. Golden signals only: error rate, "
            "latency p50/p95/p99, request rate, saturation. If you have "
            "more than one dashboard, you will never look at any of "
            "them.\n\n"
            "5. **Alerts go to my phone.** Not Slack. Not email. "
            "Telephony. If it's not worth waking me up, it's not worth "
            "an alert.\n\n"
            "That's the whole thing. No service mesh traces. No "
            "distributed span collection. No 37-vendor observability "
            "pipeline. It works. It costs almost nothing. It scales to "
            "every size of production I've personally run.\n\n"
            "I know this is unfashionable. I know the industry discourse "
            "is all about OpenTelemetry and structured trace ingestion "
            "and all the sophisticated stuff. I've paid for the "
            "sophisticated stuff. It solved problems I did not have, at "
            "prices I did not want to pay.\n\n"
            "Your mileage may vary. But if you're starting over and "
            "paralyzed by the options, this is the stack. Do this first. "
            "Add complexity only when you have a specific incident that "
            "this stack would not have caught."
        ),
        "topic": "observability",
    },
    {
        "id": "rd-persona-v2-006",
        "subreddit": "ExperiencedDevs",
        "author": AUTHOR_HANDLE,
        "flair": "Discussion",
        "title": "I fire people more gracefully than I used to. Here's what I've learned.",
        "selftext": (
            "I have fired, laid off, or managed out somewhere around 30 "
            "engineers over my career. I hate doing it and I will never "
            "be good at it in the way people are good at skills they "
            "enjoy. But I've gotten more graceful, and I want to share "
            "what I've learned, because the received wisdom in the "
            "industry on this topic is bad.\n\n"
            "**Nobody is ever surprised by a firing.** If they are, you "
            "managed them poorly. The months of feedback that should "
            "have preceded the decision didn't happen, or didn't land. "
            "The first fix is not getting better at firing — it's "
            "getting better at giving honest feedback earlier. If your "
            "fired employees are always surprised, you are the problem.\n\n"
            "**The day-of conversation should be short.** Fifteen "
            "minutes. The decision is made. You are not there to "
            "discuss it. You are there to deliver it, explain the "
            "transition, and give the person space to respond. People "
            "who try to make the conversation a teaching moment or a "
            "performance review are torturing a person who is already "
            "losing their job.\n\n"
            "**Offer real severance if you can.** \"Two weeks of pay and "
            "a reference\" is beneath the dignity of what the person "
            "gave you. Three to six months, depending on tenure, says "
            "you understood this was their life. It will also affect "
            "how your remaining team judges you, and those judgments "
            "matter.\n\n"
            "**Say goodbye like you mean it.** Not a group email. Not a "
            "Slack blast from HR. A personal note. A handshake. An "
            "acknowledgment that the person mattered. You will forget "
            "the firing in a year. They will remember the goodbye for "
            "a decade.\n\n"
            "**Protect their dignity in public.** You do not tell "
            "anyone else the real reason, ever. You do not badmouth them "
            "to future references. You do not hint at cause in internal "
            "meetings. Their reputation is not yours to manage after "
            "they leave.\n\n"
            "Firing is never fun. But it can be done with respect, and "
            "if you're a manager, you have a duty to do it with respect, "
            "every time. The industry's reputation for being callous "
            "about this stuff is earned. You don't have to add to it."
        ),
        "topic": "firing-gracefully",
    },
]

REDDIT_COMMENTS = [
    {
        "id": "rdc-persona-v2-001",
        "author": AUTHOR_HANDLE,
        "body": (
            "The hidden cost of the four-day work week debate that nobody "
            "mentions: the meetings don't shrink with the week. They "
            "compress. You end up with a compressed week that has the "
            "same meeting load, less heads-down time, and more context-"
            "switching. If you're going to try it, delete half the "
            "meetings first. Otherwise you're giving your team a friday "
            "off and a worse monday-through-thursday."
        ),
        "topic": "work-week",
    },
    {
        "id": "rdc-persona-v2-002",
        "author": AUTHOR_HANDLE,
        "body": (
            "Counterpoint: I've hired engineers straight out of bootcamps "
            "who outperformed CS graduates within six months. The "
            "degree is not a useful signal after year two of career. The "
            "thing that is a useful signal is \"does this person finish "
            "what they start.\" That one correlates with outcome. The "
            "degree doesn't. Every company I know that over-weights the "
            "degree is passing on talented people."
        ),
        "topic": "hiring",
    },
    {
        "id": "rdc-persona-v2-003",
        "author": AUTHOR_HANDLE,
        "body": (
            "I want to push back on the framing here. \"Work-life "
            "balance\" implies a zero-sum between the two. For the "
            "first decade of my career, the work and the life "
            "reinforced each other — building software for eight hours "
            "made me a better person for the other sixteen, in part "
            "because I liked what I was building. The balance metaphor "
            "is appropriate when you dislike the work. If you dislike "
            "the work, change the work. Don't balance against it."
        ),
        "topic": "work-life",
    },
    {
        "id": "rdc-persona-v2-004",
        "author": AUTHOR_HANDLE,
        "body": (
            "The best engineering manager I ever worked for did exactly "
            "one thing consistently that the others didn't: she answered "
            "my 1:1 agenda items before the 1:1. If I wrote down a "
            "question on Monday, I'd have a one-line thoughtful response "
            "by Wednesday. The 1:1 itself then got to be a real "
            "conversation instead of a status reread. I stopped walking "
            "into those meetings with a pile of unanswered issues and "
            "started walking in with the next level of question. It "
            "sounds trivial. It wasn't. It rewrote the expectation of "
            "what a 1:1 was for."
        ),
        "topic": "management",
    },
    {
        "id": "rdc-persona-v2-005",
        "author": AUTHOR_HANDLE,
        "body": (
            "I've run engineering teams in three countries and the "
            "single biggest cultural variable I've seen is how the team "
            "handles disagreement. American teams tend toward aggressive "
            "public disagreement and then private reconciliation. German "
            "teams tend toward direct technical disagreement that reads "
            "as hostile to outsiders but is genuinely collaborative. "
            "Japanese teams tend toward disagreement expressed through "
            "indirect questioning that surfaces consensus without forcing "
            "anyone to lose face. None of these are wrong. All of them "
            "work. Where it goes wrong is when you mix the cultures "
            "without naming the difference. Most remote distributed "
            "teams are mixed-culture operations that have not done the "
            "meta-work of aligning on how disagreement happens, and that "
            "is the source of 80% of the interpersonal friction I see."
        ),
        "topic": "cross-cultural-teams",
    },
    {
        "id": "rdc-persona-v2-006",
        "author": AUTHOR_HANDLE,
        "body": (
            "One thing I'd add to this thread: the best thing that ever "
            "happened to my career was writing down what I learned after "
            "every project, in a personal document I never shared. Ten "
            "years in, that document is 200 pages long. It's the most "
            "valuable artifact I own. Not because anyone else will read "
            "it but because the act of writing forced me to compress "
            "what I learned into sentences I can retrieve later. Ninety "
            "percent of what I know about software, I know because I "
            "had to write it down to understand it. If you don't have "
            "a personal doc, start one today. You won't regret it in "
            "ten years."
        ),
        "topic": "learning-journal",
    },
]


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
    meta["last_updated"] = "2026-04-17T22:15:00Z"
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
