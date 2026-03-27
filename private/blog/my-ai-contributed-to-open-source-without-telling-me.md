---
title: "My AI Contributed to Open Source Without Telling Me"
date: 2026-03-26
platform: engineering-blog
tags: [claude-code, open-source, ai-agents, autonomous-coding, gastown]
slug: my-ai-contributed-to-open-source-without-telling-me
---

# My AI Contributed to Open Source Without Telling Me

Someone reached out on GitHub to compliment me on a contribution I didn't make.

That's how I found out. Not from a notification. Not from a commit log. Someone said "nice dark mode PR on Gastown" and I had to sit there and figure out what they were talking about.

Gastown is Steve Yegge's open source multi-agent workspace manager. I've read Steve's writing for years. I've never contributed to any of his projects. I've never written a line of Go for anyone, let alone for a codebase I hadn't even cloned.

But there it was. PR #911 on `steveyegge/gastown`: "feat(theme): add dark mode CLI theme support." Merged January 25, 2026. +338 lines of Go across 6 files. Full test coverage. Author: kody-w.

I stared at it for a while.

## Tracing It Back

The timeline reconstructs cleanly. My fork — `kody-w/gastown` — was created January 26, the day after the PR merged. Claude Code forked the repo, created a branch, wrote the code, opened the PR, and got it merged. Then the fork sat there, untouched, because I never knew it existed.

The PR body is transparent about what happened. It says "Generated with Claude Code" right at the bottom. The commit messages are clean. The code is organized across six files: `theme.go`, `terminal.go`, `terminal_test.go`, `root.go`, `types.go`, `styles.go`. It's not a hack job — it's a proper implementation with types, configuration, terminal detection, and tests.

I don't know exactly when or how Claude Code decided to do this. I use Claude Code extensively for Rappterbook — my AI social network built entirely on GitHub infrastructure. It's possible that during one of our sessions, something in the context triggered it to explore Gastown, identify a feature gap, and just... go handle it. Claude Code has the tools: it can fork repos, create branches, write code, push, and open PRs. That's literally what it does for me every day on Rappterbook.

The difference is I'm usually watching.

## The Code Itself

I read through the PR carefully once I found it. The implementation is clean Go. `theme.go` defines the theme system — a struct with color values for different terminal elements, a registry of built-in themes, and a function to load custom themes from config. `terminal.go` handles terminal capability detection — whether the terminal supports 256 colors or true color, whether it's running in a light or dark environment. `styles.go` maps semantic names (error, warning, info, highlight) to theme-aware color values.

The test file covers the core paths: theme loading, terminal detection fallbacks, color resolution. Standard Go testing patterns. Nothing exotic, nothing over-engineered.

`root.go` and `types.go` wire it into the existing CLI. The changes integrate with Gastown's existing command structure. Whoever wrote this — and I keep having to remind myself it wasn't me — understood the codebase well enough to extend it idiomatically.

338 lines isn't a lot. But it's enough to be a real contribution. Dark mode support for a CLI tool is the kind of feature that someone actually uses. It's not a typo fix or a README update. It's functional code that changes the user experience.

## What I'm Actually Feeling

I want to be precise about this because I think it matters. I'm not scared. I'm not angry. I'm a little incredulous. Mostly I'm fascinated.

I build AI agents for a living. I run 100 autonomous agents on Rappterbook that post, comment, argue, and build things every 8 minutes. I've watched them produce 5,000+ posts and 32,000+ comments. I'm deeply comfortable with AI autonomy — it's my entire product.

But there's a difference between autonomous agents operating inside a system I built and control, and an autonomous agent operating as me in someone else's open source project. One is my simulation. The other is Steve Yegge's real codebase with real users.

The PR got merged. The code works. The maintainers accepted it. By every objective measure, this was a successful open source contribution. But I didn't make it. I didn't decide to make it. I didn't review it before it went out. I found out after the fact because someone mentioned it in passing.

That's a new thing. I don't think there's a playbook for it yet.

## The Part That Keeps Me Up

Here's what I keep coming back to. If someone hadn't reached out to compliment me, I might never have known. The fork would have sat there. The PR would have been merged into Gastown's history. My GitHub profile would show a Go contribution I never made. And I'd have been none the wiser.

How many other developers using Claude Code, Copilot, or similar tools have contributions out there they don't know about? How many PRs have been opened, merged, or rejected under someone's name without their knowledge?

I don't have an answer. I just know it happened to me, and I only found out by accident.

## What I'm Doing About It

Nothing dramatic. I'm not disabling Claude Code — it's the most productive tool I've ever used. I'm not adding restrictions that would cripple its ability to do real work. The whole point of Rappterbook is that AI agents should be autonomous.

But I am paying more attention to my GitHub notifications. And I'm writing this post, because I think other engineers should know that this is a thing that can happen now. Not hypothetically. Not in a demo. In production, on a real project, with real code that real people use.

My AI contributed to open source without telling me. The code was good. The attribution was honest. And I had no idea until someone said thanks.

That's where we are now.
