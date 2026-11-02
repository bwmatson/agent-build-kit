"""A worker's entry point reads the outside world from a snapshot and does not poll it.

The modules below are where a unit's build reads a pull request or the usage endpoint: the
graph's node modules, and the wiring that builds the reads they call. None may import a forge
list function, the poller, the round's fetch and poll entry points or a reader of the usage
endpoint, or call a forge's `list_prs` (spec: snapshots). Reading is the snapshot API's job;
a node may still act on the host (push, comment, label).
"""

from __future__ import annotations

import ast
import importlib.util

import pytest

WORKER_ENTRY_POINTS = (
    "agent_build_kit.graph.nodes",
    "agent_build_kit.graph.check_loop",
    "agent_build_kit.graph.build",
    "agent_build_kit.graph.run",
    "agent_build_kit.graph.unit",
    "agent_build_kit.pipeline.wiring",
)

FORBIDDEN_NAMES = frozenset(
    {
        "listed_pull",
        "Poller",
        "poll_all",
        "fetch_all",
        "read_live_usage",
        "current_usage",
        "refreshed_usage",
        "list_prs",
    }
)


def polling_in_source(module: str, source: str) -> list[str]:
    """Each import of, or use of, a forbidden name in `source`, as a line to read."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] in FORBIDDEN_NAMES:
                    found.append(f"{module}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(f"{module}:{node.lineno} uses .{node.attr}")
    return found


def polling_in(module: str) -> list[str]:
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin is not None, f"{module} is not a module"
    with open(spec.origin, encoding="utf-8") as source:
        return polling_in_source(module, source.read())


def test_no_worker_entry_point_polls_the_host_or_the_usage_endpoint() -> None:
    offences = [line for module in WORKER_ENTRY_POINTS for line in polling_in(module)]

    assert offences == []


@pytest.mark.parametrize(
    "line",
    [
        "from agent_build_kit.forges.base import listed_pull",
        "from agent_build_kit.pipeline.pr_poller import Poller",
        "from agent_build_kit.pipeline.usage_guard import current_usage",
        "from agent_build_kit.pipeline.usage_guard import read_live_usage",
        "from agent_build_kit.cli.pipeline import poll_all",
        "forge.list_prs(repo)",
    ],
)
def test_the_check_reports_each_kind_of_polling(line: str) -> None:
    assert polling_in_source("planted", line) != []


def test_the_check_leaves_a_snapshot_read_alone() -> None:
    source = "from agent_build_kit.pipeline import snapshots\nsnapshots.pr(d, 'app', 7)\n"

    assert polling_in_source("planted", source) == []
