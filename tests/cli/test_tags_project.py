"""`abk tags` prints a group's project, and a heading naming an undeclared one is refused by it
and by planning alike (spec: unit-projects)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.work_graph import unrelated_parent_warnings
from tests.cli.replan_driver import Replan, answer, planned
from tests.project_workspace import repos_declaring, tasks_with

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "feature"


TAGS = argparse.Namespace(change=CHANGE, all=False)


def replan_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *headings: str) -> Replan:
    return Replan(
        tmp_path,
        monkeypatch,
        repos=repos_declaring(tmp_path / "planning", "app", ("web",)),
        feature=tasks_with(*headings),
    )


def test_tags_lists_each_group_with_its_project_beside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = replan_with(
        tmp_path, monkeypatch, "[app] [tier1] Add the route", "[app/web] [tier1] Add the filter"
    )

    status = cli.cmd_tags(TAGS, run.inst)

    lines = capsys.readouterr().out.splitlines()
    assert status == 0
    assert "  1. [app] [unit-test] Add the route" in lines
    assert "  2. [app/web] [unit-test] Add the filter" in lines


def test_tags_on_an_undeclared_project_prints_the_message_with_file_and_line_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = replan_with(tmp_path, monkeypatch, "[app/mobile] [tier1] Add the screen")

    status = cli.cmd_tags(TAGS, run.inst)

    out = capsys.readouterr().out
    path = run.inst.changes_dir / CHANGE / "tasks.md"
    assert status == 1
    assert f"{path}:line 5:" in out
    assert "unknown project" in out
    assert "mobile" in out
    assert "web" in out


def test_planning_plans_a_declared_project_and_refuses_an_undeclared_one_without_a_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = replan_with(tmp_path, monkeypatch, "[app/mobile] [tier1] Add the screen")
    run.write("declared", tasks_with("[app/web] [tier1] Add the filter"))
    run.runtime.answer = answer(planned("declared/1", (1,)))

    results = cli.plan_all(run.inst, store=run.store, only={CHANGE})

    assert results[CHANGE].status == "refused"
    assert run.calls == 0

    results = cli.plan_all(run.inst, store=run.store, only={"declared"})

    assert results["declared"].status == "planned"
    assert run.calls == 1


def test_a_project_group_takes_part_in_the_unrelated_parent_warning_given_the_projects(
    tmp_path: Path,
) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        tasks_with(
            "[app] [tier1] First",
            "[app/web] [tier1] Second\n\nIndependent: it needs nothing earlier",
            "[app] [tier1] Third",
        )
    )

    warnings = unrelated_parent_warnings(
        tasks, tmp_path, repos=("platform", "app"), projects={"app": ("web",)}
    )

    assert len(warnings) == 1
    assert "group 3" in warnings[0]
