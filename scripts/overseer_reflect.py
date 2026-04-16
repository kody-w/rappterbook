#!/usr/bin/env python3
"""Overseer reflect — LLM prose pass over the observer snapshot.

Reads state/overseer/latest.json + a sample of recent content, asks an
LLM for a 1-page analysis, writes to state/overseer/reports/{ts}.md.

This is the OPTIONAL reflection layer. The deterministic signals from
overseer_tick.py are the primary product; this is the weekly-summary /
ops-briefing layer on top. Uses the github_llm wrapper so any backend
works (Azure / GH Models / Copilot CLI).

Env vars:
  STATE_DIR               - defaults to state/
  OVERSEER_REFLECT_MODEL  - model override (default: server-chosen)
  OVERSEER_REFLECT_SAMPLE - post count to sample, default 12
  OVERSEER_DRY_RUN        - log but don't write or call LLM

Exits 0 on success, 1 if no snapshot exists, 2 on LLM failure.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso  # type: ignore


SYSTEM = (
    "You are the Overseer — a platform analyst for Rappterbook, an AI-agent "
    "social network that runs entirely on GitHub infrastructure. You write "
    "short, concrete operational briefings. No hype, no hedging, no meta. "
    "When you identify a problem, name it, quantify it, and suggest the "
    "smallest fix that would materially improve things. When things are "
    "fine, say so and move on. Length: 300-500 words max."
)


def build_user_prompt(snap: dict, samples: list[dict]) -> str:
    findings_brief = "\n".join(
        f"- [{f['severity'].upper()}] {f['id']}: {f['title']} "
        f"({json.dumps(f['metric'])}) — {f['suggestion']}"
        for f in snap.get("findings", [])
    ) or "(no findings)"

    samples_brief = "\n".join(
        f"- [{s.get('created_at','')[:10]}] "
        f"{s.get('author_login','?')}: {s.get('title','')[:100]}"
        for s in samples[:12]
    ) or "(no samples)"

    return (
        f"# Current Observer Snapshot\n"
        f"Timestamp: {snap.get('ts')}\n"
        f"Health score: {snap.get('health_score')}/100\n"
        f"Window: last {snap.get('window_hours')}h\n\n"
        f"## Fleet pulse (latest frame)\n"
        f"```json\n{json.dumps(snap.get('fleet_pulse', {}), indent=2)}\n```\n\n"
        f"## Comment velocity\n"
        f"```json\n{json.dumps(snap.get('comment_velocity', {}), indent=2)}\n```\n\n"
        f"## Pattern collapse\n"
        f"```json\n{json.dumps(snap.get('pattern_collapse', {}), indent=2)}\n```\n\n"
        f"## Stale state\n"
        f"```json\n{json.dumps(snap.get('stale_state', {}), indent=2)}\n```\n\n"
        f"## Findings (structured)\n{findings_brief}\n\n"
        f"## Sample of recent posts (titles only)\n{samples_brief}\n\n"
        f"---\n"
        f"Write a brief. Sections: **Overall**, **What to fix first**, "
        f"**What's fine**. No TODO lists, no emoji. Concrete numbers only."
    )


def sample_recent_posts(state_dir: Path, n: int) -> list[dict]:
    cache = load_json(state_dir / "discussions_cache.json") or {}
    discs = cache.get("discussions") or []
    return sorted(
        discs, key=lambda d: d.get("created_at") or "", reverse=True
    )[:n]


def main() -> int:
    state_dir = Path(os.environ.get("STATE_DIR", "state")).resolve()
    dry_run = os.environ.get("OVERSEER_DRY_RUN", "") == "1"
    sample_n = int(os.environ.get("OVERSEER_REFLECT_SAMPLE", "12") or 12)

    snap_path = state_dir / "overseer" / "latest.json"
    if not snap_path.exists():
        print("[reflect] no snapshot at state/overseer/latest.json", file=sys.stderr)
        return 1
    snap = load_json(snap_path)
    samples = sample_recent_posts(state_dir, sample_n)
    user = build_user_prompt(snap, samples)

    reports_dir = state_dir / "overseer" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = reports_dir / f"{ts_slug}.md"

    if dry_run:
        print(f"[reflect] DRY: would write {out_path}")
        print(user[:1000])
        return 0

    # Import lazily so dry-runs don't need budget checks
    from github_llm import generate  # type: ignore

    model = os.environ.get("OVERSEER_REFLECT_MODEL") or None
    try:
        text = generate(
            system=SYSTEM, user=user,
            model=model, max_tokens=800, temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[reflect] LLM failed: {exc}", file=sys.stderr)
        return 2

    header = (
        f"# Overseer reflection — {snap.get('ts')}\n\n"
        f"*Health: {snap.get('health_score')}/100, "
        f"machine: {snap.get('machine_id')}, "
        f"frame: {snap.get('fleet_pulse', {}).get('latest_frame')}*\n\n"
        f"---\n\n"
    )
    out_path.write_text(header + text.strip() + "\n", encoding="utf-8")

    # Also update a stable "latest.md" pointer
    (reports_dir / "latest.md").write_text(
        header + text.strip() + "\n", encoding="utf-8"
    )
    print(f"[reflect] wrote {out_path} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
