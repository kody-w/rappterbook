#!/usr/bin/env python3
"""Parse seed-trigger events without evaluating event data as shell source."""
from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from pathlib import Path


def parse_discussion_event(event: dict) -> dict[str, str]:
    """Return normalized seed inputs from a Discussion event."""
    discussion = event.get("discussion", {})
    title = str(discussion.get("title") or "")
    seed_text = re.sub(r"^\[BUILD\]\s*", "", title).strip()
    number = str(discussion.get("number") or "")
    author = str((discussion.get("user") or {}).get("login") or "unknown")
    body = str(discussion.get("body") or "")
    if not seed_text or not number:
        raise ValueError("Discussion event is missing a seed title or number")
    return {
        "seed_text": seed_text,
        "context": f"From discussion #{number} by {author}. {body}",
        "tags": "artifact,code,build",
        "source": f"discussion-{number}",
        "event_number": number,
    }


def parse_issue_event(event: dict) -> dict[str, str]:
    """Return normalized seed inputs from an Issue event."""
    issue = event.get("issue", {})
    title = str(issue.get("title") or "")
    seed_text = re.sub(r"^SEED:\s*", "", title, flags=re.IGNORECASE).strip()
    number = str(issue.get("number") or "")
    body = str(issue.get("body") or "")
    labels = []
    for label in issue.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if name and str(name).lower() != "seed":
            labels.append(str(name))
    if not seed_text or not number:
        raise ValueError("Issue event is missing a seed title or number")
    return {
        "seed_text": seed_text,
        "context": body,
        "tags": ",".join(labels),
        "source": f"github-issue-{number}",
        "event_number": number,
    }


def write_github_outputs(values: dict[str, str], output_path: Path) -> None:
    """Append values to GITHUB_OUTPUT using collision-resistant delimiters."""
    with output_path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            delimiter = f"RB_{uuid.uuid4().hex}"
            while delimiter in value:
                delimiter = f"RB_{uuid.uuid4().hex}"
            output.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def main() -> int:
    """Parse one GitHub event and emit safe step outputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("event_type", choices=("discussion", "issue"))
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()
    if not args.event or not args.output:
        parser.error("GITHUB_EVENT_PATH and GITHUB_OUTPUT are required")

    event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    if args.event_type == "discussion":
        values = parse_discussion_event(event)
    else:
        values = parse_issue_event(event)
    write_github_outputs(values, Path(args.output))
    print(f"Parsed {args.event_type} seed event #{values['event_number']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
