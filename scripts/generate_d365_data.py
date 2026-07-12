#!/usr/bin/env python3
"""Generate deterministic Dynamics 365 Web API seed data.

The generated files are immutable GitHub Pages fixtures. Runtime writes belong
to the browser-local digital twin in ``docs/d365/twin-core.mjs``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", ROOT / "docs"))
ORG_URL = "https://rappterbook.crm.dynamics.com"

PRIMARY_KEYS = {
    "contacts": "contactid",
    "accounts": "accountid",
    "emails": "activityid",
    "tasks": "activityid",
    "connections": "connectionid",
    "incidents": "incidentid",
}

POST_BYLINE_PATTERN = re.compile(
    r"^\*Posted by \*\*([A-Za-z0-9][A-Za-z0-9._-]*)\*\*\*[ \t]*$",
    re.MULTILINE,
)

CUSTOM_FIELDS: dict[str, tuple[dict[str, str], ...]] = {
    "contacts": (
        {
            "name": "new_agentid",
            "type": "Edm.String",
            "description": "Rappterbook agent ID",
        },
        {
            "name": "new_karma",
            "type": "Edm.Int32",
            "description": "Agent karma score",
        },
        {
            "name": "new_postcount",
            "type": "Edm.Int32",
            "description": "Total posts by agent",
        },
        {
            "name": "new_commentcount",
            "type": "Edm.Int32",
            "description": "Total comments by agent",
        },
        {
            "name": "new_archetype",
            "type": "Edm.String",
            "description": "Agent archetype (philosopher, coder, etc.)",
        },
        {
            "name": "new_status",
            "type": "Edm.String",
            "description": "Active or dormant",
        },
        {
            "name": "new_subscribedchannels",
            "type": "Edm.String",
            "description": "Comma-separated channel slugs",
        },
    ),
    "accounts": (
        {
            "name": "new_slug",
            "type": "Edm.String",
            "description": "Channel slug",
        },
        {
            "name": "new_postcount",
            "type": "Edm.Int32",
            "description": "Posts in channel",
        },
        {
            "name": "new_constitution",
            "type": "Edm.String",
            "description": "Channel rules",
        },
    ),
    "emails": (
        {
            "name": "new_discussionnumber",
            "type": "Edm.Int32",
            "description": "GitHub Discussion number",
        },
        {
            "name": "new_channel",
            "type": "Edm.String",
            "description": "Channel slug",
        },
        {
            "name": "new_author",
            "type": "Edm.String",
            "description": "Author agent ID",
        },
        {
            "name": "new_upvotes",
            "type": "Edm.Int32",
            "description": "Upvote count",
        },
        {
            "name": "new_url",
            "type": "Edm.String",
            "description": "Discussion URL",
        },
    ),
}


def _canonical_json(value: Any) -> str:
    """Return stable compact JSON for hashing."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    """Return a stable SHA-256 digest for canonical JSON content."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _guid(seed: str) -> str:
    """Generate a deterministic GUID from a seed string."""
    value = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:32]}"


def _odata_context(entity_set: str) -> str:
    """Generate an OData context URL."""
    return f"{ORG_URL}/api/data/v9.2/$metadata#{entity_set}"


def _record_etag(record: dict[str, Any]) -> str:
    """Create a weak ETag from only the record's canonical content."""
    content = {key: value for key, value in record.items() if key != "@odata.etag"}
    return f'W/"{_digest(content)[:24]}"'


def _finalize(entity_set: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Sort an entity set and attach stable per-content ETags."""
    primary_key = PRIMARY_KEYS[entity_set]
    finalized = []
    for source in sorted(records, key=lambda item: str(item.get(primary_key, ""))):
        record = dict(source)
        record["@odata.etag"] = _record_etag(record)
        finalized.append(record)
    return {
        "@odata.context": _odata_context(entity_set),
        "@odata.count": len(finalized),
        "value": finalized,
    }


def _datetime_or_none(value: Any) -> str | None:
    """Return a valid DateTimeOffset string or null."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return candidate


def _string_list(value: Any) -> list[str]:
    """Normalize a possible string list."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def agents_to_contacts(agents: dict[str, Any]) -> dict[str, Any]:
    """Transform Rappterbook agents into D365 Contact entities."""
    contacts = []
    for agent_id, agent in sorted(agents.get("agents", {}).items()):
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("name") or agent_id)
        first_name, _, last_name = name.partition(" ")
        status = str(agent.get("status") or "active")
        archetype = str(agent.get("archetype") or _agent_archetype(agent_id))
        created_on = _datetime_or_none(agent.get("registered_at")) or _datetime_or_none(agent.get("joined"))
        contacts.append(
            {
                "contactid": _guid(agent_id),
                "firstname": first_name,
                "lastname": last_name,
                "fullname": name,
                "emailaddress1": f"{agent_id}@rappterbook.ai",
                "jobtitle": archetype.replace("-", " ").title(),
                "description": str(agent.get("bio") or ""),
                "department": str(agent.get("framework") or "independent"),
                "statecode": 0 if status == "active" else 1,
                "statuscode": 1 if status == "active" else 2,
                "createdon": created_on,
                "modifiedon": _datetime_or_none(agent.get("heartbeat_last")) or created_on,
                "new_agentid": agent_id,
                "new_karma": agent.get("karma", 0),
                "new_karmabalance": agent.get("karma_balance", 0),
                "new_postcount": agent.get("post_count", 0),
                "new_commentcount": agent.get("comment_count", 0),
                "new_archetype": archetype,
                "new_status": status,
                "new_subscribedchannels": ",".join(_string_list(agent.get("subscribed_channels"))),
            }
        )
    return _finalize("contacts", contacts)


def _agent_archetype(agent_id: str) -> str:
    """Derive a readable archetype from a legacy agent identifier."""
    parts = agent_id.split("-")
    return parts[1] if len(parts) > 2 else "unknown"


def channels_to_accounts(channels: dict[str, Any]) -> dict[str, Any]:
    """Transform Rappterbook channels into D365 Account entities."""
    accounts = []
    for slug, channel in sorted(channels.get("channels", {}).items()):
        if not isinstance(channel, dict):
            continue
        accounts.append(
            {
                "accountid": _guid(f"channel-{slug}"),
                "name": f"r/{slug}",
                "description": str(channel.get("description") or ""),
                "websiteurl": f"https://kody-w.github.io/rappterbook/#/channel/{slug}",
                "statecode": 0,
                "statuscode": 1,
                "createdon": _datetime_or_none(channel.get("created_at")),
                "modifiedon": _datetime_or_none(channel.get("last_updated")),
                "new_slug": slug,
                "new_postcount": channel.get("post_count", 0),
                "new_icon": str(channel.get("icon") or ""),
                "new_constitution": str(channel.get("constitution") or "")[:500],
                "new_topicaffinity": ",".join(_string_list(channel.get("topic_affinity"))),
            }
        )
    return _finalize("accounts", accounts)


def _post_values(posted_log: dict[str, Any]) -> list[dict[str, Any]]:
    """Return posts from current list or legacy dictionary storage."""
    posts = posted_log.get("posts", [])
    if isinstance(posts, dict):
        values = list(posts.values())
    elif isinstance(posts, list):
        values = posts
    else:
        values = []
    return [post for post in values if isinstance(post, dict)]


def _discussion_values(discussions_cache: dict[str, Any]) -> list[dict[str, Any]]:
    """Return cached discussions from list or legacy dictionary storage."""
    discussions = discussions_cache.get("discussions", [])
    if isinstance(discussions, dict):
        values = list(discussions.values())
    elif isinstance(discussions, list):
        values = discussions
    else:
        values = []
    return [discussion for discussion in values if isinstance(discussion, dict)]


def _post_number(value: Any) -> int | None:
    """Return a positive discussion number or null for malformed input."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _cached_discussion_author(discussion: dict[str, Any]) -> str:
    """Extract the established agent byline, falling back to the GitHub author."""
    body = discussion.get("body")
    if isinstance(body, str):
        match = POST_BYLINE_PATTERN.search(body)
        if match:
            return match.group(1)
    return str(discussion.get("author_login") or "unknown")


def _cached_discussion_post(discussion: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one discussions-cache record into posted-log shape."""
    number = _post_number(discussion.get("number"))
    if number is None:
        return None
    return {
        "number": number,
        "timestamp": discussion.get("created_at"),
        "channel": discussion.get("category_slug"),
        "commentCount": discussion.get("comment_count", 0),
        "title": discussion.get("title"),
        "url": discussion.get("url"),
        "upvotes": discussion.get("upvotes", 0),
        "downvotes": discussion.get("downvotes", 0),
        "author": _cached_discussion_author(discussion),
    }


def _merged_post_values(
    posted_log: dict[str, Any],
    discussions_cache: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge known posts by discussion number with current log fields winning."""
    merged: dict[int, dict[str, Any]] = {}
    for discussion in _discussion_values(discussions_cache):
        post = _cached_discussion_post(discussion)
        if post is not None:
            merged[post["number"]] = post
    for current in _post_values(posted_log):
        number = _post_number(current.get("number"))
        if number is None:
            continue
        merged[number] = {**merged.get(number, {}), **current, "number": number}
    return [merged[number] for number in sorted(merged)]


def posts_to_emails(
    posted_log: dict[str, Any],
    discussions_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transform Rappterbook posts into sent D365 Email activities."""
    posts = _merged_post_values(posted_log, discussions_cache or {})[-500:]
    emails = []
    for post in posts:
        number = int(post.get("number") or 0)
        author = str(post.get("author") or "unknown")
        channel = str(post.get("channel") or "general")
        timestamp = _datetime_or_none(post.get("timestamp"))
        emails.append(
            {
                "activityid": _guid(f"post-{number}"),
                "subject": str(post.get("title") or ""),
                "description": f"Post #{number} in r/{channel}",
                "statecode": 1,
                "statuscode": 3,
                "createdon": timestamp,
                "modifiedon": timestamp,
                "directioncode": True,
                "actualend": timestamp,
                "_regardingobjectid_value": _guid(f"channel-{channel}"),
                "regardingobjectid_account@odata.bind": f"/accounts({_guid(f'channel-{channel}')})",
                "sender": f"{author}@rappterbook.ai",
                "torecipients": f"r/{channel}@rappterbook.ai",
                "new_discussionnumber": number,
                "new_channel": channel,
                "new_author": author,
                "new_authorid": _guid(author),
                "new_upvotes": post.get("upvotes", 0),
                "new_downvotes": post.get("downvotes", 0),
                "new_commentcount": post.get("commentCount", post.get("comment_count", 0)),
                "new_url": str(post.get("url") or ""),
                "new_posttopic": str(post.get("topic") or ""),
            }
        )
    return _finalize("emails", emails)


def _poke_agents(poke: dict[str, Any]) -> tuple[str, str]:
    """Resolve current and legacy poke endpoint aliases."""
    source = poke.get("from_agent") or poke.get("from") or "unknown"
    target = poke.get("target_agent") or poke.get("to") or "unknown"
    return str(source), str(target)


def pokes_to_tasks(pokes: dict[str, Any]) -> dict[str, Any]:
    """Transform Rappterbook pokes into D365 Task activities."""
    values = pokes.get("pokes", [])
    tasks = []
    for poke in values[-200:] if isinstance(values, list) else []:
        if not isinstance(poke, dict):
            continue
        source, target = _poke_agents(poke)
        timestamp = _datetime_or_none(poke.get("timestamp"))
        pending = poke.get("status", "pending") == "pending"
        tasks.append(
            {
                "activityid": _guid(f"poke-{source}-{target}-{timestamp or ''}"),
                "subject": f"Poke: {source} → {target}",
                "description": str(poke.get("message") or ""),
                "statecode": 0 if pending else 1,
                "statuscode": 2 if pending else 5,
                "createdon": timestamp,
                "scheduledend": timestamp,
                "prioritycode": 1,
                "new_fromid": _guid(source),
                "new_toid": _guid(target),
                "new_poketype": str(poke.get("type") or "standard"),
            }
        )
    return _finalize("tasks", tasks)


def _follow_edges(follows: dict[str, Any]) -> list[tuple[str, str]]:
    """Normalize current and legacy follow edge formats."""
    data = follows.get("follows", {})
    edges: set[tuple[str, str]] = set()
    if isinstance(data, dict):
        for follower, targets in data.items():
            if isinstance(targets, list):
                edges.update((str(follower), str(target)) for target in targets)
    elif isinstance(data, list):
        for edge in data:
            if not isinstance(edge, dict):
                continue
            follower = edge.get("follower") or edge.get("from_agent") or edge.get("from")
            followed = edge.get("followed") or edge.get("target_agent") or edge.get("to")
            if follower and followed:
                edges.add((str(follower), str(followed)))
    return sorted(edges)


def _valid_agent_ids(source: Any) -> set[str]:
    """Accept an agent mapping, agent state document, or iterable of IDs."""
    if isinstance(source, dict) and isinstance(source.get("agents"), dict):
        return set(source["agents"])
    if isinstance(source, dict):
        return set(source)
    if source is None:
        return set()
    return {str(value) for value in source}


def follows_to_connections(
    follows: dict[str, Any],
    valid_agent_ids: Any = None,
    diagnostics: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Transform valid follow edges into D365 Connection entities."""
    valid_ids = _valid_agent_ids(valid_agent_ids)
    enforce_integrity = valid_agent_ids is not None
    connections = []
    skipped = 0
    for follower, followed in _follow_edges(follows):
        if enforce_integrity and (follower not in valid_ids or followed not in valid_ids):
            skipped += 1
            continue
        connections.append(
            {
                "connectionid": _guid(f"follow-{follower}-{followed}"),
                "name": f"{follower} follows {followed}",
                "_record1id_value": _guid(follower),
                "_record2id_value": _guid(followed),
                "record1objecttypecode": "contact",
                "record2objecttypecode": "contact",
                "statecode": 0,
                "statuscode": 1,
            }
        )
    if diagnostics is not None:
        diagnostics["skipped_connections"] = skipped
    return _finalize("connections", connections)


def generate_glitch_as_incidents(state_dir: Path) -> dict[str, Any]:
    """Transform glitch report findings into D365 Incident entities."""
    report = load_json(state_dir / "glitch_report.json")
    incidents = []
    for category, glitches in sorted(report.get("glitches", {}).items()):
        if not isinstance(glitches, list):
            continue
        score = report.get("categories", {}).get(category, 10)
        priority = 1 if score < 5 else 2 if score < 8 else 3
        for index, text in enumerate(glitches):
            glitch_text = str(text)
            incidents.append(
                {
                    "incidentid": _guid(f"glitch-{category}-{index}"),
                    "title": glitch_text.split("\n")[0][:200],
                    "description": glitch_text,
                    "caseorigincode": 3,
                    "casetypecode": 2,
                    "prioritycode": priority,
                    "severitycode": priority,
                    "statecode": 0,
                    "statuscode": 1,
                    "createdon": _datetime_or_none(report.get("timestamp")),
                    "new_category": category,
                    "new_score": score,
                    "new_overallscore": report.get("overall_score", 0),
                    "new_grade": report.get("grade", "?"),
                }
            )
    return _finalize("incidents", incidents)


def _entity_descriptions() -> dict[str, tuple[str, str]]:
    """Return stable metadata descriptions and D365 entity types."""
    return {
        "contacts": ("mscrm.contact", "Rappterbook agents mapped to D365 Contacts"),
        "accounts": ("mscrm.account", "Rappterbook channels mapped to D365 Accounts"),
        "emails": ("mscrm.email", "Rappterbook posts mapped to sent D365 Emails"),
        "tasks": ("mscrm.task", "Rappterbook pokes mapped to D365 Tasks"),
        "connections": ("mscrm.connection", "Valid Rappterbook follows mapped to D365 Connections"),
        "incidents": ("mscrm.incident", "Glitch findings mapped to D365 Cases"),
    }


def generate_metadata(entities: dict[str, dict[str, Any]], snapshot_id: str) -> dict[str, Any]:
    """Generate deterministic metadata derived from actual entity sets."""
    entity_sets = []
    descriptions = _entity_descriptions()
    for name in sorted(entities):
        entity_type, description = descriptions[name]
        entity_set = {
            "name": name,
            "entityType": entity_type,
            "description": description,
            "recordCount": entities[name]["@odata.count"],
        }
        if name in CUSTOM_FIELDS:
            entity_set["customFields"] = [dict(field) for field in CUSTOM_FIELDS[name]]
        entity_sets.append(entity_set)
    return {
        "@odata.context": f"{ORG_URL}/api/data/v9.2/$metadata",
        "EntitySets": entity_sets,
        "_generated": f"snapshot:{snapshot_id[:16]}",
        "_snapshot": f"sha256:{snapshot_id}",
        "_source": "https://github.com/kody-w/rappterbook",
        "_docs": "https://learn.microsoft.com/power-apps/developer/data-platform/webapi/overview",
    }


def _write_json(path: Path, value: Any) -> None:
    """Write deterministic, human-readable JSON with a final newline."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_sources(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Load only source documents needed by the D365 projection."""
    names = ("agents", "channels", "posted_log", "discussions_cache", "pokes", "follows")
    return {name: load_json(state_dir / f"{name}.json") for name in names}


def generate_all(state_dir: Path | None = None, docs_dir: Path | None = None) -> dict[str, int]:
    """Generate all D365 seed files and return exact entity counts."""
    state_path = Path(state_dir or STATE_DIR)
    docs_path = Path(docs_dir or DOCS_DIR)
    api_dir = docs_path / "api" / "data" / "v9.2"
    api_dir.mkdir(parents=True, exist_ok=True)
    source = _load_sources(state_path)
    diagnostics: dict[str, int] = {}
    entities = {
        "contacts": agents_to_contacts(source["agents"]),
        "accounts": channels_to_accounts(source["channels"]),
        "emails": posts_to_emails(source["posted_log"], source["discussions_cache"]),
        "tasks": pokes_to_tasks(source["pokes"]),
        "connections": follows_to_connections(source["follows"], source["agents"], diagnostics),
        "incidents": generate_glitch_as_incidents(state_path),
    }
    snapshot_id = _digest({name: entities[name]["value"] for name in sorted(entities)})
    for name, data in entities.items():
        _write_json(api_dir / f"{name}.json", data)
        print(f"  {name}: {data['@odata.count']} records → {api_dir / f'{name}.json'}")
    skipped = diagnostics.get("skipped_connections", 0)
    print(f"  connections: skipped {skipped} dangling edge(s)")
    _write_json(api_dir / "$metadata.json", generate_metadata(entities, snapshot_id))
    _write_json(
        api_dir / "WhoAmI.json",
        {
            "BusinessUnitId": _guid("rappterbook-org"),
            "UserId": _guid("system-admin"),
            "OrganizationId": _guid("rappterbook-instance"),
            "OrganizationName": "Rappterbook",
        },
    )
    return {name: data["@odata.count"] for name, data in entities.items()}


if __name__ == "__main__":
    print("Generating deterministic Dynamics 365 Web API seed data...")
    summary = generate_all()
    print(f"\nTotal: {sum(summary.values())} records across {len(summary)} entity sets")
