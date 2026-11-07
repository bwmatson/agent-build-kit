"""Which changes the tick applies, what a failure or a wait outlives, and where it is shown
(spec: project-lines)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.doctor import run_doctor
from agent_build_kit.init.scaffold import add_project
from agent_build_kit.pipeline.project_actions import (
    apply_project_actions,
    failed_lines,
    status_lines,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.test_doctor import Answers
from tests.factories import stored_unit, which_all
from tests.pipeline.test_project_actions_apply import CHANGE, Planning, carrier
from tests.project_workspace import OPT_OUT


@pytest.fixture
def planning(tmp_path: Path) -> Planning:
    return Planning(tmp_path / "planning")


def other_in_old(state: str = "in_review"):
    return stored_unit("other/1", change="other", repo="app", project="old", state=state)


def test_the_tick_applies_the_adds_of_planned_changes_only(planning: Planning) -> None:
    planning.tasks(("Project: add planned-one python-uv",), change="planned")
    planning.tasks(("Project: add refused-one python-uv",), change="refused")
    planning.tasks(("Project: add draft-one python-uv",), change="draft")
    broken = planning.inst.changes_dir / "broken"
    broken.mkdir()
    (broken / "tasks.md").write_text(
        f"# Tasks\n\n{OPT_OUT}\n## 1. [app/nowhere] [unit-test] Group 1\n\n"
        "Project: add broken-one python-uv\n\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"
    )
    state = planning.inst.state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "planned.json").write_text(
        json.dumps({"planned": {"ok": True}, "refused": {"ok": False}, "broken": {"ok": True}})
    )

    cli.apply_project_lines(planning.inst, UnitStore(state / "units.json"))

    assert set(planning.listed()) == {"old", "planned-one"}


def test_a_failure_whose_line_was_edited_is_forgotten_once_the_new_line_applies(
    planning: Planning,
) -> None:
    if os.geteuid() == 0:
        pytest.skip("a root user can write a read-only folder")
    planning.tasks(("Project: add conformance python-uv",))
    planning.root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        planning.run(planning=(CHANGE,))
    finally:
        planning.root.chmod(stat.S_IRWXU)
    assert len(failed_lines(planning.inst)) == 1

    planning.tasks(("Project: add conformance2 python-uv",))
    planning.run(planning=(CHANGE,))

    assert "conformance2" in planning.listed()
    assert failed_lines(planning.inst) == []


def test_a_removal_that_is_waiting_survives_the_archive_of_its_change(planning: Planning) -> None:
    planning.tasks(("Project: remove old",))
    units = [carrier(), other_in_old()]
    planning.run(units)
    shutil.rmtree(planning.inst.changes_dir / CHANGE)

    assert planning.run(units).waiting
    assert any("old" in line for line in status_lines(planning.inst, units))
    assert "old" in planning.listed()

    planning.run([carrier(), other_in_old("merged")])

    assert "old" not in planning.listed()


def test_an_abk_yaml_that_does_not_parse_is_reported_not_raised(planning: Planning) -> None:
    planning.tasks(("Project: add conformance python-uv",))
    inst = planning.inst
    planning.config.write_text("repos: [unclosed\n")

    report = apply_project_actions(inst, [], planning=(CHANGE,), log=planning.logged.append)

    assert len(report.failed) == 1
    assert planning.logged


def test_abk_doctor_warns_of_a_failed_project_edit(planning: Planning) -> None:
    state = planning.inst.state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "project_actions.json").write_text(
        json.dumps(
            {
                "failed": {
                    "k": {"change": CHANGE, "group": 1, "line": "Project: add x python-uv"}
                    | {"error": "no way"}
                }
            }
        )
    )

    checks = run_doctor(planning.config, run=Answers(), which=which_all)

    found = [c for c in checks if c.name == "project edit"]
    assert [c.status for c in found] == ["warn"]
    assert "no way" in found[0].detail


def test_abk_status_shows_a_waiting_removal(
    planning: Planning, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planning.tasks(("Project: remove old",))
    inst = planning.inst
    UnitStore(inst.state_dir / "units.json").upsert([carrier(), other_in_old()])
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    assert "project removal waiting" in capsys.readouterr().out


def test_two_lines_of_one_group_are_published_once_after_both_are_written(
    planning: Planning,
) -> None:
    planning.tasks(("Project: add one python-uv", "Project: add two python-uv"))
    seen: list[tuple[str, int, set[str]]] = []

    def publish(change: str, group: int) -> None:
        seen.append((change, group, set(planning.listed())))

    apply_project_actions(planning.inst, [], planning=(CHANGE,), publish=publish)

    assert seen == [(CHANGE, 1, {"old", "one", "two"})]


def test_a_waiting_removal_whose_line_was_edited_applies_only_the_new_line(
    planning: Planning,
) -> None:
    add_project(planning.config, "app", {"path": "older", "profile": "python-uv"})
    planning.tasks(("Project: remove old",))
    planning.run([carrier(), other_in_old()])
    planning.tasks(("Project: remove older",))

    planning.run([carrier(), other_in_old("merged")])

    assert set(planning.listed()) == {"old"}
