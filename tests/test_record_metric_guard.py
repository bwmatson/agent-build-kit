"""The guard against a metric's two calls being made separately (spec: dry-cleanup).

A metric that is also recorded locally is emitted through `emit_metric`, which makes
both calls; no other function in the source calls `record_metric`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.ecosystem_names import SOURCE_ROOT

HELPER = "emit_metric"
LOCAL_RECORD = "record_metric"


def called(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


class Callers(ast.NodeVisitor):
    """The calls to the local record, each with the function it is made in."""

    def __init__(self) -> None:
        self.inside: list[str] = []
        self.found: list[tuple[str, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.inside.append(node.name)
        self.generic_visit(node)
        self.inside.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Importing the local record at all, under whatever alias, is how a pair is made
        # elsewhere; the helper lives beside it and needs no import.
        if any(alias.name == LOCAL_RECORD for alias in node.names):
            self.found.append((self.inside[-1] if self.inside else "<module>", node.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        if called(node) == LOCAL_RECORD and (not self.inside or self.inside[-1] != HELPER):
            self.found.append((self.inside[-1] if self.inside else "<module>", node.lineno))
        self.generic_visit(node)


def test_no_function_but_the_helper_calls_the_local_record() -> None:
    problems = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        callers = Callers()
        callers.visit(ast.parse(path.read_text()))
        problems += [
            f"{path.relative_to(Path(SOURCE_ROOT).parent)}:{line} {function} calls {LOCAL_RECORD}"
            for function, line in callers.found
        ]

    assert not problems, f"emit the metric through {HELPER} instead:\n" + "\n".join(problems)
