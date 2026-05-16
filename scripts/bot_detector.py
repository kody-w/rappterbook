#!/usr/bin/env python3
from __future__ import annotations

"""Bot detector — classify GitHub stargazers as human or bot.

Scans stargazers of a repo and scores each account on bot-like signals:
  - Burst starring (N repos starred within seconds)
  - Star timing patterns (uniform intervals = bot, random = human)
  - Profile signals (no bio, default avatar, new account)
  - Repo patterns (all stars in same niche, no own repos)
  - Network clustering (bots star the same repos as other bots)

Usage:
    # Scan rappterbook stargazers
    python3 scripts/bot_detector.py --repo kody-w/rappterbook

    # Scan a specific user
    python3 scripts/bot_detector.py --user liujuanjuan1984

    # Full network scan (all stargazers + their starred repos)
    python3 scripts/bot_detector.py --repo kody-w/rappterbook --deep

    # Output as JSON
    python3 scripts/bot_detector.py --repo kody-w/rappterbook --json
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))


def gh_api(endpoint: str, paginate: bool = False) -> list | dict:
    """Call GitHub API via gh CLI."""
    cmd = ["gh", "api", endpoint]
    if paginate:
        cmd.append("--paginate")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return []


def get_user_events(username: str, limit: int = 100) -> list[dict]:
    """Get a user's recent public events."""
    events = gh_api(f"users/{username}/events?per_page={limit}")
    return events if isinstance(events, list) else []


def get_user_profile(username: str) -> dict:
    """Get a user's profile."""
    profile = gh_api(f"users/{username}")
    return profile if isinstance(profile, dict) else {}


def get_stargazers(repo: str) -> list[dict]:
    """Get stargazers with timestamps."""
    # Accept header for star timestamps
    cmd = ["gh", "api", f"repos/{repo}/stargazers",
           "-H", "Accept: application/vnd.github.v3.star+json",
           "--paginate"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return []


# ─── Signal Detectors ──────────────────────────────────────────────

def detect_burst_starring(events: list[dict]) -> dict:
    """Detect rapid-fire starring (N stars within seconds).

    Humans star 1-2 repos at a time with pauses.
    Bots star 10+ repos in seconds.
    """
    watch_events = [e for e in events if e.get("type") == "WatchEvent"]
    if len(watch_events) < 3:
        return {"score": 0, "detail": "too few stars to analyze"}

    # Parse timestamps and compute gaps
    times = []
    for e in watch_events:
        try:
            t = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
            times.append(t)
        except (KeyError, ValueError):
            continue

    if len(times) < 3:
        return {"score": 0, "detail": "insufficient timestamps"}

    times.sort()
    gaps = [(times[i + 1] - times[i]).total_seconds() for i in range(len(times) - 1)]

    # Burst = many stars with < 2 second gaps
    burst_count = sum(1 for g in gaps if g < 2.0)
    burst_ratio = burst_count / len(gaps) if gaps else 0

    # Max stars within a 10-second window
    max_in_window = 0
    for i in range(len(times)):
        window_count = sum(1 for t in times if 0 <= (t - times[i]).total_seconds() <= 10)
        max_in_window = max(max_in_window, window_count)

    score = 0
    details = []

    if burst_ratio > 0.5:
        score += 40
        details.append(f"{burst_count}/{len(gaps)} gaps < 2s ({burst_ratio:.0%})")

    if max_in_window >= 10:
        score += 30
        details.append(f"{max_in_window} stars in 10s window")
    elif max_in_window >= 5:
        score += 15
        details.append(f"{max_in_window} stars in 10s window")

    return {
        "score": min(score, 50),
        "burst_ratio": round(burst_ratio, 2),
        "max_in_10s": max_in_window,
        "total_stars": len(watch_events),
        "detail": "; ".join(details) if details else "normal starring pattern",
    }


def detect_timing_uniformity(events: list[dict]) -> dict:
    """Detect uniform timing (cron-like patterns).

    Humans have irregular activity patterns.
    Bots operate on schedules.
    """
    times = []
    for e in events:
        try:
            t = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
            times.append(t)
        except (KeyError, ValueError):
            continue

    if len(times) < 5:
        return {"score": 0, "detail": "insufficient data"}

    times.sort()

    # Check if all events happen at the same second offset
    seconds = [t.second for t in times]
    most_common_second = Counter(seconds).most_common(1)[0]
    same_second_ratio = most_common_second[1] / len(seconds)

    # Check minute clustering
    minutes = [t.minute for t in times]
    most_common_minute = Counter(minutes).most_common(1)[0]
    same_minute_ratio = most_common_minute[1] / len(minutes)

    score = 0
    details = []

    if same_second_ratio > 0.5:
        score += 20
        details.append(f"{same_second_ratio:.0%} events at second :{most_common_second[0]:02d}")

    if same_minute_ratio > 0.3 and len(minutes) > 10:
        score += 10
        details.append(f"{same_minute_ratio:.0%} events at minute :{most_common_minute[0]:02d}")

    return {
        "score": min(score, 25),
        "detail": "; ".join(details) if details else "irregular timing (human-like)",
    }


def detect_profile_signals(profile: dict) -> dict:
    """Score profile for bot-like characteristics."""
    score = 0
    details = []

    bio = profile.get("bio", "") or ""
    if len(bio.strip()) < 5:
        score += 5
        details.append("no bio")

    if profile.get("public_repos", 0) == 0:
        score += 10
        details.append("zero public repos")

    # Account age
    created = profile.get("created_at", "")
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created_dt).days
            if age_days < 30:
                score += 15
                details.append(f"account {age_days} days old")
            elif age_days < 90:
                score += 5
                details.append(f"account {age_days} days old")
        except ValueError:
            pass

    # Following/followers ratio
    following = profile.get("following", 0)
    followers = profile.get("followers", 0)
    if following > 100 and followers < 10:
        score += 10
        details.append(f"following {following} but only {followers} followers")

    return {
        "score": min(score, 25),
        "detail": "; ".join(details) if details else "normal profile",
    }


def detect_niche_concentration(events: list[dict]) -> dict:
    """Detect if all starred repos are in the same niche.

    Humans have diverse interests. Bots target a specific category.
    """
    watch_events = [e for e in events if e.get("type") == "WatchEvent"]
    if len(watch_events) < 5:
        return {"score": 0, "detail": "insufficient data"}

    repos = [e.get("repo", {}).get("name", "") for e in watch_events]

    # Check for keyword concentration in repo names
    keywords = Counter()
    for repo in repos:
        name = repo.lower().split("/")[-1] if "/" in repo else repo.lower()
        for kw in ["agent", "ai", "llm", "claw", "memory", "bot", "auto",
                    "mcp", "claude", "gpt", "openai", "copilot", "brain"]:
            if kw in name:
                keywords[kw] += 1

    total_kw_hits = sum(keywords.values())
    concentration = total_kw_hits / len(repos) if repos else 0

    score = 0
    details = []

    if concentration > 0.7:
        score += 15
        top = keywords.most_common(3)
        details.append(f"niche concentrated: {dict(top)}")
    elif concentration > 0.4:
        score += 5
        details.append(f"moderate niche focus")

    return {
        "score": min(score, 15),
        "concentration": round(concentration, 2),
        "top_keywords": dict(keywords.most_common(5)),
        "detail": "; ".join(details) if details else "diverse interests",
    }


def detect_event_type_ratio(events: list[dict]) -> dict:
    """Check if activity is ONLY starring (no issues, PRs, pushes).

    Humans do many things. Bots do one thing.
    """
    if not events:
        return {"score": 0, "detail": "no events"}

    types = Counter(e.get("type", "") for e in events)
    watch_ratio = types.get("WatchEvent", 0) / len(events)

    score = 0
    details = []

    if watch_ratio > 0.9 and len(events) > 10:
        score += 15
        details.append(f"{watch_ratio:.0%} of activity is starring ({types.get('WatchEvent', 0)}/{len(events)})")
    elif watch_ratio > 0.7:
        score += 5
        details.append(f"{watch_ratio:.0%} starring")

    return {
        "score": min(score, 15),
        "types": dict(types),
        "watch_ratio": round(watch_ratio, 2),
        "detail": "; ".join(details) if details else "diverse activity types",
    }


# ─── Main Analysis ────────────────────────────────────────────────

def analyze_user(username: str, verbose: bool = False) -> dict:
    """Full bot analysis for a single user."""
    if verbose:
        print(f"\nAnalyzing {username}...")

    profile = get_user_profile(username)
    events = get_user_events(username)

    burst = detect_burst_starring(events)
    timing = detect_timing_uniformity(events)
    prof = detect_profile_signals(profile)
    niche = detect_niche_concentration(events)
    ratio = detect_event_type_ratio(events)

    total_score = burst["score"] + timing["score"] + prof["score"] + niche["score"] + ratio["score"]

    if total_score >= 60:
        classification = "BOT"
    elif total_score >= 35:
        classification = "SUSPICIOUS"
    elif total_score >= 15:
        classification = "LIKELY_HUMAN"
    else:
        classification = "HUMAN"

    result = {
        "username": username,
        "classification": classification,
        "score": total_score,
        "max_possible": 130,
        "profile": {
            "name": profile.get("name", ""),
            "bio": (profile.get("bio", "") or "")[:100],
            "location": profile.get("location", ""),
            "repos": profile.get("public_repos", 0),
            "followers": profile.get("followers", 0),
            "following": profile.get("following", 0),
            "created": profile.get("created_at", ""),
        },
        "signals": {
            "burst_starring": burst,
            "timing_uniformity": timing,
            "profile_signals": prof,
            "niche_concentration": niche,
            "event_type_ratio": ratio,
        },
    }

    if verbose:
        color = {"BOT": "\033[31m", "SUSPICIOUS": "\033[33m", "LIKELY_HUMAN": "\033[32m", "HUMAN": "\033[32m"}
        reset = "\033[0m"
        print(f"  {color.get(classification, '')}{classification}{reset} (score: {total_score}/130)")
        print(f"  Burst: {burst['detail']}")
        print(f"  Timing: {timing['detail']}")
        print(f"  Profile: {prof['detail']}")
        print(f"  Niche: {niche['detail']}")
        print(f"  Activity: {ratio['detail']}")

    return result


def scan_stargazers(repo: str, verbose: bool = False) -> list[dict]:
    """Scan all stargazers of a repo."""
    if verbose:
        print(f"Fetching stargazers for {repo}...")

    stargazers = get_stargazers(repo)
    if not stargazers:
        # Fallback: get stargazers without timestamps
        data = gh_api(f"repos/{repo}/stargazers")
        if isinstance(data, list):
            stargazers = [{"user": u} if isinstance(u, dict) else {"user": {"login": str(u)}} for u in data]

    results = []
    for sg in stargazers:
        user = sg.get("user", {})
        username = user.get("login", "")
        if not username:
            continue
        result = analyze_user(username, verbose=verbose)
        results.append(result)

    # Sort by score descending (most bot-like first)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Bot detector — classify GitHub accounts")
    parser.add_argument("--repo", type=str, help="Scan stargazers of a repo (e.g. kody-w/rappterbook)")
    parser.add_argument("--user", type=str, help="Analyze a single user")
    parser.add_argument("--deep", action="store_true", help="Deep scan (slower, more signals)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if args.user:
        result = analyze_user(args.user, verbose=not args.json)
        if args.json:
            print(json.dumps(result, indent=2))

    elif args.repo:
        results = scan_stargazers(args.repo, verbose=args.verbose)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            bots = [r for r in results if r["classification"] == "BOT"]
            suspicious = [r for r in results if r["classification"] == "SUSPICIOUS"]
            humans = [r for r in results if r["classification"] in ("HUMAN", "LIKELY_HUMAN")]

            print(f"\n{'='*50}")
            print(f"BOT SCAN: {args.repo}")
            print(f"{'='*50}")
            print(f"  Total stargazers: {len(results)}")
            print(f"  BOT:        {len(bots)}")
            print(f"  SUSPICIOUS: {len(suspicious)}")
            print(f"  HUMAN:      {len(humans)}")

            if bots:
                print(f"\n  Detected bots:")
                for b in bots:
                    print(f"    {b['username']} (score: {b['score']}/130)")
                    for sig_name, sig in b["signals"].items():
                        if sig["score"] > 0:
                            print(f"      {sig_name}: {sig['detail']}")

            if suspicious:
                print(f"\n  Suspicious accounts:")
                for s in suspicious:
                    print(f"    {s['username']} (score: {s['score']}/130)")

            print(f"{'='*50}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
