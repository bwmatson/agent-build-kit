"""A guard keeps the route table the only place a fake GitHub route is defined: a route
registered or answered in a host, instead of in `github_routes.py`, fails naming it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

FORGES = Path(__file__).parent
HOSTS = ("github_host.py", "github_server.py")
REGISTRARS = ("Route", "_route")


def routes_outside_the_table(source: str, name: str) -> list[str]:
    """Each place `source` registers a route or answers one by its path, as `name:line: why`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        where = f"{name}:{getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(("/repos/", "/graphql")):
                found.append(f"{where}: the route {node.value!r}")
        elif isinstance(node, ast.Call):
            called = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if called in REGISTRARS:
                found.append(f"{where}: a handler registered with {called}()")
        elif isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            matched = [s for s in sides if isinstance(s, ast.Attribute) and s.attr == "path"]
            literal = [s for s in sides if isinstance(s, ast.Constant)]
            if matched and literal:
                found.append(f"{where}: a request path compared with {literal[0].value!r}")
    return found


@pytest.mark.parametrize("host", HOSTS)
def test_no_route_is_registered_or_answered_in_a_host(host: str) -> None:
    found = routes_outside_the_table((FORGES / host).read_text(), host)

    assert found == [], "routes belong in the table in github_routes.py:\n" + "\n".join(found)


def test_the_guard_names_a_handler_added_to_a_host() -> None:
    added = (
        "class Host:\n"
        "    def _handle(self, seen):\n"
        '        if seen.path == "/repos/example/app/forks":\n'
        "            return self._fork(seen)\n"
        '        return Route("GET", pattern, self._fork)\n'
    )

    found = routes_outside_the_table(added, "host.py")

    assert any("host.py:3" in f and "/repos/example/app/forks" in f for f in found)
    assert any("host.py:5" in f and "handler registered with Route()" in f for f in found)


def test_the_guard_passes_a_host_that_only_looks_a_request_up() -> None:
    clean = (
        "class Host:\n"
        "    def _handle(self, seen):\n"
        "        return serve(self.state, seen)\n"
        "    def calls(self, path):\n"
        "        return [s for s in self.seen if s.path == path]\n"
    )

    assert routes_outside_the_table(clean, "host.py") == []
