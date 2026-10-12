"""The graph labels a failed unit that waits on another unit, and keeps it failed."""

from __future__ import annotations

from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.units import FAILED, RUNNING
from tests.factories import new_unit


def test_a_failed_unit_that_waits_reads_failed_waiting_on_its_prerequisites() -> None:
    graph = [
        new_unit("base/1", state=RUNNING),
        new_unit("other/1", state=RUNNING),
        new_unit("next/1", state=FAILED, depends_on=("base/1", "other/1")),
        new_unit("alone/1", state=FAILED),
    ]

    drawn = render_mermaid(graph)

    assert "· failed, waiting on base/1, other/1" in drawn
    assert "class next_1 failed" in drawn
    assert drawn.count("waiting on") == 1
    assert "· failed</small>" in drawn
    assert "class alone_1 failed" in drawn
