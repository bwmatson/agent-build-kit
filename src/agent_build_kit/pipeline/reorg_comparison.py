"""The before-and-after comparison of a reorganization's test files (standard T26).

A reorganization changes tests only mechanically. This module reads each changed test file
at the parent and at the new version, by AST, and reports every difference that is not
mechanical: an assertion or expected value that differs, a test that is gone or new, a skip,
expected failure or marker that is added, a time limit that is raised.

"Mechanical" means the file was moved (git follows the rename), its imports were edited, or a
name it imports or defines, or a marker it uses, was renamed consistently. Such names are
numbered by first appearance inside each test, so a renamed import compares equal to the
original.

A characterization test committed first, before the code moves, is the one allowed addition.
"""

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git

STANDARD = "T26"

# Markers pytest or a plugin gives meaning to; any other marker name may be renamed as a whole.
_BUILTIN_MARKERS = frozenset(
    {"skip", "skipif", "xfail", "timeout", "parametrize", "usefixtures", "filterwarnings"}
)
_SKIPS = frozenset({"skip", "skipif", "xfail"})


class Finding(Frozen):
    """One way a changed test file differs from its parent's version beyond a mechanical edit."""

    standard: str
    path: str
    test: str
    reason: str


@dataclass(frozen=True)
class _Shape:
    """A test as the comparison sees it: normalised decorators, time limit and body."""

    decorators: tuple[tuple[str, str], ...]  # (marker name, normalised dump)
    timeout: float | None
    body: str


class _Numbering(ast.NodeTransformer):
    """Replaces each bound name by its order of first appearance and applies marker renames."""

    def __init__(self, bound: set[str], renames: dict[str, str]) -> None:
        self.bound = bound
        self.renames = renames
        self.numbers: dict[str, int] = {}

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id in self.bound:
            node.id = f"_{self.numbers.setdefault(node.id, len(self.numbers))}"
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        node.attr = self.renames.get(node.attr, node.attr)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str) and node.value in self.renames:
            node.value = self.renames[node.value]
        return node


def _bound_names(tree: ast.Module) -> set[str]:
    """Names a test may reach at module level: imports, helpers and constants."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update((a.asname or a.name.split(".")[0]) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update((a.asname or a.name) for a in node.names)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if not node.name.startswith(("test", "Test")):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _functions(tree: ast.Module) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and item.name.startswith("test"):
                    found.append((f"{node.name}.{item.name}", item))
    return found


def _marker_name(decorator: ast.expr) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return target.attr if isinstance(target, ast.Attribute) else ast.dump(target)


def _custom_markers(tree: ast.Module) -> list[str]:
    """The distinct marker names the file uses beyond pytest's own, in order of appearance."""
    seen: list[str] = []
    for _, fn in _functions(tree):
        for decorator in fn.decorator_list:
            name = _marker_name(decorator)
            if name not in _BUILTIN_MARKERS and name not in seen:
                seen.append(name)
    return seen


def _marker_renames(before: ast.Module, after: ast.Module) -> dict[str, str]:
    """Marker names of the new version mapped back to the parent's, when the sets line up."""
    old, new = _custom_markers(before), _custom_markers(after)
    if len(old) != len(new):
        return {}
    return {n: o for o, n in zip(old, new, strict=True) if o != n}


def _timeout(decorator: ast.expr) -> float | None:
    if isinstance(decorator, ast.Call) and _marker_name(decorator) == "timeout" and decorator.args:
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, int | float):
            return float(first.value)
    return None


def _shapes(tree: ast.Module, renames: dict[str, str]) -> dict[str, _Shape]:
    bound = _bound_names(tree)
    shapes: dict[str, _Shape] = {}
    for name, fn in _functions(tree):
        decorators: list[tuple[str, str]] = []
        timeout: float | None = None
        numbering = _Numbering(bound, renames)
        for decorator in fn.decorator_list:
            limit = _timeout(decorator)
            if limit is not None:
                timeout = limit
                continue
            marker = renames.get(_marker_name(decorator), _marker_name(decorator))
            copy = ast.parse(ast.unparse(decorator), mode="eval").body
            decorators.append((marker, ast.dump(numbering.visit(copy))))
        numbering = _Numbering(bound, renames)
        body = "".join(
            ast.dump(numbering.visit(ast.parse(ast.unparse(s)).body[0])) for s in fn.body
        )
        shapes[name] = _Shape(tuple(decorators), timeout, body)
    return shapes


def _differences(name: str, before: _Shape, after: _Shape) -> list[tuple[str, str]]:
    """(test, reason) for how `after` differs from `before`."""
    found: list[tuple[str, str]] = []
    remaining = list(before.decorators)
    for marker, dump in after.decorators:
        if (marker, dump) in remaining:
            remaining.remove((marker, dump))
        elif marker in _SKIPS:
            found.append((name, f"a {marker} is added"))
        else:
            found.append((name, f"the marker {marker} is added or changed"))
    found.extend((name, f"the marker {marker} is removed or changed") for marker, _ in remaining)
    if after.timeout is not None and (before.timeout is None or after.timeout > before.timeout):
        found.append((name, f"the time limit is raised to {after.timeout:g}"))
    elif after.timeout is None and before.timeout is not None:
        found.append((name, "the time limit is removed"))
    if before.body != after.body:
        found.append((name, "an assertion or expected value differs from the parent's"))
    return found


def _parse(source: str) -> ast.Module:
    return ast.parse(source)


def _compare(
    before: str, after: str, path: str
) -> tuple[list[Finding], dict[str, _Shape], dict[str, _Shape]]:
    """Findings for tests present in both versions, and the tests found only in one."""
    old_tree, new_tree = _parse(before), _parse(after)
    old = _shapes(old_tree, {})
    new = _shapes(new_tree, _marker_renames(old_tree, new_tree))
    findings = [
        Finding(standard=STANDARD, path=path, test=test, reason=reason)
        for name in old.keys() & new.keys()
        for test, reason in _differences(name, old[name], new[name])
    ]
    findings.sort(key=lambda f: (f.test, f.reason))
    return (
        findings,
        {k: v for k, v in old.items() if k not in new},
        {k: v for k, v in new.items() if k not in old},
    )


def compare_sources(before: str, after: str) -> list[Finding]:
    """Findings for one Python test file, read by AST, with renamed imports and names normalised."""
    findings, gone, new = _compare(before, after, "")
    findings += [
        Finding(
            standard=STANDARD, path="", test=name, reason="the test is absent from the new version"
        )
        for name in gone
    ]
    findings += [
        Finding(standard=STANDARD, path="", test=name, reason="the test is added") for name in new
    ]
    return findings


def _is_python_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return name.endswith(".py") and (
        "tests" in parts[:-1] or bool(re.match(r"test_.*\.py$|.*_test\.py$", name))
    )


def compare_changes(
    repo: Path,
    base: str,
    head: str = "HEAD",
    *,
    is_test_path: Callable[[str], bool] = _is_python_test_path,
) -> list[Finding]:
    """Findings for every test file changed between `base` and `head`, following git renames.

    A test that leaves one file and arrives unchanged in another (a merge of files) is not
    reported. One added test, in a file the range's first commit added, is allowed."""
    status = git(repo, "diff", "--name-status", "-M", f"{base}..{head}").stdout.splitlines()
    findings: list[Finding] = []
    gone: list[tuple[str, str, _Shape]] = []
    new: list[tuple[str, str, _Shape]] = []

    def show(rev: str, path: str) -> str:
        return git(repo, "show", f"{rev}:{path}").stdout

    for line in status:
        code, *paths = line.split("\t")
        old_path, new_path = paths[0], paths[-1]
        if not any(is_test_path(p) for p in paths):
            continue
        if code[0] in "MR":
            found, missing, added = _compare(show(base, old_path), show(head, new_path), new_path)
            findings += found
            gone += [(old_path, n, s) for n, s in missing.items()]
            new += [(new_path, n, s) for n, s in added.items()]
        elif code[0] == "D":
            gone += [(old_path, n, s) for n, s in _shapes(_parse(show(base, old_path)), {}).items()]
        elif code[0] == "A":
            new += [(new_path, n, s) for n, s in _shapes(_parse(show(head, new_path)), {}).items()]

    for path, name, shape in gone:
        twin = next((n for n in new if n[1] == name), None)
        if twin is None:
            findings.append(
                Finding(
                    standard=STANDARD,
                    path=path,
                    test=name,
                    reason="the test is absent from the new version",
                )
            )
            continue
        new.remove(twin)
        findings += [
            Finding(standard=STANDARD, path=twin[0], test=t, reason=r)
            for t, r in _differences(name, shape, twin[2])
        ]

    if len(new) == 1 and new[0][0] in _first_commit_additions(repo, base, head):
        new = []
    findings += [
        Finding(standard=STANDARD, path=path, test=name, reason="the test is added")
        for path, name, _ in new
    ]
    return findings


def _first_commit_additions(repo: Path, base: str, head: str) -> set[str]:
    """Paths the first commit after `base` on the way to `head` added."""
    commits = git(repo, "rev-list", "--reverse", f"{base}..{head}").stdout.split()
    if not commits:
        return set()
    out = git(repo, "diff", "--name-only", "--diff-filter=A", f"{commits[0]}^", commits[0])
    return set(out.stdout.splitlines())
