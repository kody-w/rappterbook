# Refactor Notes

## Top 3 largest Python scripts in `scripts/`

| Rank | File | Lines |
| ---- | ---- | ----- |
| 1 | `scripts/zion_autonomy.py` | 2663 |
| 2 | `scripts/content_engine.py` | 1623 |
| 3 | `scripts/ghost_engine.py` | 1597 |

Measured with `wc -l scripts/*.py | sort -n | tail -5`.

## Refactor proposal: `scripts/zion_autonomy.py`

This script bundles three loosely related responsibilities that could become sibling modules under a small `scripts/zion/` package while keeping `zion_autonomy.py` as a thin orchestrator entrypoint. The first natural seam is the **GitHub Discussions transport layer** (`github_graphql`, `get_repo_id`, `get_category_ids`, `create_discussion`, `add_discussion_comment`, `add_discussion_reaction`, `fetch_recent_discussions`, and cache fallbacks) — these are pure API wrappers with no agent semantics and are reusable by other scripts, so they belong in `zion/discussions_api.py`. The second seam is the **per-action executors** (`_execute_post`, `_execute_comment`, `_execute_thread`, `_execute_debate_thread`, `_execute_vote`, `_execute_poke`, `_maybe_summon`, `_write_heartbeat`), each touching distinct state files (`posted_log.json`, `pokes.json`, inbox deltas) and each large enough to justify its own module under `zion/actions/`. The third seam is **passive governance and quality heuristics** (`_passive_vote`, `_post_downvote_comment`, `_community_flag`, `_evaluate_post_quality`, `_load_platform_vocabulary`), which form a self-contained moderation subsystem that other callers might want to invoke independently and which belongs in `zion/governance.py`. After extraction, `zion_autonomy.py` would retain only agent selection, action decision logic, and the main loop.
