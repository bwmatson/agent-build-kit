"""A cycle among stored planned units is reported as a deadlock, once per cycle, in the
status and in the reason a pass starts nothing (spec: planned-dependencies-never-close-a-cycle)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from tests.cli.test_tick_scheduling import (  # noqa: F401
    Builder,
    builder,
    isolated,
    limit_workspace,
    open_pr,
    stored,
    tick,
    warm_unit_graphs,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


def status_lines(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return [
        re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line) for line in capsys.readouterr().out.splitlines()
    ]


def two_units_waiting_on_each_other(builder: Builder) -> None:  # noqa: F811
    builder.store.upsert([stored("a/1", depends_on=("b/2",)), stored("b/2", depends_on=("a/1",))])


def test_the_status_lists_a_cycle_once_not_once_per_unit(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 5)
    two_units_waiting_on_each_other(builder)

    lines = status_lines(inst, capsys)

    found = [line for line in lines if line.startswith("deadlocked:")]
    assert len(found) == 1
    assert "a/1 -> b/2 -> a/1" in found[0]


def test_two_separate_cycles_are_two_lines(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 5)
    two_units_waiting_on_each_other(builder)
    builder.store.upsert(
        [
            stored("c/1", depends_on=("d/1",)),
            stored("d/1", depends_on=("e/1",)),
            stored("e/1", depends_on=("c/1",)),
        ]
    )

    lines = status_lines(inst, capsys)

    found = [line for line in lines if line.startswith("deadlocked:")]
    assert len(found) == 2
    assert any("c/1 -> d/1 -> e/1 -> c/1" in line for line in found)


def test_removing_an_edge_ends_the_report(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 5)
    two_units_waiting_on_each_other(builder)
    assert any(line.startswith("deadlocked:") for line in status_lines(inst, capsys))

    builder.store.set_dependencies("a/1", ())

    assert not any("deadlocked" in line for line in status_lines(inst, capsys))


def test_a_pass_that_starts_nothing_names_the_deadlock(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 5)
    two_units_waiting_on_each_other(builder)

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert "nothing can start: deadlocked: a/1 -> b/2 -> a/1" in out
    assert "nothing ready to build" not in out


def test_a_cycle_is_not_reported_as_a_full_queue(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 2)
    two_units_waiting_on_each_other(builder)
    open_pr(builder, "rev/1", 11)
    open_pr(builder, "rev2/1", 12, repo="platform")

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert "nothing can start: deadlocked: a/1 -> b/2 -> a/1" in out
    assert "queue is full" not in out


def test_the_ready_queue_report_gives_the_cycle_and_what_waits_on_it_the_reason(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 5)
    two_units_waiting_on_each_other(builder)
    builder.store.upsert([stored("w/1", depends_on=("a/1",)), stored("free/1")])

    lines = status_lines(inst, capsys)

    for member in ("a/1", "b/2"):
        assert any(
            member in line and "deadlocked" in line and not line.startswith("deadlocked:")
            for line in lines
        )
    assert any("w/1" in line and "waits on a/1" in line for line in lines)
    assert any(line.lstrip().startswith("1. free/1") for line in lines)
    assert "cannot start:" in lines, "the per-unit lines sit under a heading"


def test_a_cycle_through_a_unit_that_can_start_is_no_deadlock(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A same-repo parent in review does not stop its child, so `b/1` can start."""
    inst = limit_workspace(tmp_path, 2)
    builder.store.upsert([stored("b/1", depends_on=("a/1",))])
    open_pr(builder, "a/1", 11, depends_on=("b/1",))
    open_pr(builder, "rev/1", 12)

    lines = status_lines(inst, capsys)

    assert not any("deadlocked" in line for line in lines)
    assert any("queue is full" in line for line in lines)
    assert tick(inst) == 0
    out = capsys.readouterr().out
    assert "queue is full" in out
    assert "deadlocked" not in out


def test_a_chain_and_a_diamond_of_planned_units_are_never_deadlocked(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 9)
    builder.store.upsert(
        [
            stored("chain-a/1"),
            stored("chain-b/1", depends_on=("chain-a/1",)),
            stored("chain-c/1", depends_on=("chain-b/1",)),
            stored("dia-a/1"),
            stored("dia-b/1", depends_on=("dia-a/1",)),
            stored("dia-c/1", depends_on=("dia-a/1",)),
            stored("dia-d/1", depends_on=("dia-b/1", "dia-c/1")),
        ]
    )

    assert not any("deadlocked" in line for line in status_lines(inst, capsys))


def test_a_unit_two_steps_behind_a_cycle_gets_the_reason_too(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 5)
    two_units_waiting_on_each_other(builder)
    builder.store.upsert([stored("w/1", depends_on=("a/1",)), stored("v/1", depends_on=("w/1",))])

    lines = status_lines(inst, capsys)

    assert any("v/1" in line and "waits on w/1" in line and "deadlocked" in line for line in lines)
