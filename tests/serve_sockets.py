"""The guard against a socket in a tier 1 test under `tests/serve`.

A module that is not marked `integration` (a module-level `pytestmark` naming
`pytest.mark.integration`) must not, found by parsing it (strings and comments never count):
  - import or name `uvicorn`, `socket`, `http.client` or `ThreadingHTTPServer`, or import the
    `tests.serve.socket_api` fixture, which serves over a socket for its importer;
  - call `start_server`, which serves the application over a socket;
  - build an `httpx.Client` (or a `Client` imported from `httpx`) whose `base_url` is
    anything but `http://testserver`.
`check_serve_tests` returns one message per problem, each naming `path:line`; files are
paths under `root`, all of its `.py` files (`conftest.py` among them) unless `only` lists
them. A file on the allowlist may keep its hazards; one with none left is reported as stale.
"""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

from tests.timing_hazards import TESTS_ROOT

SERVE_TESTS = TESTS_ROOT / "serve"

# The in-process client's base URL: the one an ASGI transport answers.
IN_PROCESS_URL = "http://testserver"

SOCKET_MODULES: frozenset[str] = frozenset({"uvicorn", "socket"})
SOCKET_NAMES: frozenset[str] = frozenset({"ThreadingHTTPServer", "start_server"})
# Modules that open a socket for their importer: `http.client` itself, and the shared `api`
# fixture over a real socket, whose importers would otherwise serve over one unseen.
SOCKET_PROVIDERS: frozenset[str] = frozenset({"http.client", "tests.serve.socket_api"})

# Modules under `tests/serve` that open a socket today, as paths under it. It may only
# shrink: a module leaves it when it moves to the in-process client (or is marked
# `integration`), and nothing is added.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "test_chat_agent_environment.py",
        "test_chat_commit.py",
        "test_chat_editing.py",
        "test_chat_guards.py",
        "test_chat_permissions.py",
        "test_chat_turns.py",
        "test_serve_actions.py",
        "test_serve_approve.py",
        "test_serve_binding.py",
        "test_serve_metrics.py",
        "test_serve_review_store.py",
        # The `api` fixture over a real socket, for the modules whose subject needs one.
        "socket_api.py",
    }
)


def _is_pytestmark(target: ast.expr) -> bool:
    return isinstance(target, ast.Name) and target.id == "pytestmark"


def _is_integration(tree: ast.Module) -> bool:
    for node in tree.body:
        value = None
        if isinstance(node, ast.Assign) and any(_is_pytestmark(t) for t in node.targets):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and _is_pytestmark(node.target):
            value = node.value
        if value is not None:
            return any(
                isinstance(part, ast.Attribute) and part.attr == "integration"
                for part in ast.walk(value)
            )
    return False


def _httpx_clients(tree: ast.Module) -> frozenset[str]:
    """The names `Client` was imported from `httpx` as."""
    return frozenset(
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "httpx"
        for alias in node.names
        if alias.name == "Client"
    )


def _builds_client(call: ast.Call, clients: frozenset[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in clients
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "Client"
        and isinstance(func.value, ast.Name)
        and func.value.id == "httpx"
    )


def _hazard(node: ast.AST, clients: frozenset[str]) -> str | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] in SOCKET_MODULES or alias.name in SOCKET_PROVIDERS:
                return f"imports {alias.name}"
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module.split(".")[0] in SOCKET_MODULES or module in SOCKET_PROVIDERS:
            return f"imports from {module}"
        for alias in node.names:
            if f"{module}.{alias.name}" in SOCKET_PROVIDERS or alias.name in SOCKET_NAMES:
                return f"imports {alias.name}"
    elif isinstance(node, ast.Name) and node.id in SOCKET_NAMES:
        return f"uses {node.id}"
    elif isinstance(node, ast.Attribute) and node.attr in SOCKET_NAMES:
        return f"uses {node.attr}"
    elif isinstance(node, ast.Call) and _builds_client(node, clients):
        for keyword in node.keywords:
            if keyword.arg == "base_url" and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value == IN_PROCESS_URL
            ):
                return f"builds an httpx.Client for a base URL other than {IN_PROCESS_URL}"
    return None


def _hazards(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    if _is_integration(tree):
        return []
    clients = _httpx_clients(tree)
    found = {
        (node.lineno, reason)
        for node in ast.walk(tree)
        if isinstance(node, ast.stmt | ast.expr)
        if (reason := _hazard(node, clients)) is not None
    }
    return sorted(found)


def check_serve_tests(
    root: Path,
    only: Collection[str] | None = None,
    allowlist: Collection[str] = frozenset(),
) -> list[str]:
    files = sorted(root / name for name in only) if only is not None else sorted(root.rglob("*.py"))
    problems: list[str] = []
    hazardous: set[str] = set()
    for path in files:
        name = path.relative_to(root).as_posix()
        found = _hazards(path)
        if found:
            hazardous.add(name)
        if name in allowlist:
            continue
        problems.extend(f"{name}:{line}: {reason}" for line, reason in found)
    problems.extend(
        f"{name}: on the allowlist but opens no socket; remove it"
        for name in sorted(set(allowlist) - hazardous)
    )
    return problems
