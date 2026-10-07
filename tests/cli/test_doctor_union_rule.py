"""`abk doctor` warns when a repo with a changelog has no union-merge rule for it."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, *, changelog: str | None, attributes: str | None) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    (app / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n")
    if attributes is not None:
        (app / ".gitattributes").write_text(attributes)
    config = WorkspaceConfig(
        repos={"app": RepoConfig(path=app, slug="example/app", changelog=changelog)}
    )
    (planning / "abk.yaml").write_text(dump(config))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def union_warnings(checks: list[Check]) -> list[Check]:
    return [
        c
        for c in checks
        if c.status == "warn"
        and "abk init" in c.fix
        and any(word in f"{c.name} {c.detail}" for word in ("union", "merge", ".gitattributes"))
    ]


def test_a_changelog_without_a_union_rule_is_warned_about_naming_the_repo_and_the_fix(
    tmp_path: Path,
) -> None:
    found = union_warnings(doctor(tmp_path, changelog="CHANGELOG.md", attributes=None))

    assert len(found) == 1
    assert "app" in f"{found[0].name} {found[0].detail}"


def test_a_gitattributes_without_the_rule_is_warned_about_too(tmp_path: Path) -> None:
    found = union_warnings(doctor(tmp_path, changelog="CHANGELOG.md", attributes="*.png binary\n"))

    assert len(found) == 1


def test_a_repo_with_the_rule_is_not_warned_about(tmp_path: Path) -> None:
    attributes = "CHANGELOG.md merge=union\n"

    assert union_warnings(doctor(tmp_path, changelog="CHANGELOG.md", attributes=attributes)) == []


def test_a_repo_with_the_changelog_off_is_not_warned_about(tmp_path: Path) -> None:
    assert union_warnings(doctor(tmp_path, changelog=None, attributes=None)) == []
