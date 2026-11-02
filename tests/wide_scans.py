"""The guard that a test scanning the whole repository is an integration test (spec:
wide-scans-are-integration).

A scan is found by parsing a test module (strings and comments never count): a `test_` function that
  - calls a whole-tree helper (`guarded_files`, `hits`, `files`, `leaks`, `home_path_leaks`,
    `repo_path_leaks`, `find_live_modules`, `check_sources`, `splits_by_syntax`) with no `under=`
    folder, over a path that is not the test's own temporary tree, or
  - walks a folder with `glob` or `rglob` that is anchored at the repository: a path built from a
    module-level constant (`ROOT`, `SOURCE_ROOT`, `WORKFLOWS`) or from `__file__`. A folder the
    test made itself (`repo.glob(...)` of a local) is its own.
A call of a helper of the same module that scans is a scan too, so a test that only calls
`walk()` is found. A path is the test's own when it comes from one of its parameters (`tmp_path`
and the other fixtures) through plain assignments.

`check_tests` returns one message per problem: a scan with no `integration` selector (on the test,
its class or the module) that the baseline does not name, and a baseline entry that is no longer an
unmarked scan, as a stale entry. The baseline may only shrink. A scan reached in a way the guard
does not know is not found; the baseline and the audit catch those, and the guard learns the name.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).parent
BASELINE_FILE = TESTS_ROOT / "wide_scans_baseline.txt"

WHOLE_TREE_CALLS = frozenset(
    {
        "guarded_files",
        "hits",
        "files",
        "leaks",
        "home_path_leaks",
        "repo_path_leaks",
        "find_live_modules",
        "check_sources",
        "splits_by_syntax",
    }
)
# What every scan is made of; a file naming none of it is not parsed, which keeps a walk of the
# whole tree inside the per-test time limit under load.
SCAN_TEXT = (*(f"{name}(" for name in WHOLE_TREE_CALLS), "glob(")
GLOBS = frozenset({"glob", "rglob"})


def load_baseline(path: Path = BASELINE_FILE) -> frozenset[str]:
    """The scans that are unmarked today, as `path::test` entries under the tests root."""
    return frozenset(
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _called(node: ast.Call) -> str:
    """The name of a called function or method."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _whole_tree_helper(node: ast.Call) -> bool:
    """A call of one of the whole-tree helpers by its imported name; a method that happens to
    be called `files` or `hits` (a forge's, a result's) is not one."""
    return isinstance(node.func, ast.Name) and node.func.id in WHOLE_TREE_CALLS


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _own_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """The test's parameters and every local that is assigned from one of them."""
    arguments = function.args
    own = {a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    own.discard("self")
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and _names(node.value) & own:
            own.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return own


def _anchored(node: ast.AST) -> bool:
    """Whether a path is built from a module-level constant or from `__file__`."""
    return any(name == "__file__" or name.isupper() for name in _names(node))


def _is_scan(
    function: ast.FunctionDef | ast.AsyncFunctionDef, helpers: frozenset[str] = frozenset()
) -> bool:
    """Whether a function scans the repository itself or calls a helper of its module that does."""
    own = _own_names(function)
    calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)]
    for call in calls:
        if isinstance(call.func, ast.Name) and call.func.id in helpers:
            return True
        if _whole_tree_helper(call) and not any(k.arg == "under" for k in call.keywords):
            root = (
                call.args[0]
                if call.args
                else next((k.value for k in call.keywords if k.arg == "root"), None)
            )
            if root is None or not _names(root) & own:
                return True
    return any(
        _called(c) in GLOBS
        and isinstance(c.func, ast.Attribute)
        and _anchored(c.func.value)
        and not _names(c.func.value) & own
        for c in calls
    )


def _integration(node: ast.AST) -> bool:
    """Whether a decorator or `pytestmark` value names the `integration` marker."""
    return any(isinstance(n, ast.Attribute) and n.attr == "integration" for n in ast.walk(node))


def _module_marked(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        and _integration(node.value)
        for node in tree.body
    )


def _scan_helpers(tree: ast.Module) -> frozenset[str]:
    """The functions of a module, other than its tests, that scan the repository, directly or
    through another of them."""
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("test_")
    ]
    found: frozenset[str] = frozenset()
    while True:
        more = frozenset(f.name for f in functions if _is_scan(f, found))
        if more == found:
            return found
        found = more


def _unmarked_scans(text: str) -> list[str]:
    """The names of the tests in a module that scan the repository and carry no
    `integration` selector."""
    if not any(word in text for word in SCAN_TEXT):
        return []
    tree = ast.parse(text)
    if _module_marked(tree):
        return []
    found: list[str] = []
    helpers = _scan_helpers(tree)

    def visit(body: list[ast.stmt], marked: bool) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, marked or any(_integration(d) for d in node.decorator_list))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if (
                    node.name.startswith("test_")
                    and not marked
                    and not any(_integration(d) for d in node.decorator_list)
                    and _is_scan(node, helpers)
                ):
                    found.append(node.name)

    visit(tree.body, False)
    return found


def check_tests(root: Path = TESTS_ROOT, *, baseline: frozenset[str]) -> list[str]:
    """One message per problem in the test modules under `root`."""
    scans: set[str] = set()
    problems: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        if any(
            part.startswith(".") or part == "child_modules" for part in path.relative_to(root).parts
        ):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            names = _unmarked_scans(path.read_text())
        except SyntaxError as error:
            problems.append(f"{relative}: cannot be parsed ({error.msg}, line {error.lineno})")
            continue
        for name in names:
            scans.add(f"{relative}::{name}")
    problems += [
        f"{entry}: scans the repository and is not marked integration; mark the test "
        "`@pytest.mark.integration` (a baseline entry is for a scan that exists today)"
        for entry in sorted(scans - baseline)
    ]
    problems += [
        f"{entry}: stale baseline entry, it is no longer an unmarked scan; remove it from "
        f"{BASELINE_FILE.name}"
        for entry in sorted(baseline - scans)
    ]
    return problems
