"""`abk doctor` warns when a repo names a changelog its checkout does not have."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, *, changelog: str | None, file: str | None) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    if file is not None:
        (app / file).parent.mkdir(parents=True, exist_ok=True)
        (app / file).write_text("# Changelog\n\n## Unreleased\n")
    config = WorkspaceConfig(
        repos={"app": RepoConfig(path=app, slug="example/app", changelog=changelog)}
    )
    (planning / "abk.yaml").write_text(dump(config))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def changelog_checks(checks: list[Check]) -> list[Check]:
    return [check for check in checks if check.name.startswith("changelog")]


def test_a_set_path_whose_file_is_absent_is_warned_about(tmp_path: Path) -> None:
    found = changelog_checks(doctor(tmp_path, changelog="docs/HISTORY.md", file=None))

    assert [check.status for check in found] == ["warn"]
    assert "docs/HISTORY.md" in found[0].detail
    assert "app" in found[0].name + found[0].detail


def test_the_default_path_is_checked_too(tmp_path: Path) -> None:
    found = changelog_checks(doctor(tmp_path, changelog="CHANGELOG.md", file=None))

    assert [check.status for check in found] == ["warn"]


def test_a_set_path_whose_file_exists_is_not_warned_about(tmp_path: Path) -> None:
    checks = changelog_checks(doctor(tmp_path, changelog="docs/HISTORY.md", file="docs/HISTORY.md"))

    assert checks
    assert not [check for check in checks if check.status in ("warn", "FAIL")]


def test_a_repo_with_the_changelog_off_is_not_checked(tmp_path: Path) -> None:
    assert changelog_checks(doctor(tmp_path, changelog=None, file=None)) == []
