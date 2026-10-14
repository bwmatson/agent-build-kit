"""A project edited under a started unit is reported, never applied, and never recorded as done."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import FAILED
from tests.cli.replan_driver import Replan, tasks_md
from tests.factories import unit
from tests.project_workspace import repos_declaring

pytestmark = pytest.mark.usefixtures("scripted_engine")

IN_WEB = tasks_md(1).replace("[app]", "[app/web]")


def failed_root_unit_with_group_moved_to_web(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Replan, str]:
    run = Replan(
        tmp_path,
        monkeypatch,
        repos=repos_declaring(tmp_path, "app", ("web",)),
        feature=tasks_md(1),
    )
    run.store.upsert([unit("feature/1", change="feature", groups=(1,))])
    run.store.set_state("feature/1", FAILED, branch="spec/feature/1")
    run.record("feature")
    stale = run.records["feature"]["hash"]
    run.write("feature", IN_WEB)
    return run, stale


def test_a_group_retagged_for_a_project_is_reported_with_the_way_out_and_not_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run, stale = failed_root_unit_with_group_moved_to_web(tmp_path, monkeypatch)
    before = run.store.get("feature/1")

    code, out = run.run(capsys, "feature")

    assert code == 1
    assert run.calls == 0
    assert "feature/1" in out
    assert "project" in out
    assert "web" in out
    assert "abk requeue --restart feature/1" in out
    assert run.store.get("feature/1") == before
    assert run.records["feature"]["hash"] == stale


def test_the_report_ends_when_the_tag_is_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, stale = failed_root_unit_with_group_moved_to_web(tmp_path, monkeypatch)

    first = cli.plan_all(run.inst, store=run.store)
    run.write("feature", tasks_md(1))
    restored = cli.plan_all(run.inst, store=run.store)

    assert first["feature"].status == "refused"
    assert run.calls == 0
    assert restored["feature"].status in ("planned", "skipped")
    assert run.records["feature"]["hash"] == stale
