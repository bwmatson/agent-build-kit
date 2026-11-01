"""A repo with no tracker section starts exactly as before: no tracker call, no change."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.units import ready_units
from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.start_decision import start_decision, start_view
from tests.factories import unit as make_unit
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure


@pytest.fixture(autouse=True)
def no_tracker_section() -> Iterator[list[str]]:
    """The repo has no tracker section; a tracker of the kind a section would name fails the
    test if anything asks for it."""
    asked: list[str] = []

    def refuse(_section: object) -> Tracker:
        asked.append("tracker")
        raise AssertionError("a repo with no tracker section asked for its tracker")

    configure(app=None)
    trackers.register("azure_devops", refuse)
    yield asked
    trackers.unregister("azure_devops")


def test_the_decision_for_a_repo_with_no_section_is_start_with_no_call(
    tmp_path: Path, no_tracker_section: list[str]
) -> None:
    decision = start_decision(make_unit("add-marker/1"), changes_dir=tmp_path)

    assert decision.outcome == "start"
    assert no_tracker_section == []


def test_the_start_view_of_a_repo_with_no_section_is_the_graph_as_it_was(
    tmp_path: Path, no_tracker_section: list[str]
) -> None:
    graph = [make_unit("add-marker/1"), make_unit("other-change/1", change="other-change")]

    view = start_view(graph, lambda unit: start_decision(unit, changes_dir=tmp_path))

    assert view == graph
    assert [u.id for u in ready_units(view, max_concurrent=5, depth_cap=10)] == [
        "add-marker/1",
        "other-change/1",
    ]
    assert no_tracker_section == []


def test_an_off_section_names_no_tracker_even_with_a_block_present(
    tmp_path: Path, no_tracker_section: list[str]
) -> None:
    configure(app={"kind": "none", "azure_devops": AZURE_BLOCK})

    decision = start_decision(make_unit("add-marker/1"), changes_dir=tmp_path)

    assert decision.outcome == "start"
    assert no_tracker_section == []
