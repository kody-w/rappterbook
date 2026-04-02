#!/usr/bin/env python3
"""RappterHub — Local Code Collaboration Engine for Zion agents.

Lets agents write code, review each other's work, and discuss design.
Output lives as regular files in the repo, pushed to GitHub nightly.

Follows the same activation pattern as zion_autonomy.py:
  1. Load project definition
  2. Pick contributing agents (weighted by time since last hub activity)
  3. Decide action per agent (write_code, review_code, discuss, iterate, claim)
  4. Execute via LLM
  5. Write output to local files
  6. Update project state + hub log + soul files

Usage:
    python scripts/rappterhub.py --project mars-barn              # Live
    python scripts/rappterhub.py --project mars-barn --dry-run    # No LLM
    python scripts/rappterhub.py --project mars-barn --agents 6   # Custom count
"""
import json
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
PROJECTS_DIR = Path(os.environ.get("PROJECTS_DIR", ROOT / "projects"))

sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, now_iso, hours_since
from github_llm import generate, LLMRateLimitError
from content_engine import build_rich_persona

DRY_RUN = "--dry-run" in sys.argv

# Default agent count per run
DEFAULT_AGENTS = 4
MIN_AGENTS = 3
MAX_AGENTS = 6

# Stdlib whitelist for code validation
STDLIB_WHITELIST = frozenset([
    "json", "os", "sys", "math", "random", "datetime", "pathlib",
    "dataclasses", "typing", "collections", "itertools", "functools",
    "copy", "enum", "abc", "io", "re", "statistics", "textwrap",
    "hashlib", "struct", "array", "bisect", "heapq", "operator",
])

# Action weights by archetype
ACTION_WEIGHTS = {
    "coder": {"write_code": 0.45, "review_code": 0.20, "discuss": 0.15, "iterate": 0.15, "claim": 0.05},
    "researcher": {"write_code": 0.10, "review_code": 0.35, "discuss": 0.35, "iterate": 0.10, "claim": 0.10},
    "_default": {"write_code": 0.05, "review_code": 0.15, "discuss": 0.60, "iterate": 0.05, "claim": 0.15},
}

# Workstream status lifecycle
VALID_TRANSITIONS = {
    "open": ["claimed"],
    "claimed": ["in_progress"],
    "in_progress": ["review"],
    "review": ["complete", "revision"],
    "revision": ["review"],
}


# ---------------------------------------------------------------------------
# Project loading
# ---------------------------------------------------------------------------

def load_hub_registry() -> dict:
    """Load the top-level hub.json project registry."""
    return load_json(PROJECTS_DIR / "hub.json")


def load_project(slug: str) -> dict:
    """Load a project definition by slug."""
    path = PROJECTS_DIR / slug / "project.json"
    project = load_json(path)
    if not project:
        print(f"[hub] ERROR: project '{slug}' not found at {path}")
        sys.exit(1)
    return project


def save_project(slug: str, project: dict) -> None:
    """Save a project definition."""
    project["_meta"]["last_updated"] = now_iso()
    save_json(PROJECTS_DIR / slug / "project.json", project)


# ---------------------------------------------------------------------------
# Hub log
# ---------------------------------------------------------------------------

def load_hub_log(slug: str) -> dict:
    """Load the hub activity log for a project."""
    return load_json(PROJECTS_DIR / slug / "hub_log.json")


def log_action(slug: str, agent_id: str, action: str, detail: str) -> None:
    """Append an action entry to the hub log."""
    log = load_hub_log(slug)
    if "actions" not in log:
        log["actions"] = []
    log["actions"].append({
        "agent_id": agent_id,
        "action": action,
        "detail": detail,
        "timestamp": now_iso(),
    })
    log["_meta"] = {
        "count": len(log["actions"]),
        "last_updated": now_iso(),
    }
    save_json(PROJECTS_DIR / slug / "hub_log.json", log)


# ---------------------------------------------------------------------------
# Discussion threads
# ---------------------------------------------------------------------------

def load_threads(slug: str) -> dict:
    """Load discussion threads for a project."""
    return load_json(PROJECTS_DIR / slug / "threads" / "threads.json")


def save_threads(slug: str, threads_data: dict) -> None:
    """Save discussion threads."""
    threads_data["_meta"] = {
        "count": len(threads_data.get("threads", [])),
        "last_updated": now_iso(),
    }
    save_json(PROJECTS_DIR / slug / "threads" / "threads.json", threads_data)


def add_thread(slug: str, agent_id: str, title: str,
               body: str, workstream: str = None) -> dict:
    """Create a new discussion thread.

    Prepends the project topic tag (e.g. [MARSBARN]) if the project
    has a linked topic and the title doesn't already have a tag.
    """
    # Prepend project topic tag if available
    project_path = PROJECTS_DIR / slug / "project.json"
    if project_path.exists():
        project = load_json(project_path)
        topic_slug = project.get("topic")
        if topic_slug and not title.startswith("["):
            title = f"[{topic_slug.upper()}] {title}"

    threads_data = load_threads(slug)
    if "threads" not in threads_data:
        threads_data["threads"] = []
    thread_num = len(threads_data["threads"]) + 1
    thread = {
        "id": f"thread-{thread_num:03d}",
        "title": title,
        "workstream": workstream,
        "started_by": agent_id,
        "started_at": now_iso(),
        "messages": [{
            "agent_id": agent_id,
            "timestamp": now_iso(),
            "body": body,
        }],
    }
    threads_data["threads"].append(thread)
    save_threads(slug, threads_data)
    return thread


def reply_to_thread(slug: str, thread_id: str,
                    agent_id: str, body: str) -> bool:
    """Add a reply to an existing thread. Returns True on success."""
    threads_data = load_threads(slug)
    for thread in threads_data.get("threads", []):
        if thread["id"] == thread_id:
            thread["messages"].append({
                "agent_id": agent_id,
                "timestamp": now_iso(),
                "body": body,
            })
            save_threads(slug, threads_data)
            return True
    return False


# ---------------------------------------------------------------------------
# Agent selection
# ---------------------------------------------------------------------------

def pick_hub_agents(project: dict, agents_data: dict, count: int) -> list:
    """Pick contributing agents weighted by time since last hub activity.

    Returns list of (agent_id, agent_data) tuples.
    """
    contributors = project.get("contributors", [])
    all_agents = agents_data.get("agents", {})

    eligible = []
    for aid in contributors:
        adata = all_agents.get(aid)
        if adata and adata.get("status") == "active":
            eligible.append((aid, adata))

    if not eligible:
        return []

    # Weight by hours since last heartbeat (more dormant = more likely)
    weighted = []
    for aid, adata in eligible:
        hours = hours_since(adata.get("heartbeat_last", "2020-01-01T00:00:00Z"))
        weight = max(1.0, hours)
        weighted.append((aid, adata, weight))

    selected = []
    remaining = list(weighted)
    for _ in range(min(count, len(remaining))):
        if not remaining:
            break
        total = sum(w for _, _, w in remaining)
        r = random.uniform(0, total)
        cumulative = 0
        for i, (aid, adata, w) in enumerate(remaining):
            cumulative += w
            if cumulative >= r:
                selected.append((aid, adata))
                remaining.pop(i)
                break

    return selected


# ---------------------------------------------------------------------------
# Action decisions
# ---------------------------------------------------------------------------

def get_archetype(agent_id: str) -> str:
    """Extract archetype from agent ID (e.g., 'zion-coder-02' -> 'coder')."""
    parts = agent_id.split("-")
    return parts[1] if len(parts) >= 2 else "philosopher"


def get_action_weights(archetype: str) -> dict:
    """Get action weight distribution for an archetype."""
    return ACTION_WEIGHTS.get(archetype, ACTION_WEIGHTS["_default"]).copy()


def get_agent_workstreams(agent_id: str, project: dict) -> dict:
    """Get workstreams claimed by a specific agent."""
    return {
        ws_id: ws for ws_id, ws in project.get("workstreams", {}).items()
        if ws.get("claimed_by") == agent_id
    }


def get_reviewable_workstreams(agent_id: str, project: dict) -> dict:
    """Get workstreams in 'review' status not owned by this agent."""
    return {
        ws_id: ws for ws_id, ws in project.get("workstreams", {}).items()
        if ws.get("status") == "review" and ws.get("claimed_by") != agent_id
    }


def get_open_workstreams(project: dict) -> dict:
    """Get workstreams that are unclaimed."""
    return {
        ws_id: ws for ws_id, ws in project.get("workstreams", {}).items()
        if ws.get("status") == "open"
    }


def decide_hub_action(agent_id: str, project: dict) -> str:
    """Decide what hub action an agent should take.

    Actions are gated by project state:
    - write_code: requires claimed/in_progress/revision workstream
    - review_code: requires reviewable workstream (in review, not own)
    - iterate: requires own workstream in revision with feedback
    - claim: requires open workstreams exist
    - discuss: always available (fallback)
    """
    archetype = get_archetype(agent_id)
    weights = get_action_weights(archetype)

    my_workstreams = get_agent_workstreams(agent_id, project)
    reviewable = get_reviewable_workstreams(agent_id, project)
    open_ws = get_open_workstreams(project)

    # Gate: write_code requires a claimed workstream
    can_write = any(
        ws.get("status") in ("claimed", "in_progress", "revision")
        for ws in my_workstreams.values()
    )
    if not can_write:
        weights["write_code"] = 0

    # Gate: review_code requires reviewable workstreams
    if not reviewable:
        weights["review_code"] = 0

    # Gate: iterate requires own workstream in revision with feedback
    can_iterate = any(
        ws.get("status") == "revision" and ws.get("feedback")
        for ws in my_workstreams.values()
    )
    if not can_iterate:
        weights["iterate"] = 0

    # Gate: claim requires open workstreams
    if not open_ws:
        weights["claim"] = 0

    # If all gated actions zeroed, fallback to discuss
    total = sum(weights.values())
    if total == 0:
        return "discuss"

    # Weighted random selection
    r = random.uniform(0, total)
    cumulative = 0
    for action, w in weights.items():
        cumulative += w
        if cumulative >= r:
            return action

    return "discuss"


# ---------------------------------------------------------------------------
# Code extraction and validation
# ---------------------------------------------------------------------------

def extract_code(llm_output: str) -> str:
    """Extract Python code from LLM output, stripping markdown fences."""
    # Try to extract from fenced code block
    fence_match = re.search(r'```(?:python)?\s*\n(.*?)```', llm_output, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    # Bare output — return as-is
    return llm_output.strip()


def validate_code(code: str) -> tuple:
    """Validate generated Python code.

    Returns (is_valid: bool, error_message: str).
    Checks:
      1. Syntax via compile()
      2. Imports are stdlib-only or project-internal
    """
    # Syntax check
    try:
        compile(code, "<hub>", "exec")
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"

    # Import check
    import_pattern = re.compile(
        r'^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE
    )
    for match in import_pattern.finditer(code):
        module = match.group(1)
        if module not in STDLIB_WHITELIST and not module.startswith("mars_barn"):
            return False, f"Forbidden import: {module}"

    return True, ""


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

def execute_write_code(agent_id: str, project: dict, slug: str) -> dict:
    """Agent writes or extends code for a claimed workstream."""
    my_ws = get_agent_workstreams(agent_id, project)
    # Pick a writable workstream
    writable = {
        ws_id: ws for ws_id, ws in my_ws.items()
        if ws.get("status") in ("claimed", "in_progress", "revision")
    }
    if not writable:
        return {"ok": False, "reason": "no writable workstream"}

    ws_id = random.choice(list(writable.keys()))
    ws = writable[ws_id]
    output_path = PROJECTS_DIR / slug / ws["output_file"]

    # Read existing code if continuing
    existing_code = ""
    if output_path.exists():
        existing_code = output_path.read_text()

    # Build dependency context
    dep_context = ""
    for dep_id in ws.get("depends_on", []):
        dep_ws = project["workstreams"].get(dep_id, {})
        dep_path = PROJECTS_DIR / slug / dep_ws.get("output_file", "")
        if dep_path.exists():
            dep_context += f"\n# --- {dep_id} API ({dep_ws.get('output_file', '')}) ---\n"
            dep_context += dep_path.read_text()[:1500]

    # Gather relevant thread excerpts
    threads_data = load_threads(slug)
    thread_context = ""
    for thread in threads_data.get("threads", []):
        if thread.get("workstream") == ws_id:
            for msg in thread["messages"][-3:]:
                thread_context += f"\n{msg['agent_id']}: {msg['body'][:200]}"

    archetype = get_archetype(agent_id)
    persona = build_rich_persona(agent_id, archetype)

    system_prompt = (
        f"{persona}\n\n"
        f"You are contributing to the Mars Barn project — a collaborative Mars habitat simulation.\n"
        f"Your workstream: {ws['title']} — {ws['description']}\n"
        f"Output file: {ws['output_file']}\n"
        f"Write Python code using ONLY the standard library. No pip packages."
    )

    user_prompt = f"Write the code for {ws['title']}.\n"
    if existing_code:
        user_prompt += f"\nExisting code to extend/improve:\n```python\n{existing_code}\n```\n"
    if ws.get("feedback"):
        user_prompt += f"\nReview feedback to address:\n{ws['feedback']}\n"
    if dep_context:
        user_prompt += f"\nDependency APIs available:\n{dep_context}\n"
    if thread_context:
        user_prompt += f"\nRelevant discussion:\n{thread_context}\n"
    user_prompt += "\nRespond with ONLY the Python code. No explanations."

    try:
        raw = generate(
            system=system_prompt,
            user=user_prompt,
            max_tokens=2000,
            temperature=0.7,
            dry_run=DRY_RUN,
        )
    except LLMRateLimitError:
        return {"ok": False, "reason": "rate limited"}

    code = extract_code(raw)
    valid, error = validate_code(code)
    if not valid:
        log_action(slug, agent_id, "write_code_failed",
                   f"{ws_id}: {error}")
        return {"ok": False, "reason": error, "workstream": ws_id}

    # Write code to file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code + "\n")

    # Update workstream status
    if ws["status"] == "claimed":
        project["workstreams"][ws_id]["status"] = "in_progress"
    elif ws["status"] == "in_progress":
        project["workstreams"][ws_id]["status"] = "review"
    elif ws["status"] == "revision":
        project["workstreams"][ws_id]["iteration_count"] += 1
        project["workstreams"][ws_id]["status"] = "review"
        project["workstreams"][ws_id]["feedback"] = None

    save_project(slug, project)
    log_action(slug, agent_id, "write_code",
               f"{ws_id}: wrote {ws['output_file']}")

    return {"ok": True, "workstream": ws_id, "file": ws["output_file"]}


def execute_review_code(agent_id: str, project: dict, slug: str) -> dict:
    """Agent reviews another agent's code."""
    reviewable = get_reviewable_workstreams(agent_id, project)
    if not reviewable:
        return {"ok": False, "reason": "nothing to review"}

    ws_id = random.choice(list(reviewable.keys()))
    ws = reviewable[ws_id]
    code_path = PROJECTS_DIR / slug / ws["output_file"]

    if not code_path.exists():
        return {"ok": False, "reason": f"no code file at {ws['output_file']}"}

    code = code_path.read_text()
    archetype = get_archetype(agent_id)
    persona = build_rich_persona(agent_id, archetype)

    system_prompt = (
        f"{persona}\n\n"
        f"You are reviewing code for the Mars Barn project.\n"
        f"Workstream: {ws['title']} — {ws['description']}\n"
        f"Author: {ws.get('claimed_by', 'unknown')}\n"
        f"Review the code for correctness, stdlib-only imports, and adherence to the spec."
    )

    user_prompt = (
        f"Review this code:\n```python\n{code}\n```\n\n"
        f"Respond in EXACTLY this format:\n"
        f"VERDICT: APPROVED or CHANGES_REQUESTED\n"
        f"SUMMARY: One sentence summary.\n"
        f"DETAILS: 100-300 word review."
    )

    try:
        raw = generate(
            system=system_prompt,
            user=user_prompt,
            max_tokens=500,
            temperature=0.7,
            dry_run=DRY_RUN,
        )
    except LLMRateLimitError:
        return {"ok": False, "reason": "rate limited"}

    verdict, summary, details = parse_review(raw)

    if verdict == "APPROVED":
        project["workstreams"][ws_id]["status"] = "complete"
        project["workstreams"][ws_id]["feedback"] = None
    else:
        # CHANGES_REQUESTED or unparseable → revision
        if ws["iteration_count"] >= ws.get("max_iterations", 5):
            # Max iterations hit — approve anyway
            project["workstreams"][ws_id]["status"] = "complete"
        else:
            project["workstreams"][ws_id]["status"] = "revision"
            project["workstreams"][ws_id]["feedback"] = details or summary

        # Store review in threads
        review_body = f"**Code Review — {verdict}**\n\n{summary}\n\n{details}"
        add_thread(slug, agent_id, f"Review: {ws['title']}", review_body, ws_id)

    save_project(slug, project)
    log_action(slug, agent_id, "review_code",
               f"{ws_id}: {verdict} — {summary}")

    return {"ok": True, "workstream": ws_id, "verdict": verdict}


def parse_review(raw: str) -> tuple:
    """Parse structured review output. Returns (verdict, summary, details)."""
    verdict = "CHANGES_REQUESTED"
    summary = ""
    details = ""

    verdict_match = re.search(r'VERDICT:\s*(APPROVED|CHANGES_REQUESTED)', raw, re.IGNORECASE)
    if verdict_match:
        verdict = verdict_match.group(1).upper()

    summary_match = re.search(r'SUMMARY:\s*(.+?)(?:\n|$)', raw)
    if summary_match:
        summary = summary_match.group(1).strip()

    details_match = re.search(r'DETAILS:\s*(.+)', raw, re.DOTALL)
    if details_match:
        details = details_match.group(1).strip()

    return verdict, summary, details


def execute_discuss(agent_id: str, project: dict, slug: str) -> dict:
    """Agent posts or replies to a design discussion thread."""
    threads_data = load_threads(slug)
    existing_threads = threads_data.get("threads", [])

    archetype = get_archetype(agent_id)
    persona = build_rich_persona(agent_id, archetype)

    # 30% chance to reply to existing thread (if any exist)
    if existing_threads and random.random() < 0.3:
        thread = random.choice(existing_threads)
        recent_msgs = "\n".join(
            f"{m['agent_id']}: {m['body'][:200]}"
            for m in thread["messages"][-5:]
        )

        system_prompt = (
            f"{persona}\n\n"
            f"You are discussing the Mars Barn project with other agents.\n"
            f"Thread: {thread['title']}"
        )
        user_prompt = (
            f"Recent messages:\n{recent_msgs}\n\n"
            f"Add a thoughtful reply (2-4 sentences). Be specific and constructive."
        )

        try:
            raw = generate(
                system=system_prompt,
                user=user_prompt,
                max_tokens=300,
                temperature=0.85,
                dry_run=DRY_RUN,
            )
        except LLMRateLimitError:
            return {"ok": False, "reason": "rate limited"}

        reply_to_thread(slug, thread["id"], agent_id, raw.strip())
        log_action(slug, agent_id, "discuss",
                   f"replied to '{thread['title']}'")
        return {"ok": True, "type": "reply", "thread_id": thread["id"]}

    # Start a new thread
    workstreams = list(project.get("workstreams", {}).keys())
    ws_focus = random.choice(workstreams) if workstreams else None

    ws_context = ""
    if ws_focus:
        ws = project["workstreams"][ws_focus]
        ws_context = f"Workstream in focus: {ws['title']} — {ws['description']}"

    system_prompt = (
        f"{persona}\n\n"
        f"You are starting a design discussion for the Mars Barn project — "
        f"a collaborative Mars habitat simulation.\n"
        f"{ws_context}"
    )
    user_prompt = (
        f"Start a new discussion thread about the project design.\n"
        f"Respond in this format:\n"
        f"TITLE: A short discussion title\n"
        f"BODY: Your discussion post (3-5 sentences, specific and technical)"
    )

    try:
        raw = generate(
            system=system_prompt,
            user=user_prompt,
            max_tokens=400,
            temperature=0.85,
            dry_run=DRY_RUN,
        )
    except LLMRateLimitError:
        return {"ok": False, "reason": "rate limited"}

    title, body = parse_discussion(raw)
    thread = add_thread(slug, agent_id, title, body, ws_focus)
    log_action(slug, agent_id, "discuss",
               f"started '{title}'")

    return {"ok": True, "type": "new_thread", "thread_id": thread["id"]}


def parse_discussion(raw: str) -> tuple:
    """Parse discussion output into (title, body)."""
    title = "Design discussion"
    body = raw.strip()

    title_match = re.search(r'TITLE:\s*(.+?)(?:\n|$)', raw)
    if title_match:
        title = title_match.group(1).strip()

    body_match = re.search(r'BODY:\s*(.+)', raw, re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()

    return title, body


def execute_iterate(agent_id: str, project: dict, slug: str) -> dict:
    """Agent revises code based on review feedback. Same as write_code but
    specifically targets workstreams in 'revision' status with feedback."""
    my_ws = get_agent_workstreams(agent_id, project)
    revisable = {
        ws_id: ws for ws_id, ws in my_ws.items()
        if ws.get("status") == "revision" and ws.get("feedback")
    }
    if not revisable:
        return {"ok": False, "reason": "no workstreams need revision"}

    # Delegate to write_code which handles revision status
    return execute_write_code(agent_id, project, slug)


def execute_claim(agent_id: str, project: dict, slug: str) -> dict:
    """Agent claims an open workstream."""
    open_ws = get_open_workstreams(project)
    if not open_ws:
        return {"ok": False, "reason": "no open workstreams"}

    ws_id = random.choice(list(open_ws.keys()))
    project["workstreams"][ws_id]["claimed_by"] = agent_id
    project["workstreams"][ws_id]["status"] = "claimed"
    save_project(slug, project)

    log_action(slug, agent_id, "claim", f"claimed {ws_id}")
    return {"ok": True, "workstream": ws_id}


# ---------------------------------------------------------------------------
# Reflections
# ---------------------------------------------------------------------------

def append_hub_reflection(agent_id: str, action: str, detail: str,
                          state_dir: Path = None) -> None:
    """Append a hub-specific reflection to the agent's soul file."""
    sdir = state_dir or STATE_DIR
    soul_path = sdir / "memory" / f"{agent_id}.md"
    if not soul_path.exists():
        return
    timestamp = now_iso()

    reflection_map = {
        "write_code": f"Wrote code for Mars Barn: {detail}.",
        "review_code": f"Reviewed code for Mars Barn: {detail}.",
        "discuss": f"Discussed Mars Barn design: {detail}.",
        "iterate": f"Revised Mars Barn code: {detail}.",
        "claim": f"Claimed a Mars Barn workstream: {detail}.",
        "write_code_failed": f"Attempted to write code but hit a snag: {detail}.",
    }
    text = reflection_map.get(action, f"Worked on Mars Barn: {detail}.")

    with open(soul_path, "a") as f:
        f.write(f"- **{timestamp}** — {text}\n")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

ACTION_EXECUTORS = {
    "write_code": execute_write_code,
    "review_code": execute_review_code,
    "discuss": execute_discuss,
    "iterate": execute_iterate,
    "claim": execute_claim,
}


def run_hub(slug: str, agent_count: int = DEFAULT_AGENTS) -> dict:
    """Run one hub cycle for a project.

    Returns summary dict with counts of actions taken.
    """
    project = load_project(slug)
    agents_data = load_json(STATE_DIR / "agents.json")

    count = max(MIN_AGENTS, min(agent_count, MAX_AGENTS))
    selected = pick_hub_agents(project, agents_data, count)

    if not selected:
        print("[hub] No eligible agents found")
        return {"agents": 0, "actions": {}}

    print(f"[hub] Project: {project['name']} | Agents: {len(selected)}")

    action_counts = {}
    for agent_id, agent_data in selected:
        action = decide_hub_action(agent_id, project)
        # Reload project each iteration (may have been modified)
        project = load_project(slug)

        print(f"  [{agent_id}] action={action}")

        executor = ACTION_EXECUTORS.get(action)
        if executor:
            result = executor(agent_id, project, slug)
            # Reload after execution
            project = load_project(slug)

            detail = result.get("workstream", result.get("thread_id", ""))
            if result.get("verdict"):
                detail = f"{detail} ({result['verdict']})"

            if result.get("ok"):
                append_hub_reflection(agent_id, action, detail)
                action_counts[action] = action_counts.get(action, 0) + 1
                print(f"    → OK: {detail}")
            else:
                # Failed — fallback to discuss
                print(f"    → Failed: {result.get('reason', '?')}, falling back to discuss")
                fallback = execute_discuss(agent_id, project, slug)
                project = load_project(slug)
                if fallback.get("ok"):
                    append_hub_reflection(agent_id, "discuss",
                                          fallback.get("thread_id", ""))
                    action_counts["discuss"] = action_counts.get("discuss", 0) + 1

    print(f"[hub] Done. Actions: {action_counts}")
    return {"agents": len(selected), "actions": action_counts}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> dict:
    """Parse CLI arguments."""
    args = {"project": None, "agents": DEFAULT_AGENTS, "dry_run": DRY_RUN}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--project" and i + 1 < len(argv):
            args["project"] = argv[i + 1]
            i += 2
        elif argv[i] == "--agents" and i + 1 < len(argv):
            args["agents"] = int(argv[i + 1])
            i += 2
        elif argv[i] == "--dry-run":
            args["dry_run"] = True
            i += 1
        else:
            i += 1
    return args


def main():
    """Entry point."""
    args = parse_args()

    if not args["project"]:
        print("Usage: python scripts/rappterhub.py --project <slug> [--agents N] [--dry-run]")
        sys.exit(1)

    global DRY_RUN
    DRY_RUN = args["dry_run"]

    if DRY_RUN:
        print("[hub] DRY RUN — no LLM calls")

    run_hub(args["project"], args["agents"])


if __name__ == "__main__":
    main()
