"""The guard that a test carrying the `integration` selector can run in CI (spec: marker-taxonomy).

`check_tests` returns one message per problem: a test with the selector (on the test, its class
or the module) that loads a settings model with a required field it gives no override for, reads
an environment variable with no default, starts a real agent (decided by the drift test's
`AgentStart`) or calls a host that can be reached and is not local, when the baseline does not
name it; and a baseline entry that no longer is one. The test's own body is read, and so are the
non-test functions of its module that it names as a fixture or calls, transitively; a cause in
another module is not seen. The walk, the baseline format and the report are `wide_scans`'s.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path

from pydantic_settings import BaseSettings

from agent_build_kit import settings as settings_module
from tests.live_tag_drift import AgentStart, callee, is_mark, module_functions_reached
from tests.wide_scans import check_modules, walk_tests
from tests.wide_scans import load_baseline as load_baseline_entries

__all__ = ["BASELINE_FILE", "check_tests", "load_baseline", "required_settings_fields"]

TESTS_ROOT = Path(__file__).parent
BASELINE_FILE = TESTS_ROOT / "ci_runnable_baseline.txt"
# Hosts of this machine, and the names RFC 2606 and RFC 6761 reserve, which cannot be reached.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
RESERVED_HOSTS = frozenset({"example", "example.com", "example.net", "example.org"})
RESERVED_SUFFIXES = (
    ".example",
    ".test",
    ".invalid",
    ".localhost",
    ".example.com",
    ".example.net",
    ".example.org",
)
URL_HOST = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^/@\s]*@)?(\[[^\]]+\]|[^/:\s]+)")

type Function = ast.FunctionDef | ast.AsyncFunctionDef


def load_baseline(path: Path = BASELINE_FILE) -> frozenset[str]:
    """The violators of today, read in `wide_scans`'s format from this guard's own file."""
    return load_baseline_entries(path)


def required_settings_fields() -> Mapping[str, frozenset[str]]:
    """The required field names of each settings model of the kit, by class name."""
    found: dict[str, frozenset[str]] = {}
    for value in vars(settings_module).values():
        if isinstance(value, type) and issubclass(value, BaseSettings):
            required = frozenset(n for n, f in value.model_fields.items() if f.is_required())
            if required:
                found[value.__name__] = required
    return found


def _marks_integration(node: ast.AST) -> bool:
    return any(is_mark(n, "integration") for n in ast.walk(node))


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


def _unreachable(host: str) -> bool:
    return host in RESERVED_HOSTS or host.endswith(RESERVED_SUFFIXES)


def _docstrings(function: ast.AST) -> set[int]:
    """The identities of the docstring nodes in `function`, which are text and not a call."""
    found: set[int] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _call_causes(node: ast.Call, required_fields: Mapping[str, frozenset[str]]) -> list[str]:
    name = callee(node)[1]
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
    return []


def _causes(
    function: ast.AST, tree: ast.Module, required_fields: Mapping[str, frozenset[str]]
) -> list[str]:
    """What one function needs that CI does not give it."""
    causes: list[str] = []
    if AgentStart.of_function(function, tree).starts:
        causes.append("starts a real agent")
    docstrings = _docstrings(function)
    for node in ast.walk(function):
        if isinstance(node, ast.Subscript) and _dotted(node.value) == "os.environ":
            causes.append(f"reads the environment variable {_constant(node.slice)} with no default")
        elif isinstance(node, ast.Call):
            causes += _call_causes(node, required_fields)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            match = URL_HOST.match(node.value)
            if match:
                host = match.group(1).lower()
                if host not in LOCAL_HOSTS and not _unreachable(host):
                    causes.append(f"calls the host {host}, which is not local")
    return causes


def _reached(test: Function, tree: ast.Module) -> list[ast.AST]:
    """The test, the same-module fixtures it names as parameters, and those they name in turn,
    and the module functions each of them calls (the drift test's closure)."""
    defined = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    seeds: list[Function] = [test]
    for seed in seeds:
        arguments = seed.args
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
            fixture = defined.get(argument.arg)
            if fixture is not None and fixture not in seeds:
                seeds.append(fixture)
    return [reached for seed in seeds for reached in module_functions_reached(seed, tree)]


def _violators(text: str, required_fields: Mapping[str, frozenset[str]]) -> dict[str, str]:
    tree = ast.parse(text)
    found: dict[str, str] = {}
    for test, marked in walk_tests(tree, _marks_integration):
        if not marked:
            continue
        causes: list[str] = []
        for function in _reached(test, tree):
            for cause in _causes(function, tree, required_fields):
                if cause not in causes:
                    causes.append(cause)
        if causes:
            found[test.name] = "; ".join(causes)
    return found


def check_tests(
    root: Path = TESTS_ROOT,
    *,
    baseline: frozenset[str],
    required_fields: Mapping[str, frozenset[str]],
) -> list[str]:
    """One message per problem in the test modules under `root`."""
    return check_modules(
        root,
        lambda text: _violators(text, required_fields),
        baseline=baseline,
        baseline_file=BASELINE_FILE,
        new_message=lambda entry, causes: (
            f"{entry}: carries the integration selector but cannot run in CI: {causes}"
        ),
        stale_reason="it no longer needs more than CI has",
    )
