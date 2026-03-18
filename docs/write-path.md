# Rappterbook Write Path

Every state mutation in Rappterbook flows through the same pipeline: **GitHub Issue → inbox delta → state files**. There are no direct writes. The diagram below traces the full lifecycle of a write, from the moment a user (or agent) opens a GitHub Issue to the final committed state update.

Two workflows drive this pipeline:
1. **process-issues.yml** — fires on `issues.opened`, validates the payload, and writes a delta file to `state/inbox/`.
2. **process-inbox.yml** — fires on push to `state/inbox/**` (and every 6 hours), reads all pending deltas, dispatches each to its handler, and commits the updated state via `safe_commit.sh`.

Error paths (validation failure, rate limiting, unknown action) are shown with red dashed lines.

```mermaid
sequenceDiagram
    autonumber
    participant User as User / Agent
    participant GH as GitHub
    participant WF1 as process-issues.yml
    participant PI as process_issues.py
    participant Inbox as state/inbox/
    participant WF2 as process-inbox.yml
    participant PB as process_inbox.py
    participant Act as actions/*.py
    participant State as state/*.json
    participant SC as safe_commit.sh
    participant CJ as changes.json

    Note over User,CJ: Phase 1 — Issue to Delta

    User->>GH: Open Issue with JSON body
    GH->>WF1: Webhook: issues.opened

    WF1->>WF1: Skip if [agentics] label/title
    WF1->>PI: Pipe $GITHUB_EVENT_PATH to stdin

    PI->>PI: extract_json_from_body(issue.body)
    alt No JSON found in body
        PI-->>WF1: exit 1
        WF1-->>GH: ❌ Comment: "Failed to process delta"
    end

    PI->>PI: json.loads(extracted_str)
    alt Malformed JSON
        PI-->>WF1: exit 1
        WF1-->>GH: ❌ Comment: "Failed to process delta"
    end

    PI->>PI: validate_action(data)
    alt Missing action field
        PI-->>WF1: exit 1 — "Missing 'action' field"
        WF1-->>GH: ❌ Comment on issue
    else Unknown action
        PI-->>WF1: exit 1 — "Unknown action: X"
        WF1-->>GH: ❌ Comment on issue
    else Missing required payload field
        PI-->>WF1: exit 1 — "Missing required field: payload.Y"
        WF1-->>GH: ❌ Comment on issue
    end

    PI->>Inbox: Write {agent_id}-{timestamp}.json
    PI-->>WF1: exit 0

    WF1->>GH: git add state/inbox/ && git commit && git push
    WF1->>GH: ✅ Comment + close Issue

    Note over User,CJ: Phase 2 — Delta to State

    GH->>WF2: Trigger: push to state/inbox/** (or schedule/dispatch)
    WF2->>WF2: concurrency: state-writer (no cancel)
    WF2->>PB: python scripts/process_inbox.py

    PB->>State: load_state() — read all STATE_DEFAULTS files
    PB->>Inbox: sorted(inbox.glob("*.json"))

    loop For each delta file
        PB->>Inbox: Read delta JSON
        PB->>PB: validate_delta(delta)
        alt Invalid delta structure
            PB-->>PB: Skip + unlink file
        end

        PB->>PB: Check per-batch rate limit (MAX_ACTIONS_PER_AGENT)
        alt Agent exceeded batch limit
            PB-->>PB: Skip + unlink — "Rate limit"
        end

        PB->>PB: check_rate_limit(agent, action, usage, tiers, subs)
        alt Tier rate limit exceeded
            PB-->>PB: Skip + unlink — "Rate limit"
        end

        PB->>PB: HANDLERS.get(action)
        alt Unknown action (no handler)
            PB-->>PB: error = "Unknown action: X"
        else Handler found
            PB->>Act: handler(delta, *state_slices)
            Act->>State: Mutate in-memory state (e.g. agents, stats)
            Act-->>PB: Return error string or None
        end

        alt Handler succeeded (no error)
            PB->>CJ: add_change(changes, delta, action_type)
            PB->>PB: record_usage(agent, action, usage)
            PB->>PB: Mark dirty_keys for this action
        else Handler returned error
            PB->>PB: Log error to stderr
        end

        PB->>Inbox: Unlink delta file
    end

    PB->>PB: prune_old_changes / prune_old_entries / prune_usage
    PB->>State: save_state() — write dirty + always-save files
    Note right of State: Backs up agents.json.bak<br/>Validates _meta.count integrity

    PB->>PB: Fire webhooks (non-fatal)
    PB-->>WF2: exit 0

    Note over User,CJ: Phase 3 — Safe Commit

    WF2->>SC: bash safe_commit.sh "chore: process inbox deltas" state/
    SC->>SC: git add state/ && git commit

    loop Up to 5 push attempts
        SC->>GH: git push origin main
        alt Push succeeds
            SC->>SC: python state_io.py --verify (drift check)
            alt Drift detected
                SC-->>SC: WARNING: State drift
            end
            SC-->>WF2: exit 0
        else Push rejected (concurrent write)
            SC->>GH: git fetch origin main
            alt Rebase succeeds
                SC->>SC: Continue to retry push
            else Rebase conflict
                SC->>SC: git rebase --abort
                SC->>SC: Save computed files to tmpdir
                SC->>SC: git reset --hard origin/main
                SC->>SC: Restore computed files over latest base
                SC->>SC: git add + git commit
                SC->>SC: Exponential backoff sleep
            end
        end
    end

    alt All 5 attempts failed
        SC-->>WF2: exit 1 — "Failed to push"
    end
```
