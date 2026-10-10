"""The queue line, the reason nothing started and the status name the blocked
units that hold no place, and what each waits on."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import FAILED
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


def full_queue_with_a_blocked_unit(builder: Builder) -> None:  # noqa: F811
    """Two places held: a failed prerequisite and a unit in review, and a
    started unit that waits on the failed one."""
    builder.store.upsert([stored("base/1"), stored("wait/1", depends_on=("base/1",), branch="x")])
    builder.store.set_state("base/1", FAILED)
    open_pr(builder, "rev/1", 11)


def test_the_status_counts_the_blocked_units_and_says_what_each_waits_on(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 2)
    full_queue_with_a_blocked_unit(builder)

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    lines = capsys.readouterr().out.splitlines()
    queue = next(line for line in lines if "queue is full" in line)
    assert "1 blocked" in queue
    detail = next(line for line in lines if "wait/1" in line and "blocked" in line)
    assert "base/1" in detail


def test_the_reason_nothing_started_says_how_many_blocked_units_are_not_counted(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 2)
    full_queue_with_a_blocked_unit(builder)
    builder.store.upsert([stored("new/1")])

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert "1 blocked" in out
    assert "wait/1" in out
