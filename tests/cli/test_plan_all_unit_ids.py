"""A replan renumbers nothing: the program names each unit from its groups
(spec: unit-ids-come-from-the-groups)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UNPLANNED
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def seed(run: Replan, uid: str, groups: tuple[int, ...], **fields) -> None:
    run.store.upsert([stored_unit(uid, change="feature", groups=groups, **fields)])


def snapshot(run: Replan) -> dict[str, tuple[str, tuple[int, ...]]]:
    return {u.id: (u.state.value, u.groups) for u in run.store.all()}


def test_a_change_planned_twice_with_different_labels_keeps_every_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))

    first = answer(planned("feature/a", (1, 2)), planned("feature/b", (3,)))
    run.run(capsys, "feature", reply=first)
    before = snapshot(run)
    second = answer(planned("feature/p", (1, 2)), planned("feature/q", (3,)))
    run.run(capsys, "feature", "--accept-unplanned", reply=second)

    assert set(before) == {"feature/1", "feature/3"}
    assert snapshot(run) == before
    assert not [u for u in run.store.all() if u.state == UNPLANNED]


def test_unstarted_units_with_ids_the_model_once_chose_keep_them_at_the_first_replan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    seed(run, "feature/2", (1, 2))
    seed(run, "feature/4", (3, 4))
    run.record("feature")

    reply = answer(planned("feature/m", (1, 2)), planned("feature/n", (3, 4)))
    run.run(capsys, "feature", reply=reply)

    assert snapshot(run) == {
        "feature/2": ("planned", (1, 2)),
        "feature/4": ("planned", (3, 4)),
    }


def test_a_replan_that_joins_groups_gives_the_lowest_groups_id_and_unplans_the_old_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    seed(run, "feature/1", (1,))
    seed(run, "feature/2", (2,))
    run.record("feature")

    run.run(capsys, "feature", "--accept-unplanned", reply=answer(planned("feature/z", (1, 2))))

    assert run.store.get("feature/1").groups == (1, 2)
    assert run.store.get("feature/1").state == PLANNED
    assert run.store.get("feature/2").state == UNPLANNED
    assert "feature/z" not in snapshot(run)


def test_a_started_unit_that_depends_on_an_unstarted_one_keeps_its_stored_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))
    seed(run, "feature/1", (1,))
    seed(run, "feature/2", (2,))
    seed(run, "feature/3", (3,), depends_on=("feature/2",))
    run.store.set_state("feature/3", RUNNING, branch="spec/feature/3")
    run.record("feature")

    reply = answer(planned("feature/8", (1,)), planned("feature/9", (2,)))
    run.run(capsys, "feature", reply=reply)

    assert run.store.get("feature/3").depends_on == ("feature/2",)
    assert run.store.get("feature/2").state == PLANNED
    assert "feature/9" not in snapshot(run)
