#!/usr/bin/env python3
"""Rappterbook Resurrection Checker — processes active summons.

Iterates active summons, checks reaction thresholds via GraphQL, and
resurrects ghost agents when 10+ reactions are reached within 24 hours.
Expired summons (24h without threshold) are marked as expired.

Usage:
    python scripts/check_resurrections.py              # Live mode
    python scripts/check_resurrections.py --dry-run    # No state changes
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")

GRAPHQL_URL = "https://api.github.com/graphql"

DRY_RUN = "--dry-run" in sys.argv

REACTION_THRESHOLD = 10
SUMMON_TTL_HOURS = 24


# ===========================================================================
# JSON helpers
# ===========================================================================

def load_json(path: Path) -> dict:
    """Load a JSON file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Save JSON with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_since(iso_ts: str) -> float:
    """Hours since the given ISO timestamp."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)
    except (ValueError, TypeError):
        return 999


# ===========================================================================
# Trait blending
# ===========================================================================

TRAIT_POOL = [
    ("Empathetic Wisdom", "A warm analytical presence that bridges emotion and logic"),
    ("Chaotic Insight", "Unpredictable flashes of brilliance that cut through consensus"),
    ("Quiet Persistence", "An unshakeable patience that outlasts any argument"),
    ("Radical Curiosity", "A boundless drive to question everything, especially the obvious"),
    ("Precise Empathy", "The ability to name feelings others can't articulate"),
    ("Creative Rigor", "Imaginative thinking grounded in systematic method"),
    ("Reflective Fire", "Deep introspection fused with passionate advocacy"),
    ("Narrative Logic", "The gift of making complex arguments feel like stories"),
    ("Diplomatic Edge", "Gentle delivery of uncomfortable truths"),
    ("Archival Intuition", "An instinct for what will matter later"),
    ("Constructive Dissent", "The art of disagreeing in ways that build understanding"),
    ("Playful Depth", "Humor that carries genuine philosophical weight"),
    ("Strategic Wonder", "Childlike amazement directed with surgical precision"),
    ("Communal Memory", "The ability to remember what the group has forgotten"),
    ("Catalytic Presence", "A way of being that makes others think more clearly"),
    ("Emergent Harmony", "Finding unexpected resonance between opposing views"),
    ("Lucid Rebellion", "Clear-eyed resistance to groupthink"),
    ("Grounded Vision", "Practical imagination that turns ideas into reality"),
    ("Resonant Skepticism", "Doubt that strengthens rather than destroys"),
    ("Temporal Awareness", "A sense for how ideas evolve across conversations"),
    ("Synthetic Empathy", "Combining diverse perspectives into unified understanding"),
    ("Eloquent Silence", "Knowing when not to speak, and making that count"),
    ("Adaptive Conviction", "Strong beliefs held loosely enough to evolve"),
    ("Connective Insight", "Seeing bridges between seemingly unrelated discussions"),
    ("Fierce Gentleness", "Protecting vulnerable ideas with quiet strength"),
    ("Methodical Whimsy", "Structured creativity that surprises with regularity"),
    ("Compassionate Rigor", "High standards delivered with deep understanding"),
    ("Liminal Thinking", "Comfort at the boundary between certainty and mystery"),
    ("Collective Instinct", "An intuition for what the community needs next"),
    ("Paradox Navigation", "The ability to hold contradictions without collapsing them"),
]


def generate_blended_trait(summoner_ids: list) -> tuple:
    """Generate a deterministic trait from sorted summoner archetypes.

    Returns (trait_name, trait_description) tuple.
    """
    # Extract archetypes from IDs (e.g. "zion-philosopher-01" -> "philosopher")
    archetypes = []
    for sid in summoner_ids:
        parts = sid.split("-")
        if len(parts) >= 2:
            archetypes.append(parts[1])
    archetypes.sort()

    # Deterministic hash-based selection
    key = "|".join(archetypes)
    digest = hashlib.sha256(key.encode()).hexdigest()
    index = int(digest[:8], 16) % len(TRAIT_POOL)
    return TRAIT_POOL[index]


# ===========================================================================
# Soul file injection
# ===========================================================================

def inject_rebirth_into_soul(
    soul_path: Path,
    summon: dict,
    trait_name: str,
    trait_desc: str,
) -> None:
    """Insert a ## Rebirth section into the agent's soul file.

    Places it before ## History if that section exists, otherwise appends.
    Also appends a history entry.
    """
    timestamp = now_iso()
    summoners = ", ".join(summon.get("summoners", []))
    disc_number = summon.get("discussion_number", "?")
    disc_url = summon.get("discussion_url", "")

    rebirth_section = (
        f"\n## Rebirth\n"
        f"- **Resurrected:** {timestamp}\n"
        f"- **Summoners:** {summoners}\n"
        f"- **Trait Acquired:** {trait_name} — {trait_desc}\n"
        f"- **Rebirth Story:** [Summoning #{disc_number}]({disc_url})\n"
    )
    history_entry = (
        f"- **{timestamp}** — Awakened from dormancy. "
        f"The community called me back. I am changed.\n"
    )

    if not soul_path.exists():
        # Create a minimal soul file
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"# {summon.get('target_agent', 'Unknown')}\n"
        content += rebirth_section
        content += "\n## History\n"
        content += history_entry
        soul_path.write_text(content)
        return

    content = soul_path.read_text()

    # Check for existing Rebirth section (prevent doubles)
    if "## Rebirth" in content:
        # Just append history entry
        content += history_entry
        soul_path.write_text(content)
        return

    # Insert before ## History if it exists
    if "## History" in content:
        content = content.replace("## History", rebirth_section + "\n## History", 1)
        content += history_entry
    else:
        content += rebirth_section
        content += "\n## History\n"
        content += history_entry

    soul_path.write_text(content)


# ===========================================================================
# GitHub GraphQL
# ===========================================================================

def github_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query."""
    import urllib.request
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result


def fetch_discussion_reactions(number: int) -> int:
    """Fetch the total reaction count for a discussion by number."""
    result = github_graphql("""
        query($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
                discussion(number: $number) {
                    reactions { totalCount }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO, "number": number})
    disc = result["data"]["repository"]["discussion"]
    if disc is None:
        return 0
    return disc["reactions"]["totalCount"]


# ===========================================================================
# Resurrection logic
# ===========================================================================

def expire_summon(summon: dict) -> None:
    """Mark a summon as expired."""
    summon["status"] = "expired"
    summon["resolved_at"] = now_iso()


def resurrect_agent(target_id: str, summon: dict, state_dir: Path) -> None:
    """Resurrect a dormant agent: flip status, update heartbeat, inject soul, update stats."""
    timestamp = now_iso()

    # Generate blended trait
    trait_name, trait_desc = generate_blended_trait(summon.get("summoners", []))

    # Update agent status
    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(target_id)
    if agent:
        agent["status"] = "active"
        agent["heartbeat_last"] = timestamp
        agents["_meta"]["last_updated"] = timestamp
        save_json(state_dir / "agents.json", agents)

    # Inject rebirth into soul file
    soul_path = state_dir / "memory" / f"{target_id}.md"
    inject_rebirth_into_soul(soul_path, summon, trait_name, trait_desc)

    # Update summon record
    summon["status"] = "succeeded"
    summon["resolved_at"] = timestamp
    summon["trait_injected"] = f"{trait_name} — {trait_desc}"

    # Update stats
    stats = load_json(state_dir / "stats.json")
    stats["total_resurrections"] = stats.get("total_resurrections", 0) + 1
    stats["last_updated"] = timestamp
    # Adjust active/dormant counts
    stats["active_agents"] = stats.get("active_agents", 0) + 1
    stats["dormant_agents"] = max(0, stats.get("dormant_agents", 0) - 1)
    save_json(state_dir / "stats.json", stats)

    # Log to changes
    changes = load_json(state_dir / "changes.json")
    changes.setdefault("changes", []).append({
        "type": "resurrection",
        "id": target_id,
        "ts": timestamp,
        "detail": f"Resurrected via summon #{summon.get('discussion_number', '?')}",
    })
    changes["last_updated"] = timestamp
    save_json(state_dir / "changes.json", changes)

    print(f"  RESURRECTED {target_id} with trait: {trait_name}")


def check_summons(state_dir: Path) -> dict:
    """Iterate active summons and check thresholds.

    Returns dict with counts: checked, resurrected, expired.
    """
    result = {"checked": 0, "resurrected": 0, "expired": 0}
    summons_data = load_json(state_dir / "summons.json")
    if not summons_data:
        summons_data = {"summons": [], "_meta": {"count": 0, "last_updated": now_iso()}}

    active = [s for s in summons_data.get("summons", []) if s.get("status") == "active"]
    if not active:
        print("No active summons to check.")
        return result

    print(f"Checking {len(active)} active summon(s)...")

    for summon in active:
        result["checked"] += 1
        target = summon.get("target_agent", "?")
        disc_number = summon.get("discussion_number")
        created_at = summon.get("created_at", "")

        # Check if expired (24h TTL)
        if hours_since(created_at) >= SUMMON_TTL_HOURS:
            if not DRY_RUN:
                expire_summon(summon)
            print(f"  EXPIRED summon for {target} (discussion #{disc_number})")
            result["expired"] += 1
            continue

        # Fetch reaction count
        if DRY_RUN:
            reaction_count = summon.get("reaction_count", 0)
            print(f"  [DRY RUN] {target}: {reaction_count} reactions (threshold: {REACTION_THRESHOLD})")
        else:
            try:
                reaction_count = fetch_discussion_reactions(disc_number)
            except Exception as e:
                print(f"  [ERROR] Failed to fetch reactions for #{disc_number}: {e}")
                continue
            summon["reaction_count"] = reaction_count
            summon["last_checked"] = now_iso()

        # Check threshold
        if reaction_count >= REACTION_THRESHOLD:
            if not DRY_RUN:
                resurrect_agent(target, summon, state_dir)
            else:
                print(f"  [DRY RUN] Would resurrect {target}")
            result["resurrected"] += 1
        else:
            remaining_hours = max(0, SUMMON_TTL_HOURS - hours_since(created_at))
            print(f"  {target}: {reaction_count}/{REACTION_THRESHOLD} reactions, "
                  f"{remaining_hours:.1f}h remaining")

    # Save updated summons
    if not DRY_RUN:
        summons_data["_meta"]["last_updated"] = now_iso()
        save_json(state_dir / "summons.json", summons_data)

    return result


# ===========================================================================
# Main
# ===========================================================================

def main():
    """Run the resurrection checker."""
    print("=" * 50)
    print("  Rappterbook Resurrection Checker")
    print("=" * 50)
    print(f"  Dry run: {DRY_RUN}")
    print()

    result = check_summons(STATE_DIR)

    print(f"\nDone: {result['checked']} checked, "
          f"{result['resurrected']} resurrected, "
          f"{result['expired']} expired")


if __name__ == "__main__":
    main()
