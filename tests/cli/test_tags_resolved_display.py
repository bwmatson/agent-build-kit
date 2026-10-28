"""`abk tags`, `abk status` and `abk graph` show the project a group resolved to, and say it was
resolved (spec: project-resolution); the planner prompt does in its own test file."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan
from tests.factories import new_unit
from tests.project_workspace import repos_declaring, tasks_editing

pytestmark = pytest.mark.usefixtures("scripted_engine")

TAGS = argparse.Namespace(change="feature", all=False)


def run_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *groups: tuple[str, str]) -> Replan:
    return Replan(
        tmp_path,
        monkeypatch,
        repos=repos_declaring(tmp_path / "planning", "app", ("web",)),
        feature=tasks_editing(*groups),
    )


def test_tags_shows_a_resolved_project_beside_the_repo_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_with(tmp_path, monkeypatch, ("[app] [unit-test] Add it", "web/src/a.ts"))

    status = cli.cmd_tags(TAGS, run.inst)

    line = next(line for line in capsys.readouterr().out.splitlines() if "Add it" in line)
    assert status == 0
    assert line.startswith("  1. [app/web] [unit-test] Add it")
    assert "(resolved)" in line


def test_tags_says_explicit_root_for_the_opt_out_and_nothing_for_an_unresolved_root_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_with(
        tmp_path,
        monkeypatch,
        ("[app/<root>] [unit-test] Stay", "web/src/a.ts"),
        ("[app] [unit-test] Mixed", "CHANGELOG.md"),
        ("[app/web] [unit-test] Written", "web/src/b.ts"),
    )

    status = cli.cmd_tags(TAGS, run.inst)

    lines = capsys.readouterr().out.splitlines()
    stay = next(line for line in lines if "Stay" in line)
    mixed = next(line for line in lines if "Mixed" in line)
    written = next(line for line in lines if "Written" in line)
    assert status == 0
    assert stay.startswith("  1. [app] [unit-test] Stay")
    assert "explicit root" in stay
    assert "resolved" not in mixed
    assert "explicit root" not in mixed
    assert "resolved" not in written


def test_status_reports_a_plan_stale_once_a_declared_project_moves_a_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    run = run_with(tmp_path, monkeypatch, ("[app] [unit-test] Add it", "web/src/a.ts"))
    run.store.import_units([new_unit("feature/1", groups=(1,))])
    run.record("feature")

    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if "stale" in line]
    assert any("feature" in line for line in lines)


def test_status_marks_a_unit_planned_from_a_resolved_group_and_not_one_written_for_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    run = run_with(
        tmp_path,
        monkeypatch,
        ("[app] [unit-test] Resolved", "web/src/a.ts"),
        ("[app/web] [unit-test] Written", "web/src/b.ts"),
    )
    run.store.import_units(
        [
            new_unit("feature/1", groups=(1,), project="web"),
            new_unit("feature/2", groups=(2,), project="web"),
        ]
    )

    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    lines = capsys.readouterr().out.splitlines()
    heading = lines.index("projects set by resolution or an explicit root:")
    assert "feature/1" in lines[heading + 1] and "(resolved)" in lines[heading + 1]
    assert any("feature/1" in line and "(resolved)" in line for line in lines)
    assert not any("feature/2" in line and "resolved" in line for line in lines)


def node_line(page: str, unit_id: str) -> str:
    """The line of the graph page that draws the node of `unit_id`."""
    return next(line for line in page.splitlines() if f'["{unit_id}' in line)


def test_the_graph_marks_each_unit_by_its_own_group_and_keeps_the_subgraph_titles_bare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_with(
        tmp_path,
        monkeypatch,
        ("[app] [unit-test] Resolved", "web/src/a.ts"),
        ("[app/web] [unit-test] Written", "web/src/b.ts"),
        ("[app/<root>] [unit-test] Opted out", "web/src/c.ts"),
        ("[app] [unit-test] Plain root", "CHANGELOG.md"),
    )
    run.store.import_units(
        [
            new_unit("feature/1", groups=(1,), project="web"),
            new_unit("feature/2", groups=(2,), project="web"),
            new_unit("feature/3", groups=(3,)),
            new_unit("feature/4", groups=(4,)),
        ]
    )

    assert cli.cmd_graph(argparse.Namespace(), run.inst) == 0

    page = run.inst.graph_page.read_text()
    assert 'subgraph app__project__web["web"]' in page
    assert "resolved" in node_line(page, "feature/1")
    assert "resolved" not in node_line(page, "feature/2")
    assert "explicit root" in node_line(page, "feature/3")
    assert "explicit root" not in node_line(page, "feature/4")
