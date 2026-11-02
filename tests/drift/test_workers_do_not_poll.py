"""A worker's entry point reads the outside world from a snapshot and does not poll it.

The modules below are where a unit's build reads a pull request or the usage endpoint: the
graph's node modules, and the wiring that builds the reads they call. None may import a forge
list function, the poller, the round's fetch and poll entry points or the usage endpoint
reader, or call a forge's `list_prs` (spec: snapshots). Reading is the snapshot API's job;
a node may still act on the host (push, comment, label).
"""

from __future__ import annotations

import ast
import importlib.util

WORKER_ENTRY_POINTS = (
    "agent_build_kit.graph.nodes",
    "agent_build_kit.graph.check_loop",
    "agent_build_kit.graph.build",
    "agent_build_kit.graph.run",
    "agent_build_kit.graph.unit",
    "agent_build_kit.pipeline.wiring",
)

FORBIDDEN_NAMES = frozenset(
    {"listed_pull", "Poller", "poll_all", "fetch_all", "read_live_usage", "list_prs"}
)


def polling_in(module: str) -> list[str]:
    """Each import of, or call to, a forbidden name in `module`, as a line to read."""
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin is not None, f"{module} is not a module"
    with open(spec.origin, encoding="utf-8") as source:
        tree = ast.parse(source.read())
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] in FORBIDDEN_NAMES:
                    found.append(f"{module}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(f"{module}:{node.lineno} uses .{node.attr}")
    return found


def test_no_worker_entry_point_polls_the_host_or_the_usage_endpoint() -> None:
    offences = [line for module in WORKER_ENTRY_POINTS for line in polling_in(module)]

    assert offences == []
