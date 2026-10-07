"""What the restack built by `build_stack_moves` is given for the repo it moves.

A branch moved cleanly onto a new base is checked again before it is pushed, and
that check is the repo's own tier 1: its changelog check when the setting is on,
and the repo's settings reach the conflict resolver.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.restack import ConflictContext, Moved
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_tier1
from tests.conftest import make_installation


def workspace(tmp_path: Path, *, app_changelog: str | None) -> Installation:
    root = tmp_path / "planning"
    repos = {
        "platform": RepoConfig(path=root / "checkouts" / "platform", slug="example/platform"),
        "app": RepoConfig(
            path=root / "checkouts" / "app", slug="example/app", changelog=app_changelog
        ),
    }
    return make_installation(
        root, repos={name: r.model_dump(mode="json") for name, r in repos.items()}
    )


def is_changelog_check(command: list[str]) -> bool:
    return "changelog" in command and "check" in command


def restack_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installation: Installation
) -> tuple[dict[str, Any], list[list[str]]]:
    """The keyword arguments `build_restack` was given, and the commands every
    tier 1 it builds would run in place of a real one."""
    ran: list[list[str]] = []

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    def faked(**kwargs: Any) -> Callable[..., tuple[bool, str]]:
        return build_tier1(run=run, changed=lambda *a: ["tests/test_x.py"], **kwargs)

    given: dict[str, Any] = {}
    monkeypatch.setattr(cli, "build_tier1", faked)
    monkeypatch.setattr(cli, "build_restack", lambda **kwargs: given.update(kwargs) or {})
    cli.build_stack_moves(UnitStore(tmp_path / "units.json"), installation)
    return given, ran


def test_a_restacked_branch_is_checked_with_the_changelog_check_when_its_repo_has_it_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = workspace(tmp_path, app_changelog="CHANGELOG.md")
    given, ran = restack_wiring(tmp_path, monkeypatch, installation)

    passed, _ = given["tier1"](cwd=installation.checkouts["app"], base="origin/main")

    assert passed
    assert [c for c in ran if is_changelog_check(c)]


def test_a_restacked_branch_in_its_worktree_is_checked_as_its_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = workspace(tmp_path, app_changelog="CHANGELOG.md")
    given, ran = restack_wiring(tmp_path, monkeypatch, installation)
    worktree = installation.worktree_root / "app" / "spec_feature_1"

    given["tier1"](cwd=worktree, base="origin/main")

    assert [c for c in ran if is_changelog_check(c)]


def test_a_restacked_branch_gets_no_changelog_check_when_its_repo_has_it_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = workspace(tmp_path, app_changelog=None)
    given, ran = restack_wiring(tmp_path, monkeypatch, installation)

    given["tier1"](cwd=installation.checkouts["app"], base="origin/main")

    assert ran
    assert not [c for c in ran if is_changelog_check(c)]


def test_the_restacks_tier_one_is_the_setting_of_the_repo_the_branch_is_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = workspace(tmp_path, app_changelog=None)
    given, ran = restack_wiring(tmp_path, monkeypatch, installation)

    given["tier1"](cwd=installation.checkouts["platform"], base="origin/main")

    assert [c for c in ran if is_changelog_check(c)]


@pytest.mark.parametrize("changelog", ["CHANGELOG.md", None])
def test_the_resolver_is_told_the_settings_of_the_repo_it_moves_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changelog: str | None
) -> None:
    installation = workspace(tmp_path, app_changelog=changelog)
    given, _ = restack_wiring(tmp_path, monkeypatch, installation)
    contexts: list[ConflictContext] = []

    def move(*args: Any, context: ConflictContext, **kwargs: Any) -> Moved:
        contexts.append(context)
        return Moved(sha="abc123", resolved=())

    given["move"](
        installation.checkouts["app"],
        "spec/feature/2",
        new_base="main",
        old_base="spec/feature/1",
        moving_unit="feature/2",
        moving_intent="b",
        onto_unit="feature/1",
        onto_intent="a",
        move=move,
    )

    assert len(contexts) == 1
    assert contexts[0].repo is not None
    assert contexts[0].repo.slug == "example/app"
    assert contexts[0].repo.changelog == changelog
