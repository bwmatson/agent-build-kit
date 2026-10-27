"""A declared project that moves where a group resolves makes the plan stale, and the replan puts
an unstarted unit there while a started one stays (spec: project-resolution)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, answer, listing, planned
from tests.factories import new_unit
from tests.project_workspace import repos_declaring, tasks_editing

pytestmark = pytest.mark.usefixtures("scripted_engine")

IN_WEB = ("[app] [unit-test] Add it", "web/src/a.ts")


def planned_before_web_was_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, state: str = "planned"
) -> Replan:
    """A change whose one group names a file of `web`, planned into the root and recorded at the
    text as it digested before the repo declared `web` (which it now does)."""
    run = Replan(
        tmp_path,
        monkeypatch,
        repos=repos_declaring(tmp_path, "app", ("web",)),
        feature=tasks_editing(IN_WEB),
    )
    fields = {} if state == "planned" else {"state": state, "branch": "spec/feature/1", "pr": 1}
    run.store.import_units([new_unit("feature/1", groups=(1,), **fields)])
    run.record("feature")
    run.runtime.answer = answer(planned("feature/1", (1,)))
    return run


def test_the_listing_reports_the_plan_stale_once_a_group_resolves_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planned_before_web_was_declared(tmp_path, monkeypatch)

    assert "stale" in listing(run, capsys)["feature"]


def test_an_unstarted_unit_is_replanned_into_the_project_the_group_now_resolves_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planned_before_web_was_declared(tmp_path, monkeypatch)

    results = cli.plan_all(run.inst, store=run.store)

    assert results["feature"].status == "planned"
    assert run.calls == 1
    assert run.store.get("feature/1").project == "web"
    assert "stale" not in listing(run, capsys)["feature"]


def test_a_merged_unit_stays_in_the_root_when_its_group_now_resolves_to_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planned_before_web_was_declared(tmp_path, monkeypatch, state="merged")

    cli.plan_all(run.inst, store=run.store)

    assert run.store.get("feature/1").project == "."
    assert "kept feature/1 in .; the heading says web" in capsys.readouterr().out
