"""The guard that the worker's and the orchestrator's modules never import each other (spec:
package-boundaries).

An AST scan of every source tree of the `agent_build_kit` namespace (`source_trees` in
`tests/tracked_files.py`: the root package's and each package's under `packages/`) assigns every
module to the core, the worker or the orchestrator from the seeds in
`tests/support/package_seeds.py`: the longest seed that names the module or a package above it
wins, and a module no seed names is core. A module that a core
module imports at module level is then lifted into the core, unless a seed names that very
module (a seed that names a module pins it; one that names a package is lifted from). The scan
fails on an import between a worker and an orchestrator module, on a core module importing a
worker or orchestrator module, and on a module-level cycle. Imports inside functions and inside
`TYPE_CHECKING` blocks are ignored. A baseline lists the crossings that exist today; it may only
shrink, so an entry that no longer exists fails until it is removed.
"""

from __future__ import annotations

import ast
import fnmatch
import subprocess
import sys
import tomllib
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import COMMANDS_GROUP
from tests.ecosystem_names import WORKER_MODULES
from tests.placement_baseline import (
    BASELINE,
    PlacementTree,
    kit_trees,
    placement_problems,
    read_baseline,
    write_baseline,
)
from tests.support.package_seeds import Seeds, baseline, seeds
from tests.tracked_files import (
    ORCHESTRATOR_SOURCE,
    ROOT,
    SOURCE_ROOT,
    WORKER_SOURCE,
    source_trees,
    tracked,
)
from tests.wide_scans import scans_the_repository
from tests.workspace_packages import PACKAGE_NAME, PACKAGES, source_root

WORKER_ROOT = WORKER_SOURCE.parents[1]
ORCHESTRATOR_ROOT = ORCHESTRATOR_SOURCE.parents[1]
# The source trees that install into the root package's namespace.
OTHER_TREES = [tree for tree in source_trees() if tree != SOURCE_ROOT]
TESTS = Path("tests")
WORKER_TESTS = Path("packages") / "worker" / "tests"
ORCHESTRATOR_TESTS = Path("packages") / "orchestrator" / "tests"
CORE_TESTS = Path("packages") / "core" / "tests"
CORE_TESTS_BASELINE = ROOT / "packages" / "core" / "core_tests_baseline.toml"
CORE_TEST_PREFIX = "test_checkpoint"
CORE, WORKER, ORCHESTRATOR = "core", "worker", "orchestrator"
BASELINE_CEILING = 13
# Lowered by each group that moves core tests and deletes baseline lines.
CORE_TESTS_BASELINE_CEILING = 14
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


def module_imports(root: Path, beside: Collection[Path] = ()) -> dict[str, set[str]]:
    """Every module of the tree under `root` with the modules it imports at module level.

    `beside` names trees of other packages that install into the same namespace; their modules are
    scanned as if they sat under `root`.
    """
    paths = {
        module_name(tree_root, p): p
        for tree_root in (root, *beside)
        for p in sorted(tree_root.rglob("*.py"))
    }
    return imports_of(paths, root.name)


def imports_of(paths: Mapping[str, Path], root_name: str) -> dict[str, set[str]]:
    """The module-level imports of each module in `paths` (module name to file)."""
    modules = set(paths)
    edges: dict[str, set[str]] = {}
    for module, path in paths.items():
        tree = ast.parse(path.read_text())
        is_package = path.name == "__init__.py"
        found: set[str] = set()
        for node in import_statements(tree):
            found |= targets(node, module, is_package, root_name, modules)
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


def boundary_problems(
    root: Path, given: Seeds, known: Collection[Edge], beside: Collection[Path] = ()
) -> list[str]:
    edges = module_imports(root, beside)
    found = crossings(edges, assign(edges, given))
    problems = [message for edge, message in sorted(found.items()) if edge not in known]
    problems += [
        f"baseline entry {a} -> {b} no longer exists: remove it from the baseline"
        for a, b in sorted(set(known) - found.keys())
    ]
    problems += [f"module-level cycle: {' <-> '.join(group)}" for group in cycles(edges)]
    return problems


def layout_problems(packages: Mapping[str, Path], given: Seeds) -> list[str]:
    """What the files of each package (name to its project folder) get wrong about the table.

    A module the table assigns to the core must be in the `core` package's source folder (a
    package's `__init__.py` is exempt, as the layout test owns where those sit), and no core
    module may import a worker or orchestrator module.
    """
    paths: dict[str, Path] = {}
    owner: dict[str, str] = {}
    for package, folder in packages.items():
        source = source_root(folder)
        for path in sorted(source.rglob("*.py")):
            module = module_name(source, path)
            paths[module] = path
            owner[module] = package
    edges = imports_of(paths, PACKAGE_NAME)
    assigned = assign(edges, given)
    problems = [
        f"{module} is assigned to the core but is in the {owner[module]} package"
        for module in sorted(paths)
        if assigned[module] == CORE
        and owner[module] != CORE
        and paths[module].name != "__init__.py"
    ]
    problems += [
        f"core module {message}"
        for (module, _), message in sorted(crossings(edges, assigned).items())
        if assigned[module] == CORE
    ]
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
    problems = boundary_problems(SOURCE_ROOT, seeds(), baseline(), OTHER_TREES)

    assert problems == [], "\n".join(problems)


def package_folder(root: Path, files: dict[str, str]) -> Path:
    """A project folder of the workspace holding `files` under `src/agent_build_kit`."""
    tree(source_root(root), files)
    return root


def test_a_core_module_in_the_root_package_is_reported_naming_both(tmp_path: Path) -> None:
    packages = {
        "root": package_folder(tmp_path / "root", {"forges/base.py": ""}),
        "core": package_folder(tmp_path / "core", {"model.py": ""}),
    }

    problems = layout_problems(packages, seeds())

    assert problems == ["forges.base is assigned to the core but is in the root package"]


def test_a_core_module_in_the_core_package_is_not_reported(tmp_path: Path) -> None:
    packages = {
        "root": package_folder(tmp_path / "root", {"pipeline/verify.py": ""}),
        "core": package_folder(tmp_path / "core", {"forges/base.py": ""}),
    }

    assert layout_problems(packages, seeds()) == []


def test_a_core_module_importing_a_worker_module_is_reported_as_a_core_module(
    tmp_path: Path,
) -> None:
    packages = {
        "root": package_folder(tmp_path / "root", {"pipeline/verify.py": ""}),
        "core": package_folder(
            tmp_path / "core", {"forges/base.py": "from agent_build_kit.pipeline import verify\n"}
        ),
    }

    problems = layout_problems(packages, seeds())

    assert len(problems) == 1
    assert problems[0].startswith("core module ")
    assert "forges.base" in problems[0]
    assert "pipeline.verify" in problems[0]


def test_an_init_file_in_the_root_package_is_not_reported(tmp_path: Path) -> None:
    packages = {
        "root": package_folder(tmp_path / "root", {"forges/__init__.py": ""}),
        "core": package_folder(tmp_path / "core", {"forges/base.py": ""}),
    }

    assert layout_problems(packages, seeds()) == []


@pytest.mark.integration
def test_the_core_modules_are_in_the_core_package_and_import_nothing_from_the_others() -> None:
    problems = layout_problems(PACKAGES, seeds())

    assert problems == [], "\n".join(problems)


def foreign_imports(
    own_tree: Path, forbidden: str, given: Seeds, known: Collection[Edge], trees: list[Path]
) -> list[str]:
    """Each module-level import in `own_tree` of a module the seeds assign to the package
    `forbidden`, beyond `known`; the modules of every tree in `trees` (the root's first) are
    scanned, so an import of a module that sits in another package's tree is recognised."""
    edges = module_imports(trees[0], trees[1:])
    packages = assign(edges, given)
    own = {module_name(own_tree, p) for p in own_tree.rglob("*.py")}
    return [
        f"{module} imports {other} ({forbidden})"
        for module, imported in sorted(edges.items())
        if module in own
        for other in sorted(imported)
        if packages.get(other) == forbidden and (module, other) not in known
    ]


def assigned_modules(package: str, *, packages_as_init: bool) -> list[str]:
    """The modules the seeds assign to `package`, as paths under a source tree. A package folder
    is its `__init__.py` when `packages_as_init`, and is left out otherwise."""
    trees = [SOURCE_ROOT, *OTHER_TREES]
    found = []
    for module, assigned in assign(module_imports(SOURCE_ROOT, OTHER_TREES), seeds()).items():
        if assigned != package:
            continue
        stem = module.replace(".", "/")
        if not any((tree / stem).is_dir() for tree in trees):
            found.append(f"{stem}.py")
        elif packages_as_init:
            found.append(f"{stem}/__init__.py")
    return sorted(found)


def worker_modules() -> list[str]:
    """The modules the seeds assign to the worker; a package whose `__init__` stays in another
    package to extend the namespace is not a module of the worker."""
    return assigned_modules(WORKER, packages_as_init=False)


@pytest.mark.parametrize("module", worker_modules())
def test_a_module_the_table_assigns_to_the_worker_is_in_the_worker_package(module: str) -> None:
    assert (WORKER_SOURCE / module).is_file()
    assert not (SOURCE_ROOT / module).exists()


def test_the_worker_modules_the_wheel_test_lists_are_those_the_seeds_assign() -> None:
    assert sorted(WORKER_MODULES) == worker_modules()


@pytest.mark.integration
def test_no_file_of_the_worker_package_imports_an_orchestrator_module() -> None:
    assert (WORKER_SOURCE / "cli" / "worker.py").is_file()

    problems = foreign_imports(WORKER_SOURCE, ORCHESTRATOR, seeds(), baseline(), source_trees())

    assert problems == [], "\n".join(problems)


def test_a_worker_file_importing_a_module_only_the_orchestrator_tree_holds_is_reported(
    tmp_path: Path,
) -> None:
    core = tree(tmp_path / "core" / "pkg", {"__init__.py": ""})
    worker = tree(
        tmp_path / "worker" / "pkg",
        {"graph/__init__.py": "", "graph/nodes.py": "from pkg.cli.pipeline import main\n"},
    )
    orchestrator = tree(
        tmp_path / "orchestrator" / "pkg", {"cli/__init__.py": "", "cli/pipeline.py": ""}
    )
    given = Seeds(core=frozenset(), worker=frozenset({"graph"}), orchestrator=frozenset({"cli"}))

    problems = foreign_imports(worker, ORCHESTRATOR, given, set(), [core, worker, orchestrator])

    assert problems == [f"graph.nodes imports cli.pipeline ({ORCHESTRATOR})"]


def test_the_worker_package_depends_on_the_core_and_registers_abk_worker_as_a_command() -> None:
    manifest = WORKER_ROOT / "pyproject.toml"
    assert manifest.is_file()
    project = tomllib.loads(manifest.read_text())["project"]

    assert project["name"] == "agent-build-kit-worker"
    assert any(d.startswith("agent-build-kit-core") for d in project["dependencies"])
    assert project["entry-points"][COMMANDS_GROUP] == {
        "worker": "agent_build_kit.cli.worker:register"
    }


def orchestrator_modules() -> list[str]:
    """The modules the seeds assign to the orchestrator, as paths under a source tree; a package
    is its `__init__.py`."""
    return assigned_modules(ORCHESTRATOR, packages_as_init=True)


def unresolved_imports(
    source: Path, installed: Collection[Path], known: Collection[Edge], trees: Collection[Path]
) -> list[str]:
    """Each module-level import in the tree `source` of a module no file under `installed` holds,
    beyond the crossings in `known`. An import is resolved against the modules of every tree in
    `trees`, so `from pkg import sub` and `from pkg.mod import sub` name the submodule `sub` where
    one exists."""
    modules = {module_name(t, p) for t in trees for p in t.rglob("*.py")}
    available = {module_name(t, p) for t in installed for p in t.rglob("*.py")}
    found: list[str] = []
    for path in sorted(source.rglob("*.py")):
        module = module_name(source, path)
        for node in import_statements(ast.parse(path.read_text())):
            is_package = path.name == "__init__.py"
            for name in sorted(targets(node, module, is_package, source.name, modules)):
                if name not in available and (module, name) not in known:
                    found.append(f"{module} imports {name}, which is in no installed package")
    return found


def split_trees(tmp_path: Path, orchestrator_file: str) -> tuple[Path, Path, Path]:
    """A core tree, a worker tree holding `graph/nodes.py` and `sub.py`, and an orchestrator tree
    whose one module is `orchestrator_file`."""
    core = tree(tmp_path / "core" / "pkg", {"__init__.py": "", "graph/__init__.py": ""})
    worker = tree(tmp_path / "worker" / "pkg", {"graph/nodes.py": "", "sub.py": ""})
    orchestrator = tree(tmp_path / "orchestrator" / "pkg", {"cli.py": orchestrator_file})
    return core, worker, orchestrator


@pytest.mark.parametrize("module", orchestrator_modules())
def test_a_module_the_table_assigns_to_the_orchestrator_is_in_the_orchestrator_package(
    module: str,
) -> None:
    assert (ORCHESTRATOR_SOURCE / module).is_file()
    assert not (SOURCE_ROOT / module).exists()


@pytest.mark.integration
def test_no_file_of_the_orchestrator_package_imports_a_worker_module() -> None:
    assert (ORCHESTRATOR_SOURCE / "cli" / "pipeline.py").is_file()

    problems = foreign_imports(ORCHESTRATOR_SOURCE, WORKER, seeds(), baseline(), source_trees())

    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize(
    ("statement", "missing"),
    [
        ("from pkg.graph import nodes\n", "graph.nodes"),
        ("from pkg import sub\n", "sub"),
        ("import pkg.sub\n", "sub"),
    ],
)
def test_an_orchestrator_import_of_a_submodule_only_the_worker_tree_holds_is_reported(
    tmp_path: Path, statement: str, missing: str
) -> None:
    core, worker, orchestrator = split_trees(tmp_path, statement)

    problems = unresolved_imports(
        orchestrator, [core, orchestrator], set(), [core, worker, orchestrator]
    )

    assert problems == [f"cli imports {missing}, which is in no installed package"]


def test_an_orchestrator_import_of_an_attribute_of_a_module_the_core_holds_is_not_reported(
    tmp_path: Path,
) -> None:
    core, worker, orchestrator = split_trees(tmp_path, "from pkg.graph import Thing\n")

    problems = unresolved_imports(
        orchestrator, [core, orchestrator], set(), [core, worker, orchestrator]
    )

    assert problems == []


@pytest.mark.integration
def test_the_core_and_orchestrator_files_alone_resolve_every_orchestrator_import() -> None:
    assert (ORCHESTRATOR_SOURCE / "cli" / "pipeline.py").is_file()
    core_trees = [tree for tree in source_trees() if tree != WORKER_SOURCE]

    problems = unresolved_imports(ORCHESTRATOR_SOURCE, core_trees, baseline(), source_trees())

    assert problems == [], "\n".join(problems)


def test_the_orchestrator_package_depends_on_the_core_not_the_worker_and_owns_the_abk_script() -> (
    None
):
    manifest = ORCHESTRATOR_ROOT / "pyproject.toml"
    assert manifest.is_file()
    project = tomllib.loads(manifest.read_text())["project"]

    assert project["name"] == "agent-build-kit-orchestrator"
    assert any(d.startswith("agent-build-kit-core") for d in project["dependencies"])
    assert not any(d.startswith("agent-build-kit-worker") for d in project["dependencies"])
    assert project["scripts"]["abk"] == "agent_build_kit.cli:main"


@pytest.mark.integration
def test_the_root_source_tree_holds_no_module_once_the_packages_hold_them() -> None:
    assert (ORCHESTRATOR_SOURCE / "cli" / "pipeline.py").is_file()

    left = [
        p.relative_to(SOURCE_ROOT).as_posix()
        for p in sorted(SOURCE_ROOT.rglob("*.py"))
        if p.name != "__init__.py"
    ]

    assert left == [], "\n".join(left)


def test_the_root_project_depends_on_the_worker_and_the_orchestrator() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    names = {d.split(">")[0].split("=")[0].split("[")[0].strip() for d in project["dependencies"]}

    assert {"agent-build-kit-worker", "agent-build-kit-orchestrator"} <= names


def test_the_root_project_leaves_the_abk_script_and_the_worker_command_to_the_packages() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert "abk" not in project["scripts"]
    assert COMMANDS_GROUP not in project.get("entry-points", {})


def test_every_package_the_root_project_installs_from_packages_is_a_workspace_member() -> None:
    uv = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]

    packages = {name for name in uv["sources"] if name.startswith("agent-build-kit-")}

    assert {"agent-build-kit-worker", "agent-build-kit-orchestrator"} <= packages
    assert {name for name in packages if uv["sources"][name] != {"workspace": True}} == set()
    assert "packages/*" in uv["workspace"]["members"]


@pytest.mark.integration
def test_a_plain_interpreter_imports_the_cli_and_the_worker_from_the_packages() -> None:
    code = (
        "import agent_build_kit.cli as cli, agent_build_kit.graph.unit as unit;"
        "print(cli.__file__); print(unit.__file__)"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True, timeout=120
    )

    cli_file, unit_file = (Path(line).resolve() for line in result.stdout.splitlines())
    assert cli_file.is_relative_to(ORCHESTRATOR_SOURCE)
    assert unit_file.is_relative_to(WORKER_SOURCE)


def is_worker_test(relative: Path, modules: Collection[str]) -> bool:
    """Whether the test file `relative` (below a tests folder) tests a module of the worker.

    A package the worker owns whole (`graph`) owns every test file in its mirror folder except
    those of a module that stays in the core (`graph.checkpointer`); any other worker module owns
    the test files in its mirror folder named `test_<module>*.py`.
    """
    if not relative.name.startswith("test_") or relative.suffix != ".py":
        return False
    folder = relative.parent.as_posix()
    if folder == "graph":
        return not relative.name.startswith(CORE_TEST_PREFIX)
    return is_module_test(relative, modules)


def owning_module(relative: Path, modules: Collection[str]) -> str | None:
    """The module (path under a source tree) whose test file `relative` (below a tests folder) is:
    the one in its mirror folder with the longest name that `test_<module>` begins the file name
    with; none when no module is."""
    folder = relative.parent.as_posix()
    matches = [
        module
        for module in modules
        if not module.startswith("graph/")
        and Path(module).parent.as_posix() == folder
        and relative.name.startswith(f"test_{Path(module).stem}")
    ]
    matches.sort(key=lambda module: len(Path(module).stem))
    return matches[-1] if matches else None


def is_module_test(relative: Path, modules: Collection[str]) -> bool:
    """Whether the test file `relative` (below a tests folder) sits in the mirror folder of one of
    `modules` (paths under a source tree) and is named `test_<module>*.py`."""
    return owning_module(relative, modules) is not None


@pytest.mark.integration
def test_every_test_file_of_a_worker_module_is_under_the_worker_package_mirroring_the_source() -> (
    None
):
    modules = worker_modules()
    files = tracked(ROOT)
    misplaced = [
        str(path)
        for path in files
        if path.is_relative_to(TESTS) and is_worker_test(path.relative_to(TESTS), modules)
    ]
    moved = [
        path.relative_to(WORKER_TESTS)
        for path in files
        if path.is_relative_to(WORKER_TESTS) and path.name.startswith("test_")
    ]

    assert misplaced == [], "move under packages/worker/tests/: " + ", ".join(misplaced)
    assert moved, "packages/worker/tests holds no test file"
    assert [str(p) for p in moved if not is_worker_test(p, modules)] == []


@pytest.mark.integration
def test_every_orchestrator_module_test_file_is_in_the_orchestrator_package_mirroring_source() -> (
    None
):
    modules = [m for m in orchestrator_modules() if not m.endswith("__init__.py")]
    files = tracked(ROOT)
    misplaced = [
        str(path)
        for path in files
        if path.is_relative_to(TESTS)
        and path.name.startswith("test_")
        and path.suffix == ".py"
        and is_module_test(path.relative_to(TESTS), modules)
    ]
    moved = [
        path.relative_to(ORCHESTRATOR_TESTS)
        for path in files
        if path.is_relative_to(ORCHESTRATOR_TESTS) and path.name.startswith("test_")
    ]

    assert misplaced == [], "move under packages/orchestrator/tests/: " + ", ".join(misplaced)
    assert moved, "packages/orchestrator/tests holds no test file"
    assert [str(p) for p in moved if not is_module_test(p, modules)] == []


def test_the_pytest_run_and_the_ci_test_job_cover_the_root_suite_and_each_package_tests() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]
    testpaths = config["pytest"]["ini_options"]["testpaths"]
    task = config["poe"]["tasks"]["test"]
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    commands = [step.get("run", "") for step in workflow["jobs"]["test"]["steps"]]

    assert {
        "tests",
        CORE_TESTS.as_posix(),
        WORKER_TESTS.as_posix(),
        ORCHESTRATOR_TESTS.as_posix(),
    } <= set(testpaths)
    # The task names no test path of its own, so it runs what `testpaths` lists.
    arguments = (task if isinstance(task, str) else task["cmd"]).split()
    assert [a for a in arguments if a.startswith(("tests", "packages"))] == []
    assert any("poe test" in command for command in commands)


@pytest.mark.integration
def test_a_test_file_base_name_is_unique_across_the_repository() -> None:
    files = tracked(ROOT)
    for folder in (WORKER_TESTS, ORCHESTRATOR_TESTS):
        assert any(
            path.is_relative_to(folder) and path.name.startswith("test_") for path in files
        ), f"{folder} holds no test file, so the uniqueness check does not span it"

    assert base_name_clashes(files) == {}


def core_owned_whole() -> frozenset[str]:
    """The packages the core's seeds name whole: every test file in their mirror folder is the
    core's."""
    return frozenset(seed for seed in seeds().core if "." not in seed)


def is_core_test(
    relative: Path,
    core_modules: Collection[str],
    other_modules: Collection[str],
    *,
    scans_repository: bool = False,
) -> bool:
    """Whether the test file `relative` (below a tests folder) tests a module of the core.

    It is the core's when it is in the mirror folder of a core module and named
    `test_<module>*.py` (the longest module name across the core and the other packages wins),
    when its folder is a package the core's seeds name whole, or when it is a
    `graph/test_checkpoint*` file; a file that reads the whole repository (`scans_repository`) is
    never the core's.
    """
    if scans_repository or not relative.name.startswith("test_") or relative.suffix != ".py":
        return False
    folder = relative.parent.as_posix()
    if folder in core_owned_whole():
        return True
    if folder == "graph":
        return relative.name.startswith(CORE_TEST_PREFIX)
    owner = owning_module(relative, [*core_modules, *other_modules])
    return owner is not None and owner in core_modules


def core_baseline() -> list[str]:
    """The globs, relative to `tests/`, of the core tests the baseline tolerates in the root."""
    return tomllib.loads(CORE_TESTS_BASELINE.read_text())["globs"]


def core_test_problems(
    root: Path,
    files: Iterable[Path],
    core_modules: Collection[str],
    other_modules: Collection[str],
    baseline_globs: Sequence[str],
) -> list[str]:
    """What the tracked `files` (relative to `root`, under `tests/`) get wrong about where the
    core's tests are: a root test the core claims that no baseline glob covers, and a baseline
    glob that covers no claimed file."""
    claimed: list[Path] = []
    for path in files:
        if not path.is_relative_to(TESTS):
            continue
        scans = scans_the_repository((root / path).read_text())
        if is_core_test(
            path.relative_to(TESTS), core_modules, other_modules, scans_repository=scans
        ):
            claimed.append(path.relative_to(TESTS))

    def covered(relative: Path, pattern: str) -> bool:
        # A `*` stays within one path segment.
        names, patterns = relative.parts, pattern.split("/")
        return len(names) == len(patterns) and all(
            fnmatch.fnmatchcase(n, p) for n, p in zip(names, patterns, strict=True)
        )

    problems = [
        f"{TESTS / path} is a core test: move it under {CORE_TESTS / path.parent}/"
        for path in claimed
        if not any(covered(path, pattern) for pattern in baseline_globs)
    ]
    problems += [
        f"baseline entry {pattern} covers no core test: remove it from the baseline"
        for pattern in baseline_globs
        if not any(covered(path, pattern) for path in claimed)
    ]
    return problems


def base_name_clashes(files: Iterable[Path]) -> dict[str, list[str]]:
    """The test file base names (`test_*.py` below a tests folder of the root, the core, the worker
    or the orchestrator) that more than one file carries, each with all its paths."""
    seen: dict[str, list[str]] = {}
    for path in files:
        if (
            any(
                path.is_relative_to(f)
                for f in (TESTS, CORE_TESTS, WORKER_TESTS, ORCHESTRATOR_TESTS)
            )
            and path.name.startswith("test_")
            and path.suffix == ".py"
        ):
            seen.setdefault(path.name, []).append(path.as_posix())
    return {name: paths for name, paths in seen.items() if len(paths) > 1}


def written(tmp_path: Path, files: Mapping[str, str]) -> list[Path]:
    """Write `files` (relative path to text) under `tmp_path`; the relative paths."""
    tree(tmp_path, dict(files))
    return [Path(name) for name in files]


CORE_MODULES = ["pipeline/plan.py", "pipeline/unit_store.py", "forges/base.py"]
OTHER_MODULES = ["pipeline/plan_review.py", "graph/nodes.py"]


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("pipeline/test_unit_store_new_case.py", True),
        ("pipeline/test_plan.py", True),
        ("pipeline/test_plan_review_x.py", False),
        ("pipeline/test_unrelated.py", False),
        ("cli/test_unit_store.py", False),
        ("forges/test_anything_at_all.py", True),
        ("hooks/test_anything_at_all.py", True),
        ("graph/test_checkpoint_resume.py", True),
        ("graph/test_nodes.py", False),
        ("pipeline/helper_unit_store.py", False),
    ],
)
def test_the_core_rule_claims_a_test_by_its_folder_and_its_longest_module_name(
    relative: str, expected: bool
) -> None:
    assert is_core_test(Path(relative), CORE_MODULES, OTHER_MODULES) is expected


def test_a_test_that_scans_the_whole_repository_is_not_claimed_by_the_core() -> None:
    relative = Path("pipeline/test_unit_store_scan.py")

    assert not is_core_test(relative, CORE_MODULES, OTHER_MODULES, scans_repository=True)


def test_a_core_test_left_in_the_root_fails_naming_the_file_and_its_folder_in_the_core(
    tmp_path: Path,
) -> None:
    files = written(tmp_path, {"tests/pipeline/test_unit_store_new_case.py": ""})

    problems = core_test_problems(tmp_path, files, CORE_MODULES, OTHER_MODULES, [])

    assert len(problems) == 1
    assert "tests/pipeline/test_unit_store_new_case.py" in problems[0]
    assert "packages/core/tests/pipeline/" in problems[0]


def test_a_core_test_a_baseline_glob_covers_is_not_reported(tmp_path: Path) -> None:
    files = written(tmp_path, {"tests/pipeline/test_unit_store_new_case.py": ""})

    problems = core_test_problems(
        tmp_path, files, CORE_MODULES, OTHER_MODULES, ["pipeline/test_unit_store*.py"]
    )

    assert problems == []


def test_a_test_that_calls_a_whole_tree_helper_is_not_asked_to_move(tmp_path: Path) -> None:
    text = "from tests.tracked_files import ROOT\n\n\ndef test_scan():\n    hits(ROOT)\n"
    files = written(tmp_path, {"tests/pipeline/test_unit_store_scan.py": text})

    assert core_test_problems(tmp_path, files, CORE_MODULES, OTHER_MODULES, []) == []


def test_a_test_that_imports_only_the_repository_root_is_asked_to_move(tmp_path: Path) -> None:
    text = "from tests.tracked_files import ROOT\nPATH = ROOT / 'x'\n"
    files = written(tmp_path, {"tests/pipeline/test_unit_store_x.py": text})

    problems = core_test_problems(tmp_path, files, CORE_MODULES, OTHER_MODULES, [])

    assert len(problems) == 1
    assert "tests/pipeline/test_unit_store_x.py" in problems[0]


def test_a_baseline_entry_that_covers_no_file_fails_until_it_is_removed(tmp_path: Path) -> None:
    files = written(tmp_path, {"tests/cli/test_other.py": ""})

    problems = core_test_problems(tmp_path, files, CORE_MODULES, OTHER_MODULES, ["forges/*.py"])

    assert len(problems) == 1
    assert "forges/*.py" in problems[0]


@pytest.mark.integration
def test_the_root_holds_no_core_test_the_core_baseline_does_not_cover() -> None:
    modules = assigned_modules(CORE, packages_as_init=False)
    others = [m for m in worker_modules() + orchestrator_modules() if not m.endswith("__init__.py")]
    files = [path for path in tracked(ROOT) if path.is_relative_to(TESTS)]

    problems = core_test_problems(ROOT, files, modules, others, core_baseline())

    assert problems == [], "\n".join(problems)


def test_the_two_paths_of_a_test_base_name_shared_across_the_trees_are_named() -> None:
    files = [Path("packages/core/tests/pipeline/test_x.py"), Path("tests/cli/test_x.py")]

    assert base_name_clashes(files) == {"test_x.py": [f.as_posix() for f in files]}


def test_a_test_base_name_held_once_in_each_tree_is_no_clash() -> None:
    files = [Path("packages/core/tests/test_a.py"), Path("tests/test_b.py")]

    assert base_name_clashes(files) == {}


def test_pyrefly_checks_the_core_tests() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]

    assert CORE_TESTS.as_posix() in config["pyrefly"]["project-includes"]


def test_the_core_tests_baseline_holds_no_more_lines_than_the_ceiling() -> None:
    assert 0 < len(core_baseline()) <= CORE_TESTS_BASELINE_CEILING


EXTRA_TEST = "pipeline/test_units_in_progress.py"
OWN_TEST = "pipeline/test_units.py"


def units_tree(tests_root: str = "tests", *, root_tests: bool = False) -> PlacementTree:
    return PlacementTree(
        tests_root=Path(tests_root), modules=("pipeline/units.py",), root_tests=root_tests
    )


def lay_out(tmp_path: Path, tests_root: str, *names: str) -> None:
    tree(tmp_path, {f"{tests_root}/{name}": "" for name in names})


def test_a_second_test_file_for_a_module_fails_naming_it_and_the_file_it_belongs_in(
    tmp_path: Path,
) -> None:
    lay_out(tmp_path, "tests", OWN_TEST, EXTRA_TEST)

    problems = placement_problems(tmp_path, [units_tree()], [])

    assert len(problems) == 1
    assert EXTRA_TEST in problems[0] and OWN_TEST in problems[0]


def test_a_test_file_in_the_baseline_passes(tmp_path: Path) -> None:
    lay_out(tmp_path, "tests", OWN_TEST, EXTRA_TEST)

    assert placement_problems(tmp_path, [units_tree()], [EXTRA_TEST]) == []


@pytest.mark.parametrize("names", [(OWN_TEST,), (OWN_TEST, EXTRA_TEST)], ids=["gone", "fixed"])
def test_a_baseline_entry_that_names_no_offending_file_fails_until_removed(
    names: tuple[str, ...], tmp_path: Path
) -> None:
    entry = "pipeline/test_units_gone.py" if len(names) == 1 else OWN_TEST
    lay_out(tmp_path, "tests", *names)

    listed = [name for name in names if name == EXTRA_TEST]

    problems = placement_problems(tmp_path, [units_tree()], [*listed, entry])

    assert len(problems) == 1 and entry in problems[0]


def test_a_baseline_entry_still_allows_a_file_after_it_moves_to_the_core_tests(
    tmp_path: Path,
) -> None:
    lay_out(tmp_path, "packages/core/tests", OWN_TEST, EXTRA_TEST)

    problems = placement_problems(tmp_path, [units_tree("packages/core/tests")], [EXTRA_TEST])

    assert problems == []


@pytest.mark.parametrize(
    "name",
    [
        "integration/test_anything_goes.py",
        "e2e/test_anything_goes.py",
        "docs/test_anything_goes.py",
        "test_anything_goes.py",
    ],
)
def test_a_file_under_integration_or_e2e_or_unclaimed_in_the_root_tests_is_outside_the_rule(
    name: str, tmp_path: Path
) -> None:
    lay_out(tmp_path, "tests", OWN_TEST, name)

    assert placement_problems(tmp_path, [units_tree(root_tests=True)], []) == []


def test_a_root_test_file_named_for_a_module_of_another_package_is_left_to_that_package(
    tmp_path: Path,
) -> None:
    lay_out(tmp_path, "tests", OWN_TEST, "pipeline/test_gate_extra.py")
    root_tree = PlacementTree(
        tests_root=Path("tests"),
        modules=("pipeline/units.py",),
        other_modules=("pipeline/gate.py",),
        root_tests=True,
    )

    assert placement_problems(tmp_path, [root_tree], []) == []


def test_the_baseline_generator_writes_the_sorted_offenders_and_a_second_run_changes_nothing(
    tmp_path: Path,
) -> None:
    lay_out(tmp_path, "tests", OWN_TEST, EXTRA_TEST, "pipeline/test_a_second.py", "e2e/test_x.py")
    path = tmp_path / "placement_baseline.toml"

    write_baseline(tmp_path, [units_tree()], path)
    first = path.read_text()
    write_baseline(tmp_path, [units_tree()], path)

    assert read_baseline(path) == ["pipeline/test_a_second.py", EXTRA_TEST]
    assert path.read_text() == first


@pytest.mark.integration
def test_the_kit_test_trees_break_the_placement_rule_only_where_the_baseline_says() -> None:
    problems = placement_problems(ROOT, kit_trees(ROOT), read_baseline(BASELINE))

    assert problems == [], "\n".join(problems)
