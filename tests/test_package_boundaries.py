"""The guard that the worker's and the orchestrator's modules never import each other (spec:
package-boundaries).

An AST scan of `src/agent_build_kit` assigns every module to the core, the worker or the
orchestrator from the seeds in `tests/support/package_seeds.py`: the longest seed that names the
module or a package above it wins, and a module no seed names is core. A module that a core
module imports at module level is then lifted into the core, unless a seed names that very
module (a seed that names a module pins it; one that names a package is lifted from). The scan
fails on an import between a worker and an orchestrator module, on a core module importing a
worker or orchestrator module, and on a module-level cycle. Imports inside functions and inside
`TYPE_CHECKING` blocks are ignored. A baseline lists the crossings that exist today; it may only
shrink, so an entry that no longer exists fails until it is removed.
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Iterator, Mapping
from pathlib import Path

import pytest

from tests.support.package_seeds import Seeds, baseline, seeds

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "agent_build_kit"
CORE, WORKER, ORCHESTRATOR = "core", "worker", "orchestrator"
BASELINE_CEILING = 13
ROOT_MODULE = "__init__"

Edge = tuple[str, str]


def module_name(root: Path, path: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or ROOT_MODULE


def is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def import_statements(node: ast.AST) -> Iterator[ast.Import | ast.ImportFrom]:
    """The imports that run when the module loads, not those in a function or TYPE_CHECKING."""
    if isinstance(node, ast.Import | ast.ImportFrom):
        yield node
        return
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        return
    if isinstance(node, ast.If) and is_type_checking(node.test):
        for child in node.orelse:
            yield from import_statements(child)
        return
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt | ast.excepthandler | ast.match_case):
            yield from import_statements(child)


def longest_known(dotted: str, modules: Collection[str]) -> str | None:
    """`dotted` or its longest parent that is a module of the tree."""
    parts = dotted.split(".") if dotted else []
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return ROOT_MODULE if ROOT_MODULE in modules else None


def targets(
    node: ast.Import | ast.ImportFrom,
    module: str,
    is_package: bool,
    root_name: str,
    modules: set[str],
) -> set[str]:
    found: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == root_name or alias.name.startswith(f"{root_name}."):
                found.add(
                    longest_known(alias.name.removeprefix(root_name).strip("."), modules) or ""
                )
        return found - {""}
    if node.level:
        here = [] if module == ROOT_MODULE else module.split(".")
        package = here if is_package else here[:-1]
        base_parts = package[: len(package) - (node.level - 1)]
        base = ".".join([*base_parts, *([node.module] if node.module else [])])
    elif node.module and (node.module == root_name or node.module.startswith(f"{root_name}.")):
        base = node.module.removeprefix(root_name).strip(".")
    else:
        return found
    for alias in node.names:
        sub = f"{base}.{alias.name}" if base else alias.name
        known = sub if sub in modules else longest_known(base, modules)
        if known:
            found.add(known)
    return found


def module_imports(root: Path) -> dict[str, set[str]]:
    """Every module of the tree under `root` with the modules it imports at module level."""
    paths = {module_name(root, p): p for p in sorted(root.rglob("*.py"))}
    modules = set(paths)
    edges: dict[str, set[str]] = {}
    for module, path in paths.items():
        tree = ast.parse(path.read_text())
        is_package = path.name == "__init__.py"
        found: set[str] = set()
        for node in import_statements(tree):
            found |= targets(node, module, is_package, root.name, modules)
        edges[module] = found - {module}
    return edges


def seed_match(module: str, seed: str) -> bool:
    return module == seed or module.startswith(f"{seed}.")


def assign(edges: Mapping[str, Collection[str]], given: Seeds) -> dict[str, str]:
    """Each module's package: from its seed, then lifted into the core by core importers."""
    named = {CORE: given.core, WORKER: given.worker, ORCHESTRATOR: given.orchestrator}
    packages: dict[str, str] = {}
    pinned: set[str] = set()
    for module in edges:
        best = ("", CORE)
        for package, names in named.items():
            for seed in names:
                if seed_match(module, seed) and len(seed) > len(best[0]):
                    best = (seed, package)
        packages[module] = best[1]
        if best[0] == module:
            pinned.add(module)
    changed = True
    while changed:
        changed = False
        for module, imported in edges.items():
            if packages[module] != CORE:
                continue
            for other in imported:
                if other not in pinned and packages[other] != CORE:
                    packages[other] = CORE
                    changed = True
    return packages


def crossings(edges: Mapping[str, Collection[str]], packages: Mapping[str, str]) -> dict[Edge, str]:
    found: dict[Edge, str] = {}
    for module, imported in edges.items():
        for other in imported:
            here, there = packages[module], packages[other]
            if here != there and (here == CORE or CORE not in (here, there)):
                found[(module, other)] = f"{module} ({here}) imports {other} ({there})"
    return found


def cycles(edges: Mapping[str, Collection[str]]) -> list[list[str]]:
    """The strongly connected groups of more than one module."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    groups: list[list[str]] = []

    def visit(module: str) -> None:
        index[module] = low[module] = len(index)
        stack.append(module)
        on_stack.add(module)
        for other in sorted(edges[module]):
            if other not in index:
                visit(other)
                low[module] = min(low[module], low[other])
            elif other in on_stack:
                low[module] = min(low[module], index[other])
        if low[module] == index[module]:
            group = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                group.append(member)
                if member == module:
                    break
            if len(group) > 1:
                groups.append(sorted(group))

    for module in sorted(edges):
        if module not in index:
            visit(module)
    return groups


def boundary_problems(root: Path, given: Seeds, known: Collection[Edge]) -> list[str]:
    edges = module_imports(root)
    found = crossings(edges, assign(edges, given))
    problems = [message for edge, message in sorted(found.items()) if edge not in known]
    problems += [
        f"baseline entry {a} -> {b} no longer exists: remove it from the baseline"
        for a, b in sorted(set(known) - found.keys())
    ]
    problems += [f"module-level cycle: {' <-> '.join(group)}" for group in cycles(edges)]
    return problems


def tree(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


NODES_TO_EVENTS = {
    "__init__.py": "",
    "graph/__init__.py": "",
    "graph/nodes.py": "from pkg.pipeline.events import held_cause\n",
    "pipeline/__init__.py": "",
    "pipeline/events.py": "def held_cause(): ...\n",
}


@pytest.mark.parametrize(
    ("importer", "imported", "importer_package", "imported_package"),
    [
        ("graph/nodes.py", "pipeline/events.py", "worker", "orchestrator"),
        ("pipeline/events.py", "graph/nodes.py", "orchestrator", "worker"),
        ("forges/base.py", "pipeline/verify.py", "core", "worker"),
        ("forges/base.py", "pipeline/events.py", "core", "orchestrator"),
    ],
)
def test_an_import_across_the_boundary_fails_naming_both_modules_and_packages(
    tmp_path: Path, importer: str, imported: str, importer_package: str, imported_package: str
) -> None:
    def dotted(path: str) -> str:
        return path.removesuffix(".py").replace("/", ".")

    root = tree(
        tmp_path / "pkg",
        {
            "__init__.py": "",
            "graph/__init__.py": "",
            "graph/nodes.py": "",
            "pipeline/__init__.py": "",
            "pipeline/events.py": "",
            "pipeline/verify.py": "",
            "forges/__init__.py": "",
            "forges/base.py": "",
        },
    )
    (root / importer).write_text(f"from pkg.{dotted(imported)} import thing\n")

    problems = boundary_problems(root, seeds(), set())

    assert len(problems) == 1
    for expected in (dotted(importer), dotted(imported), importer_package, imported_package):
        assert expected in problems[0]


def test_a_tree_whose_imports_follow_the_boundary_has_no_problem(tmp_path: Path) -> None:
    root = tree(
        tmp_path / "pkg",
        {
            "__init__.py": "",
            "graph/__init__.py": "",
            "graph/nodes.py": "from pkg.pipeline.unit_store import Store\n",
            "cli/__init__.py": "",
            "cli/pipeline.py": "from pkg.pipeline import unit_store\n",
            "pipeline/__init__.py": "",
            "pipeline/unit_store.py": "class Store: ...\n",
        },
    )

    assert boundary_problems(root, seeds(), set()) == []


def test_a_module_a_core_module_imports_is_lifted_into_the_core_with_what_it_imports(
    tmp_path: Path,
) -> None:
    root = tree(
        tmp_path / "pkg",
        {
            "__init__.py": "",
            "forges/__init__.py": "",
            "forges/base.py": "from pkg.serve.zz_lifted import Tracker\n",
            "serve/__init__.py": "",
            "serve/zz_lifted.py": "from pkg.serve.zz_leaf import Level\n",
            "serve/zz_leaf.py": "class Level: ...\n",
            "serve/zz_unlifted.py": "",
            "graph/__init__.py": "",
            "graph/nodes.py": "from pkg.serve.zz_unlifted import Other\n",
        },
    )

    problems = boundary_problems(root, seeds(), set())

    assert len(problems) == 1
    assert "graph.nodes" in problems[0]
    assert "serve.zz_unlifted" in problems[0]


@pytest.mark.parametrize(
    "source",
    [
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import pkg.pipeline.events\n",
        "import typing\nif typing.TYPE_CHECKING:\n    import pkg.pipeline.events\n",
        "def later():\n    from pkg.pipeline.events import x\n    return x\n",
    ],
    ids=["type-checking-name", "type-checking-attribute", "inside-a-function"],
)
def test_an_import_in_a_type_checking_block_or_a_function_is_ignored(
    tmp_path: Path, source: str
) -> None:
    root = tree(tmp_path / "pkg", {**NODES_TO_EVENTS, "graph/nodes.py": source})

    problems = boundary_problems(root, seeds(), set())

    assert problems == []


@pytest.mark.parametrize(
    "source",
    [
        "import pkg.pipeline.events\n",
        "from pkg.pipeline import events\n",
        "from ..pipeline import events\n",
        "from ..pipeline.events import held_cause\n",
        "try:\n    from pkg.pipeline.events import x\nexcept ImportError:\n    x = None\n",
        "class Holder:\n    from pkg.pipeline.events import x\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\nelse:\n"
        "    from pkg.pipeline.events import x\n",
    ],
    ids=["import", "from-package", "relative-package", "relative-module", "try", "class", "else"],
)
def test_an_import_that_runs_when_the_module_loads_is_found_in_any_spelling(
    tmp_path: Path, source: str
) -> None:
    root = tree(tmp_path / "pkg", {**NODES_TO_EVENTS, "graph/nodes.py": source})

    problems = boundary_problems(root, seeds(), set())

    assert len(problems) == 1
    assert "graph.nodes" in problems[0]


def test_two_modules_that_import_each_other_at_module_level_fail_naming_both(
    tmp_path: Path,
) -> None:
    root = tree(
        tmp_path / "pkg",
        {
            "__init__.py": "",
            "first.py": "from pkg import second\n",
            "second.py": "from pkg import first\n",
        },
    )

    problems = boundary_problems(root, seeds(), set())

    assert len(problems) == 1
    assert "cycle" in problems[0]
    assert "first" in problems[0]
    assert "second" in problems[0]


def test_two_modules_that_import_each_other_inside_functions_are_no_cycle(tmp_path: Path) -> None:
    root = tree(
        tmp_path / "pkg",
        {
            "__init__.py": "",
            "first.py": "def f():\n    from pkg import second\n",
            "second.py": "def g():\n    from pkg import first\n",
        },
    )

    assert boundary_problems(root, seeds(), set()) == []


def test_a_crossing_in_the_baseline_is_allowed(tmp_path: Path) -> None:
    root = tree(tmp_path / "pkg", NODES_TO_EVENTS)

    problems = boundary_problems(root, seeds(), {("graph.nodes", "pipeline.events")})

    assert problems == []


def test_a_baseline_entry_that_no_longer_exists_fails_until_it_is_removed(tmp_path: Path) -> None:
    root = tree(tmp_path / "pkg", {**NODES_TO_EVENTS, "graph/nodes.py": ""})

    problems = boundary_problems(root, seeds(), {("graph.nodes", "pipeline.events")})

    assert len(problems) == 1
    assert "graph.nodes" in problems[0]
    assert "pipeline.events" in problems[0]


@pytest.mark.parametrize(
    ("module", "package"),
    [
        ("cli.worker", WORKER),
        ("graph.nodes", WORKER),
        ("pipeline.resolution_lane", WORKER),
        ("pipeline.verify", WORKER),
        ("worker_run", WORKER),
        ("run_support", CORE),
        ("cli.pipeline", ORCHESTRATOR),
        ("pipeline.events", ORCHESTRATOR),
        ("pipeline.admission", ORCHESTRATOR),
        ("serve.server", ORCHESTRATOR),
        ("forges.base", CORE),
        ("pipeline.unit_store", CORE),
    ],
)
def test_the_seeds_assign_the_modules_the_design_names_to_its_packages(
    module: str, package: str
) -> None:
    assert assign({module: set()}, seeds())[module] == package


def test_the_baseline_holds_no_more_than_the_thirteen_imports_of_the_design() -> None:
    assert 0 < len(baseline()) <= BASELINE_CEILING


@pytest.mark.integration
def test_the_kit_has_no_import_across_the_packages_beyond_the_baseline() -> None:
    problems = boundary_problems(SOURCE_ROOT, seeds(), baseline())

    assert problems == [], "\n".join(problems)
