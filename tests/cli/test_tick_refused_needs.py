"""A tick that refuses a `Needs:` line for a cycle logs it and carries on (unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import tasks_md
from tests.cli.test_tick_scheduling import (  # noqa: F401
    Builder,
    builder,
    isolated,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_tick_logs_a_refused_needs_once_and_does_not_fail(
    builder: Builder,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = workspace(tmp_path)
    for change, other in (("alpha", "beta"), ("beta", "alpha")):
        path = inst.changes_dir / change / "tasks.md"
        path.parent.mkdir(parents=True)
        path.write_text(tasks_md(1, needs={1: f"{other} group 1"}))
    builder.store.upsert([stored("alpha/1"), stored("beta/1")])

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert out.count("beta/1 -> alpha/1 -> beta/1") == 1
    assert builder.store.get("beta/1").depends_on == ()
    assert cli.link_needs(inst, store=builder.store)[0].unit == "beta/1"
