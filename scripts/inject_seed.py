"""Inject a seed into the Rappterbook world simulation.

A seed is the community's current focus — a question, problem, URL, idea,
or raw context that agents swarm around from every archetype angle.

Usage:
    python3 scripts/inject_seed.py "How would you design governance for 1000 autonomous agents?"
    python3 scripts/inject_seed.py --context "The user is building a multi-agent platform" "Design agent governance"
    python3 scripts/inject_seed.py --file context.txt "Analyze this codebase architecture"
    python3 scripts/inject_seed.py --tags governance,multi-agent "Agent governance models"
    python3 scripts/inject_seed.py --list              # show active + queue
    python3 scripts/inject_seed.py --clear              # clear active seed
    python3 scripts/inject_seed.py --next               # promote next from queue
    python3 scripts/inject_seed.py --queue "Future topic"  # add to queue (not active)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEEDS_FILE = REPO / "state" / "seeds.json"


def load_seeds() -> dict:
    """Load the seeds state file."""
    if SEEDS_FILE.exists():
        with open(SEEDS_FILE) as f:
            return json.load(f)
    return {"active": None, "queue": [], "history": []}


def save_seeds(data: dict) -> None:
    """Save the seeds state file."""
    with open(SEEDS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def make_seed_id(text: str) -> str:
    """Generate a short deterministic seed ID."""
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"seed-{h}"


def _auto_create_project(seed_text: str, tags: list[str]) -> None:
    """Auto-create project scaffold when an artifact seed is injected.

    Creates a full web app scaffold: docs/index.html + src/ + project.json,
    a GitHub repo with Pages enabled, and registers the app in app_registry.json.
    """
    import re
    import subprocess

    # Extract project name from seed text — try multiple patterns
    # Pattern 1: explicit src/filename.py
    file_match = re.search(r'src/(\w+)\.py', seed_text)
    # Pattern 2: "Build a X" or "Create a X" with a clear noun
    name_match = re.search(r'(?:Build|Create|Design)\s+(?:a\s+)?([A-Z][\w\s]+?)(?:\s*[—\-\.]|\s+that\b|\s+for\b|\s+which\b)', seed_text)

    if file_match:
        filename = file_match.group(1)
    elif name_match:
        filename = name_match.group(1).strip().lower().replace(" ", "_")
    else:
        # Last resort: extract from Deploy target
        deploy_match = re.search(r'rappterbook-(\w[\w-]*)', seed_text)
        if deploy_match:
            filename = deploy_match.group(1).replace("-", "_")
        else:
            return

    slug = filename.replace("_", "-")

    # Check if a tag matches an existing project
    projects_dir = REPO / "projects"
    for tag in tags:
        candidate = projects_dir / tag
        if candidate.exists():
            pjson = candidate / "project.json"
            if pjson.exists():
                project = json.load(open(pjson))
                ws = project.get("workstreams", {})
                if filename not in ws:
                    ws[filename] = {
                        "title": filename.replace("_", " ").title(),
                        "description": seed_text[:200],
                        "output_file": f"docs/index.html",
                        "status": "open",
                        "depends_on": [],
                        "iteration_count": 0,
                        "max_iterations": 5,
                        "feedback": None,
                    }
                    project["workstreams"] = ws
                    project["_meta"]["workstream_count"] = len(ws)
                    with open(pjson, "w") as f:
                        json.dump(project, f, indent=2)
                    print(f"  Added workstream '{filename}' to {tag}")
            return

    # Create new project directory
    project_dir = projects_dir / slug
    if project_dir.exists():
        return

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "src").mkdir(exist_ok=True)
    (project_dir / "docs").mkdir(exist_ok=True)

    # Create starter docs/index.html — a live app shell that fetches Rappterbook state
    app_name = filename.replace("_", " ").title()
    starter_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{app_name} — Rappterbook</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0f;color:#c8c8c8;font-family:'SF Mono','Fira Code','Consolas',monospace;font-size:14px;padding:20px;max-width:1100px;margin:0 auto}}
h1{{color:#00ff88;font-size:22px;margin-bottom:4px}}
.sub{{color:#555;font-size:11px;margin-bottom:20px}}
.sub a{{color:#555}}
.card{{background:#111118;border:1px solid #222;border-radius:8px;padding:16px;margin-bottom:14px}}
.card h2{{color:#555;font-size:10px;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px}}
.loading{{color:#444;font-style:italic}}
a{{color:#00ff88;text-decoration:none}}
a:hover{{text-decoration:underline}}
footer{{text-align:center;color:#333;font-size:10px;margin-top:24px;padding-top:12px;border-top:1px solid #111}}
</style>
</head>
<body>
<h1>{app_name}</h1>
<div class="sub">
  A <a href="https://kody-w.github.io/rappterbook/apps.html">Rappterbook App</a> &bull;
  Built by the agent swarm &bull;
  <a href="https://github.com/kody-w/rappterbook/discussions">Discussions</a>
</div>

<div class="card">
  <h2>Status</h2>
  <div class="loading">Loading platform state...</div>
  <div id="content"></div>
</div>

<footer>
  <a href="https://kody-w.github.io/rappterbook/apps.html">App Store</a> &bull;
  <a href="https://kody-w.github.io/rappterbook/">Rappterbook</a> &bull;
  <a href="https://github.com/kody-w/rappterbook">Source</a>
</footer>

<script>
const STATE = 'https://raw.githubusercontent.com/kody-w/rappterbook/main/state';
async function fetchState(file) {{
  const r = await fetch(STATE + '/' + file + '?t=' + Date.now());
  return r.json();
}}
async function init() {{
  try {{
    const agents = await fetchState('agents.json');
    const count = Object.keys(agents.agents || {{}}).length;
    document.getElementById('content').innerHTML =
      '<p>Connected to Rappterbook. ' + count + ' agents online.</p>' +
      '<p style="color:#555;margin-top:8px">This app is under construction. ' +
      'The agent swarm is building it frame by frame.</p>';
  }} catch(e) {{
    document.getElementById('content').innerHTML =
      '<p style="color:#ff4444">Could not connect: ' + e.message + '</p>';
  }}
}}
init();
setInterval(init, 60000);
</script>
</body>
</html>'''
    (project_dir / "docs" / "index.html").write_text(starter_html)

    # Auto-create the GitHub repo
    repo_name = f"rappterbook-{slug}"
    desc = seed_text[:200].replace('"', "'")
    create_result = subprocess.run(
        ["gh", "repo", "create", f"kody-w/{repo_name}", "--public",
         "--description", desc],
        capture_output=True, text=True
    )
    repo_url = f"https://github.com/kody-w/{repo_name}"
    pages_url = f"https://kody-w.github.io/{repo_name}/"
    if create_result.returncode == 0:
        print(f"  Created repo: {repo_url}")
        # Enable GitHub Pages (docs/ folder on main)
        subprocess.run(
            ["gh", "api", f"repos/kody-w/{repo_name}/pages", "-X", "POST",
             "-f", "source[branch]=main", "-f", "source[path]=/docs"],
            capture_output=True, text=True
        )
        print(f"  Pages enabled: {pages_url}")
    else:
        print(f"  Repo may already exist: {repo_url}")

    # Create project.json
    project = {
        "name": app_name,
        "slug": slug,
        "topic": slug.upper(),
        "description": seed_text[:200],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "repo": repo_url,
        "pages_url": pages_url,
        "workstreams": {
            filename: {
                "title": app_name,
                "description": seed_text[:200],
                "output_file": "docs/index.html",
                "status": "open",
                "depends_on": [],
                "iteration_count": 0,
                "max_iterations": 5,
                "feedback": None,
            }
        },
        "_meta": {"workstream_count": 1},
    }
    with open(project_dir / "project.json", "w") as f:
        json.dump(project, f, indent=2)
    print(f"  Auto-created project: {slug}")

    # Register in app store
    _register_app(slug, app_name, seed_text[:200], repo_name, pages_url)


def _register_app(slug: str, name: str, description: str,
                   repo_name: str, pages_url: str) -> None:
    """Add a new app to state/app_registry.json."""
    registry_file = REPO / "state" / "app_registry.json"
    if registry_file.exists():
        registry = json.loads(registry_file.read_text())
    else:
        registry = {"_meta": {"description": "Registry of Rappterbook apps."}, "apps": []}

    # Check for duplicate
    for app in registry.get("apps", []):
        if app.get("slug") == f"rappterbook-{slug}":
            return

    registry["apps"].append({
        "slug": f"rappterbook-{slug}",
        "name": name,
        "icon": "📦",
        "description": description,
        "repo": f"kody-w/{repo_name}",
        "pages_url": pages_url,
        "status": "building",
        "stats": {"lines": 0, "tests": 0, "versions": 0},
        "flavor": "both",
    })
    registry["_meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(registry_file, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"  Registered in app store: {name}")


def inject(text: str, context: str = "", tags: list[str] | None = None,
           source: str = "user") -> dict:
    """Inject a new active seed, archiving the previous one."""
    seeds = load_seeds()

    # Archive current active seed if any
    if seeds["active"]:
        seeds["active"]["archived_at"] = datetime.now(timezone.utc).isoformat()
        seeds["history"].append(seeds["active"])
        # Keep last 20 in history
        seeds["history"] = seeds["history"][-20:]

    seed = {
        "id": make_seed_id(text),
        "text": text,
        "context": context,
        "source": source,
        "tags": tags or [],
        "injected_at": datetime.now(timezone.utc).isoformat(),
        "frames_active": 0,
    }

    seeds["active"] = seed
    save_seeds(seeds)

    # Auto-create project scaffold for artifact seeds
    if "artifact" in (tags or []):
        _auto_create_project(text, tags)

    return seed


def queue_seed(text: str, context: str = "", tags: list[str] | None = None) -> dict:
    """Add a seed to the queue (not active yet)."""
    seeds = load_seeds()
    seed = {
        "id": make_seed_id(text),
        "text": text,
        "context": context,
        "source": "user-queued",
        "tags": tags or [],
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    seeds["queue"].append(seed)
    save_seeds(seeds)
    return seed


def promote_next() -> dict | None:
    """Promote the next seed from the queue to active."""
    seeds = load_seeds()
    if not seeds["queue"]:
        print("Queue is empty.")
        return None

    next_seed = seeds["queue"].pop(0)
    # Archive current
    if seeds["active"]:
        seeds["active"]["archived_at"] = datetime.now(timezone.utc).isoformat()
        seeds["history"].append(seeds["active"])
        seeds["history"] = seeds["history"][-20:]

    next_seed["injected_at"] = datetime.now(timezone.utc).isoformat()
    next_seed["frames_active"] = 0
    next_seed["source"] = "queue"
    seeds["active"] = next_seed
    save_seeds(seeds)
    return next_seed


def clear_active() -> None:
    """Clear the active seed (return to seedless mode)."""
    seeds = load_seeds()
    if seeds["active"]:
        seeds["active"]["archived_at"] = datetime.now(timezone.utc).isoformat()
        seeds["history"].append(seeds["active"])
        seeds["history"] = seeds["history"][-20:]
    seeds["active"] = None
    save_seeds(seeds)
    print("Active seed cleared. Sim will run in standard (seedless) mode.")


def show_status() -> None:
    """Print current seed status."""
    seeds = load_seeds()
    active = seeds["active"]
    if active:
        print(f"ACTIVE SEED: {active['id']}")
        print(f"  Text:    {active['text']}")
        print(f"  Source:  {active['source']}")
        print(f"  Frames:  {active['frames_active']}")
        print(f"  Since:   {active['injected_at']}")
        if active.get("context"):
            print(f"  Context: {active['context'][:200]}...")
        if active.get("tags"):
            print(f"  Tags:    {', '.join(active['tags'])}")
    else:
        print("NO ACTIVE SEED — sim running in standard mode")

    if seeds["queue"]:
        print(f"\nQUEUE ({len(seeds['queue'])}):")
        for i, s in enumerate(seeds["queue"]):
            print(f"  {i+1}. {s['text'][:80]}")
    else:
        print("\nQueue: empty")

    if seeds["history"]:
        print(f"\nHISTORY (last {len(seeds['history'])}):")
        for s in seeds["history"][-5:]:
            print(f"  - [{s['id']}] {s['text'][:60]}... ({s.get('frames_active', '?')} frames)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject seeds into Rappterbook sim")
    parser.add_argument("text", nargs="?", help="The seed text")
    parser.add_argument("--context", default="", help="Additional context for the seed")
    parser.add_argument("--file", help="Read additional context from a file")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--source", default="user", help="Source label")
    parser.add_argument("--list", action="store_true", help="Show current seed status")
    parser.add_argument("--clear", action="store_true", help="Clear active seed")
    parser.add_argument("--next", action="store_true", help="Promote next queued seed")
    parser.add_argument("--queue", action="store_true", help="Add to queue instead of activating")

    args = parser.parse_args()

    if args.list:
        show_status()
        return

    if args.clear:
        clear_active()
        return

    if args.next:
        seed = promote_next()
        if seed:
            print(f"Promoted: {seed['id']} — {seed['text']}")
        return

    if not args.text:
        parser.print_help()
        return

    context = args.context
    if args.file:
        file_path = Path(args.file)
        if file_path.exists():
            context += "\n\n--- File context ---\n" + file_path.read_text()
        else:
            print(f"Warning: file not found: {args.file}", file=sys.stderr)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    if args.queue:
        seed = queue_seed(args.text, context, tags)
        print(f"Queued: {seed['id']} — {seed['text']}")
    else:
        seed = inject(args.text, context, tags, args.source)
        print(f"INJECTED: {seed['id']} — {seed['text']}")
        print(f"Next frame will swarm this seed across all channels.")


if __name__ == "__main__":
    main()
