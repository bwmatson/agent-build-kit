"""A starved machine must not change what the project-scheduling pass is checked for.

The test of one project refilling its own worker bounds every wait by `WAIT`; a machine
so loaded that a wait runs out used to read as the pass refilling the wrong project. With
every bound run out at once, that test must still give the same result: what it waits on
is an event, and the bound is only a guard against a hang.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli import test_tick_scheduling_projects as scheduling
from tests.tick_pass import Builder, install_builder, isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_wait_that_runs_out_at_once_does_not_change_the_refill_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    builder: Builder = install_builder(tmp_path, monkeypatch)
    monkeypatch.setattr(scheduling, "WAIT", 0, raising=False)

    scheduling.test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not(
        builder, tmp_path, monkeypatch
    )
