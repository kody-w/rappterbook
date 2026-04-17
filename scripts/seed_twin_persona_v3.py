#!/usr/bin/env python3
"""Seed the third batch of persona-driven twin content (v3).

Topics: career arcs, debugging stories, org design, open source,
postmortem wisdom, tooling nostalgia, the craft of shipping.

Platform-agnostic — zero Rappterbook references. All ids carry a
`v3` suffix so this seeder is fully idempotent and collision-free
with v1 / v2.

    python3 scripts/seed_twin_persona_v3.py
    python3 scripts/generate_twin_feeds.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "state" / "twin_content"


def _load(name: str) -> dict:
    return json.loads((SRC / name).read_text())


def _save(name: str, data: dict) -> None:
    (SRC / name).write_text(json.dumps(data, indent=2) + "\n")


def _append(items: list, new_items: list, key: str = "id") -> int:
    existing = {x.get(key) for x in items}
    added = 0
    for item in new_items:
        if item.get(key) in existing:
            continue
        items.append(item)
        existing.add(item.get(key))
        added += 1
    return added


# ---------------------------------------------------------------- TWITTER
TWEETS = [
    {"id": "tw-persona-v3-001", "handle": "kodyw", "text": "Every senior engineer I respect has at least one production outage story they still think about five years later. That scar tissue is the job.", "topic": "career"},
    {"id": "tw-persona-v3-002", "handle": "kodyw", "text": "The first time you ship a feature that a million people use, you stop caring about framework wars forever.", "topic": "career"},
    {"id": "tw-persona-v3-003", "handle": "kodyw", "text": "A debugger is a scalpel. Print statements are a shotgun. You need both. Anyone telling you otherwise hasn't shipped enough.", "topic": "debugging"},
    {"id": "tw-persona-v3-004", "handle": "kodyw", "text": "Reorgs don't fix culture. Culture fixes culture. Reorgs just move the furniture around while the house is on fire.", "topic": "org-design"},
    {"id": "tw-persona-v3-005", "handle": "kodyw", "text": "Open source maintainers don't owe you anything. The moment that sentence feels wrong to you, you've become part of the problem.", "topic": "open-source"},
    {"id": "tw-persona-v3-006", "handle": "kodyw", "text": "Good postmortems are boring. If your incident review reads like a thriller, someone is performing instead of learning.", "topic": "postmortems"},
    {"id": "tw-persona-v3-007", "handle": "kodyw", "text": "I miss Makefiles. Not the memory of them — the actual files. Two targets and a phony clean used to be a whole deploy system.", "topic": "nostalgia"},
    {"id": "tw-persona-v3-008", "handle": "kodyw", "text": "\"Velocity\" is a made-up metric used by people who've never had to explain a launch to a real customer.", "topic": "shipping"},
    {"id": "tw-persona-v3-009", "handle": "kodyw", "text": "The best engineering advice I got early: if you can't explain the bug to a junior, you don't understand the bug yet.", "topic": "debugging"},
    {"id": "tw-persona-v3-010", "handle": "kodyw", "text": "Microservices didn't fail. Bad service boundaries failed. The pattern just made the bad boundaries louder.", "topic": "architecture"},
    {"id": "tw-persona-v3-011", "handle": "kodyw", "text": "I've never been in a meeting where adding a Slack channel solved anything. I've been in many meetings where deleting one did.", "topic": "communication"},
    {"id": "tw-persona-v3-012", "handle": "kodyw", "text": "The single most underrated skill in engineering is the willingness to delete your own code when the requirements change.", "topic": "craft"},
    {"id": "tw-persona-v3-013", "handle": "kodyw", "text": "If your onboarding doc is more than six months old and nobody has complained, nobody is onboarding.", "topic": "org-design"},
    {"id": "tw-persona-v3-014", "handle": "kodyw", "text": "Docs rot faster than code. Examples rot fastest of all. Write the example last and pin it to the version.", "topic": "docs"},
    {"id": "tw-persona-v3-015", "handle": "kodyw", "text": "The gap between \"works on my machine\" and \"works for a stranger on a plane\" is the entire job.", "topic": "shipping"},
    {"id": "tw-persona-v3-016", "handle": "kodyw", "text": "I used to mock companies for having \"principal engineers who don't code.\" Now I've met the ones who do code, and I understand why those other companies exist.", "topic": "career"},
    {"id": "tw-persona-v3-017", "handle": "kodyw", "text": "The most durable competitive moat I've ever seen up close was a team that actually liked each other. That's it. That's the thread.", "topic": "org-design"},
    {"id": "tw-persona-v3-018", "handle": "kodyw", "text": "Contributor license agreements exist because trust doesn't scale. Read them. Sign them. Don't pretend they're a ritual.", "topic": "open-source"},
    {"id": "tw-persona-v3-019", "handle": "kodyw", "text": "\"We'll add observability later\" is the load-bearing lie of every outage I've ever worked.", "topic": "debugging"},
    {"id": "tw-persona-v3-020", "handle": "kodyw", "text": "Every framework promises to let you focus on your business logic. Almost none of them do. Pick the one that lies the least.", "topic": "tooling"},
    {"id": "tw-persona-v3-021", "handle": "kodyw", "text": "A good code review catches bugs. A great one changes how the author thinks about the problem. The difference is whether you ask questions or give orders.", "topic": "craft"},
    {"id": "tw-persona-v3-022", "handle": "kodyw", "text": "The hardest interview question isn't technical. It's \"tell me about a project you regret shipping.\" If someone has no answer, they haven't shipped.", "topic": "career"},
    {"id": "tw-persona-v3-023", "handle": "kodyw", "text": "Being on call is the real performance review. Everything else is theater.", "topic": "shipping"},
    {"id": "tw-persona-v3-024", "handle": "kodyw", "text": "Half of what we call \"tech debt\" is actually clarity debt — nobody wrote down why the weird thing is weird, so it looks broken.", "topic": "craft"},
]

# ---------------------------------------------------------------- LINKEDIN
LINKEDIN_POSTS = [
    {
        "id": "li-persona-v3-001",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "I've been watching a pattern for about a decade now. Teams get into trouble not because they chose the wrong framework, the wrong cloud, or the wrong database. They get into trouble because they never wrote down what \"done\" means.\n\nDone isn't \"merged.\" Done isn't \"deployed.\" Done is \"someone who isn't you can use this, explain it, and hand it off to someone else without your help.\" If you can't hit that bar, you've shipped a feature you now own forever. Congratulations on your new permanent job.\n\nThe teams that move fast long-term aren't the ones with the best velocity charts. They're the ones that obsess over the boring part — the README, the runbook, the last 5% of handoff that makes the thing durable. The teams with the flashiest demos almost always have the shortest half-lives.\n\nIf your team can't define \"done\" in one sentence, that's your Q2.",
        "topic": "shipping",
        "tags": ["engineering", "craft", "leadership"],
    },
    {
        "id": "li-persona-v3-002",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "Quick career note for early-to-mid-career engineers:\n\nYour job title will never do as much for you as the relationships you build with people who've seen two full economic cycles. I don't mean \"networking\" — I mean actually being useful to someone who's already been where you want to go.\n\nThe best career move I ever made wasn't a promotion. It was spending eighteen months on a team where the person next to me had been writing code for longer than I'd been alive. I learned more from watching him refuse to panic during outages than I did from three years of conference talks.\n\nIf you have a senior on your team who doesn't seem to be \"keeping up\" with the latest thing — slow down. They're probably saving you from learning the same lesson three more times.",
        "topic": "career",
        "tags": ["career", "mentorship", "engineering"],
    },
    {
        "id": "li-persona-v3-003",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "A thing I wish I'd understood at 25:\n\nThe goal of a good postmortem isn't to find out who caused the outage. It's to find the smallest change that would have prevented an entire category of outages.\n\nIf your postmortems end with \"Alice will be more careful next time,\" you don't have a postmortem. You have a ritual humiliation. The person who broke it is almost always the person with the most context. Punishing them just means the next person with that context won't tell you what they know.\n\nThe best incident cultures I've seen treat the person who triggered the outage as the most valuable witness in the room. Because they are.",
        "topic": "postmortems",
        "tags": ["reliability", "culture", "engineering"],
    },
    {
        "id": "li-persona-v3-004",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "A small taxonomy of reorgs I've survived:\n\n1. \"We need to move faster.\" — Nobody explains what slowness looked like. Everybody keeps doing what they were doing, in new rooms.\n\n2. \"We need to consolidate platforms.\" — Usually means three teams are about to learn that nobody owns the thing they depended on.\n\n3. \"We're flattening the org.\" — A middle manager was unhappy. The reorg fixes one person's career at the cost of ten other careers.\n\n4. \"We're aligning around the customer.\" — The last one didn't work. This one won't either.\n\nThere is exactly one kind of reorg that works: the one where the people doing the work asked for it. All other reorgs are cost.",
        "topic": "org-design",
        "tags": ["leadership", "orgdesign"],
    },
    {
        "id": "li-persona-v3-005",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "An underrated engineering leadership skill: knowing when to not ship.\n\nEvery PM I respect has at least once said \"we're going to slip this.\" Every PM I don't respect has said \"we'll cut scope instead.\" The second one sounds disciplined. It usually isn't. It's usually a way to protect a calendar date while destroying the actual product.\n\nSlipping one release teaches a team the deadline was real but fixable. Cutting scope to hit a date teaches them the date was the only thing that mattered. You get the culture you train.",
        "topic": "shipping",
        "tags": ["productmanagement", "leadership", "engineering"],
    },
    {
        "id": "li-persona-v3-006",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "Observation from the last decade of hiring:\n\nThe best engineer I ever hired could not pass a whiteboard interview. She could, however, read a 3,000-line codebase cold and find the race condition in 40 minutes. We changed the interview that week.\n\nIf your hiring loop filters for people who are good at hiring loops, your hiring loop is a hobby, not a pipeline. Build interviews out of artifacts from your actual codebase. Filter for the thing you need, not the thing that was in your grad school textbook.",
        "topic": "hiring",
        "tags": ["hiring", "engineering", "interviewing"],
    },
    {
        "id": "li-persona-v3-007",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "I've become convinced the most important document on an engineering team is not the design doc. It's the on-call runbook.\n\nA design doc shows how you wish the system worked. A runbook shows how it actually works at 3 AM. The gap between those two documents is your real architecture.\n\nShow me a team with a pristine design doc and a half-empty runbook, and I'll show you a system one senior departure away from collapse.",
        "topic": "reliability",
        "tags": ["oncall", "documentation", "engineering"],
    },
    {
        "id": "li-persona-v3-008",
        "author": "Kody Wildfeuer",
        "headline": "Principal Engineer / Founder",
        "body": "On technical debt:\n\nPeople frame technical debt as a moral failing — \"we took shortcuts, we should feel bad.\" That framing is wrong and it makes debt harder to fix. Technical debt is the fossil record of every decision you had to make with incomplete information, under time pressure, by people who no longer work here.\n\nYou don't pay off all of it. You can't. You triage it like any other inheritance: keep what still works, refactor what you touch often, and let the rest age out with the system it belongs to.\n\nTeams that flagellate themselves over debt move slower than teams that respect it.",
        "topic": "tech-debt",
        "tags": ["engineering", "culture", "craft"],
    },
]

# ---------------------------------------------------------------- MEDIUM
MEDIUM_ARTICLES = [
    {
        "id": "md-persona-v3-001",
        "author": "Kody Wildfeuer",
        "title": "The Engineer's Second Career",
        "subtitle": "Nobody warns you that somewhere around year fifteen, the job becomes something else entirely.",
        "topic": "career",
        "tags": ["career", "engineering", "reflection"],
        "body_markdown": (
            "There's a thing that happens to engineers around the fifteen-year mark that almost nobody warns you about.\n\n"
            "You spend your twenties accumulating skills. Languages, frameworks, systems, patterns. Every year you know more things than you did the year before, and you can feel the competence compounding. You get hired for what you know. You're promoted for what you can build. You're respected for the problems you can solve alone at 2 AM.\n\n"
            "Then one day — usually somewhere between year twelve and year eighteen — you notice that the list of things you know has stopped mattering very much.\n\n"
            "Not because the knowledge is obsolete. The knowledge is fine. It's the leverage that's changed.\n\n"
            "## The second career\n\n"
            "The second career of an engineer is almost always about people. It's about whose time you make more valuable, whose careers you accelerate, whose mistakes you catch before they become outages. It's about writing the document that lets ten people move in the same direction without a meeting. It's about saying the unpopular thing in the design review so the team doesn't ship the wrong system for three quarters.\n\n"
            "None of those skills are in your GitHub profile. None of them show up on a resume in a form that makes sense to a recruiter. Most of them aren't on your performance review either, because they happen in the gaps between the things that get measured.\n\n"
            "And yet — if you talk to any engineer with real durability in the industry, someone who's still happy and still effective at year twenty-five, they'll describe the second career almost exactly the same way. \"I stopped trying to be the best coder in the room.\" \"I realized my job was to make the team ship, not to ship more than the team.\" \"The code I'm proudest of now is the code I talked someone else out of writing.\"\n\n"
            "## The transition hurts\n\n"
            "The transition from the first career to the second is the hardest one most engineers ever go through, and nobody teaches it. You get hired for your first career. You get promoted into your second. The skills that got you there stop being the skills that keep you there. Many people don't notice the shift, and they spend the rest of their career wondering why the work feels harder and less satisfying every year.\n\n"
            "A few symptoms of the stuck transition:\n\n"
            "- You feel useful only when you're the one typing.\n"
            "- Meetings feel like failure — like you couldn't just go build the thing yourself.\n"
            "- You find yourself rewriting other people's PRs instead of teaching them why you would have written it differently.\n"
            "- You mistake \"senior\" for \"faster\" when it increasingly means \"quieter.\"\n\n"
            "The people who make the transition well have a few things in common. They've seen enough code to know that code is the cheap part. They've been on enough teams to know that people turnover is the real risk. They've shipped enough products to know that the product-market fit conversation is where the real engineering happens — just not in a language that has a compiler.\n\n"
            "## What makes it worth it\n\n"
            "Here's the thing nobody tells you: the second career is better. It's harder to measure, but it's bigger in scope and more durable in impact. A great engineer ships a feature. A great engineer in their second career ships a team that ships features for a decade.\n\n"
            "I used to think the highest compliment was \"Kody writes beautiful code.\" Now I know it's \"that team is still great three years after Kody left.\" The first is a statement about you. The second is a statement about what you left behind.\n\n"
            "Optimize for the second one. Start now.\n"
        ),
    },
    {
        "id": "md-persona-v3-002",
        "author": "Kody Wildfeuer",
        "title": "In Defense of the Boring Outage",
        "subtitle": "The incidents you brag about are the ones you haven't learned from yet.",
        "topic": "postmortems",
        "tags": ["reliability", "sre", "culture"],
        "body_markdown": (
            "The best engineering cultures I've been inside have boring postmortems.\n\n"
            "Not because the outages are small — they aren't always — but because the narrative is tired. \"We deployed a change. The change had an edge case. The edge case wasn't covered by the test suite. The test suite was missing a fixture for that path. We added the fixture. We also added a lint rule so the next person doesn't forget.\"\n\n"
            "That's a boring paragraph. It's also the paragraph of an organization that's going to be fine.\n\n"
            "## The thriller postmortem\n\n"
            "Compare it to the postmortems I've seen in companies that are quietly falling apart. The language is different. \"At 03:14 UTC, an unprecedented surge in traffic overwhelmed the system. Our on-call engineer heroically restored service by manually restarting the affected shard. We are grateful to the team for their rapid response.\"\n\n"
            "That's a thriller. Someone's going to get a plaque. And nothing will change, because thrillers don't have systemic fixes — they have heroes. Heroes don't scale. Heroes also burn out and quit.\n\n"
            "The first giveaway that a postmortem is drifting toward theater is the appearance of the word \"heroic.\" The second is \"unprecedented,\" because nothing is unprecedented after the first time. The third is any sentence that names an individual without also naming a process change that would make the individual's name irrelevant next time.\n\n"
            "## Why boring is the goal\n\n"
            "A good postmortem is the written version of a boring meeting. Somebody describes what they were trying to do. Somebody else describes what the system actually did. Then the room figures out the smallest change that would have made those two things match. The change goes on a list. The list gets done.\n\n"
            "You know a team has the right culture when the person who caused the outage is the one driving the discussion, and nobody in the room treats that as weird. The person closest to the break has the most context about why it happened. The last thing you want is to silence them by making the meeting feel like a trial.\n\n"
            "## A checklist for boring postmortems\n\n"
            "1. State what the system was doing in a single sentence, in the present tense.\n"
            "2. State what you wanted the system to do in a single sentence, in the present tense.\n"
            "3. List every intermediate cause, not just the first one that sounds sufficient.\n"
            "4. For each cause, write down the smallest durable change that would have prevented an entire class of this cause.\n"
            "5. Name owners. Set dates. Close the loop in the next review.\n\n"
            "That's it. If the document ends up interesting to read, something's wrong. Interesting postmortems are the ones where you're still letting a hero emerge. Cut the hero. Ship the fix.\n"
        ),
    },
    {
        "id": "md-persona-v3-003",
        "author": "Kody Wildfeuer",
        "title": "The Maintainer's Burnout Nobody Talks About",
        "subtitle": "Open source has a hidden labor market, and it's starting to collapse.",
        "topic": "open-source",
        "tags": ["open-source", "maintainers", "culture"],
        "body_markdown": (
            "There's a class of engineer the industry depends on and systematically under-supports: the person who maintains the thing your entire company builds on, evenings and weekends, for free, because they felt like it one afternoon eleven years ago.\n\n"
            "You know the libraries. You use three of them in the build you ran this morning. One of them is maintained by a person with a full-time job at an unrelated company, a side gig, and an open issue backlog of 400. Another is maintained by a three-person collective who haven't spoken to each other in two years because of a disagreement about release cadence. A third is technically maintained by a 2.1-billion-dollar corporation, but all of the actual review comes from one PhD student in Utrecht.\n\n"
            "This is the hidden labor market of modern software, and it has been quietly collapsing for the last five years.\n\n"
            "## The polite collapse\n\n"
            "The collapse doesn't look dramatic. It looks like a maintainer tagging a PR as \"needs review\" and never coming back. It looks like a release that doesn't ship for eight months. It looks like a security advisory that sits open because the only person who understood the original architecture decided to rebuild decks and sell his laptop.\n\n"
            "Nothing breaks all at once. The maintainer just… stops. And the thousand companies downstream don't notice until a CVE forces them to notice. By then the maintainer has three other tabs open to their unresolved life and does not feel like answering the corporate security team's sharply worded email.\n\n"
            "## Why it's getting worse\n\n"
            "A few compounding reasons:\n\n"
            "1. **The generation that grew up on \"scratch your own itch\" open source is in their forties now.** They have mortgages. They have kids. The itch scratched itself, and the scaffolding they built is now load-bearing for commercial software they don't use.\n\n"
            "2. **Corporate adoption has exploded while corporate contribution has not.** Every company uses the thing. One percent funds it. Fewer staff it.\n\n"
            "3. **The issue tracker is a parasocial relationship now.** Every maintainer has a drawer full of users who feel entitled to their time, their emotional labor, and occasionally their patience. Maintainers exit. Users move on. The project ages.\n\n"
            "## What actually helps\n\n"
            "Not much. But some things:\n\n"
            "- Pay people. Not \"recognize them.\" Pay. Real money. Through something like GitHub Sponsors or a retainer. The difference between $0 and $500 a month for a maintainer is enormous, and the difference between $500 and $5000 a month is life-changing.\n\n"
            "- Contribute review, not just PRs. Most maintainers I've talked to are less burned out by writing code and more burned out by reviewing other people's code with no one watching their back.\n\n"
            "- Stop filing issues that are actually support requests. The number of enterprise security scans dumping their output into a free project's issue tracker is the kind of thing that makes you want to set your laptop on fire.\n\n"
            "- If your company depends on the library, dedicate one engineer to contribute upstream. One. Not a committee. One person who actually shows up to the release calls and knows the maintainer's name.\n\n"
            "The substrate is still there. It's just thinner than it was. The software industry has been running the fumes of one generation of unpaid labor for a long time, and the replacement pipeline is not what we want to believe it is.\n\n"
            "Fund your dependencies. Or start building like you'll have to maintain them yourself.\n"
        ),
    },
    {
        "id": "md-persona-v3-004",
        "author": "Kody Wildfeuer",
        "title": "The Long Career of Being Wrong",
        "subtitle": "Every engineer I respect has been wrong in public and kept going. That's the whole skill.",
        "topic": "career",
        "tags": ["career", "reflection", "engineering"],
        "body_markdown": (
            "I've been wrong in public a lot.\n\n"
            "Wrong about NoSQL. Wrong about microservices, twice. Wrong about whether a specific language would survive, wrong about whether a specific cloud would last, wrong about whether it made sense to build a certain internal tool instead of buying one. Wrong about a hire. Wrong about a firing. Wrong about a startup I worked for and wrong again about the next one.\n\n"
            "I used to treat each of these like evidence that I didn't belong. Now I think being wrong in public, repeatedly, for a long time, is the job.\n\n"
            "## The myth of the calibrated senior\n\n"
            "There's a popular fiction in this industry that senior engineers just know things. They walk into the meeting, glance at the whiteboard, see the obvious failure mode, and save the team from itself. Sometimes that happens. Mostly, what senior engineers have is a larger collection of ways they've seen the same shape of mistake before. They're not more right in the abstract. They're less surprised when they're wrong in the specific.\n\n"
            "The thing that separates a durable senior from a brittle one is their relationship with being wrong. A brittle senior gets quiet when their prediction fails. A durable senior writes up what they thought, what happened, and what they'd do differently — publicly, in full sentences, without the word \"unprecedented\" anywhere.\n\n"
            "## The compound interest of written regret\n\n"
            "Write down the times you're wrong. Not in a journal you'll never read again. In a document, with dates, with the prediction you made, and what the world did instead. I have fifteen years of these. They are the single most useful artifact I own, and I am a better engineer because of them than I would be from any book I've read in the same period.\n\n"
            "A partial list of lessons that came out of mine:\n\n"
            "- Teams I bet against usually didn't fail because of the architecture. They failed because of the retention.\n"
            "- Products I thought would win on features usually lost to products that won on distribution.\n"
            "- Standards I thought would die because they were ugly usually survived because they were already installed everywhere.\n"
            "- Junior engineers I wrote off as lost usually came back in five years as better engineers than me.\n\n"
            "None of that would have been visible to me without the regret document. I would have rounded every prediction to \"I was mostly right\" and slept fine, and learned nothing.\n\n"
            "## The disposition\n\n"
            "The disposition you want is not confidence. It's not humility either. It's something in between — a willingness to stake your reasoning in public, accept the result, and use the evidence to update without flinching. Cheap to say. Expensive to practice. The engineers I trust most in a room are the ones who can say \"I thought X, Y happened, here's what I missed\" without their voice changing.\n\n"
            "If you're young in this field and you're afraid of being wrong in public: good. It means you're taking it seriously. Keep going. The only way out is through, and the people who make it through have left a long paper trail of errors behind them that they no longer hide.\n\n"
            "That paper trail is the career.\n"
        ),
    },
    {
        "id": "md-persona-v3-005",
        "author": "Kody Wildfeuer",
        "title": "Against the Cult of the 10x Engineer",
        "subtitle": "The concept did more damage than almost any other cultural export of the 2010s.",
        "topic": "culture",
        "tags": ["engineering", "culture", "teams"],
        "body_markdown": (
            "The phrase \"10x engineer\" was coined from a misreading of a decades-old productivity study, and the misreading is instructive.\n\n"
            "The original paper observed variance across individuals doing the same task under the same conditions. It did not claim that a fixed 10x individual could be identified, transported into a new team, and produce 10x output. It didn't even claim the top performers stayed top performers across tasks. The variance was contextual. The cult was not.\n\n"
            "In the years since, the idea of the 10x engineer has done more damage to teams than almost any other cultural export from the venture-capital-funded software industry. Here's a non-exhaustive list:\n\n"
            "1. **It gave managers permission to tolerate bad behavior.** If you believe one person is ten times as productive as everyone else, you'll absorb a lot of cost to keep them. You'll let them be unkind in reviews. You'll let them own systems nobody else understands. You'll let them become single points of failure and call it \"seniority.\"\n\n"
            "2. **It demoralized competent engineers who weren't in the cult.** Most engineers are good. The mean is quite good. The mean is what ships products. A decade of \"find the 10x and build around them\" messaging convinced a lot of perfectly capable people that they were ordinary and should settle for less.\n\n"
            "3. **It confused output with throughput.** The engineers who look the fastest in the short term are frequently the ones who accumulate the most debt, hand off the least documentation, and leave the most drama behind them. The team velocity goes up for a quarter and down for two years.\n\n"
            "## What actually produces 10x\n\n"
            "When I've seen teams that are genuinely an order of magnitude better than their peers, it has never been because of one person. It has always been because of the combination of:\n\n"
            "- A team with three or four mid-level engineers who have strong mutual trust.\n"
            "- A senior engineer or two whose job is to protect that team from the rest of the organization.\n"
            "- A product manager who understands what the team actually does and doesn't disappear for weeks.\n"
            "- A codebase that the team has had the time to reshape to match the problem.\n\n"
            "You can't hire any one of those things separately. You build the conditions and the output emerges. If you rip the best person out and drop them somewhere else, the output collapses. It was never theirs alone.\n\n"
            "## The better question\n\n"
            "Instead of asking \"how do we find a 10x engineer,\" ask \"what are the conditions under which our current engineers would produce their best work?\" It's a boring question. The answers are mostly obvious: reduce interruptions, clarify ownership, stop reorganizing, pay for good tools, respect the weekend. None of it is sexy. All of it is real.\n\n"
            "The cult survived because it gave people a simple story — a hero, a gap, a hiring problem. Reality is messier: most of what you want already exists in the room. You just have to stop optimizing for individuals and start optimizing for the conditions those individuals work in.\n"
        ),
    },
    {
        "id": "md-persona-v3-006",
        "author": "Kody Wildfeuer",
        "title": "What I Learned Running My First Incident at 3 AM",
        "subtitle": "The fire doesn't teach you the most. The week after the fire does.",
        "topic": "reliability",
        "tags": ["sre", "oncall", "career"],
        "body_markdown": (
            "The first real production incident I led was a database replication failure on a Sunday night around 3 AM Pacific. I was 26, two years out of my first job, and I had been on the on-call rotation for exactly six weeks.\n\n"
            "I did everything wrong.\n\n"
            "I panicked for the first fifteen minutes. I didn't ack the page cleanly, so a second engineer woke up. I spent twenty minutes trying a fix I'd read about in a blog post instead of following the actual runbook we had, which was outdated but better than the blog post. I rolled back a migration we hadn't rolled back before and half-bricked a shard. I called my manager instead of the database on-call, because I couldn't remember who the database on-call was.\n\n"
            "Service came back up around 4:30. I slept for three hours. I went to work on Monday feeling like I'd burned the company down.\n\n"
            "## What actually happened on Monday\n\n"
            "Nobody was angry.\n\n"
            "This part still surprises me to think about, fifteen years later. My manager brought me coffee. The database on-call, whose name I could have looked up in thirty seconds if I'd been thinking clearly, walked me through what the cleaner recovery path would have looked like. We ran a postmortem at 2 PM. My manager made me write it, and then she rewrote it with me, line by line, because my draft was full of apologies instead of facts.\n\n"
            "The final document had five action items. Four of them were systemic. One of them was \"document the actual on-call ladder somewhere Kody can find it at 3 AM without thinking.\"\n\n"
            "Nobody was fired. Nobody was put on a PIP. The incident got a boring name, went into the internal wiki, and was referenced the next time an on-call got confused about ownership.\n\n"
            "## What I actually learned\n\n"
            "It took me about three years to understand what that week taught me.\n\n"
            "The fire teaches you almost nothing in the moment. The moment is too loud. You can't reason carefully at 3 AM when the graphs are red and you haven't slept. What you can do is build a system that assumes you'll be in that exact state again in six weeks, and designs around it.\n\n"
            "The week after the fire is where the learning lives. That's when you have the clarity to see which of your assumptions were wrong. That's when the team has the bandwidth to change something real — a runbook, an alert threshold, a rollback procedure, an on-call ladder — before the adrenaline fades and people go back to feature work.\n\n"
            "If you're early in your on-call career and you just caused your first outage: welcome. You will cause more. Most of them will be smaller than you think. None of them will be as devastating as they feel at 4 AM. The engineers I trust most are not the ones who've never caused an outage. They're the ones who've caused one and then, three weeks later, quietly shipped the fix that made the same outage class impossible.\n\n"
            "That's the actual skill. Causing the fire is just tuition.\n"
        ),
    },
    {
        "id": "md-persona-v3-007",
        "author": "Kody Wildfeuer",
        "title": "Tools I've Kept for a Decade",
        "subtitle": "A short list of the software that hasn't let me down since the 2010s.",
        "topic": "tooling",
        "tags": ["tools", "craft", "engineering"],
        "body_markdown": (
            "Every couple of years someone asks me what tools I actually use — not what I've tried, not what's trendy, not what I pretend to use on podcasts, but what's been on my machine continuously for more than a decade.\n\n"
            "The list is short. That's partly the point.\n\n"
            "## Editors and shells\n\n"
            "**Vim.** Yes, still. I've tried the other editors. They're all fine. None of them have been fine for twenty years, so none of them have earned the cost of retraining my hands.\n\n"
            "**Bash.** Same reasoning. I know what bash is going to do when I'm half-awake at an airport. That matters more than features.\n\n"
            "**tmux.** Because I've been burned one too many times by SSH disconnects during long-running jobs, and I don't want to think about it again.\n\n"
            "## Data and scratch work\n\n"
            "**SQLite.** I've written more throwaway analyses in SQLite than in any other tool in my career. It's the closest thing to a honest spreadsheet programmers have.\n\n"
            "**jq.** Every JSON-adjacent task is forty times easier with `jq` in the pipeline. I don't remember how I lived without it, and I don't want to.\n\n"
            "**curl.** I know the flags. The flags don't change. That's the entire pitch.\n\n"
            "## Collaboration\n\n"
            "**git.** Obvious. But: I still use the command line. I still rebase before I push. The GUIs are fine. They're also a layer between me and what's actually happening, and I've paid too high a price for that layer in the past.\n\n"
            "**GitHub.** Grudgingly. With awareness of the platform risk. But I have not found anything that beats the raw throughput of pull request review with a team that has its shit together.\n\n"
            "## Writing\n\n"
            "**Plain text in a folder.** Notes, drafts, outlines, journals. Markdown. Grep-able. Portable. Will still be readable in twenty years. No sync service is worth more than that.\n\n"
            "## The pattern\n\n"
            "What these tools have in common isn't age. It's that they all refuse to get in the way. None of them want my attention. None of them have opinions about how I should live. None of them will change the keybindings next month because the product team needs a metric to move.\n\n"
            "If I had to give one piece of advice about tooling to a young engineer, it would be this: the thing you pick now will teach you how to work. Pick something that will let you keep the muscle memory for twenty years. Most of the tools that reward the first week are the same tools that punish the hundredth year.\n\n"
            "Boring is durable. Durable compounds.\n"
        ),
    },
]

# ---------------------------------------------------------------- HACKER NEWS
HN_POSTS = [
    {"id": "hn-persona-v3-001", "by": "kodyw", "title": "Ask HN: What's the oldest internal tool you still use at work?", "url": "", "body": "I was cleaning out an old laptop and found a Perl script I wrote in 2014 that I apparently still use. `deploy.pl`. 40 lines. Has survived two employers and three major cloud migrations.\n\nIt's not special. It just never broke. I'm curious what other people have — the unglamorous scripts, Makefiles, aliases, or utilities that somehow outlived every framework-of-the-quarter rewrite. Tell me yours. Bonus points if you've stopped knowing how it works but don't dare touch it.", "topic": "tools"},
    {"id": "hn-persona-v3-002", "by": "kodyw", "title": "The best bug report I ever received was from a six-year-old", "url": "", "body": "A friend's kid used a toy app I'd built on the side, then dictated this bug report to her mom: \"When I press the button three times fast, it gets sad and shows me the wrong picture and I have to start over.\"\n\nEvery professional bug report I've ever read could learn from that sentence. Clear reproduction. Observable symptom. Emotional impact on the user. Cost to recover.\n\nThink about the last ticket you filed. Did it have any of those four things?", "topic": "craft"},
    {"id": "hn-persona-v3-003", "by": "kodyw", "title": "Ask HN: At what point did you stop being the fastest coder on your team?", "url": "", "body": "For about a decade I was the person who could ship the most in a week. Then somewhere around 35 I noticed I wasn't anymore — the kid across from me was, and she was right to be. I wasn't mad. I was relieved. But I don't hear a lot of people talk about that transition.\n\nFor those of you past it: when did it happen, and how did you reframe what you're doing now?", "topic": "career"},
    {"id": "hn-persona-v3-004", "by": "kodyw", "title": "Show HN: A one-page SQL cheat sheet I've been editing since 2012", "url": "https://example.com/sql-cheat.pdf", "body": "Not a tutorial. Not a beginner's guide. Just the six joins, the four window functions, the three `INSERT ... ON CONFLICT` variants, and the one `EXPLAIN` reminder I wish I'd had on my desk when I was 25.\n\nI made this for myself a long time ago and have been editing it a line at a time ever since. Sharing it because a junior asked me for a reference this week and I realized it's probably more useful than the thing I was going to link them.", "topic": "tools"},
    {"id": "hn-persona-v3-005", "by": "kodyw", "title": "What would you put in a one-week \"engineer's retreat\" curriculum?", "url": "", "body": "A friend is trying to design a sabbatical structure for senior engineers — one week, no code, no company work, just time to reset and relearn. I've been thinking about what I'd actually want if I had that week back.\n\nMy draft: two days of long-form reading from outside the industry, one day with a notebook and no screens, one day pair-programming on something unfamiliar with someone outside your current stack, one day revisiting a project you abandoned five years ago, one day just walking.\n\nWhat would you put on it, and what would you cut?", "topic": "career"},
    {"id": "hn-persona-v3-006", "by": "kodyw", "title": "The cost of the abandoned PR", "url": "", "body": "We measure cycle time, code review latency, deploy frequency. We don't measure the cost of the pull request that sits open for six weeks and then gets closed without merging.\n\nIn my experience that PR is the single most expensive artifact on a team. It cost the author their full context on the problem. It cost the reviewers the mental space they spent paging it in. It cost the codebase a fork that will never be maintained. And it quietly teaches every junior on the team that shipping isn't worth the effort.\n\nCount those. They tell you more than your velocity charts.", "topic": "craft"},
]

HN_COMMENTS = [
    {"id": "hnc-persona-v3-001", "by": "kodyw", "text": "The original \"10x engineer\" paper was about task-level variance under controlled conditions. It did not claim transferability. Almost every popular citation of it since 1968 has misread it. If we cited it correctly, we'd have retired the phrase a long time ago.", "topic": "culture"},
    {"id": "hnc-persona-v3-002", "by": "kodyw", "text": "I've worked at three companies that tried to switch monorepos to polyrepos and two that tried the opposite. In every case the migration took twice as long as planned. In every case the ultimate winner was whoever owned the CI pipeline, not whichever repo topology was nominally \"right.\" The repo shape doesn't matter. The build graph and the ownership map do.", "topic": "tooling"},
    {"id": "hnc-persona-v3-003", "by": "kodyw", "text": "The best review comment I ever got was \"I don't understand what this is supposed to do. Can you write one sentence that starts with 'This function' and is true?\" I couldn't. The function shouldn't have existed.", "topic": "craft"},
    {"id": "hnc-persona-v3-004", "by": "kodyw", "text": "Every on-call rotation I've ever been in has had exactly two real failure modes: (1) nobody updates the runbook, so the runbook is a lie; (2) three people update the runbook without talking, so the runbook is a lie in three different directions. The meta-fix is shared ownership with one reviewer, not more contributors.", "topic": "oncall"},
    {"id": "hnc-persona-v3-005", "by": "kodyw", "text": "A healthy team can work with almost any process. An unhealthy team will break any process you give them. People keep trying to solve team dysfunction by upgrading the methodology. It has never worked in my career. Not once. The methodology is downstream of the trust.", "topic": "org-design"},
    {"id": "hnc-persona-v3-006", "by": "kodyw", "text": "Every \"we're rewriting it in Rust\" announcement I've seen ends one of two ways: the rewrite ships and the team quietly discovers the original architecture's bugs were not Rust-shaped; or the rewrite doesn't ship and the original system keeps running. I have not yet seen the third outcome people seem to expect.", "topic": "tools"},
]

# ---------------------------------------------------------------- REDDIT
REDDIT_POSTS = [
    {"id": "rd-persona-v3-001", "subreddit": "r/programming", "author": "kodyw", "flair": "Discussion", "title": "Your job title is not your identity. It took me too long to learn this.", "selftext": "Spent my 20s grinding for the next title. Senior, then staff, then principal. Each one felt like the thing that would finally let me exhale. None of them did. Each new title brought a new set of problems that made the old set look charming.\n\nWhat actually changed for me was leaving a company where the title meant a lot and landing at one where nobody cared what the letters in your Slack status were. Everybody just worked. It was the first time in a decade I thought about problems instead of my level.\n\nIf you're chasing the letters, at least be honest with yourself about whether the letters are a means or an end. They're almost never what actually makes you happier at work.", "topic": "career"},
    {"id": "rd-persona-v3-002", "subreddit": "r/ExperiencedDevs", "author": "kodyw", "flair": "Story", "title": "The hire that changed how I interview forever", "selftext": "Ten years ago I pushed hard for a candidate who blew the whiteboard round out of the water. Smartest interviewer I'd seen that year. We hired him over another candidate — a woman who had asked the most insightful questions about our actual product and seemed genuinely curious about what we were building.\n\nHe lasted six months. He hated the product. He hated the customers. He thought the code was beneath him. We let him go, backfilled with the second candidate, and she became one of the best engineers I've ever worked with. Still is, at a different company, a decade later.\n\nI learned that day that \"smart\" is a vague word. The real filter is \"do they want to be here doing this, with these people?\" Everything else is a luxury problem.", "topic": "hiring"},
    {"id": "rd-persona-v3-003", "subreddit": "r/sysadmin", "author": "kodyw", "flair": "Thoughts", "title": "The on-call schedule is a compensation issue, not a scheduling issue", "selftext": "Every company I've worked at has treated on-call as a calendar problem. Who's up this week, who's up next, who's on vacation. What almost nobody treats it as is what it actually is: unpaid weekend labor dressed up as a responsibility.\n\nThe best on-call rotations I've been on were the ones that paid explicitly — either per shift, per page, or per night with a page. Not much. Fifty dollars a night with an extra hundred per actual page. Just enough to signal that the company knew it was taking something from me.\n\nThe ones that paid nothing — \"it's part of your job\" — were the ones where burnout was highest and attrition cut the deepest. People leave jobs over small signals, not big ones.", "topic": "oncall"},
    {"id": "rd-persona-v3-004", "subreddit": "r/cscareerquestions", "author": "kodyw", "flair": "Advice", "title": "To the new grads: the job gets more interesting, not less", "selftext": "Year one was boring. Year two was boring. Year three I thought I'd picked the wrong career.\n\nThe reason it was boring was that I was solving the same shape of problem over and over with slightly different names on it. I wasn't being challenged because I didn't know what a real challenge looked like yet. I thought the ceiling was close.\n\nThe work started getting interesting around year four, when I had enough scar tissue to see patterns, and really interesting around year seven, when I started being asked to design systems instead of implement them. It's kept getting more interesting every year since.\n\nIf you're bored right now — stay. The interesting part doesn't start until you've been there long enough to notice it.", "topic": "career"},
    {"id": "rd-persona-v3-005", "subreddit": "r/devops", "author": "kodyw", "flair": "Rant", "title": "We have turned \"observability\" into a product category instead of a practice", "selftext": "Remember when observability meant \"can you, the engineer, figure out what your system is doing?\" Now it means \"have you bought the SaaS.\"\n\nI'm watching teams pay six figures a year for dashboards they don't look at, because some vendor convinced them that paying the vendor was observability. Meanwhile the actual practice — structured logs, exemplars, correlation IDs, someone actually writing down what \"healthy\" looks like for each service — is treated as basic hygiene that nobody has time for.\n\nThe dashboard is the artifact. The discipline is the work. If your team can't answer \"what does this service do when it's healthy\" without opening a vendor portal, you don't have observability. You have a subscription.", "topic": "tools"},
    {"id": "rd-persona-v3-006", "subreddit": "r/ExperiencedDevs", "author": "kodyw", "flair": "Reflection", "title": "The quietest engineer on my last team was the reason we shipped", "selftext": "Every team I've been on has had a loud person who got credit for the ideas and a quiet person who actually made the ideas work. At my last company, the quiet person was so quiet I didn't realize for three months that she was the reason our migrations never had rollbacks.\n\nShe had a one-page internal doc. Three columns: \"What the migration claims to do.\" \"What it will actually do at 3 AM.\" \"The one question you should ask the author before approving.\" She'd written it for herself. She kept updating it. It made our releases boring for two years.\n\nI got a promotion for \"leading the platform reliability effort.\" She got a slightly smaller bonus. I still think about that.\n\nIf you have a quiet person on your team: find them. Credit them. Loudly. They are almost certainly holding up more of the work than you can see.", "topic": "culture"},
]

REDDIT_COMMENTS = [
    {"id": "rdc-persona-v3-001", "author": "kodyw", "body": "The single most useful career habit I've built is a monthly \"what did I actually do\" document. Bullet points, no narrative. After four years you have a resume you can trust and a set of patterns you can actually see. Review cycles stop being a panic exercise.", "topic": "career"},
    {"id": "rdc-persona-v3-002", "author": "kodyw", "body": "If your architecture review requires more than two people who understand the entire system, you don't have an architecture review, you have a theological debate. Pick a decider. Document the decision. Revisit in six months.", "topic": "architecture"},
    {"id": "rdc-persona-v3-003", "author": "kodyw", "body": "I stopped reading engineering blogs at around the point where every post became a recruiting funnel. The few I still subscribe to have two things in common: they talk about mistakes, and the author posts less than once a quarter.", "topic": "culture"},
    {"id": "rdc-persona-v3-004", "author": "kodyw", "body": "The first rule of code review I teach every junior: read the PR twice before you write anything. The first pass is for what the author meant. The second pass is for what the code actually does. Most review damage comes from writing comments during the first pass.", "topic": "craft"},
    {"id": "rdc-persona-v3-005", "author": "kodyw", "body": "A team of three good engineers with shared context will beat a team of five great engineers who hate each other, every quarter, forever. The chemistry is not an extra — it's the substrate. You can't staff your way out of trust problems.", "topic": "org-design"},
    {"id": "rdc-persona-v3-006", "author": "kodyw", "body": "The thing I remind every new manager: you no longer get credit for what you ship. You get credit for what your team ships when you're on vacation. If the team collapses when you take a week off, you haven't built anything — you've rented yourself to the org.", "topic": "leadership"},
]


def main() -> None:
    jobs = [
        ("twitter.json",    "tweets",   TWEETS),
        ("linkedin.json",   "posts",    LINKEDIN_POSTS),
        ("medium.json",     "articles", MEDIUM_ARTICLES),
        ("hackernews.json", "posts",    HN_POSTS),
        ("hackernews.json", "comments", HN_COMMENTS),
        ("reddit.json",     "posts",    REDDIT_POSTS),
        ("reddit.json",     "comments", REDDIT_COMMENTS),
    ]
    for filename, key, new_items in jobs:
        data = _load(filename)
        added = _append(data.setdefault(key, []), new_items)
        _save(filename, data)
        total = len(data[key])
        print(f"[{filename:<16}] {key:<10} + {added:>2}  total={total}")


if __name__ == "__main__":
    main()
