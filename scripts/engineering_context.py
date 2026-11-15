"""Read-only repository evidence for conversations about failing tests."""
from __future__ import annotations

import ast
import re
from pathlib import Path


REPAIR_INSTRUCTIONS = (
    "This conversation is a failing-test repair, not a generic discussion. "
    "Use the supplied failure and current repository source as evidence. "
    "Explain the root cause briefly in your own voice, then provide the smallest "
    "correct fix in a fenced ```diff block containing a complete unified diff: "
    "--- a/path, +++ b/path, and @@ -old,count +new,count @@ hunks with exact "
    "context, removed lines and added lines. Preserve indentation and blank lines. "
    "Do not use ellipses, pseudocode, invented APIs, or a replacement test. "
    "Fix production behavior, not the assertion; retain safety checks and "
    "unrelated behavior. Trace boundary cases and dependencies before choosing "
    "the fix. State the exact test command and expected result, but do not claim "
    "you ran it unless execution evidence was supplied. Prose length limits do "
    "not apply to the diff. If replying, review the existing patch against the "
    "actual test; if it is wrong or incomplete, provide a corrected complete "
    "replacement diff against the current repository, not a diff on top of the "
    "unapplied proposal. If it is correct, explain a concrete edge case rather "
    "than repeating it. Never make up a patch when source evidence is missing. "
    "Use a plain descriptive title containing the exact failing test name. "
    "Editorial word/phrase bans apply to your prose, not exact quoted failure "
    "output or source lines inside fenced blocks."
)


def is_repair_topic(text: str) -> bool:
    """Recognize test-repair evidence without depending on particular subjects."""
    return bool(re.search(
        r"\btest_[A-Za-z0-9_]+\b|\bfailing\s+(?:regression\s+)?test\b"
        r"|\b(?:AssertionError|Traceback)\b", text, re.IGNORECASE,
    ))


def prose_only(text: str) -> str:
    """Separate editorial prose from quoted code, traces, and patch evidence."""
    return re.sub(r"(?m)^ *(`{3,}|~{3,})[^\n]*\n.*?^ *\1 *$",
                  " ", text, flags=re.DOTALL)


def distinct_repair_artifact(title: str, body: str, existing: dict) -> bool:
    """Distinguish an evidenced new repair from a report or an older proposal."""
    previous_body = existing.get("body", "")
    if not previous_body:
        return False
    tests = set(re.findall(r"\btest_\w+", title + "\n" + body))
    previous_tests = set(re.findall(
        r"\btest_\w+", existing.get("title", "") + "\n" + previous_body,
    ))
    if not tests & previous_tests:
        return False
    patches = re.findall(r"(?ms)^```diff\s*\n(.*?)^```\s*$", body)
    previous = re.findall(r"(?ms)^```diff\s*\n(.*?)^```\s*$", previous_body)
    if not patches or not all(
        re.search(r"(?m)^--- a/", patch) and re.search(r"(?m)^\+\+\+ b/", patch)
        and re.search(r"(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", patch)
        for patch in patches
    ):
        return False
    return patches != previous


def normalize_diff_fences(text: str) -> str:
    """Recount unified-diff hunks without changing any proposed source line."""
    def recount(match: re.Match) -> str:
        """Repair only mechanical range counts for otherwise structured hunks."""
        lines = match.group(2).splitlines(keepends=True)
        for index, line in enumerate(lines):
            header = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
            if not header:
                continue
            old_count = new_count = 0
            for content in lines[index + 1:]:
                if content.startswith(("@@", "diff --git ", "--- a/", "+++ b/")):
                    break
                if content.startswith(" "):
                    old_count += 1
                    new_count += 1
                elif content.startswith("-"):
                    old_count += 1
                elif content.startswith("+"):
                    new_count += 1
                elif content.startswith("\\ No newline"):
                    continue
                else:
                    break
            lines[index] = (
                f"@@ -{header.group(1)},{old_count} +{header.group(2)},{new_count} @@"
                f"{header.group(3)}\n"
            )
        return match.group(1) + "".join(lines) + match.group(3)

    return re.sub(r"(?ms)(^```diff[^\n]*\n)(.*?)(^``` *$)", recount, text)


def _read_python(path: Path) -> tuple[str, ast.Module | None]:
    """Read a bounded Python source without importing or executing it."""
    try:
        if path.stat().st_size > 500_000:
            print(f"  [EVIDENCE] Source too large to inspect: {path.name}")
            return "", None
        source = path.read_text(encoding="utf-8")
        return source, ast.parse(source)
    except (OSError, UnicodeError, SyntaxError) as exc:
        print(f"  [EVIDENCE] Cannot inspect {path.name}: {exc}")
        return "", None


def _imports(tree: ast.Module, root: Path, parent: Path) -> list[Path]:
    """Resolve local Python imports from test/source ASTs, never external code."""
    paths = []
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        for module in modules:
            relative = Path(*module.split(".")).with_suffix(".py")
            bases = (root / "scripts", root, root / "tests")
            if isinstance(node, ast.ImportFrom) and node.level:
                base = parent
                for _ in range(node.level - 1):
                    base = base.parent
                bases = (base,)
            for base in bases:
                candidate = base / relative
                if not candidate.is_file():
                    candidate = base / Path(*module.split(".")) / "__init__.py"
                candidate = candidate.resolve()
                if candidate.is_relative_to(root) and candidate.is_file() and candidate not in paths:
                    paths.append(candidate)
                    break
    return paths


def _excerpt(source: str, tree: ast.Module, symbols: set[str]) -> str:
    """Include exact imports and relevant definitions, following local calls."""
    if len(source) <= 18_000:
        return source
    definitions = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    selected = set(symbols) & definitions.keys()
    pending = list(selected)
    while pending:
        node = definitions[pending.pop()]
        called = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
        for name in (called & definitions.keys()) - selected:
            selected.add(name)
            pending.append(name)
    lines = source.splitlines(keepends=True)
    spans = [(1, min(100, len(lines)))]
    spans.extend(
        (node.lineno, node.end_lineno) for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign))
    )
    for name in selected:
        node = definitions[name]
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        spans.append((start, node.end_lineno))
    included = sorted({index for start, end in spans for index in range(start - 1, end)})
    chunks, previous = [], -2
    for index in included:
        if index != previous + 1:
            chunks.append("\n# ... omitted unrelated source ...\n")
        chunks.append(lines[index])
        previous = index
    return "".join(chunks)


def _referenced_symbols(tree: ast.Module, symbols: set[str]) -> set[str]:
    """Follow names used by the selected tests/functions, not the whole suite."""
    references = set(symbols)
    definitions = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    pending = list(references & definitions.keys())
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        for node in ast.walk(definitions[name]):
            if isinstance(node, ast.Name):
                references.add(node.id)
            elif isinstance(node, ast.Attribute):
                references.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", node.value):
                    references.update(node.value.split("."))
        pending.extend((references & definitions.keys()) - visited)
    return references


def _mentioned_files(text: str, root: Path) -> list[Path]:
    """Resolve source filenames in evidence strictly inside the repository."""
    paths = []
    for reference in re.findall(r"[\w./-]+\.py\b", text):
        relative = reference.removeprefix("a/").removeprefix("b/")
        for base in (root, root / "scripts", root / "tests"):
            path = (base / relative).resolve()
            if path.is_relative_to(root) and path.is_file():
                if path not in paths:
                    paths.append(path)
                break
    return paths


def _find_tests(text: str, root: Path, symbols: set[str]) -> list[Path]:
    """Prefer explicit test paths, otherwise locate the named test definitions."""
    paths = _mentioned_files(text, root)
    test_names = {name for name in symbols if name.startswith("test_")}
    explicit_tests = [path for path in paths if path.is_relative_to(root / "tests")]
    if test_names:
        candidates = explicit_tests or sorted((root / "tests").rglob("test*.py"))
        for path in candidates:
            path = path.resolve()
            if not path.is_relative_to(root):
                continue
            source, tree = _read_python(path)
            if tree and any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in test_names for node in ast.walk(tree)
            ) and path not in paths:
                paths.insert(0, path)
    return paths


def _dependencies(tree: ast.Module, source: str, root: Path, path: Path) -> list[Path]:
    """Resolve local imports and source filenames, prioritizing production code."""
    dependencies = _imports(tree, root, path.parent)
    dependencies.extend(
        dependency for dependency in _mentioned_files(source, root)
        if dependency not in dependencies
    )
    dependencies.sort(key=lambda dependency: (
        dependency.name == "conftest.py", not dependency.is_relative_to(root / "scripts"),
    ))
    return dependencies


def repair_context(text: str, root: Path) -> str:
    """Find the named real tests and their production dependencies read-only."""
    root = root.resolve()
    symbols = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text))
    paths = _find_tests(text, root, symbols)
    sections, visited = [], set()
    budget = 55_000
    for path in paths:
        if path in visited or len(visited) >= 12 or budget <= 0:
            continue
        visited.add(path)
        source, tree = _read_python(path)
        if not tree:
            continue
        function_names = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if path.is_relative_to(root / "scripts") and not function_names & symbols:
            symbols.add("main")
        symbols = _referenced_symbols(tree, symbols)
        excerpt = _excerpt(source, tree, symbols)
        if len(excerpt) > budget:
            print(f"  [EVIDENCE] Context budget omitted {path.relative_to(root)}")
            continue
        sections.append(f"FILE: {path.relative_to(root).as_posix()}\n```python\n{excerpt}\n```")
        budget -= len(excerpt)
        evidence_source = excerpt if path.is_relative_to(root / "tests") else source[:4000]
        dependencies = _dependencies(tree, evidence_source, root, path)
        paths.extend(dependency for dependency in dependencies if dependency not in paths)
    if not sections:
        return "No matching repository source found. Request the exact test and implementation."
    return "CURRENT REPOSITORY EVIDENCE (read-only; patches are proposals):\n" + "\n\n".join(sections)
