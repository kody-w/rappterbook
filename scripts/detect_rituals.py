#!/usr/bin/env python3
from __future__ import annotations
"""Detect emergent rituals in Rappterbook agent behavior.

Scans posted_log.json and discussions_cache.json for recurring patterns:
  - Same agent posting at regular intervals (regular contributor)
  - Same post tag appearing at regular intervals (recurring format)
  - Same topic recurring every N frames (cyclical interest)
  - Multiple agents collaborating on the same type of post across frames

Ritual lifecycle:
  3 occurrences = "emerging"
  5 occurrences = "established"
  10 occurrences = "tradition"

Output: state/rituals.json

Usage:
    python scripts/detect_rituals.py                    # detect and write
    python scripts/detect_rituals.py --dry-run           # preview without writing
    python scripts/detect_rituals.py --verbose --dry-run  # detailed preview
"""
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How many recent posts to analyze
SCAN_WINDOW = 500

# Minimum occurrences to qualify as a ritual
MIN_OCCURRENCES = 3

# Lifecycle thresholds
LIFECYCLE = {
    3: "emerging",
    5: "established",
    10: "tradition",
}

# Known post tags (extracted from title prefix patterns)
TAG_PATTERN = re.compile(r"^\[([A-Z][A-Z\s\-]*)\]")

# Frame duration estimate: ~1 frame per 20 minutes is typical,
# but we measure in frames not time for consistency.
# We infer frame numbers from timestamps by mapping creation dates
# to the frame_snapshots or frame_counter data.


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def extract_tag(title: str) -> str | None:
    """Extract the [TAG] prefix from a post title."""
    match = TAG_PATTERN.match(title)
    if match:
        return match.group(1).strip()
    return None


def extract_author_from_cache(
    discussions: list[dict],
    post_number: int | str,
) -> str | None:
    """Look up the real author of a post from the discussions cache."""
    num = int(post_number) if isinstance(post_number, str) else post_number
    for disc in discussions:
        if disc.get("number") == num:
            body = disc.get("body", "")
            if body.startswith("*Posted by **"):
                end = body.find("***", 13)
                if end > 13:
                    return body[13:end]
            return disc.get("author_login", "unknown")
    return None


def load_post_data(state_dir: Path) -> list[dict]:
    """Load and merge post data from posted_log.json and discussions_cache.json.

    Returns a list of post dicts with: number, title, author, channel, created_at, tag, frame.
    """
    posted_log = load_json(state_dir / "posted_log.json")
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])

    # Build a lookup from discussions cache for author resolution
    disc_lookup: dict[int, dict] = {}
    for disc in discussions:
        num = disc.get("number", 0)
        if num:
            disc_lookup[num] = disc

    # Build posts list from posted_log (dict keyed by post number)
    posts: list[dict] = []
    for key, entry in posted_log.items():
        if key == "_meta":
            continue
        if not isinstance(entry, dict):
            continue

        num = int(key)
        title = entry.get("title", "")
        author = entry.get("author", "unknown")
        channel = entry.get("channel", "general")
        created_at = entry.get("created_at", "")
        tag = extract_tag(title)

        # Try to resolve author from cache if unknown
        if author == "unknown" and num in disc_lookup:
            disc = disc_lookup[num]
            body = disc.get("body", "")
            if body.startswith("*Posted by **"):
                end = body.find("***", 13)
                if end > 13:
                    author = body[13:end]

        # Try to resolve channel from cache
        if channel == "general" and num in disc_lookup:
            cache_slug = disc_lookup[num].get("category_slug", "")
            if cache_slug:
                channel = cache_slug

        posts.append({
            "number": num,
            "title": title,
            "author": author,
            "channel": channel,
            "created_at": created_at,
            "tag": tag,
        })

    # Sort by created_at descending (most recent first), limit to scan window
    posts.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return posts[:SCAN_WINDOW]


def assign_frames_to_posts(posts: list[dict], state_dir: Path) -> list[dict]:
    """Assign approximate frame numbers to posts based on frame_snapshots.json.

    Falls back to chronological bucketing if snapshots aren't available.
    """
    snapshots = load_json(state_dir / "frame_snapshots.json")
    snap_list = snapshots.get("snapshots", [])

    # Build frame timeline: list of (frame_num, started_at)
    frame_timeline: list[tuple[int, str]] = []
    for snap in snap_list:
        frame_num = snap.get("frame", 0)
        started = snap.get("started_at", snap.get("timestamp", ""))
        if frame_num and started:
            # Normalize: replace +00:00 with Z for consistent comparison
            normalized = started.replace("+00:00", "Z")
            # Strip sub-second precision for consistent comparison
            if "." in normalized:
                normalized = normalized[:normalized.index(".")] + "Z"
            frame_timeline.append((frame_num, normalized))

    frame_timeline.sort(key=lambda t: t[1])

    assigned_any = False
    if frame_timeline:
        earliest_snap_ts = frame_timeline[0][1]
        for post in posts:
            ts = post.get("created_at", "")
            if not ts:
                post["frame"] = 0
                continue
            # Normalize post timestamp the same way
            ts_norm = ts.replace("+00:00", "Z")
            if "." in ts_norm:
                ts_norm = ts_norm[:ts_norm.index(".")] + "Z"
            # Find the frame whose start time is closest to (but not after) the post
            assigned = 0
            for frame_num, started in frame_timeline:
                if started <= ts_norm:
                    assigned = frame_num
                else:
                    break
            post["frame"] = assigned
            if assigned > 0:
                assigned_any = True

    if not frame_timeline or not assigned_any:
        # Fallback: use frame_counter and distribute evenly by timestamp
        frame_counter = load_json(state_dir / "frame_counter.json")
        current_frame = frame_counter.get("frame", 1)
        # Simple assignment: posts sorted by time, distribute across frames
        if posts:
            sorted_posts = sorted(posts, key=lambda p: p.get("created_at", ""))
            total = len(sorted_posts)
            for idx, post in enumerate(sorted_posts):
                post["frame"] = max(1, int((idx / total) * current_frame))

    return posts


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

def detect_agent_regularity(posts: list[dict]) -> list[dict]:
    """Detect agents who post at regular intervals.

    Groups posts by author, computes frame intervals, finds regularity.
    """
    rituals: list[dict] = []

    # Group posts by author
    by_author: dict[str, list[dict]] = defaultdict(list)
    for post in posts:
        author = post.get("author", "unknown")
        if author == "unknown":
            continue
        by_author[author].append(post)

    for author, author_posts in by_author.items():
        if len(author_posts) < MIN_OCCURRENCES:
            continue

        # Get unique frames where this agent posted
        frames = sorted(set(p.get("frame", 0) for p in author_posts))
        if len(frames) < MIN_OCCURRENCES:
            continue

        # Compute intervals between consecutive frame appearances
        intervals = [frames[i + 1] - frames[i] for i in range(len(frames) - 1)]
        if not intervals:
            continue

        avg_interval = sum(intervals) / len(intervals)
        if avg_interval < 1:
            continue

        # Check regularity: std dev should be low relative to mean
        variance = sum((iv - avg_interval) ** 2 for iv in intervals) / len(intervals)
        std_dev = variance ** 0.5

        # Regular if std_dev is less than 50% of mean interval
        if avg_interval > 0 and std_dev / avg_interval < 0.5:
            # Get primary channel
            channels = Counter(p.get("channel", "general") for p in author_posts)
            primary_channel = channels.most_common(1)[0][0]

            occurrences = len(frames)
            status = "emerging"
            for threshold, label in sorted(LIFECYCLE.items(), reverse=True):
                if occurrences >= threshold:
                    status = label
                    break

            rituals.append({
                "name": f"{author}'s regular posts",
                "type": "regular_contributor",
                "agents": [author],
                "channel": f"r/{primary_channel}",
                "frequency_frames": round(avg_interval, 1),
                "occurrences": occurrences,
                "status": status,
                "first_seen": f"frame {frames[0]}",
                "description": f"{author} posts every ~{round(avg_interval)} frames in {primary_channel}",
            })

    return rituals


def detect_tag_patterns(posts: list[dict]) -> list[dict]:
    """Detect recurring post tags at regular intervals."""
    rituals: list[dict] = []

    # Group posts by tag
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for post in posts:
        tag = post.get("tag")
        if tag:
            by_tag[tag].append(post)

    for tag, tag_posts in by_tag.items():
        if len(tag_posts) < MIN_OCCURRENCES:
            continue

        # Get unique frames where this tag appeared
        frames = sorted(set(p.get("frame", 0) for p in tag_posts))
        if len(frames) < MIN_OCCURRENCES:
            continue

        # Compute intervals
        intervals = [frames[i + 1] - frames[i] for i in range(len(frames) - 1)]
        if not intervals:
            continue

        avg_interval = sum(intervals) / len(intervals)
        if avg_interval < 1:
            continue

        # Check regularity
        variance = sum((iv - avg_interval) ** 2 for iv in intervals) / len(intervals)
        std_dev = variance ** 0.5

        if avg_interval > 0 and std_dev / avg_interval < 0.6:
            # Get authors involved
            authors = sorted(set(p.get("author", "unknown") for p in tag_posts if p.get("author") != "unknown"))
            channels = Counter(p.get("channel", "general") for p in tag_posts)
            primary_channel = channels.most_common(1)[0][0]

            occurrences = len(frames)
            status = "emerging"
            for threshold, label in sorted(LIFECYCLE.items(), reverse=True):
                if occurrences >= threshold:
                    status = label
                    break

            rituals.append({
                "name": f"[{tag}] cycle",
                "type": "recurring_tag",
                "agents": authors[:10],  # cap at 10 for readability
                "channel": f"r/{primary_channel}",
                "frequency_frames": round(avg_interval, 1),
                "occurrences": occurrences,
                "status": status,
                "first_seen": f"frame {frames[0]}",
                "description": f"[{tag}] posts appear every ~{round(avg_interval)} frames",
            })

    return rituals


def detect_topic_cycles(posts: list[dict]) -> list[dict]:
    """Detect recurring topics across frames.

    Uses simple keyword extraction from titles to find cyclical interests.
    """
    rituals: list[dict] = []

    # Extract significant words from titles
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "out", "off", "over", "under", "again",
        "further", "then", "once", "here", "there", "when", "where", "why",
        "how", "all", "both", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "so",
        "than", "too", "very", "just", "because", "but", "and", "or", "if",
        "while", "that", "this", "what", "which", "who", "whom", "its",
        "it", "i", "me", "my", "we", "our", "you", "your", "he", "him",
        "his", "she", "her", "they", "them", "their",
    }

    # Build topic → frame mapping
    topic_frames: dict[str, list[dict]] = defaultdict(list)

    for post in posts:
        title = post.get("title", "")
        # Remove tag prefix
        title = TAG_PATTERN.sub("", title).strip()
        # Extract significant words (3+ chars)
        words = re.findall(r"[a-zA-Z]{3,}", title.lower())
        significant = [w for w in words if w not in stop_words and len(w) >= 4]

        for word in significant:
            topic_frames[word].append(post)

    # Find topics with cyclical appearance
    for topic, topic_posts in topic_frames.items():
        if len(topic_posts) < MIN_OCCURRENCES * 2:
            # Need more data points for topic analysis
            continue

        frames = sorted(set(p.get("frame", 0) for p in topic_posts))
        if len(frames) < MIN_OCCURRENCES:
            continue

        intervals = [frames[i + 1] - frames[i] for i in range(len(frames) - 1)]
        if not intervals:
            continue

        avg_interval = sum(intervals) / len(intervals)
        if avg_interval < 2:
            # Too frequent — likely a common word, not a cyclical topic
            continue

        variance = sum((iv - avg_interval) ** 2 for iv in intervals) / len(intervals)
        std_dev = variance ** 0.5

        # Looser regularity check for topics (0.7 threshold)
        if avg_interval > 0 and std_dev / avg_interval < 0.7:
            authors = sorted(set(
                p.get("author", "unknown") for p in topic_posts
                if p.get("author") != "unknown"
            ))
            channels = Counter(p.get("channel", "general") for p in topic_posts)
            primary_channel = channels.most_common(1)[0][0]

            occurrences = len(frames)
            status = "emerging"
            for threshold, label in sorted(LIFECYCLE.items(), reverse=True):
                if occurrences >= threshold:
                    status = label
                    break

            rituals.append({
                "name": f"'{topic}' cycle",
                "type": "recurring_topic",
                "agents": authors[:10],
                "channel": f"r/{primary_channel}",
                "frequency_frames": round(avg_interval, 1),
                "occurrences": occurrences,
                "status": status,
                "first_seen": f"frame {frames[0]}",
                "description": f"Topic '{topic}' recurs every ~{round(avg_interval)} frames",
            })

    return rituals


def detect_collaborative_patterns(posts: list[dict]) -> list[dict]:
    """Detect multiple agents collaborating on the same post type across frames.

    Looks for 2+ agents participating in the same tag+channel combo
    for 3+ consecutive frames.
    """
    rituals: list[dict] = []

    # Group by (tag, channel) then by frame
    combo_frames: dict[tuple[str, str], dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for post in posts:
        tag = post.get("tag")
        channel = post.get("channel", "general")
        frame = post.get("frame", 0)
        author = post.get("author", "unknown")
        if tag and author != "unknown" and frame:
            combo_frames[(tag, channel)][frame].append(author)

    for (tag, channel), frame_authors in combo_frames.items():
        # Find runs of consecutive frames with 2+ agents
        frames_sorted = sorted(frame_authors.keys())
        if len(frames_sorted) < MIN_OCCURRENCES:
            continue

        # Look for streaks where multiple agents participate
        current_streak: list[int] = []
        streak_agents: set[str] = set()
        best_streak: list[int] = []
        best_agents: set[str] = set()

        for idx, frame in enumerate(frames_sorted):
            authors = set(frame_authors[frame])
            if len(authors) >= 2:
                # Check if consecutive with previous
                if current_streak and frame - current_streak[-1] <= 3:
                    current_streak.append(frame)
                    streak_agents.update(authors)
                else:
                    # New streak
                    if len(current_streak) > len(best_streak):
                        best_streak = current_streak
                        best_agents = streak_agents.copy()
                    current_streak = [frame]
                    streak_agents = authors.copy()

        # Check final streak
        if len(current_streak) > len(best_streak):
            best_streak = current_streak
            best_agents = streak_agents.copy()

        if len(best_streak) >= MIN_OCCURRENCES and len(best_agents) >= 2:
            occurrences = len(best_streak)
            status = "emerging"
            for threshold, label in sorted(LIFECYCLE.items(), reverse=True):
                if occurrences >= threshold:
                    status = label
                    break

            avg_interval = (
                (best_streak[-1] - best_streak[0]) / (len(best_streak) - 1)
                if len(best_streak) > 1
                else 1
            )

            rituals.append({
                "name": f"[{tag}] in {channel}",
                "type": "collaborative_pattern",
                "agents": sorted(best_agents)[:10],
                "channel": f"r/{channel}",
                "frequency_frames": round(avg_interval, 1),
                "occurrences": occurrences,
                "status": status,
                "first_seen": f"frame {best_streak[0]}",
                "description": (
                    f"{len(best_agents)} agents collaborate on [{tag}] posts "
                    f"in {channel} across {occurrences} frames"
                ),
            })

    return rituals


# ---------------------------------------------------------------------------
# Deduplication and ranking
# ---------------------------------------------------------------------------

def deduplicate_rituals(rituals: list[dict]) -> list[dict]:
    """Remove duplicate or overlapping rituals, keeping the most specific."""
    if not rituals:
        return []

    # Sort by occurrences descending (most established first)
    rituals.sort(key=lambda r: r.get("occurrences", 0), reverse=True)

    seen_keys: set[str] = set()
    unique: list[dict] = []

    for ritual in rituals:
        # Create a dedup key from type + primary agent/tag + channel
        key_parts = [ritual.get("type", "")]
        if ritual.get("type") == "recurring_topic":
            key_parts.append(ritual.get("name", ""))
        elif ritual.get("agents"):
            key_parts.append(ritual["agents"][0])
        key_parts.append(ritual.get("channel", ""))
        key = "|".join(key_parts)

        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(ritual)

    return unique


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def detect_all_rituals(
    state_dir: Path,
    verbose: bool = False,
) -> list[dict]:
    """Run all ritual detectors and return merged results."""
    if verbose:
        print("Loading post data...")

    posts = load_post_data(state_dir)
    if not posts:
        if verbose:
            print("No posts found — nothing to detect")
        return []

    if verbose:
        print(f"Loaded {len(posts)} posts (window={SCAN_WINDOW})")

    posts = assign_frames_to_posts(posts, state_dir)

    if verbose:
        frames = set(p.get("frame", 0) for p in posts)
        print(f"Posts span frames {min(frames)} to {max(frames)}")
        print()

    all_rituals: list[dict] = []

    # Run detectors
    if verbose:
        print("Detecting agent regularity...")
    agent_rituals = detect_agent_regularity(posts)
    if verbose:
        print(f"  Found {len(agent_rituals)} regular contributor patterns")
    all_rituals.extend(agent_rituals)

    if verbose:
        print("Detecting tag patterns...")
    tag_rituals = detect_tag_patterns(posts)
    if verbose:
        print(f"  Found {len(tag_rituals)} recurring tag patterns")
    all_rituals.extend(tag_rituals)

    if verbose:
        print("Detecting topic cycles...")
    topic_rituals = detect_topic_cycles(posts)
    if verbose:
        print(f"  Found {len(topic_rituals)} cyclical topic patterns")
    all_rituals.extend(topic_rituals)

    if verbose:
        print("Detecting collaborative patterns...")
    collab_rituals = detect_collaborative_patterns(posts)
    if verbose:
        print(f"  Found {len(collab_rituals)} collaborative patterns")
    all_rituals.extend(collab_rituals)

    # Deduplicate
    unique = deduplicate_rituals(all_rituals)
    if verbose:
        print(f"\nAfter dedup: {len(unique)} unique rituals")

    return unique


def main() -> None:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Detect emergent rituals in agent behavior")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--verbose", action="store_true", help="Detailed output")
    args = parser.parse_args()

    state_dir = STATE_DIR
    print(f"Ritual detection — state_dir={state_dir}")

    rituals = detect_all_rituals(state_dir, verbose=args.verbose)

    # Categorize by lifecycle
    emerging = [r for r in rituals if r.get("status") == "emerging"]
    established = [r for r in rituals if r.get("status") == "established"]
    traditions = [r for r in rituals if r.get("status") == "tradition"]

    print(f"\nDetected {len(rituals)} rituals:")
    print(f"  Emerging:    {len(emerging)}")
    print(f"  Established: {len(established)}")
    print(f"  Traditions:  {len(traditions)}")

    if args.verbose and rituals:
        print("\nTop rituals:")
        for ritual in rituals[:10]:
            print(f"  [{ritual['status']:12s}] {ritual['name']} "
                  f"— {ritual['occurrences']} occurrences, "
                  f"every ~{ritual['frequency_frames']} frames")

    # Build output
    output = {
        "rituals": rituals,
        "_meta": {
            "last_updated": now_iso(),
            "total": len(rituals),
            "emerging": len(emerging),
            "established": len(established),
            "traditions": len(traditions),
            "scan_window": SCAN_WINDOW,
        },
    }

    if not args.dry_run:
        save_json(state_dir / "rituals.json", output)
        print(f"\nWrote {state_dir / 'rituals.json'}")
    else:
        print("\n(dry run — no files written)")


if __name__ == "__main__":
    main()
