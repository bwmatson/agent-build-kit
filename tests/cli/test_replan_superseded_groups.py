"""The groups of a superseded unit are free: a replan neither counts them as taken nor requires
them to still be in `tasks.md` (spec: unit-superseding)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import MERGED
from tests.cli.replan_driver import Replan, tasks_md
from tests.factories import stored_unit, superseded_store

pytestmark = pytest.mark.usefixtures("scripted_engine")


def split_change(run: Replan, tmp_path: Path) -> None:
    """`app`: group 1 merged, then `app/3` superseded by two planned pieces (see
    `superseded_store`), recorded as planned."""
    seed = tmp_path / "seed"
    seed.mkdir()
    run.store.import_units(
        [
            stored_unit("app/1", change="app", groups=(1,), state=MERGED),
            *superseded_store(seed).all(),
        ]
    )
    run.record("app")


def test_groups_only_a_superseded_unit_carried_are_left_for_the_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, app=tasks_md(4))
    split_change(run, tmp_path)

    code, out = run.run(capsys, "app", "--report")

    assert code == 0
    assert "would ask nothing of the planner" not in out


def test_a_tasks_file_without_its_groups_does_not_stop_a_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, app=tasks_md(2))
    split_change(run, tmp_path)

    code, out = run.run(capsys, "app", "--report")

    assert code == 0
    assert "no longer in tasks.md" not in out
