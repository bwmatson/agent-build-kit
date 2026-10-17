"""The e2e-test mechanism names no split, runtime or provider (spec: e2e-splits).

The scan reads the modules of the mechanism, ignores comments, and fails when a string,
an identifier or a docstring in them is a runtime the registry knows, the protocol
runtime's name, a name beginning `runtime_` or a provider of the provider table. The
provider table's own module is the one place a provider is named.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent_build_kit import runtimes
from agent_build_kit.runtimes import known_agents, providers

SOURCE = Path(__file__).resolve().parent.parent / "src" / "agent_build_kit"

# The modules of the mechanism: the selection, the held set, the schedule, the record (the
# per-split failure record included), the check and the `e2e-test` command group, and the text
# edit. The profile's e2e-test protocols and `E2eSession` are classes of larger modules, so
# they are scanned alone.
MODULES = (
    "pipeline/e2e.py",
    "pipeline/e2e_exclusive.py",
    "pipeline/e2e_holds.py",
    "pipeline/e2e_schedule.py",
    "pipeline/e2e_times.py",
    "pipeline/untouched_failures.py",
    "cli/e2e_cmd.py",
    "config_text_edit.py",
)
CLASSES = (
    ("profiles/base.py", "ToolchainProfile"),
    ("profiles/base.py", "AppliesE2eSelection"),
    ("profiles/base.py", "ListsRegisteredSelectors"),
    ("pipeline/wiring.py", "E2eSession"),
)
# The provider table's own module is exempt; it is not in the lists above.
PROVIDER_TABLE = "runtimes/providers.py"
# A name from the standard library that merely begins `runtime_`.
STDLIB = {"runtime_checkable"}


def forbidden() -> set[str]:
    return {*runtimes.names(), known_agents.RUNTIME_NAME, *providers.names()}


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


def hits_in(label: str, tree: ast.AST, names: set[str]) -> list[str]:
    return [
        f"{label}:{line}: {token!r}"
        for line, text in words(tree)
        for token in sorted(tokens(text))
        if (token in names or token.startswith("runtime_")) and token not in STDLIB
    ]


def test_the_tier_2_mechanism_names_no_split_runtime_or_provider() -> None:
    names = forbidden()
    hits = [hit for label, tree in scanned() for hit in hits_in(label, tree, names)]

    assert hits == []


def test_the_scan_finds_a_runtime_a_marker_and_a_provider_but_not_a_typing_name() -> None:
    snippet = ast.parse(
        "@runtime_checkable\n"
        "class Profile:\n"
        "    def pick(self, modal):\n"
        "        runtime_claude_code = 'acp'\n"
    )

    hits = hits_in("snippet", snippet, forbidden())

    joined = " ".join(hits)
    assert "snippet" in joined
    assert all(f"'{name}'" in joined for name in ("acp", "runtime_claude_code", "modal"))
    assert "runtime_checkable" not in joined


def test_the_provider_table_is_flagged_by_the_scan_so_only_its_exemption_keeps_it_out() -> None:
    table = ast.parse((SOURCE / PROVIDER_TABLE).read_text(encoding="utf-8"))

    hits = hits_in(PROVIDER_TABLE, table, forbidden())

    assert any(f"'{name}'" in hit for name in providers.names() for hit in hits)
    assert PROVIDER_TABLE not in [label for label, _ in scanned()]
