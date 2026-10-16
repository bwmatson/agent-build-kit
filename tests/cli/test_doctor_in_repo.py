"""`abk doctor` over a repository that is its own planning repo: the repo at the root, the pipeline
marker and worktree, the state ignore lines, and the skills (spec: planning-in-repo-init)."""

from __future__ import annotations

import shutil
from pathlib import Path

from agent_build_kit import __version__
from tests.cli.in_repo_doctor import (
    UNPROTECTED,
    checks_of,
    in_repo,
    named,
    with_pipeline_worktree,
)

WORKTREE = "pipeline worktree"
IGNORES = "state ignores"


def stale_skill(root: Path) -> None:
    skill = root / ".claude" / "skills" / "abk-config" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: abk-config\ngeneratedBy: agent-build-kit 0.0.1\n---\n")


def test_a_repo_at_the_root_is_listed_once_and_raises_no_failure(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="branch")
    with_pipeline_worktree(config)

    checks = checks_of(config)

    assert [c.status for c in named(checks, "repo app")] == ["ok"]
    assert [c for c in checks if c.status == "FAIL"] == []
    assert [c.status for c in named(checks, WORKTREE)] == ["ok"]


def test_a_marker_naming_an_existing_worktree_is_ok_and_names_it(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="branch", guard=UNPROTECTED)
    worktree = with_pipeline_worktree(config)

    [found] = named(checks_of(config), WORKTREE)

    assert found.status == "ok"
    assert str(worktree) in found.detail


def test_a_marker_naming_a_worktree_that_is_gone_warns_naming_install_timers(
    tmp_path: Path,
) -> None:
    config = in_repo(tmp_path / "app", publish="branch", guard=UNPROTECTED)
    shutil.rmtree(with_pipeline_worktree(config))

    [found] = named(checks_of(config), WORKTREE)

    assert found.status == "warn"
    assert "abk install-timers" in found.fix


def test_a_gitignore_without_the_state_lines_warns_naming_init(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="branch", ignore="node_modules/\n")
    with_pipeline_worktree(config)

    [found] = named(checks_of(config), IGNORES)

    assert found.status == "warn"
    assert "abk init" in found.fix


def test_a_gitignore_with_the_state_lines_is_ok(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="branch")
    with_pipeline_worktree(config)

    [found] = named(checks_of(config), IGNORES)

    assert found.status == "ok"


def test_skills_are_listed_once_when_the_root_and_the_checkout_are_the_same_directory(
    tmp_path: Path,
) -> None:
    config = in_repo(tmp_path / "app", publish="branch")
    with_pipeline_worktree(config)
    stale_skill(config.parent)

    found = named(checks_of(config), "skills")

    assert len(found) == 1
    assert f"older than {__version__}" in found[0].detail
