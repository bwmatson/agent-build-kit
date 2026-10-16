"""The tier 2 mechanism names no split, runtime or provider (spec: tier2-splits).

The scan reads the modules of the mechanism, ignores comments, and fails when a string,
an identifier or a docstring in them is a runtime the registry knows, the protocol
runtime's name, a name beginning `runtime_` or a provider of the provider table. The
provider table's own module is the one place a provider is named.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from agent_build_kit import runtimes
from agent_build_kit.runtimes import known_agents

SOURCE = Path(__file__).resolve().parent.parent / "src" / "agent_build_kit"

# The modules of the mechanism: the selection, the held set, the schedule, the record, the
# check and the `tier2` command group, the text edit, the profile protocol. `Tier2Session`
# is one class of a large module, so it is scanned alone.
MODULES = (
    "pipeline/tier2.py",
    "pipeline/tier2_exclusive.py",
    "pipeline/tier2_holds.py",
    "pipeline/tier2_schedule.py",
    "pipeline/tier2_times.py",
    "cli/tier2_cmd.py",
    "config_text_edit.py",
)
CLASSES = (
    ("profiles/base.py", "ToolchainProfile"),
    ("pipeline/wiring.py", "Tier2Session"),
)
# The provider table's own module is exempt; it is not in the lists above.
PROVIDER_TABLE = "runtimes/providers.py"
# A name from the standard library that merely begins `runtime_`.
STDLIB = {"runtime_checkable"}


def forbidden() -> set[str]:
    table = importlib.import_module("agent_build_kit.runtimes.providers")
    return {*runtimes.names(), known_agents.RUNTIME_NAME, *table.names()}


def words(node: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for child in ast.walk(node):
        line = getattr(child, "lineno", 0)
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.append((line, child.value))
        elif isinstance(child, ast.Name):
            found.append((line, child.id))
        elif isinstance(child, ast.Attribute):
            found.append((line, child.attr))
        elif isinstance(child, ast.arg):
            found.append((line, child.arg))
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.append((line, child.name))
        elif isinstance(child, ast.alias):
            found.append((line, child.asname or child.name))
    return found


def tokens(text: str) -> set[str]:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else " " for ch in text)
    return set(cleaned.split())


def scanned() -> list[tuple[str, ast.AST]]:
    trees: list[tuple[str, ast.AST]] = []
    for relative in MODULES:
        trees.append((relative, ast.parse((SOURCE / relative).read_text(encoding="utf-8"))))
    for relative, name in CLASSES:
        module = ast.parse((SOURCE / relative).read_text(encoding="utf-8"))
        found = [n for n in ast.walk(module) if isinstance(n, ast.ClassDef) and n.name == name]
        assert found, f"{relative} has no class {name}"
        # The decorators are left out: `@runtime_checkable` is a typing name, not a runtime.
        body = ast.Module(body=found[0].body, type_ignores=[])
        trees.append((f"{relative}:{name}", body))
    return trees


def test_the_tier_2_mechanism_names_no_split_runtime_or_provider() -> None:
    names = forbidden()
    assert (SOURCE / PROVIDER_TABLE).is_file()
    hits = [
        f"{relative}:{line}: {token!r}"
        for relative, tree in scanned()
        for line, text in words(tree)
        for token in sorted(tokens(text))
        if (token in names or token.startswith("runtime_")) and token not in STDLIB
    ]

    assert hits == []
