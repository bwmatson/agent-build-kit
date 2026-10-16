"""The unit the planner will not start is told its own project's queue is full, no other's."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.cli.test_wait_reasons import isolated, waits_of  # noqa: F401
from tests.factories import new_unit


def test_only_the_unit_of_the_full_project_is_told_the_queue_is_full(tmp_path: Path) -> None:
    def setup(store: UnitStore, inst: Installation) -> None:
        store.upsert(
            [
                new_unit("busy/1", project="web"),
                new_unit("held/1", project="web"),
                new_unit("free/1", project="api"),
            ]
        )
        store.set_state("busy/1", IN_REVIEW, pr=7, branch="spec/busy/1")

    waits = waits_of(tmp_path, setup, limits={"max_units_in_progress": 1})

    assert waits["held/1"].reason is WaitReason.QUEUE_FULL
    assert waits["free/1"].reason is WaitReason.READY
