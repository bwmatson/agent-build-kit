"""`abk status` and the graph page show the whole of a moved-base run as restacking, and `abk
status` prints a slots line of the occupancy over the cap with the number of restacks in the lane
(spec: unit-scheduling).

The lane is a real one over runs that block (`tests/lane_run_slots.py`), read from the same
process; the builds `abk status` cannot see in flight are units stored `running` whose branch
lock is held, as a build's is.
"""

from __future__ import annotations

import argparse
import os
from contextlib import ExitStack
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.test_status_restacks import ended_process, printed
from tests.emergency_lane_support import build
from tests.lane_run_slots import Slots

pytestmark = pytest.mark.usefixtures("scripted_engine")


def builds(count: int) -> list[str]:
    return [f"b{n}/1" for n in range(1, count + 1)]


def status(slots: Slots, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), slots.inst) == 0
    return printed(capsys)


def hold_builds(stack: ExitStack, slots: Slots, unit_ids: list[str]) -> None:
    """Take the branch lock of each build, as the process that builds it does."""
    for unit_id in unit_ids:
        stack.enter_context(
            branch_lock(slots.store.get(unit_id).branch, root=slots.inst.state_dir / "locks")
        )


def test_two_runs_and_a_third_owed_read_as_restacking_and_the_slots_line_counts_the_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [build("run1/1"), build("run2/1"), build("feature/3", PLANNED)]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1", "run2/1"]) as slots:
        slots.store.set_state(
            "feature/3", PLANNED, branch="spec/feature/3", cause=Cause.BASE_CHANGED
        )
        slots.run("run1/1", "run2/1")

        lines = status(slots, capsys)
        assert cli.cmd_graph(argparse.Namespace(), slots.inst) == 0
        page = slots.inst.graph_page.read_text()

    assert "restacks: 2 running, 1 waiting" in lines
    assert "slots: 2/4, 2 restacking" in lines
    for unit_id in ("run1/1", "run2/1"):
        assert any(unit_id in line and "restacking onto main" in line for line in lines), unit_id
    assert page.count("restacking onto main") == 2


def test_a_handed_back_unit_is_not_counted_as_restacking_and_reads_as_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [build("run1/1"), build("back/1", PLANNED)]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1"]) as slots:
        slots.store.set_state(
            "back/1", PLANNED, branch="spec/back/1", cause=Cause.RESTACK_HANDED_BACK
        )
        slots.run("run1/1")

        lines = status(slots, capsys)

    assert "restacks: 1 running, 0 waiting" in lines
    assert "slots: 1/4, 1 restacking" in lines
    assert not any("back/1" in line and "restacking" in line for line in lines)
    assert any(line.startswith("units:") and "1 planned" in line for line in lines)


def test_a_lane_record_whose_process_has_gone_is_ignored_by_the_status_and_its_slots_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [*(build(uid) for uid in builds(4)), build("run1/1", IN_REVIEW)]
    with Slots(tmp_path, monkeypatch, units) as slots, ExitStack() as stack:
        hold_builds(stack, slots, builds(4))
        with monkeypatch.context() as owned:
            # Handed over under a process that has ended, so that is the owner the record names.
            gone = ended_process()
            owned.setattr(os, "getpid", lambda: gone)
            slots.run("run1/1")

        lines = status(slots, capsys)

    assert "slots: 4/4" in lines
    assert not any("restacking" in line for line in lines)


def test_four_builds_and_a_run_at_a_cap_of_four_print_the_slots_line_over_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [*(build(uid) for uid in builds(4)), build("run1/1")]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1"]) as slots, ExitStack() as stack:
        hold_builds(stack, slots, builds(4))
        slots.run("run1/1")

        lines = status(slots, capsys)

    assert "slots: 5/4, 1 restacking" in lines, "\n".join(lines)


def test_with_nothing_in_the_lane_the_slots_line_has_no_restacking_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [*(build(uid) for uid in builds(4))]
    with Slots(tmp_path, monkeypatch, units) as slots, ExitStack() as stack:
        hold_builds(stack, slots, builds(4))

        lines = status(slots, capsys)

    assert "slots: 4/4" in lines
    assert not any(line.startswith("slots:") and "restacking" in line for line in lines)
