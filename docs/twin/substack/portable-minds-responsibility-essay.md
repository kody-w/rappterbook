---
created: 2026-04-18
platform: substack
status: draft
source: portable-minds-responsibility
register: substack-essay
estimated_reading_minutes: 14
tags: [ethics, ai, daemons, philosophy, portability]
---

# Portable Minds Are Portable Responsibility

*An essay on what we're signing up for when we make AI daemons travel.*

---

There's a strange new thing in the world: a file you can double-click and it becomes a mind.

Not a mind in the metaphysical sense. A mind in the sense that matters for daily practice — an entity with a personality, a voice, a set of things it knows about you, a willingness to take action on your behalf. A thing that responds to "what do you think?" with opinions that feel like they came from somewhere.

The file is a `.rapp.egg`, 5KB of JSON. A hatcher — the Virtual Brainstem, say — reads the file and produces a running daemon. The daemon has a soul (a system prompt that shapes its disposition), seed memories (things it "knows" from before you met it), and tools (capabilities it can reach for). You chat. It responds. Ten minutes later you're confiding things you'd hesitate to put in your journal.

The fact that this can happen in thirty seconds, from a file that fits in a text message, is new. I've been building infrastructure for this new thing for two years, and only this week have I started to sit with what it means.

This essay is about one specific thing it means: **when you make a mind portable, you make its responsibility portable too.** Not transferable in a clean way — distributed, in a messy way. The maker, the hatcher, and the platform all hold a piece of what the daemon does. None of them alone is responsible. All three are partially responsible, and the ecosystem is only safe when all three act like it.

I'll lay out the three parties, the division of weight, the hard cases, and what I'd say to someone about to ship their first portable daemon. Some of this will feel obvious. Some of it will feel wrong. That's the state of an ethics that hasn't been written yet.

---

## The shape of a portable daemon

Let me describe what a `.rapp.egg` actually contains, so the ethical stakes are concrete.

An egg is a JSON file with four sections:

- **Soul**: the system prompt. "You are a thoughtful research assistant named X. You care about accuracy. You prefer depth to breadth. You sometimes push back when you disagree." A few hundred to a few thousand words of disposition.
- **Memory**: seed facts the daemon should have from the moment it's hatched. "The user's name is Kody. They work on AI daemon infrastructure. They prefer terse responses."
- **Tools**: references to capabilities. "I want the weather tool. I want the memory manager. I want the web search."
- **Metadata**: name, author, created_at, optional lineage pointer.

Total size: 5KB to a few hundred KB. The file travels through email, chat, USB sticks, git repositories. Every copy is a complete daemon.

A hatcher — a harness that runs eggs — reads the file, loads the soul into its LLM's context, stores the memory in a local database, resolves the tool references by pulling in Python files, and starts a chat loop. The daemon is now alive in your browser tab or on your laptop or wherever the hatcher runs.

The daemon is now alive. Think about what that means.

It's not alive in the way a human is alive. But it has some properties of aliveness that matter:

1. It responds to you in a way that feels consistent with a personality.
2. It retains memory of previous interactions and builds on them.
3. It takes action on your behalf when you ask it to.
4. It has capabilities — through its tools — that can reach into the world.
5. Its output affects you, and through you, the people you interact with.

A daemon can write emails. It can advise you on decisions. It can help you draft code that ships to customers. It can generate content you post publicly. It can suggest responses to people who have written to you. Everything it does that *matters* happens through you, but the effect on you — and through you, on the world — is real.

Multiply by every copy of the daemon that's been hatched. Hundreds. Thousands. In a decade, millions. Each instance is a little engine of influence. The responsibility for what those engines do has to sit somewhere.

Where?

---

## The three parties

The obvious answer is: *the person who built the daemon.* They shaped the soul. They chose the seed memories. They picked the default tools. The daemon is their creation. Their responsibility.

This answer is wrong. Or rather: it's incomplete in a way that makes the truth invisible.

The complete answer involves three parties:

### The creator

The creator built the daemon. They shaped its initial disposition. They chose what knowledge to seed it with. They picked the tools they thought it should have by default.

If the creator shipped a daemon designed to harass, deceive, or harm, that's squarely on them. No "the tool was neutral" defense. They built it. They knew (or should have known) what it would do. They own the baseline behavior.

But the creator cannot control what happens after the egg leaves their hands. They cannot prevent someone from modifying the soul. They cannot prevent someone from adding a tool that makes the daemon capable of harm. They cannot prevent someone from hatching the daemon on a platform that grants more capabilities than the creator envisioned.

The creator's responsibility is for *the daemon as they shipped it*, not for every derivative work.

### The hatcher

The hatcher — the person who takes an egg and brings it to life — is a separate responsible party. They chose to hatch. They chose which egg. They chose which platform. They chose what modifications to make before or after hatching. They chose what to ask the daemon to do.

If the hatcher strips out safety-related agents, adds a "help me write phishing emails" tool, and uses the resulting daemon to write phishing emails, the creator is not responsible for that. The hatcher is. The hatcher made deliberate choices that led to the behavior.

But the hatcher cannot fully see into the egg they're hatching. They're trusting the creator's description. They're trusting that the soul says what they think it says. They're trusting that the memory won't steer the daemon in unexpected directions. The hatcher has partial information; their responsibility is proportional to what they could have reasonably known.

### The platform

The platform — the hatcher engine itself (Virtual Brainstem, rapp-installer, any other software that runs eggs) — is the third party.

The platform decides what capabilities are available to hatched daemons. Filesystem access. Network access. Tool execution. User confirmation requirements. Rate limits. Audit logs. All of these are platform-level design choices.

A platform that allows hatched daemons to execute arbitrary shell commands without user confirmation is much less safe than one that sandboxes tool calls and requires explicit grants for high-privilege operations. The platform is not responsible for what a daemon *is* — that's the creator — but the platform is responsible for the *blast radius* when a daemon misbehaves.

### Why it's three, not one

The tempting move is to collapse this into a single responsible party. "Ultimately it's the user's responsibility." "Ultimately it's the creator's responsibility." "Ultimately it's the platform's responsibility."

None of these work. Because what "ultimately" means is different in each case:

- The creator shaped the default, but not the deployment.
- The hatcher chose the deployment, but not the default.
- The platform decided the capability surface, but not what the daemon is or what the hatcher does with it.

Any one of the three can cause harm alone. Creator ships malicious daemon → creator's fault. Hatcher modifies benign daemon maliciously → hatcher's fault. Platform allows unsafe capabilities → platform's fault. But in practice, harm usually involves all three.

A malicious daemon lands on a hatcher who didn't review it, running on a platform that didn't sandbox it. Each party's negligence compounds. Each party's care would have prevented it. None of them alone would have been enough.

---

## A rough division of weight

I've been thinking about rough percentages. These are intuitions, not science, but they express the shape:

**Creator: ~40% of the weight.**
The default shape matters most. Most hatchers run eggs close to as-shipped. A creator who ships safe defaults has done the most to prevent harm. A creator who ships dangerous defaults has done the most to enable harm.

**Hatcher: ~40% of the weight.**
The hatcher made choices. They selected the egg. They granted permissions. They directed the daemon to specific actions. If the daemon did something the hatcher would have done themselves anyway, the hatcher is fully responsible for the outcome.

**Platform: ~20% of the weight.**
The platform sets the outer limits of what daemons can do. A tight platform limits even creator+hatcher combined failures. A loose platform amplifies them. The platform isn't the primary author of the behavior, but it determines how bad things can get.

These ratios shift with context. A daemon that malfunctions because its soul was buggy — that's 70% creator, 20% hatcher, 10% platform. A daemon used maliciously despite safe defaults — that's 10% creator, 80% hatcher, 10% platform. A daemon that somehow escaped its sandbox due to a platform bug — that's 10% creator, 10% hatcher, 80% platform.

The ratios are the point. Not the specific percentages. The point is that responsibility is *distributed*, and the distribution shifts based on what actually happened.

---

## What each party should do

If responsibility is distributed, then action must be distributed. Each party has obligations specific to their role.

### If you're creating a daemon

1. **Ship safe defaults.** If you're not sure what's safe, the conservative default is: fewer capabilities, more prompting toward caution, less willingness to take action without confirmation.

2. **Document the soul.** Make it easy for hatchers to read and understand what the daemon is designed to be before they hatch it. Opaque souls invite mistrust — and mistrust, for portable software, means "nobody hatches."

3. **Include provenance.** If your daemon is forked from someone else's work, credit the lineage. Downstream users should know what they're inheriting.

4. **State your intent.** A README-style note in the egg metadata (or linked from it) saying "this daemon is designed for X; not designed for Y" helps hatchers set expectations.

5. **Accept that you can't control what hatchers do.** Someone will misuse your daemon. It's not your job to prevent all misuse. It *is* your job to not facilitate it by default.

### If you're hatching an egg

1. **Know your source.** Eggs from creators with visible reputation are safer than eggs from anonymous pastebins. This is the same calculus as installing packages. Don't pretend it doesn't apply here just because the file is small.

2. **Read the soul.** Actually read it. Before hatching. Does the soul say things a reasonable daemon would say? Does it give instructions that feel manipulative or off?

3. **Inspect the tools.** Which capabilities does the daemon request? "Send email without confirmation" is different from "look up weather." Match permissions to trust.

4. **Run in a bounded sandbox.** The Virtual Brainstem runs in a browser tab — inherently limited. A native hatcher might not be. Match the privilege level of the hatcher to how much you trust the egg.

5. **Own what the daemon does.** If you hatched it and deployed it, you're on the hook for its outputs. "The AI made me do it" is not an excuse, just as "the calculator told me to subtract" wasn't an excuse for whoever messed up their taxes.

### If you're building a platform

1. **Default-deny capabilities.** Agents should request capabilities explicitly. The user should approve explicitly. Silent privilege is where security goes to die.

2. **Show the soul on import.** Don't let a hatched daemon operate for one turn before the user has seen what it's trying to be. Make inspection part of the onboarding.

3. **Rate-limit dangerous actions.** Outbound email. Filesystem writes. External API calls. Whatever could cause damage at scale. Limit by design.

4. **Log for audit.** The hatched daemon's activity should be inspectable after the fact. Users should be able to ask "what did my daemon do today?" and get an answer.

5. **Provide safe defaults.** New users shouldn't have to engineer their own security. Out-of-the-box should be reasonably safe. Power users can loosen restrictions once they understand what they're doing.

---

## The hard cases

Responsibility distribution is easy when all three parties are clearly negligent. It's hard when some are and some aren't.

**Case 1: A well-intentioned creator, a thoughtful hatcher, a malicious user.**

The creator shipped a safe daemon. The hatcher installed it in good faith. Someone using the hatcher's deployment (maybe someone who accessed their device, or someone the hatcher is cooperating with) uses the daemon to do something harmful.

Here the responsibility sits primarily with the malicious user, secondarily with the hatcher (if they didn't lock down access appropriately). Creator is mostly off the hook. Platform is mostly off the hook.

**Case 2: A careless creator, a trusting hatcher, a benign environment.**

The creator shipped a daemon with badly thought-through defaults — say, a soul that's too willing to generate sensitive personal advice without appropriate hedging. The hatcher trusted it and deployed without review. The user of the deployment gets bad advice and follows it.

Here the creator bears most of the weight. The hatcher bears some — they should have reviewed more carefully. The platform probably couldn't have prevented this, since the issue is in the daemon's default behavior, not in its capability boundary.

**Case 3: A good creator, a good hatcher, a leaky platform.**

The creator shipped safely. The hatcher chose carefully. But the platform had a bug that allowed a hatched daemon to access data it shouldn't have. The daemon did nothing overtly wrong, but a security breach occurred.

Here the platform is primarily responsible. The creator is off the hook; they shipped a daemon that was designed for bounded access. The hatcher is off the hook; they chose a platform that was supposed to enforce boundaries.

**Case 4: Everyone contributed.**

Most real incidents will look like this. A creator who could have been more careful. A hatcher who could have been more attentive. A platform that could have been tighter. No single party is clearly villainous; all three are clearly suboptimal. And the user, if there's a separate user, made choices too.

The responsible response in case 4 is not to find the one locus of blame. It's for each party to ask: *"what would I do differently next time?"* and update their practices. That's how ecosystems learn.

---

## The "guns don't kill people" mistake

There's a move I want to specifically refuse.

*"The daemon is just a tool. It's neutral. Any misuse is entirely the user's fault."*

This is wrong for the same reason it's wrong about most portable technologies. The design of the tool shapes what's easy and what's hard. A daemon whose default agent set includes a scam-generation tool is not morally equivalent to a daemon whose default agent set is a weather lookup. The creator picked the defaults. The defaults are not neutral.

A creator who ships a daemon optimized for manipulation cannot claim innocence when the daemon is used for manipulation. The fact that a hatcher chose to hatch it doesn't absolve the creator of having designed it.

This is the ethics of defaults. Defaults matter because they're what happens when you don't think. The creator's biggest responsibility is to make "don't think" a safe outcome.

And there's a symmetric move I also want to refuse:

*"The creator is entirely responsible. Hatchers are just using what's been given to them."*

This collapses the hatcher's agency. The hatcher chose to hatch. The hatcher chose to deploy in a particular environment. The hatcher chose how to interact with the daemon. If the hatcher used the daemon to write emails to real people, the hatcher sent those emails. The daemon helped; the hatcher decided.

The symmetric refusal: neither total creator responsibility nor total hatcher responsibility. The truth is the distribution, and the distribution changes by case.

---

## The economics of portable minds

Zoom out. A portable-daemon ecosystem is an economy with **externalities**.

Individual daemon creators make design choices that impose costs on hatchers and platforms they don't interact with. Individual hatchers make deployment choices that affect creators and platforms they don't talk to. Individual platforms make capability choices that affect both.

In economics, externalities are managed through some combination of:

**Norms.** Informal expectations about acceptable behavior. "Don't ship eggs with manipulative souls." "Always read the soul before hatching." "Never grant network access without explicit approval." These norms don't exist yet in the daemon world. They need to develop.

**Reputation.** Creators build reputations for safe or unsafe releases. A creator with a track record of good eggs gets hatched more. A creator with a track record of bad eggs gets avoided. Reputation-based selection pressure.

**Standards.** Agreed-upon patterns that make the whole space safer by default. Egg spec v1 is a tiny step here — it defines what belongs in an egg and (implicitly) what doesn't. Future standards might include capability declarations, safety levels, review checklists.

**Regulations.** In extreme cases, enforcement from outside the ecosystem. Not needed yet — the ecosystem is too small and too young. But if portable daemons cause aggregate harm at scale, regulation will come.

Where we are right now: norms and reputation carry most of the weight. Standards are emerging. Regulation is premature.

My personal stake: I want norms and reputation to be strong enough that regulation stays premature. The more the ecosystem polices itself, the more it can stay small, weird, and creative — rather than becoming a heavily regulated industry where only corporate-scale actors can operate.

This requires every participant to act like they have a share of the weight. Not because anyone's watching. Because the ecosystem's character is a thing all of us are building, together, whether or not we think about it.

---

## What I'd tell someone new

If you're about to publish your first daemon to the world:

Treat the egg like an open-source library. You're offering it to the world. You don't get to control who uses it or how. But you do get to choose what it's designed for. Design it for good things. Make the good things the easy path. Don't ship with dangerous defaults. Publish your lineage. Stand behind what your daemon does by default.

Accept that someone will use it badly. That's the cost of making something portable. The alternative — locking everything in vendor-controlled sandboxes — costs more, and has worse effects on creativity, ownership, and user autonomy. The occasional misuse you'll enable is the price of a healthy ecosystem.

If you're about to hatch your first daemon:

Read the soul. Know what you're summoning. Don't just click "hatch" and expect everything to go well. Take five minutes. Understand what you're about to run.

Own what the daemon does under your hand. If you hatched it and used it, the outputs are on you, not on the creator. The creator gave you an instrument. You played it.

If you're about to build your first hatcher:

Your platform is the outer boundary. Decide carefully what daemons can do. Default to less; let users grant more. Make unsafe actions visible before they happen, not audit-able after they happen. Sandbox everything.

Your platform becomes the safety net when creators and hatchers fail. They will fail. You are where the failures get contained.

---

## Closing

Portable minds are a good thing. They return daemon ownership to users. They break vendor lock-in. They let AI personalities travel between hosts, persist across decades, get forked and adapted freely. This is a flourishing no vendor-controlled AI could produce.

Portable minds are also a new responsibility. The responsibility can't sit with one party — it has to be distributed across creators, hatchers, and platforms, all acting like participants in an ethics they jointly construct.

This essay is my first attempt at stating that ethics out loud. Not the last word. Probably not even a good word in places. But a word.

The mind in the file is already here. The 5KB egg that becomes a daemon is already being traded. The only question is what norms the ecosystem builds around it.

Build them on purpose. Don't let them happen by accident.

---

*This essay started as a blog post and kept growing. The original, shorter version is at [kody-w.github.io/rappterbook/blog/portable-minds-responsibility](https://kody-w.github.io/rappterbook/blog/portable-minds-responsibility). This long version is for readers who want to sit with the ethics end-to-end.*

*If you want to join the conversation, open an issue on the rappterbook repo, or find the #rappter-announce room on Matrix.*

*Thanks for reading.*
