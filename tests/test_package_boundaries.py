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
import tomllib
from collections.abc import Collection, Iterator, Mapping
from pathlib import Path

import pytest

from agent_build_kit.cli import COMMANDS_GROUP
from tests.ecosystem_names import WORKER_MODULES
from tests.support.package_seeds import Seeds, baseline, seeds
from tests.tracked_files import ROOT, SOURCE_ROOT, WORKER_SOURCE, source_trees, tracked
from tests.workspace_packages import PACKAGE_NAME, PACKAGES, source_root

WORKER_ROOT = WORKER_SOURCE.parents[1]
# The source trees that install into the root package's namespace.
OTHER_TREES = [tree for tree in source_trees() if tree != SOURCE_ROOT]
TESTS = Path("tests")
WORKER_TESTS = Path("packages") / "worker" / "tests"
CORE_TEST_PREFIX = "test_checkpoint"
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


def worker_problems(
    worker_source: Path, core_source: Path, given: Seeds, known: Collection[Edge]
) -> list[str]:
    """Each module-level import in the worker's tree of an orchestrator module, beyond `known`."""
    beside = [tree for tree in OTHER_TREES if tree != core_source]
    edges = module_imports(core_source, [worker_source, *(t for t in beside if t != worker_source)])
    packages = assign(edges, given)
    own = {module_name(worker_source, p) for p in worker_source.rglob("*.py")}
    return [
        f"{module} imports {other} ({ORCHESTRATOR})"
        for module, imported in sorted(edges.items())
        if module in own
        for other in sorted(imported)
        if packages.get(other) == ORCHESTRATOR and (module, other) not in known
    ]


def worker_modules() -> list[str]:
    """The modules the seeds assign to the worker, as paths under a source tree; a package whose
    `__init__` stays in the core to extend the namespace is not a module of the worker."""
    edges = module_imports(SOURCE_ROOT, OTHER_TREES)
    return sorted(
        f"{module.replace('.', '/')}.py"
        for module, package in assign(edges, seeds()).items()
        if package == WORKER and not (SOURCE_ROOT / module.replace(".", "/")).is_dir()
    )


@pytest.mark.parametrize("module", worker_modules())
def test_a_module_the_table_assigns_to_the_worker_is_in_the_worker_package(module: str) -> None:
    assert (WORKER_SOURCE / module).is_file()
    assert not (SOURCE_ROOT / module).exists()


def test_the_worker_modules_the_wheel_test_lists_are_those_the_seeds_assign() -> None:
    assert sorted(WORKER_MODULES) == worker_modules()


@pytest.mark.integration
def test_no_file_of_the_worker_package_imports_an_orchestrator_module() -> None:
    assert (WORKER_SOURCE / "cli" / "worker.py").is_file()

    problems = worker_problems(WORKER_SOURCE, SOURCE_ROOT, seeds(), baseline())

    assert problems == [], "\n".join(problems)


def test_the_worker_package_depends_on_the_core_and_registers_abk_worker_as_a_command() -> None:
    manifest = WORKER_ROOT / "pyproject.toml"
    assert manifest.is_file()
    project = tomllib.loads(manifest.read_text())["project"]

    assert project["name"] == "agent-build-kit-worker"
    assert any(d.startswith("agent-build-kit-core") for d in project["dependencies"])
    assert project["entry-points"][COMMANDS_GROUP] == {
        "worker": "agent_build_kit.cli.worker:register"
    }


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
    return any(
        Path(module).parent.as_posix() == folder
        and relative.name.startswith(f"test_{Path(module).stem}")
        for module in modules
        if not module.startswith("graph/")
    )


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
def test_a_test_file_base_name_is_unique_across_the_repository() -> None:
    seen: dict[str, list[str]] = {}
    files = tracked(ROOT)
    assert any(
        path.is_relative_to(WORKER_TESTS) and path.name.startswith("test_") for path in files
    ), "packages/worker/tests holds no test file, so the uniqueness check does not span it"
    for path in files:
        in_a_tests_folder = path.is_relative_to(TESTS) or path.is_relative_to(WORKER_TESTS)
        if in_a_tests_folder and path.name.startswith("test_") and path.suffix == ".py":
            seen.setdefault(path.name, []).append(str(path))

    assert {name: paths for name, paths in seen.items() if len(paths) > 1} == {}
