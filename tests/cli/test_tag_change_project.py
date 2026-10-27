"""A project edited under a started unit is reconciled while the stored project is declared, and
reported, never applied, once it is not (spec: project-resolution).

Changed on purpose: a root unit whose group moved to a declared project used to be refused with
"restore the tag"; it is now kept in the root and the replan goes on."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import new_unit
from tests.project_workspace import repos_declaring

pytestmark = pytest.mark.usefixtures("scripted_engine")

IN_WEB = tasks_md(2).replace("[app]", "[app/web]")


def run_with_unit_then_groups_moved_to_web(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, groups: tuple[int, ...], **fields
) -> Replan:
    """A planned `feature` of two root groups, one unit `feature/1` of `groups` as `fields` say
    (started, in the root), and then both groups headed `[app/web]`."""
    run = Replan(
        tmp_path,
        monkeypatch,
        repos=repos_declaring(tmp_path, "app", ("web",)),
        feature=tasks_md(2),
    )
    started = {"state": "merged", "branch": "spec/feature/1", "pr": 1, **fields}
    run.store.import_units([new_unit("feature/1", groups=groups, **started)])
    run.record("feature")
    run.write("feature", IN_WEB)
    return run


def test_a_merged_root_unit_whose_group_moved_to_a_project_is_kept_and_the_replan_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_with_unit_then_groups_moved_to_web(tmp_path, monkeypatch, (1,))
    run.runtime.answer = answer(planned("feature/2", (2,)))

    results = cli.plan_all(run.inst, store=run.store)

    assert results["feature"].status == "planned"
    assert run.store.get("feature/1").project == "."
    assert run.store.get("feature/2").project == "web"
    assert "kept feature/1 in .; the heading says web" in capsys.readouterr().out


def test_a_failed_root_unit_with_every_group_taken_is_kept_without_a_planner_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_with_unit_then_groups_moved_to_web(
        tmp_path, monkeypatch, (1, 2), state="failed", pr=None
    )

    cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert run.store.get("feature/1").project == "."
    assert "kept feature/1 in .; the heading says web" in capsys.readouterr().out


def test_a_started_unit_in_a_project_the_repo_no_longer_declares_is_refused_naming_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_with_unit_then_groups_moved_to_web(
        tmp_path, monkeypatch, (1, 2), state="failed", pr=None, project="mobile"
    )

    code, out = run.run(capsys, "feature")

    assert code == 1
    assert run.calls == 0
    assert "feature/1" in out
    assert "mobile" in out
    assert "no longer declared" in out
    assert "abk requeue --restart feature/1" in out


@pytest.mark.parametrize(
    ("fields", "field"),
    [({"repo": "platform"}, "repo"), ({"tier": "integration-test"}, "tier")],
    ids=["repo", "tier"],
)
def test_a_change_of_repo_or_tier_is_still_refused_and_the_project_is_not_blamed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fields: dict,
    field: str,
) -> None:
    run = run_with_unit_then_groups_moved_to_web(tmp_path, monkeypatch, (1, 2), **fields)

    code, out = run.run(capsys, "feature")

    line = next(line for line in out.splitlines() if "feature/1" in line)
    assert code == 1
    assert run.calls == 0
    assert f"with {field}" in line
    assert "project" not in line
