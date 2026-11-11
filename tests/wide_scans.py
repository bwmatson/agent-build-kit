"""The guard that a test scanning the whole repository is an integration test (spec:
wide-scans-are-integration).

A scan is found by parsing a test module (strings and comments never count): a `test_` function that
  - calls a whole-tree helper (`guarded_files`, `hits`, `files`, `leaks`, `home_path_leaks`,
    `repo_path_leaks`, `find_live_modules`, `check_sources`, `splits_by_syntax`, `Scan`) with no
    `under=` folder, over a path that is not the test's own temporary tree, or
  - walks a folder with `glob` or `rglob` that is anchored at the repository: a path built from a
    module-level constant (`ROOT`, `SOURCE_ROOT`, `WORKFLOWS`) or from `__file__`. A folder the
    test made itself (`repo.glob(...)` of a local) is its own.
A call of a helper of the same module that scans is a scan too, so a test that only calls
`walk()` is found, and so is a test that takes such a helper as a fixture parameter. Only a
fixture of the same module counts: one moved to a `conftest.py` is not seen, so a scan fixture
that is shared must be marked on the tests that take it. A path is
the test's own when it comes from one of its parameters (`tmp_path` and the other fixtures)
through plain assignments.

`check_tests` returns one message per problem: a scan with no `integration` selector (on the test,
its class or the module) that the baseline does not name, and a baseline entry that is no longer an
unmarked scan, as a stale entry. The baseline may only shrink. A scan reached in a way the guard
does not know is not found; the baseline and the audit catch those, and the guard learns the name.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
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
        "Scan",
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
    arguments = function.args
    parameters = {a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if parameters & helpers:
        return True
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


def _module_marked(tree: ast.Module, marks: Callable[[ast.AST], bool] = _integration) -> bool:
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        and marks(node.value)
        for node in tree.body
    )


def walk_tests(
    tree: ast.Module, marks: Callable[[ast.AST], bool] = _integration
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]]:
    """Every `test_` function of a module, with whether the selector `marks` finds sits on the
    test, its class or the module (`pytestmark`)."""
    found: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]] = []

    def visit(body: list[ast.stmt], marked: bool) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, marked or any(marks(d) for d in node.decorator_list))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
                "test_"
            ):
                found.append((node, marked or any(marks(d) for d in node.decorator_list)))

    visit(tree.body, _module_marked(tree, marks))
    return found


def check_modules(
    root: Path,
    find: Callable[[str], Mapping[str, str]],
    *,
    baseline: frozenset[str],
    baseline_file: Path,
    new_message: Callable[[str, str], str],
    stale_reason: str,
) -> list[str]:
    """The skeleton both guards share: `find` maps a module's text to its offending tests (name to
    detail); one message per offender the baseline does not name, one per baseline entry that
    offends no longer, and one per module that cannot be parsed."""
    found: dict[str, str] = {}
    problems: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        if any(
            part.startswith(".") or part == "child_modules" for part in path.relative_to(root).parts
        ):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            offenders = find(path.read_text())
        except SyntaxError as error:
            problems.append(f"{relative}: cannot be parsed ({error.msg}, line {error.lineno})")
            continue
        for name, detail in offenders.items():
            found[f"{relative}::{name}"] = detail
    problems += [new_message(entry, found[entry]) for entry in sorted(found.keys() - baseline)]
    problems += [
        f"{entry}: stale baseline entry, {stale_reason}; remove it from {baseline_file.name}"
        for entry in sorted(baseline - found.keys())
    ]
    return problems


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


def _unmarked_scans(text: str) -> dict[str, str]:
    """The tests in a module that scan the repository and carry no `integration` selector."""
    if not any(word in text for word in SCAN_TEXT):
        return {}
    tree = ast.parse(text)
    helpers = _scan_helpers(tree)
    return {
        node.name: "" for node, marked in walk_tests(tree) if not marked and _is_scan(node, helpers)
    }


def check_tests(root: Path = TESTS_ROOT, *, baseline: frozenset[str]) -> list[str]:
    """One message per problem in the test modules under `root`."""
    return check_modules(
        root,
        _unmarked_scans,
        baseline=baseline,
        baseline_file=BASELINE_FILE,
        new_message=lambda entry, _: (
            f"{entry}: scans the repository and is not marked integration; mark the test "
            "`@pytest.mark.integration` (a baseline entry is for a scan that exists today)"
        ),
        stale_reason="it is no longer an unmarked scan",
    )
