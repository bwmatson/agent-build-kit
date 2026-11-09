"""The guard that a test carrying the `integration` selector can run in CI (spec: marker-taxonomy).

`check_tests` returns one message per problem: a test with the selector (on the test, its class
or the module) that loads a settings model with a required field it gives no override for, reads
an environment variable with no default, starts a real agent or calls a host other than
loopback, when the baseline does not name it; and a baseline entry that no longer is one.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path

from pydantic_settings import BaseSettings

from agent_build_kit import settings as settings_module
from tests.live_tag_drift import AGENT_SIGNALS

TESTS_ROOT = Path(__file__).parent
BASELINE_FILE = TESTS_ROOT / "ci_runnable_baseline.txt"
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})  # noqa: S104
URL_HOST = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^/@\s]*@)?(\[[^\]]+\]|[^/:\s]+)")


def load_baseline(path: Path = BASELINE_FILE) -> frozenset[str]:
    """The violators of today, as `path::test` entries under the tests root."""
    return frozenset(
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def required_settings_fields() -> Mapping[str, frozenset[str]]:
    """The required field names of each settings model of the kit, by class name."""
    found: dict[str, frozenset[str]] = {}
    for value in vars(settings_module).values():
        if isinstance(value, type) and issubclass(value, BaseSettings):
            required = frozenset(n for n, f in value.model_fields.items() if f.is_required())
            if required:
                found[value.__name__] = required
    return found


def _marked(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "integration" for n in ast.walk(node))


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _constant(node: ast.AST | None) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else "?"


def _call_causes(node: ast.Call, required_fields: Mapping[str, frozenset[str]]) -> list[str]:
    name = _callee(node)
    if _dotted(node.func) in {"os.environ.get", "os.getenv"}:
        defaulted = len(node.args) > 1 or any(k.arg == "default" for k in node.keywords)
        if defaulted:
            return []
        variable = _constant(node.args[0] if node.args else None)
        return [f"reads the environment variable {variable} with no default"]
    if name in required_fields:
        given = {k.arg for k in node.keywords}
        if None in given:
            return []
        return [
            f"loads {name} without overriding its required field {field}"
            for field in sorted(required_fields[name] - given)
        ]
    if name in AGENT_SIGNALS.calls:
        return [f"starts a real agent through {name}"]
    return []


def _causes(function: ast.AST, required_fields: Mapping[str, frozenset[str]]) -> list[str]:
    """What a test needs that CI does not give it."""
    causes: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Subscript) and _dotted(node.value) == "os.environ":
            causes.append(f"reads the environment variable {_constant(node.slice)} with no default")
        elif isinstance(node, ast.Call):
            causes += _call_causes(node, required_fields)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = URL_HOST.match(node.value)
            if match and match.group(1).lower() not in LOOPBACK:
                causes.append(f"calls the host {match.group(1)}, which is not loopback")
    return causes


def _violators(text: str, required_fields: Mapping[str, frozenset[str]]) -> dict[str, list[str]]:
    tree = ast.parse(text)
    module_marked = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and _marked(n.value)
        for n in tree.body
    )
    found: dict[str, list[str]] = {}

    def visit(body: list[ast.stmt], marked: bool) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, marked or any(_marked(d) for d in node.decorator_list))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("test_") and (
                    marked or any(_marked(d) for d in node.decorator_list)
                ):
                    causes = _causes(node, required_fields)
                    if causes:
                        found[node.name] = causes

    visit(tree.body, module_marked)
    return found


def check_tests(
    root: Path = TESTS_ROOT,
    *,
    baseline: frozenset[str],
    required_fields: Mapping[str, frozenset[str]],
) -> list[str]:
    """One message per problem in the test modules under `root`."""
    violators: dict[str, list[str]] = {}
    problems: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        if any(
            part.startswith(".") or part == "child_modules" for part in path.relative_to(root).parts
        ):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            found = _violators(path.read_text(), required_fields)
        except SyntaxError as error:
            problems.append(f"{relative}: cannot be parsed ({error.msg}, line {error.lineno})")
            continue
        for name, causes in found.items():
            violators[f"{relative}::{name}"] = causes
    problems += [
        f"{entry}: carries the integration selector but cannot run in CI: {'; '.join(causes)}"
        for entry, causes in sorted(violators.items())
        if entry not in baseline
    ]
    problems += [
        f"{entry}: stale baseline entry, it no longer needs more than CI has; remove it from "
        f"{BASELINE_FILE.name}"
        for entry in sorted(baseline - violators.keys())
    ]
    return problems
