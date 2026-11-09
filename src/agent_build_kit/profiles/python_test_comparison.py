"""The Python form of the before-and-after comparison of a test file (standard T26).

Two versions of a file are read by AST. What is compared, after normalising, is each test (its
marks, time limit, arguments and body) and each module-level constant, helper and fixture the
tests share. A difference that is only mechanical is normalised away:

- an import is resolved to what it imports (`from a import f as g` makes `g` mean `f`, and a
  module alias means "a module"), so moving the code or renaming an import changes nothing;
- a test's own local names are numbered by first appearance;
- a marker present on one side only is matched with the one on the other side that sits on the
  same test, so a marker renamed throughout compares equal, while reordering tests does not.

Everything else (a different function, a changed constant, an added skip) is a difference.
"""

import ast
import copy
from dataclasses import dataclass

from agent_build_kit.profiles.base import ChangedTest

_BUILTIN_MARKERS = frozenset(
    {"skip", "skipif", "xfail", "timeout", "parametrize", "usefixtures", "filterwarnings"}
)
_SKIPS = frozenset({"skip", "skipif", "xfail"})

type _Function = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _Mark:
    """A decorator or module mark: the marker's name (None for a decorator that is not a mark)
    and its normalised text."""

    name: str | None
    text: str


class _Normalise(ast.NodeTransformer):
    """Resolves imported names, numbers the locals of the node it visits and renames markers."""

    def __init__(
        self, resolved: dict[str, str], renames: dict[str, str], locals_: set[str]
    ) -> None:
        self.resolved = resolved
        self.renames = renames
        self.locals = locals_
        self.numbers: dict[str, int] = {}

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id in self.locals:
            node.id = f"_{self.numbers.setdefault(node.id, len(self.numbers))}"
        else:
            node.id = self.resolved.get(node.id, node.id)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        node.attr = self.renames.get(node.attr, node.attr)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str) and node.value in self.renames:
            node.value = self.renames[node.value]
        return node


def _locals(node: ast.AST) -> set[str]:
    """Names the node assigns: its own variables, which are numbered rather than compared."""
    return {
        n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }


def _normalised(node: ast.AST, resolved: dict[str, str], renames: dict[str, str]) -> str:
    copied = copy.deepcopy(node)
    return ast.dump(_Normalise(resolved, renames, _locals(copied)).visit(copied))


def _marker_of(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        owner = target.value
        if (isinstance(owner, ast.Attribute) and owner.attr == "mark") or (
            isinstance(owner, ast.Name) and owner.id == "mark"
        ):
            return target.attr
    return None


def _time_limit(decorator: ast.expr) -> float | None:
    if isinstance(decorator, ast.Call) and _marker_of(decorator) == "timeout" and decorator.args:
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, int | float):
            return float(first.value)
    return None


def _mark_expressions(value: ast.expr) -> list[ast.expr]:
    return list(value.elts) if isinstance(value, ast.List | ast.Tuple) else [value]


def _is_pytestmark(node: ast.stmt) -> ast.Assign | None:
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
    ):
        return node
    return None


def _is_test_function(node: ast.stmt) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test")


@dataclass(frozen=True)
class _Test:
    node: _Function
    inherited: tuple[ast.expr, ...]  # module marks and a class's decorators and marks


def _resolution(tree: ast.Module) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            resolved.update({a.asname: "<module>" for a in node.names if a.asname})
        elif isinstance(node, ast.ImportFrom):
            resolved.update({(a.asname or a.name): a.name for a in node.names})
    return resolved


def _tests(tree: ast.Module) -> dict[str, _Test]:
    module_marks: list[ast.expr] = []
    for node in tree.body:
        if marked := _is_pytestmark(node):
            module_marks += _mark_expressions(marked.value)
    found: dict[str, _Test] = {}
    for node in tree.body:
        if _is_test_function(node):
            assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            found[node.name] = _Test(node, tuple(module_marks))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_marks = list(node.decorator_list)
            for item in node.body:
                if marked := _is_pytestmark(item):
                    class_marks += _mark_expressions(marked.value)
            for item in node.body:
                if _is_test_function(item):
                    assert isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                    found[f"{node.name}.{item.name}"] = _Test(item, (*module_marks, *class_marks))
    return found


def _definitions(
    tree: ast.Module, resolved: dict[str, str], renames: dict[str, str]
) -> dict[str, str]:
    """Fingerprints of the module's constants, helpers and fixtures, by name."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and not _is_pytestmark(node):
            text = _normalised(node.value, resolved, renames)
            found.update({t.id: text for t in node.targets if isinstance(t, ast.Name)})
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if not node.name.startswith(("test", "Test")):
                found[node.name] = _normalised(node, resolved, renames)
    return found


def _custom_markers(test: _Test) -> list[str]:
    names = [_marker_of(d) for d in (*test.inherited, *test.node.decorator_list)]
    return [n for n in names if n is not None and n not in _BUILTIN_MARKERS]


def _renames(old: dict[str, _Test], new: dict[str, _Test]) -> dict[str, str]:
    """Marker names of the new version mapped to the parent's: a name on one side only, paired
    with the name on the other side at the same place on the same test."""
    old_names = {m for t in old.values() for m in _custom_markers(t)}
    new_names = {m for t in new.values() for m in _custom_markers(t)}
    only_old, only_new = old_names - new_names, new_names - old_names
    renames: dict[str, str] = {}
    for name in old.keys() & new.keys():
        before, after = _custom_markers(old[name]), _custom_markers(new[name])
        if len(before) == len(after):
            renames.update(
                {
                    n: o
                    for o, n in zip(before, after, strict=True)
                    if o in only_old and n in only_new
                }
            )
    return renames


@dataclass(frozen=True)
class _Shape:
    marks: tuple[_Mark, ...]
    time_limit: float | None
    signature: str
    body: str

    @property
    def fingerprint(self) -> str:
        marks = sorted(self.marks, key=lambda m: m.text)
        return f"{marks}|{self.time_limit}|{self.signature}|{self.body}"


def _shape(test: _Test, resolved: dict[str, str], renames: dict[str, str]) -> _Shape:
    marks: list[_Mark] = []
    limit: float | None = None
    for decorator in (*test.inherited, *test.node.decorator_list):
        seen = _time_limit(decorator)
        if seen is not None:
            limit = seen
            continue
        name = _marker_of(decorator)
        marks.append(
            _Mark(
                renames.get(name, name) if name else None, _normalised(decorator, resolved, renames)
            )
        )
    fn = test.node
    own = _locals(fn)
    numbering = _Normalise(resolved, renames, own)
    body = "".join(ast.dump(numbering.visit(copy.deepcopy(s))) for s in fn.body)
    signature = ast.dump(copy.deepcopy(fn.args))
    return _Shape(tuple(marks), limit, signature, body)


def _differences(name: str, before: _Shape, after: _Shape) -> list[ChangedTest]:
    found: list[str] = []
    remaining = list(before.marks)
    for mark in after.marks:
        if mark in remaining:
            remaining.remove(mark)
        elif mark.name in _SKIPS:
            found.append(f"a {mark.name} is added")
        elif mark.name is not None:
            found.append(f"the marker {mark.name} is added or changed")
        else:
            found.append("a decorator is added or changed")
    found += [f"the {m.name or 'decorator'} is removed or changed" for m in remaining]
    if after.time_limit is not None and (
        before.time_limit is None or after.time_limit > before.time_limit
    ):
        found.append(f"the time limit is raised to {after.time_limit:g}")
    elif after.time_limit is None and before.time_limit is not None:
        found.append("the time limit is removed")
    if before.signature != after.signature:
        found.append("the arguments differ")
    if before.body != after.body:
        found.append("an assertion or expected value differs from the parent's")
    return [ChangedTest(test=name, kind="changed", reason=r) for r in found]


def compare_python_tests(before: str, after: str) -> list[ChangedTest]:
    """How the Python test file `after` differs from `before` beyond a mechanical edit."""
    try:
        old_tree, new_tree = ast.parse(before), ast.parse(after)
    except SyntaxError as error:
        return [ChangedTest(test="", kind="changed", reason=f"a version cannot be parsed: {error}")]
    old_resolved, new_resolved = _resolution(old_tree), _resolution(new_tree)
    old_tests, new_tests = _tests(old_tree), _tests(new_tree)
    renames = _renames(old_tests, new_tests)
    old = {n: _shape(t, old_resolved, {}) for n, t in old_tests.items()}
    new = {n: _shape(t, new_resolved, renames) for n, t in new_tests.items()}
    old_defs = _definitions(old_tree, old_resolved, {})
    new_defs = _definitions(new_tree, new_resolved, renames)

    found: list[ChangedTest] = []
    for name in sorted(old.keys() & new.keys()):
        found += _differences(name, old[name], new[name])
    for name in sorted(old_defs.keys() & new_defs.keys()):
        if old_defs[name] != new_defs[name]:
            found.append(
                ChangedTest(
                    test=name,
                    kind="changed",
                    reason="the value or body differs from the parent's",
                    is_test=False,
                )
            )
    for kind, left, right in (("absent", old, new), ("added", new, old)):
        found += [
            ChangedTest(
                test=n,
                kind=kind,  # type: ignore[arg-type]
                reason=f"the test is {kind} {'from' if kind == 'absent' else 'in'} the new version",
                fingerprint=s.fingerprint,
            )
            for n, s in left.items()
            if n not in right
        ]
    for kind, left_defs, right_defs in (
        ("absent", old_defs, new_defs),
        ("added", new_defs, old_defs),
    ):
        found += [
            ChangedTest(
                test=n,
                kind=kind,  # type: ignore[arg-type]
                reason=f"the definition is {kind}",
                fingerprint=fp,
                is_test=False,
            )
            for n, fp in left_defs.items()
            if n not in right_defs
        ]
    return found
