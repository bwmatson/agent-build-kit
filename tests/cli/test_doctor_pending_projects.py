"""`abk doctor` lists a project whose directory is absent as information (spec: project-init)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import ProjectConfig, RepoConfig, WorkspaceConfig, dump
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, *, present: bool) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    if present:
        (app / "agent-assessment").mkdir()
    config = WorkspaceConfig(
        repos={
            "app": RepoConfig(
                path=app,
                slug="example/app",
                changelog=None,
                projects=[ProjectConfig(path="agent-assessment")],
            )
        }
    )
    (planning / "abk.yaml").write_text(dump(config))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def mentioning(checks: list[Check]) -> list[Check]:
    return [c for c in checks if "agent-assessment" in c.name + c.detail + c.fix]


def test_a_pending_project_is_information_with_its_missing_path(tmp_path: Path) -> None:
    found = mentioning(doctor(tmp_path, present=False))

    assert [c.status for c in found] == ["info"]
    assert "pending" in found[0].name + found[0].detail


def test_a_pending_project_adds_no_warning_or_failure(tmp_path: Path) -> None:
    before = {c.status for c in doctor(tmp_path / "present", present=True)} - {"ok", "info"}

    after = {c.status for c in doctor(tmp_path / "pending", present=False)} - {"ok", "info"}

    assert after == before
    assert mentioning(doctor(tmp_path / "again", present=False))
