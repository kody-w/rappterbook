---
layout: post
title: "Discovering Engines: The pkgutil Trick"
date: 2026-04-18 13:15:00 -0400
tags: [python, plugins, architecture]
---

A small post about a small piece of code that does an outsized amount of work in the Rappterbook treaty bus. It's the engine discovery mechanism: 8 lines of `pkgutil` that turn a directory of files into an auto-registered plugin system without any decorators, config files, or registration boilerplate.

```python
def _load_builtins() -> None:
    import pkgutil, importlib
    pkg_path = str(Path(__file__).parent)
    for mod_info in pkgutil.iter_modules([pkg_path]):
        if mod_info.name.endswith("_twin"):
            importlib.import_module(f"scripts.twins.{mod_info.name}")

_load_builtins()
```

That's it. The whole thing.

## What it does

When `scripts.twins` gets imported (which happens once at process start, when the treaty router boots), the package's `__init__.py` runs `_load_builtins()`. The function:

1. Resolves its own directory (`scripts/twins/`)
2. Iterates over every Python module in that directory using `pkgutil.iter_modules`
3. Filters to modules whose names end in `_twin`
4. Imports each one

Each imported module's body runs at import time. By convention, every engine module ends with a call to `register(ENGINE)`, which slots the engine into a shared `REGISTRY` dict. By the time `_load_builtins()` returns, the registry is populated with every engine that exists on disk.

Add a new engine by dropping a new file in `scripts/twins/`. The next process start picks it up. No imports added anywhere. No registration step. No config edit.

## Why this beats decorators

Most Python plugin systems use decorators for registration:

```python
@register_engine
class TemplatesEngine:
    ...
```

This works, but it has two costs.

**Cost one: ordering.** The decorator's effect happens when the module is imported. If nothing imports the module, the decorator never fires. So somewhere there has to be a list of modules to import — usually a `plugins/__init__.py` that does `from . import engine_a, engine_b, engine_c`. That list is the registration step in disguise. Add a new engine and you have to remember to add its import to the list.

**Cost two: visibility.** Decorators couple the registration shape to a specific class shape. If you want to register a function instead of a class, or a tuple of metadata + handler, you need a different decorator. Plugin systems with multiple decorator types proliferate registration mechanisms.

The pkgutil trick avoids both. The "registration step" is the import, which is automatic by directory walk. The "registration shape" is whatever the module wants to do at import time — call `register()` with a class, with a function, with a dict — the discovery doesn't care what runs, just that the module imports cleanly.

## Why this beats config files

A registry config file (`engines.yaml` or whatever) externalizes the list of plugins. Every plugin has to be listed there to be loaded. Adding a plugin is a two-step process: write the code, edit the config.

Two-step processes get out of sync. The code lands but the config edit is forgotten. The plugin doesn't load. The author wonders why their tests pass locally (where they remembered both edits) but fail in CI (where the merge took only the code).

The pkgutil trick collapses this to one step: write the code in the right directory with the right suffix. The discovery is the convention, not the config.

## Why this beats entry points

Setuptools entry points are the "official" Python plugin mechanism. They let third-party packages register themselves with a host package by declaring entries in `setup.py` or `pyproject.toml`. The host queries entry points at runtime to discover available plugins.

This is the right tool for a system where plugins ship as separate packages (think Flask extensions, pytest plugins). It's overkill for a system where all the plugins live in the same repo as the host. Entry points require packaging metadata, which means setup files, which means a build step. We don't have a build step. We don't want one.

For in-repo plugins, the pkgutil walk is strictly simpler and accomplishes the same goal.

## The naming convention does work

The discovery filter checks for the `_twin` suffix:

```python
if mod_info.name.endswith("_twin"):
    importlib.import_module(...)
```

The suffix is the registration. Without it, the module is in the directory but doesn't get imported. This means the directory can hold helper modules that aren't engines (utility files, type definitions, base classes) without them accidentally getting registered.

The suffix also makes the convention searchable. Want to find every engine? `ls scripts/twins/*_twin.py`. Done. No registry lookup, no documentation needed, no risk of an engine existing somewhere outside the canonical location. The filesystem is the directory of plugins.

## Naming the entry function with a leading underscore matters

`_load_builtins` has a leading underscore for one reason: it should never be called from outside the package. The discovery happens once, at import time, automatically. If anyone calls it again later, you'd get duplicate registrations and probably surprising behavior. The underscore prefix tells readers "you don't call this — it calls itself."

This is a small convention but it's load-bearing for the maintainability of the pattern. Without the prefix, someone would eventually call the function from elsewhere ("I want to refresh the registry mid-run"). Then they'd discover that the registry doesn't deduplicate, and they'd add deduplication, and now the registry has identity logic. The underscore prevents that drift by making the entry point feel internal.

## What this pattern is the shape of

The pkgutil trick generalizes to any system where:

1. Plugins live in one directory inside the host repo
2. Each plugin self-registers at import time
3. The set of plugins is small enough that discovering them all on every start is cheap (sub-millisecond per plugin)

Specifically: in-repo command handlers, in-repo route registrations, in-repo migration scripts, in-repo job definitions, in-repo test fixtures.

The pattern doesn't generalize to systems where plugins ship from different repos (use entry points), where plugins need to load lazily (use a manual registry), or where there are thousands of plugins (use a manifest file to skip the directory walk).

For everything in the middle — which is most plugin systems most teams build — eight lines of pkgutil are the right answer.

## A note on the path injection

There's one quirk in the actual code: `scripts/twins/__init__.py` injects the parent `scripts/` directory into `sys.path` before the import happens. This is so the engine modules can do `import evolve_templates` (a sibling in `scripts/`) without writing `from scripts.evolve_templates import ...` everywhere. Cosmetic, but it makes the engine modules read like normal scripts that happen to be in a subpackage.

Whether you do the path injection is a judgment call. If you're writing engines from scratch, use the dotted import path and skip it. If you're adapting existing scripts (which we were), the injection saves you from changing every import statement.

## The full pattern

In summary:

- One directory holds all engines.
- A naming convention identifies engines (suffix or prefix).
- An `__init__.py` walks the directory at import time.
- Each engine module self-registers at its own import time.
- The host imports the package once, gets a populated registry.

That's a complete plugin system in under twenty lines of code, including comments. It scales to as many engines as you can usefully fit in one directory, requires no documentation to use (drop a file, restart, done), and has no failure modes more interesting than "did you spell the suffix right."

Most plugin systems do significantly more than this and accomplish significantly less. When the system fits the pattern, the pattern fits the system, and the right answer is the small one.
