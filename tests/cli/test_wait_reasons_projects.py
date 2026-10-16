"""A ready unit is told its own project's queue is full, and a unit already in progress never is
(spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.cli.test_wait_reasons import isolated, waits_of  # noqa: F401
from tests.factories import new_unit


def test_a_ready_unit_of_a_full_project_is_told_the_queue_is_full_and_another_has_room(
    tmp_path: Path,
) -> None:
    def setup(store: UnitStore, inst: Installation) -> None:
        store.upsert(
            [
                new_unit("busy/1", project="web"),
                new_unit("held/1", project="web"),
                new_unit("free/1", project="api"),
            ]
        )
        # web's one place and its one worker are taken; api has both free.
        store.set_state("busy/1", RUNNING, branch="spec/busy/1")

    waits = waits_of(
        tmp_path,
        setup,
        building={"busy/1"},
        limits={"max_units_in_progress": 1, "max_concurrent_stacks": 1},
    )

    assert waits["held/1"].reason is WaitReason.QUEUE_FULL
    assert waits["free/1"].reason is WaitReason.READY


def test_a_unit_in_progress_in_a_full_project_is_never_told_the_queue_is_full(
    tmp_path: Path,
) -> None:
    def setup(store: UnitStore, inst: Installation) -> None:
        store.upsert(
            [
                new_unit("busy/1", project="web"),
                new_unit("paused/1", project="web"),
                new_unit("free/1", project="api"),
            ]
        )
        store.set_state("busy/1", IN_REVIEW, pr=7, branch="spec/busy/1")
        store.set_state("paused/1", PLANNED, branch="spec/paused/1")

    waits = waits_of(
        tmp_path, setup, limits={"max_units_in_progress": 2, "max_concurrent_stacks": 1}
    )

    assert waits["paused/1"].reason is not WaitReason.QUEUE_FULL
    assert waits["free/1"].reason is WaitReason.READY


def test_a_repo_with_one_project_gives_the_reasons_it_gave(tmp_path: Path) -> None:
    def setup(store: UnitStore, inst: Installation) -> None:
        store.upsert(
            [
                new_unit("busy/1", repo="platform"),
                new_unit("held/1", repo="platform"),
                new_unit("busy/2", project="web"),
                new_unit("free/1", project="api"),
            ]
        )
        store.set_state("busy/1", IN_REVIEW, pr=7, branch="spec/busy/1")
        store.set_state("busy/2", RUNNING, branch="spec/busy/2")

    waits = waits_of(
        tmp_path,
        setup,
        building={"busy/2"},
        limits={"max_units_in_progress": 1, "max_concurrent_stacks": 1},
    )

    assert waits["held/1"].reason is WaitReason.QUEUE_FULL
    # web's building unit takes none of the repo's workers or places.
    assert waits["free/1"].reason is WaitReason.READY
