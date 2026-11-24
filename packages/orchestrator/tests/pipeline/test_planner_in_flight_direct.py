"""The planner is shown a stored unit's direct dependencies, not an ancestor the chain reaches,
and no dependencies at all for a unit that has started."""

from __future__ import annotations

from agent_build_kit.pipeline.planner import build_prompt, in_flight_item
from agent_build_kit.pipeline.units import RUNNING
from tests.factories import stored_unit as unit


def line_of(prompt: str, uid: str) -> str:
    return next(line for line in prompt.splitlines() if line.startswith(f"- {uid} "))


def test_the_item_and_the_line_list_the_direct_dependencies_only() -> None:
    graph = [
        unit("feature/1", change="feature"),
        unit("feature/2", change="feature", depends_on=("feature/1",)),
        unit("feature/3", change="feature", depends_on=("feature/1", "feature/2")),
    ]
    items = [in_flight_item(u, graph) for u in graph]

    prompt = build_prompt({}, items)

    assert items[2]["depends_on"] == ["feature/2"]
    assert line_of(prompt, "feature/3").endswith("depends on feature/2")


def test_a_started_unit_is_shown_without_dependencies() -> None:
    graph = [
        unit("feature/1", change="feature"),
        unit(
            "feature/2",
            change="feature",
            depends_on=("feature/1",),
            state=RUNNING,
            branch="spec/feature/2",
        ),
        unit(
            "feature/3",
            change="feature",
            depends_on=("feature/1", "feature/2"),
            state=RUNNING,
            branch="spec/feature/3",
        ),
    ]

    prompt = build_prompt({}, [in_flight_item(u, graph) for u in graph])

    assert "depends on" not in line_of(prompt, "feature/3")
    assert in_flight_item(graph[2], graph)["depends_on"] == ["feature/2"]
