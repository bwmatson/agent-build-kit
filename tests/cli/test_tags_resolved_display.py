"""`abk tags`, `abk status` and `abk graph` show the project a group resolved to, and say it was
resolved (spec: project-resolution)."""

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
