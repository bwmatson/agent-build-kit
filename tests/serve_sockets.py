"""The guard against a socket in a tier 1 test under `tests/serve`.

A module that is not marked `integration` (a module-level `pytestmark` naming
`pytest.mark.integration`) must not, found by parsing it (strings and comments never count):
  - import or name `uvicorn`, `socket`, `http.client` or `ThreadingHTTPServer`;
  - call `start_server`, which serves the application over a socket;
  - build an `httpx.Client` whose `base_url` is anything but `http://testserver`.
`check_serve_tests` returns one message per problem, each naming `path:line`; files are
paths under `root`, all of its `.py` files unless `only` lists them.
"""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

TESTS_ROOT = Path(__file__).parent

# The in-process client's base URL: the one an ASGI transport answers.
IN_PROCESS_URL = "http://testserver"


SOCKET_MODULES: frozenset[str] = frozenset({"uvicorn", "socket"})
SOCKET_NAMES: frozenset[str] = frozenset({"ThreadingHTTPServer", "start_server"})


def _is_integration(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            return any(
                isinstance(part, ast.Attribute) and part.attr == "integration"
                for part in ast.walk(node.value)
            )
    return False


def _hazard(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] in SOCKET_MODULES or alias.name == "http.client":
                return f"imports {alias.name}"
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module.split(".")[0] in SOCKET_MODULES or module == "http.client":
            return f"imports from {module}"
        for alias in node.names:
            if (module, alias.name) == ("http", "client") or alias.name in SOCKET_NAMES:
                return f"imports {alias.name}"
    elif isinstance(node, ast.Name) and node.id in SOCKET_NAMES:
        return f"uses {node.id}"
    elif isinstance(node, ast.Attribute) and node.attr in SOCKET_NAMES:
        return f"uses {node.attr}"
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Client"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "httpx"
    ):
        for keyword in node.keywords:
            if keyword.arg == "base_url" and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value == IN_PROCESS_URL
            ):
                return f"builds an httpx.Client for a base URL other than {IN_PROCESS_URL}"
    return None


def check_serve_tests(root: Path, only: Collection[str] | None = None) -> list[str]:
    files = sorted(root / name for name in only) if only is not None else sorted(root.rglob("*.py"))
    problems: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(), filename=str(path))
        if _is_integration(tree):
            continue
        found = [
            (node.lineno, reason)
            for node in ast.walk(tree)
            if isinstance(node, ast.stmt | ast.expr)
            if (reason := _hazard(node)) is not None
        ]
        name = path.relative_to(root).as_posix()
        problems.extend(f"{name}:{line}: {reason}" for line, reason in sorted(set(found)))
    return problems
