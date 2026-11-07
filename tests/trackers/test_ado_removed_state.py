"""The board's Removed state is the kit's `removed` on the processes that have one."""

from __future__ import annotations

import pytest

from tests.trackers.ado_support import PROCESS_TYPES, section


@pytest.mark.parametrize("process", ["agile", "scrum"])
def test_the_removed_board_state_reads_as_the_kits_removed(process: str) -> None:
    group = PROCESS_TYPES[process]["group"]

    assert section(process).kit_state(group, "Removed") == "removed"


def test_a_process_with_no_removed_state_reads_none() -> None:
    assert section("basic").kit_state("Task", "Removed") is None
