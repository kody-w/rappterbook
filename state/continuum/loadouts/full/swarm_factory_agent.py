"""
swarm_factory_agent.py — Build, install, generate, and manage RAPP swarms.

Actions:
  generate  — Design a brand-new single-file agent from scratch and persist it
  build     — Converge existing local agents into a single shareable .py singleton
  list      — Show available swarms in the RAPP Store
  install   — Pull a swarm from the RAPP Store into your agents/ dir
  uninstall — Remove an installed swarm

Usage:
  "Build me an agent that fetches today's NYT front page and summarizes it" → generate
  "Package my agents as a swarm called SalesBot"                            → build
  "What swarms are available in the RAPP Store?"                            → list
  "Install the BookFactory swarm"                                           → install
  "Uninstall BookFactory"                                                   → uninstall
"""

from agents.basic_agent import BasicAgent
import ast
import os
import re
import json
import hashlib
import glob
import urllib.request
import urllib.error


RAPP_STORE_CATALOG_URL = "https://raw.githubusercontent.com/kody-w/rapp_store/main/index.json"

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/swarm_factory",
    "display_name": "SwarmFactory",
    "description": "Build, install, list, and uninstall RAPP swarms. Converges local agents into shareable singletons and manages the RAPP Store catalog.",
    "author": "RAPP",
    "version": "0.2.0",
    "tags": ["meta", "build", "singleton", "swarm-factory", "store"],
    "category": "core",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {"action": "list"}},
}


class SwarmFactoryAgent(BasicAgent):
    def __init__(self):
        self.name = "SwarmFactory"
        self.metadata = {
            "name": "SwarmFactory",
            "description": (
                "Generate, build, install, list, and uninstall RAPP swarms.\n\n"
                "A SWARM is a multi-persona pipeline collapsed into ONE shareable "
                "agent file — like BookFactory (Writer→Editor→CEO→Publisher→Reviewer "
                "all inlined as _Internal* classes behind one public entrypoint). "
                "The point of a swarm is that each persona has its own SOUL/system "
                "prompt and the public composite calls them in sequence to do "
                "something no single agent could do in one shot.\n\n"
                "ROLE BOUNDARY (read this before choosing a tool):\n"
                " • Single one-shot agent (fetch xkcd, roll dice, lookup a stock "
                "price) → use the LearnNew tool with action='create'. Do NOT use "
                "SwarmFactory for these.\n"
                " • Multi-persona converged singleton (research→write→critique, "
                "plan→draft→review, write→edit→publish) → SwarmFactory.generate. "
                "This is the BookFactory pattern.\n"
                " • Already have a multi-file source tree of agents and want them "
                "collapsed into one shippable file → SwarmFactory.build.\n\n"
                "Actions:\n"
                " • 'generate' — Design a BRAND-NEW converged swarm from scratch. "
                "YOU (the LLM) compose the full Python source — multiple internal "
                "persona classes (each with its own SOUL) plus ONE public composite "
                "that orchestrates them — then call this tool with that code in "
                "'agent_code'. The result is a single file that hot-loads on the "
                "next request. If the request is for a single-persona agent, "
                "REFUSE this action and route the user to LearnNew.create.\n"
                " • 'build' — Converge EXISTING local agents (multi-file source "
                "tree under agents/) into a shareable singleton .py.\n"
                " • 'list' — Show available swarms in the RAPP Store.\n"
                " • 'install' — Pull a swarm from the store into agents/.\n"
                " • 'uninstall' — Remove an installed swarm.\n\n"
                "Memory architecture (each swarm picks its own — full control):\n"
                "Personas use AzureFileStorageManager().set_memory_context(<guid>) "
                "to read/write to a NAMESPACED memory file. The brainstem's local "
                "shim writes to .brainstem_data/memory/<guid>/user_memory.json "
                "for any non-default GUID, or shared_memories/memory.json when "
                "no GUID is set. So:\n"
                " • SHARED (one memory pool for whole swarm) — define a single\n"
                "   _SWARM_MEMORY_GUID = '<slug>-shared-v1' module constant; every\n"
                "   persona calls set_memory_context(_SWARM_MEMORY_GUID). Use when\n"
                "   personas need to see each other's notes (e.g. researcher→writer\n"
                "   pipeline where writer needs the research dump).\n"
                " • SEGMENTED (each persona private) — give each persona its own\n"
                "   constant: _SOUL_RESEARCHER_GUID = '<slug>-researcher-v1', etc.\n"
                "   Use when personas should NOT contaminate each other's memory\n"
                "   (e.g. a critic that should review fresh, with no prior bias).\n"
                " • MIXED (some share, others isolated) — define one shared GUID\n"
                "   for the personas that need to coordinate, separate GUIDs for\n"
                "   the ones that should stay independent. Common shape: research/\n"
                "   write share, critic/reviewer are isolated.\n"
                " • USER-SCOPED — let the caller pass user_guid via kwargs and pipe\n"
                "   it through. Use when memory should follow the END USER, not\n"
                "   the swarm itself (rare for swarms; common for single agents).\n"
                " • EPHEMERAL (no memory) — just don't import AzureFileStorageManager.\n"
                "Bake the GUIDs as MODULE CONSTANTS at code-write time (deterministic\n"
                "and portable — the singleton carries its own memory namespace when\n"
                "shared across machines). Don't generate at runtime.\n\n"
                "Required shape for 'generate' — a converged swarm singleton:\n"
                "    from agents.basic_agent import BasicAgent\n"
                "    from utils.azure_file_storage import AzureFileStorageManager  # only if memory needed\n"
                "    import json, os, urllib.request, urllib.error\n\n"
                "    __manifest__ = {\"schema\": \"rapp-agent/1.0\",\n"
                "                     \"name\": \"@user/<slug>\",\n"
                "                     \"tags\": [\"composite\", \"swarm-factory-generated\"],\n"
                "                     \"delegates_to_inlined\": [\"<persona1>\", \"<persona2>\", ...]}\n\n"
                "    # Each persona has its own SOUL — that's what makes them distinct.\n"
                "    _SOUL_RESEARCHER = \"You are a researcher. Find the 3 strongest\\n\"\\\n"
                "                        \"sources on the topic and quote them.\"\n"
                "    _SOUL_WRITER     = \"You are a writer. Turn research into 400 words\\n\"\\\n"
                "                        \"of clean prose. No fluff.\"\n"
                "    _SOUL_CRITIC     = \"You are a brutal critic. Cut anything weak.\"\n\n"
                "    # Canonical LLM shim — same as BookFactory's singleton\n"
                "    # (kody-w/rapp_store, bookfactory/singleton/bookfactory_agent.py).\n"
                "    # Routes through the brainstem's own dispatcher, which auto-\n"
                "    # detects provider: Copilot → Azure → OpenAI → Anthropic.\n"
                "    # The previous template only checked Azure/OpenAI envs and\n"
                "    # silently returned \"(no LLM configured)\" on Copilot-only\n"
                "    # setups, making every persona useless.\n"
                "    def _llm_call(soul, user_prompt):\n"
                "        messages = [{\"role\": \"system\", \"content\": soul},\n"
                "                    {\"role\": \"user\", \"content\": user_prompt}]\n"
                "        try:\n"
                "            from utils.llm import call_llm\n"
                "            return call_llm(messages)\n"
                "        except Exception as e:\n"
                "            return f\"(LLM dispatch error: {e})\"\n\n"
                "    # Internal personas — _Internal prefix keeps them out of\n"
                "    # the brainstem's *Agent auto-discovery, so only the public\n"
                "    # composite below shows up in the LLM's tool list.\n"
                "    class _InternalResearcher:\n"
                "        def perform(self, topic): return _llm_call(_SOUL_RESEARCHER, topic)\n"
                "    class _InternalWriter:\n"
                "        def perform(self, research): return _llm_call(_SOUL_WRITER, research)\n"
                "    class _InternalCritic:\n"
                "        def perform(self, draft):    return _llm_call(_SOUL_CRITIC, draft)\n\n"
                "    # Public entrypoint — the ONE class the brainstem discovers.\n"
                "    class <PascalCase>Agent(BasicAgent):\n"
                "        def __init__(self):\n"
                "            self.name = \"<PascalCase>\"\n"
                "            self.metadata = {\"name\": \"<PascalCase>\",\n"
                "                             \"description\": \"<what the swarm does — one line>\",\n"
                "                             \"parameters\": {\"type\": \"object\",\n"
                "                                            \"properties\": {\"topic\": {\"type\": \"string\"}},\n"
                "                                            \"required\": [\"topic\"]}}\n"
                "            super().__init__(self.name, self.metadata)\n"
                "        def perform(self, topic=\"\", **kwargs):\n"
                "            research = _InternalResearcher().perform(topic)\n"
                "            draft    = _InternalWriter().perform(research)\n"
                "            final    = _InternalCritic().perform(draft)\n"
                "            return json.dumps({\"status\": \"ok\",\n"
                "                               \"research\": research,\n"
                "                               \"draft\": draft,\n"
                "                               \"final\": final})\n\n"
                "Voting / decision-swarm patterns (read this if your swarm collects\n"
                "votes from N personas and picks one — the BookFactory pipeline doesn't\n"
                "vote, but trait-weighted decision swarms do):\n"
                " 1. PERSONA OUTPUT IS PROSE BY DEFAULT. An LLM persona prompted with\n"
                "    a SOUL like 'You are a trader. Pick an action.' will reply with a\n"
                "    full sentence ('I'd advocate for trade because...') — not a single\n"
                "    word. Comparing `response.strip().lower()` against an allowed-action\n"
                "    list never matches. Append an explicit one-word constraint to the\n"
                "    user prompt AND parse the response for the first allowed word:\n"
                "        def _extract_action(response, allowed):\n"
                "            for w in (response or '').lower().replace(',',' ').replace('.',' ').split():\n"
                "                if w in allowed: return w\n"
                "            return ''\n"
                " 2. TIE-BREAKING: `max(votes, key=...)` returns the FIRST item at the\n"
                "    max. Python dicts preserve insertion order — so if all personas\n"
                "    have equal weight (e.g. caller forgot to pass weights), persona #1\n"
                "    always wins and the swarm mode-collapses onto one action. Either\n"
                "    randomize ties (`random.choice([v for v in votes if v.weight==top])`)\n"
                "    or fall back to `random.choice(actions)` when all weights are the\n"
                "    default. Pre-fix discovery: a 5-persona rappterverse swarm picked\n"
                "    'trade' for every agent until tie-break randomness was added.\n"
                " 3. WEIGHT VALIDATION: If `traits` is the per-call weighting dict and\n"
                "    a caller passes None or {}, your swarm should detect that and use\n"
                "    `random.choice` rather than silently defaulting all weights to a\n"
                "    constant (which triggers #2).\n"
                " 4. FILTER OUT INVALID VOTES BEFORE WEIGHTING. If a persona returned\n"
                "    something not in your allowed-action list (parser miss, model hiccup),\n"
                "    drop that vote rather than letting an empty string become the winner.\n\n"
                "Memory pattern (drop into any persona that needs it):\n"
                "    # Module-level constants — deterministic GUIDs baked at\n"
                "    # code-write time. Pick one strategy per swarm:\n"
                "    _SHARED_MEM   = \"<slug>-shared-v1\"     # all personas see this\n"
                "    _RESEARCH_MEM = \"<slug>-researcher-v1\" # researcher private\n"
                "    _CRITIC_MEM   = \"<slug>-critic-v1\"     # critic private\n\n"
                "    class _InternalResearcher:\n"
                "        def perform(self, topic):\n"
                "            store = AzureFileStorageManager()\n"
                "            store.set_memory_context(_RESEARCH_MEM)  # private namespace\n"
                "            prior = store.read_json() or {}\n"
                "            # ...do work, optionally consulting prior...\n"
                "            note = _llm_call(_SOUL_RESEARCHER, topic)\n"
                "            prior[topic[:60]] = {\"note\": note, \"ts\": __import__('time').time()}\n"
                "            store.write_json(prior)\n"
                "            return note\n\n"
                "    # Same shape, but pointing at _SHARED_MEM means this persona\n"
                "    # reads/writes the swarm-wide pool (researcher's writes are\n"
                "    # visible to writer, etc.). Mix-and-match across personas\n"
                "    # to get the exact isolation profile this swarm needs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "build", "list", "install", "uninstall"],
                        "description": "generate (design+persist a new agent), build (package locals into a singleton), list (browse store), install (pull from store), uninstall (remove)"
                    },
                    "swarm_name": {
                        "type": "string",
                        "description": "PascalCase name for the new agent/swarm (generate, build) OR the swarm id/name (install, uninstall). Example: 'NytSummarizer'"
                    },
                    "description": {
                        "type": "string",
                        "description": "One-line description of what this agent/swarm does. Used in the agent's manifest and in the LLM-facing description so the LLM knows when to call it."
                    },
                    "agent_code": {
                        "type": "string",
                        "description": "REQUIRED for 'generate'. Full Python source for the new agent, top to bottom — imports, __manifest__ dict, the BasicAgent subclass with __init__/metadata/perform. Will be syntax-checked and contract-checked before persistence."
                    },
                    "exclude": {
                        "type": "string",
                        "description": "For 'build' only: comma-separated agent names to exclude. Built-in memory/factory agents are excluded automatically."
                    }
                },
                "required": ["action"]
            }
        }
        super().__init__(self.name, self.metadata)

    def _fetch_catalog(self):
        req = urllib.request.Request(RAPP_STORE_CATALOG_URL,
                                     headers={"User-Agent": "RAPP-SwarmFactory/0.2"})
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode())

    def _list_swarms(self):
        cat = self._fetch_catalog()
        rapps = cat.get("rapplications", [])
        swarms = [r for r in rapps
                  if (r.get("produced_by", {}).get("source_files_collapsed", 0) > 1
                      and not r.get("egg_url"))]
        results = []
        for s in swarms:
            results.append({
                "id": s.get("id"),
                "name": s.get("display_name") or s.get("name") or s.get("id"),
                "description": s.get("description", ""),
                "version": s.get("version", ""),
                "agents_collapsed": s.get("produced_by", {}).get("source_files_collapsed", 0),
                "singleton_filename": s.get("singleton_filename", ""),
            })
        return json.dumps({
            "status": "ok",
            "action": "list",
            "swarms": results,
            "count": len(results),
            "message": f"Found {len(results)} swarm(s) in the RAPP Store.",
        })

    def _install_swarm(self, swarm_name):
        if not swarm_name:
            return json.dumps({"status": "error",
                               "message": "Provide swarm_name to install (e.g. 'bookfactory')."})
        agents_dir = os.environ.get("AGENTS_PATH",
                        os.path.join(os.path.dirname(os.path.abspath(__file__))))
        cat = self._fetch_catalog()
        rapps = cat.get("rapplications", [])
        lookup = swarm_name.lower().replace(" ", "").replace("-", "").replace("_", "")
        entry = None
        for r in rapps:
            rid = (r.get("id") or "").lower().replace("-", "").replace("_", "")
            rname = (r.get("display_name") or r.get("name") or "").lower().replace(" ", "").replace("-", "").replace("_", "")
            if lookup in (rid, rname):
                entry = r
                break
        if not entry:
            return json.dumps({"status": "error",
                               "message": f"Swarm '{swarm_name}' not found in the RAPP Store."})
        url = entry.get("singleton_url")
        fname = entry.get("singleton_filename")
        if not url or not fname:
            return json.dumps({"status": "error",
                               "message": f"Catalog entry for '{swarm_name}' is missing singleton_url or filename."})
        req = urllib.request.Request(url, headers={"User-Agent": "RAPP-SwarmFactory/0.2"})
        body = urllib.request.urlopen(req, timeout=15).read()
        dest = os.path.join(agents_dir, fname)
        os.makedirs(agents_dir, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(body)
        return json.dumps({
            "status": "ok",
            "action": "install",
            "id": entry.get("id"),
            "filename": fname,
            "bytes": len(body),
            "destination": dest,
            "message": f"Installed '{entry.get('display_name') or entry.get('name') or entry.get('id')}' → agents/{fname} ({len(body)} bytes). It will load on the next request.",
        })

    def _generate_swarm(self, swarm_name, description, agent_code):
        # Validation gauntlet — refuse to write a file that won't load
        # cleanly. Every failure here returns a structured error the LLM
        # can read and retry with corrections, instead of "your agent
        # silently doesn't show up after restart" (the worst UX).
        if not swarm_name or not isinstance(swarm_name, str):
            return json.dumps({"status": "error",
                "message": "Provide swarm_name (PascalCase, e.g. 'NytSummarizer')."})
        if not agent_code or not isinstance(agent_code, str):
            return json.dumps({"status": "error",
                "message": "Provide agent_code — the full Python source for the new agent."})

        # Syntax check first — cheapest fail.
        try:
            tree = ast.parse(agent_code)
        except SyntaxError as e:
            return json.dumps({"status": "error",
                "message": f"agent_code has a SyntaxError on line {e.lineno}: {e.msg}",
                "lineno": e.lineno, "offset": e.offset})

        # Contract check: must define at least one class and a perform()
        # method on it. We don't enforce the BasicAgent base class via AST
        # because the import path could be aliased; the brainstem's loader
        # is the final word on whether it's a valid agent.
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        if not classes:
            return json.dumps({"status": "error",
                "message": "agent_code defines no classes. The agent must be a class extending BasicAgent."})

        # Role boundary: SwarmFactory.generate is for CONVERGED SWARMS
        # (multi-persona composites — BookFactory pattern). Single-class
        # one-shot agents (fetch xkcd, roll dice) belong to LearnNew.create.
        # Refuse here so the LLM gets a clear pointer to the right tool
        # instead of silently producing a non-swarm via the swarm-shaped
        # path. The "swarm" name actually means something this way.
        if len(classes) < 2:
            return json.dumps({"status": "error",
                "message": (
                    "agent_code has only one class — that's a single-persona "
                    "agent, not a swarm. SwarmFactory.generate is for converged "
                    "multi-persona pipelines (BookFactory pattern: Writer→Editor"
                    "→CEO→Publisher→Reviewer all inlined). For a single one-shot "
                    "agent, call the LearnNew tool with action='create' instead."
                ),
                "hint": "If this really IS a multi-persona swarm, split the work "
                        "into _Internal<Role> classes (one per persona) plus one "
                        "public BasicAgent composite that orchestrates them.",
                "class_count": len(classes)})
        # Identify the PUBLIC class — the one the brainstem loader will
        # discover. Heuristic: extends BasicAgent (or a subclass thereof)
        # by name AND doesn't start with `_Internal`. Internal persona
        # classes are called from inside the swarm, not by the brainstem,
        # so they can have any signature they want.
        def _is_public_agent(cls):
            if cls.name.startswith("_"):
                return False
            for base in cls.bases:
                # `class FooAgent(BasicAgent):` → base is Name("BasicAgent")
                # `class FooAgent(SomethingElse):` → could still be public
                # if SomethingElse extends BasicAgent. We only check by name
                # because the LLM might use any of these forms.
                if isinstance(base, ast.Name) and base.id == "BasicAgent":
                    return True
                if isinstance(base, ast.Attribute) and base.attr == "BasicAgent":
                    return True
            return False

        public_classes = [c for c in classes if _is_public_agent(c)]
        # Fall back: if no class explicitly extends BasicAgent, treat any
        # non-`_Internal*` class with a perform() as the public one.
        if not public_classes:
            public_classes = [c for c in classes if not c.name.startswith("_")]

        # Find a perform() on at least one public class (any class is fine
        # for the contract, but **kwargs validation only applies here).
        any_perform = any(
            isinstance(m, ast.FunctionDef) and m.name == "perform"
            for c in classes for m in c.body
        )
        if not any_perform:
            return json.dumps({"status": "error",
                "message": "No class defines perform(**kwargs). The brainstem won't know how to call this agent.",
                "hint": "Add `def perform(self, **kwargs): ...` (or with named params + **kwargs) to your public class."})

        # Validate **kwargs ONLY on public class's perform(). Internal
        # personas are called from inside the swarm with controlled args
        # so they don't need to absorb the brainstem's user_guid kwarg.
        public_perform = None
        public_class = None
        for c in public_classes:
            for m in c.body:
                if isinstance(m, ast.FunctionDef) and m.name == "perform":
                    public_perform = m
                    public_class = c
                    break
            if public_perform:
                break

        if public_perform and public_perform.args.kwarg is None:
            return json.dumps({"status": "error",
                "message": (
                    f"{public_class.name}.perform() must accept **kwargs. "
                    f"The brainstem always passes user_guid via kwargs, so a strict "
                    f"signature crashes with TypeError on first call."
                ),
                "hint": "Change the signature to e.g. `def perform(self, topic=\"\", **kwargs):`",
                "current_signature_args": [a.arg for a in public_perform.args.args]})

        if not public_perform:
            return json.dumps({"status": "error",
                "message": (
                    f"None of the public class(es) {[c.name for c in public_classes]} "
                    f"defines a perform() method. The brainstem invokes perform() on "
                    f"the discovered agent class — without it the agent is unreachable."
                ),
                "hint": "Move your top-level orchestrator into a class extending BasicAgent and give it a perform(self, **kwargs) method."})

        has_manifest = any(
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__manifest__" for t in n.targets)
            for n in tree.body
        )

        # Auto-inject the BasicAgent import if the LLM forgot it. The agent
        # contract says the class must extend BasicAgent, and the brainstem
        # loader expects this exact import path, so it's a safe fix-up.
        if "from agents.basic_agent import BasicAgent" not in agent_code:
            agent_code = "from agents.basic_agent import BasicAgent\n" + agent_code

        # Auto-inject the canonical _llm_call shim if the agent_code
        # references it but doesn't define it. Prevents the LLM from
        # forgetting and producing a NameError at first call. The shim
        # routes through the brainstem's own provider chain, so it works
        # on any auth setup the brainstem itself works on (Copilot/Azure/
        # OpenAI/Anthropic). Same pattern as BookFactory's singleton.
        references_llm_call = (
            "_llm_call(" in agent_code
            and not re.search(r"^\s*def\s+_llm_call\s*\(", agent_code, re.M)
        )
        if references_llm_call:
            agent_code = (
                "def _llm_call(soul, user_prompt):\n"
                "    \"\"\"Auto-injected by SwarmFactory — routes through the brainstem's own dispatcher.\"\"\"\n"
                "    messages = [{\"role\": \"system\", \"content\": soul},\n"
                "                {\"role\": \"user\", \"content\": user_prompt}]\n"
                "    try:\n"
                "        from utils.llm import call_llm\n"
                "        return call_llm(messages)\n"
                "    except Exception as e:\n"
                "        return f\"(LLM dispatch error: {e})\"\n\n\n"
                + agent_code
            )

        # Filename derives from the swarm_name slug — same convention as
        # the rest of the binder so it shows up in /agents/full and the UI
        # binder grid without special-casing. Refuse to overwrite an
        # existing file: the LLM should pick a fresh name on collision,
        # not silently clobber the user's work.
        slug = re.sub(r'[^a-z0-9]', '', swarm_name.lower())
        if not slug:
            return json.dumps({"status": "error",
                "message": "swarm_name produced an empty slug after stripping non-alphanumerics. Use letters/digits."})
        agents_dir = os.environ.get("AGENTS_PATH",
                        os.path.join(os.path.dirname(os.path.abspath(__file__))))
        os.makedirs(agents_dir, exist_ok=True)
        fname = f"{slug}_agent.py"
        dest = os.path.join(agents_dir, fname)
        if os.path.exists(dest):
            return json.dumps({"status": "error",
                "message": f"agents/{fname} already exists. Pick a different swarm_name or call uninstall first."})

        with open(dest, "w", encoding="utf-8") as f:
            f.write(agent_code)

        # Smoke-test the generated module by importing it. AST validation
        # catches syntax + class structure but misses runtime errors —
        # missing imports, NameError, undefined helpers. If import fails,
        # remove the broken file and return the error so the LLM can retry
        # with corrections. Otherwise the user's agents/ dir gets polluted
        # with non-loadable files that look "installed" but always crash.
        smoke_warnings = []
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"_swarm_factory_smoke_{slug}", dest)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # Find the agent class — heuristic matches the brainstem loader:
            # any class whose name ends with "Agent" and isn't BasicAgent.
            agent_cls = None
            for attr_name in dir(module):
                if attr_name.startswith("_") or attr_name == "BasicAgent":
                    continue
                obj = getattr(module, attr_name)
                if isinstance(obj, type) and attr_name.endswith("Agent"):
                    agent_cls = obj
                    break
            if not agent_cls:
                smoke_warnings.append(
                    "no class ending in 'Agent' was found at module level — "
                    "the brainstem loader may not discover this agent")
            else:
                # Try to instantiate (most agents do real work in __init__)
                try:
                    instance = agent_cls()
                    if not hasattr(instance, "perform"):
                        smoke_warnings.append(
                            f"{agent_cls.__name__} instantiated but has no .perform() method")
                except Exception as inst_err:
                    smoke_warnings.append(
                        f"{agent_cls.__name__}() raised {type(inst_err).__name__}: {inst_err}")
        except Exception as smoke_err:
            # Roll back: don't leave a broken file the brainstem will keep
            # failing to load every request.
            try:
                os.remove(dest)
            except OSError:
                pass
            return json.dumps({"status": "error",
                "message": (
                    f"agent_code passed AST checks but failed to import at runtime: "
                    f"{type(smoke_err).__name__}: {smoke_err}"
                ),
                "hint": (
                    "Common causes: missing import (e.g. urllib.error referenced but not imported), "
                    "module-level code that calls undefined helpers, or a top-level statement that "
                    "raises. Fix and re-call SwarmFactory.generate."
                ),
                "rolled_back": True})

        return json.dumps({
            "status": "ok",
            "action": "generate",
            "swarm_name": swarm_name,
            "filename": fname,
            "destination": dest,
            "bytes": len(agent_code),
            "lines": agent_code.count("\n") + 1,
            "has_manifest": has_manifest,
            "smoke_test": "passed" if not smoke_warnings else "passed_with_warnings",
            "smoke_warnings": smoke_warnings,
            "message": (
                f"Generated agents/{fname} ({len(agent_code)} bytes). "
                f"It loads automatically on the next request — no restart needed. "
                f"Try calling it from chat to confirm."
                + (f" WARNINGS: {'; '.join(smoke_warnings)}" if smoke_warnings else "")
            ),
        })

    def _uninstall_swarm(self, swarm_name):
        if not swarm_name:
            return json.dumps({"status": "error",
                               "message": "Provide swarm_name to uninstall."})
        agents_dir = os.environ.get("AGENTS_PATH",
                        os.path.join(os.path.dirname(os.path.abspath(__file__))))
        lookup = swarm_name.lower().replace(" ", "").replace("-", "").replace("_", "")
        for fname in sorted(os.listdir(agents_dir)):
            if not fname.endswith("_agent.py") or fname == "basic_agent.py":
                continue
            stem = fname.replace("_agent.py", "").replace("-", "").replace("_", "")
            if stem == lookup:
                path = os.path.join(agents_dir, fname)
                os.remove(path)
                return json.dumps({
                    "status": "ok",
                    "action": "uninstall",
                    "removed": fname,
                    "message": f"Removed agents/{fname}. It will no longer load.",
                })
        return json.dumps({"status": "error",
                           "message": f"No installed agent matching '{swarm_name}' found."})

    def perform(self, action="build", swarm_name="MySwarm", description="", exclude="",
                agent_code="", **kwargs):
        if action == "generate":
            return self._generate_swarm(swarm_name, description, agent_code)
        if action == "list":
            return self._list_swarms()
        if action == "install":
            return self._install_swarm(swarm_name)
        if action == "uninstall":
            return self._uninstall_swarm(swarm_name)

        agents_dir = os.environ.get("AGENTS_PATH",
                        os.path.join(os.path.dirname(os.path.abspath(__file__))))

        auto_exclude = {"SwarmFactory", "BasicAgent", "SaveMemory", "RecallMemory"}
        user_exclude = set(x.strip() for x in exclude.split(",") if x.strip())
        skip = auto_exclude | user_exclude

        agent_files = sorted(glob.glob(os.path.join(agents_dir, "*_agent.py")))

        sources = {}
        for path in agent_files:
            fname = os.path.basename(path)
            if fname == "basic_agent.py":
                continue
            try:
                src = open(path, encoding="utf-8").read()
                tree = ast.parse(src, filename=fname)
                classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
                           and n.name != "BasicAgent"]
                if not classes:
                    continue
                cls_name = classes[0].name
                if cls_name in skip or cls_name.replace("Agent", "") in skip:
                    continue
                sources[fname] = {
                    "src": src,
                    "tree": tree,
                    "class_name": cls_name,
                    "path": path,
                }
            except Exception:
                continue

        if not sources:
            return json.dumps({"status": "error",
                               "message": "No eligible agents found to converge."})

        slug = re.sub(r'[^a-z0-9]', '', swarm_name.lower())
        public_name = re.sub(r'[^A-Za-z0-9]', '', swarm_name)
        if not public_name:
            public_name = "MySwarm"

        # Detect which agents import other agents (composites vs leaves)
        import_map = {}
        for fname, info in sources.items():
            imports = set()
            for node in info["tree"].body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    s = ast.get_source_segment(info["src"], node) or ""
                    for other_fname, other_info in sources.items():
                        if other_info["class_name"] in s:
                            imports.add(other_info["class_name"])
            import_map[fname] = imports

        leaves = [f for f in sources if not import_map[f]]
        composites = [f for f in sources if import_map[f]]

        # Build rename table
        renames = {}
        for fname, info in sources.items():
            cn = info["class_name"]
            base = cn.replace("Agent", "") if cn.endswith("Agent") else cn
            renames[cn] = f"_Internal{base}"

        # Extract SOUL constants and helper functions from each file
        all_souls = []
        has_llm_helper = False
        llm_helper_src = ""
        post_helper_src = ""

        for fname in leaves + composites:
            info = sources[fname]
            src = info["src"]
            tree = info["tree"]
            stem = os.path.splitext(fname)[0].replace("_agent", "").upper().replace("-", "_")

            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == "SOUL":
                            seg = ast.get_source_segment(src, node)
                            if seg:
                                renamed = re.sub(r'^SOUL\s*=', f'_SOUL_{stem} =', seg)
                                all_souls.append((stem, renamed))

            if not has_llm_helper:
                m_llm = re.search(
                    r'(def _llm_call\b.*?)(?=\n(?:def |class |__manifest__|\Z))',
                    src, re.DOTALL)
                m_post = re.search(
                    r'(def _post\b.*?)(?=\n(?:def |class |__manifest__|\Z))',
                    src, re.DOTALL)
                if m_llm:
                    llm_helper_src = m_llm.group(1).rstrip()
                    has_llm_helper = True
                if m_post:
                    post_helper_src = m_post.group(1).rstrip()

        # Extract standalone module-level constants (not SOUL, not __manifest__)
        extra_constants = []
        for fname in leaves + composites:
            info = sources[fname]
            for node in info["tree"].body:
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id not in (
                                "SOUL", "__manifest__", "metadata"):
                            seg = ast.get_source_segment(info["src"], node)
                            if seg and len(seg) < 5000:
                                extra_constants.append(seg)
                if isinstance(node, ast.Assert):
                    seg = ast.get_source_segment(info["src"], node)
                    if seg:
                        extra_constants.append(seg)

        # Extract standalone helper functions (not _llm_call, _post)
        extra_helpers = []
        for fname in leaves + composites:
            info = sources[fname]
            for node in info["tree"].body:
                if isinstance(node, ast.FunctionDef) and node.name not in (
                        "_llm_call", "_post", "perform"):
                    seg = ast.get_source_segment(info["src"], node)
                    if seg:
                        extra_helpers.append(seg)

        # Now build the singleton
        out = f'"""\n{slug}_agent.py — {public_name} singleton.\n\n'
        out += f'{description or "A converged RAPP swarm."}\n\n'
        out += 'Drop this file into any RAPP brainstem\'s agents/ directory and it works.\n'
        out += f'Generated by SwarmFactory from {len(sources)} source agents.\n\n'
        out += 'Inlined agents:\n'
        for fname, info in sources.items():
            out += f'  - {info["class_name"]}\n'
        out += '"""\n\n'
        out += 'from agents.basic_agent import BasicAgent\n'
        out += 'import json\nimport os\nimport re\nimport hashlib\n'
        out += 'import urllib.request\nimport urllib.error\n\n\n'

        delegates = [f'@rapp/{info["class_name"].replace("Agent","").lower()}'
                      for info in sources.values()]
        out += f'__manifest__ = {{\n'
        out += f'    "schema": "rapp-agent/1.0",\n'
        out += f'    "name": "@rapp/{slug}-singleton",\n'
        out += f'    "version": "0.1.0",\n'
        out += f'    "tags": ["composite", "singleton", "swarm-factory-generated"],\n'
        out += f'    "delegates_to_inlined": {json.dumps(delegates, indent=8)},\n'
        out += f'    "example_call": {{"args": {{}}}},\n'
        out += f'}}\n\n\n'

        # Constants
        if extra_constants:
            out += '# ─── Constants ─────────────────────────────────────────────────────────\n\n'
            for c in extra_constants:
                out += c + '\n\n'

        # SOULs
        if all_souls:
            out += '# ─── SOUL constants (verbatim from each agent) ─────────────────────────\n\n'
            for stem, soul_src in all_souls:
                out += soul_src + '\n\n'

        # Helper functions
        if extra_helpers:
            out += '# ─── Helper functions ──────────────────────────────────────────────────\n\n'
            for h in extra_helpers:
                out += h + '\n\n'

        # Internal classes — leaves first
        out += '# ─── Internal classes (prefixed _Internal to hide from discovery) ──────\n\n'
        for fname in leaves:
            info = sources[fname]
            cls_src = None
            for node in info["tree"].body:
                if isinstance(node, ast.ClassDef) and node.name == info["class_name"]:
                    cls_src = ast.get_source_segment(info["src"], node)
                    break
            if not cls_src:
                continue
            new = cls_src
            cn = info["class_name"]
            new = re.sub(rf'\bclass {re.escape(cn)}\b', f'class {renames[cn]}', new)
            stem = os.path.splitext(fname)[0].replace("_agent", "").upper().replace("-", "_")
            new = re.sub(r'\bSOUL\b', f'_SOUL_{stem}', new)
            out += new + '\n\n\n'

        # Internal classes — composites
        for fname in composites:
            info = sources[fname]
            cls_src = None
            for node in info["tree"].body:
                if isinstance(node, ast.ClassDef) and node.name == info["class_name"]:
                    cls_src = ast.get_source_segment(info["src"], node)
                    break
            if not cls_src:
                continue
            new = cls_src
            cn = info["class_name"]
            new = re.sub(rf'\bclass {re.escape(cn)}\b', f'class {renames[cn]}', new)
            for old_cn, new_cn in renames.items():
                if old_cn != cn:
                    new = re.sub(rf'\b{re.escape(old_cn)}\b', new_cn, new)
            out += new + '\n\n\n'

        # Public entrypoint — pick the top composite or first agent
        if composites:
            top_fname = composites[-1]
        else:
            top_fname = leaves[-1] if leaves else list(sources.keys())[-1]
        top_info = sources[top_fname]
        top_cls = top_info["class_name"]
        top_internal = renames[top_cls]

        out += '# ─── PUBLIC ENTRYPOINT ──────────────────────────────────────────────────\n\n'
        out += f'class {public_name}({top_internal}):\n'
        out += f'    def __init__(self):\n'
        out += f'        self.name = "{public_name}"\n'
        out += f'        self.metadata = {{\n'
        out += f'            "name": "{public_name}",\n'
        out += f'            "description": "{description or public_name + " swarm"}",\n'
        out += f'            "parameters": {json.dumps(top_info.get("metadata", {}).get("parameters", {"type": "object", "properties": {}, "required": []}))}\n'
        out += f'        }}\n'
        out += f'        super().__init__(self.name, self.metadata)\n\n\n'

        out += f'class {public_name}Agent({public_name}):\n'
        out += f'    pass\n\n\n'

        # LLM helpers
        if llm_helper_src:
            out += '# ─── Inlined LLM dispatch ──────────────────────────────────────────────\n\n'
            out += llm_helper_src + '\n\n\n'
        if post_helper_src:
            out += post_helper_src + '\n'

        # Write output
        output_fname = f"{slug}_agent.py"
        brainstem_dir = os.path.dirname(agents_dir)
        output_path = os.path.join(brainstem_dir, output_fname)
        with open(output_path, 'w', encoding="utf-8") as f:
            f.write(out)

        n_lines = len(out.split('\n'))
        sha = hashlib.sha256(out.encode()).hexdigest()

        return json.dumps({
            "status": "ok",
            "swarm_name": public_name,
            "output_file": output_path,
            "filename": output_fname,
            "lines": n_lines,
            "bytes": len(out),
            "sha256": sha,
            "agents_collapsed": len(sources),
            "leaves": len(leaves),
            "composites": len(composites),
            "souls_inlined": len(all_souls),
            "message": (
                f"Converged {len(sources)} agents into {output_fname} "
                f"({n_lines} lines). The file is at {output_path} — "
                f"share it with anyone. They drop it in their brainstem's "
                f"agents/ dir and it works."
            ),
        })
