# brainstem_swarms

Shareable converged-swarm agents for **RAPP-format brainstems** (the
`BasicAgent` + `metadata` + `perform()` contract — distinct from the
rappterbook brainstem under `scripts/brainstem/agents/` which uses the
`AGENT` dict + `run()` contract).

Each file here is a single-file converged swarm: multiple internal
personas (each with its own SOUL system prompt) collapsed into one
hot-loadable agent file. Same pattern as the BookFactory swarm shipped
in the RAPP store.

## Installing into a RAPP brainstem

Copy the file into the brainstem's `agents/` directory; on next request
the brainstem auto-discovers it.

```bash
# For a project-local brainstem (RAPP installer with --here):
cp brainstem_swarms/variant_factory_agent.py \
   .brainstem/src/rapp_brainstem/agents/

# For the global brainstem:
cp brainstem_swarms/variant_factory_agent.py \
   ~/.brainstem/src/rapp_brainstem/agents/
```

Restart the brainstem (or wait for the next /chat request — `load_agents()`
re-globs the agents dir each call). Then verify with `brainstem ls`
(once kody-w/RAPP#10 lands) or by calling the swarm via `/chat`.

## Available swarms

### `variant_factory_agent.py` — VariantFactory

Run a complete variant-design / simulate / score / pick bake-off in one
tool call. Four internal personas:

  1. **VariantDesigner**  — proposes N distinct variant configurations
  2. **VariantSimulator** — produces a Dream-Catcher stream delta per variant
  3. **VariantScorer**    — computes per-metric scores across all variants
  4. **VariantPicker**    — chooses the composite winner with rationale

Public entrypoint: `VariantFactory.perform(target, metric, n_variants, frame, workspace)`.
The composite scoring formula matches `scripts/bakeoff_score.py` so this
swarm's recommendation is directly comparable to a CLI-driven bakeoff.

Example chat invocation (paste into the brainstem UI):

> Run a variant factory bakeoff for the rappterbook standalone agent.py.
> The target metric is comments_per_stream — engagement is currently weak.
> Design 5 variants and pick a winner.

The brainstem's tool-calling LLM will route to `VariantFactory.perform()`.
Intermediate artifacts land in `/tmp/variant-factory/` (or whatever
`workspace=` you pass).

## Contract notes

These swarms target the RAPP brainstem contract specifically:

- `from agents.basic_agent import BasicAgent`
- `from utils.llm import call_llm` (with offline fallback for testing)
- Public class extends `BasicAgent`, has `metadata` dict + `perform(**kwargs)`
- Internal classes prefixed with `_Internal*` are excluded from auto-discovery
- File name must end in `_agent.py` to match the brainstem's glob

If the brainstem is unauthenticated (Copilot 401), `call_llm` will fail
and `_llm_call` returns an `[llm error]` string per persona — the swarm
still loads, the failure surfaces in the orchestrator's response. Run
`./.brainstem/start.sh login` once interactively to authenticate.
