"""`abk doctor`'s `unit worktrees` check: unit worktrees under another folder than the repo's
current one, and registered ones whose directory is gone (spec: unit-worktrees)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.settings import settings
from tests.cli.in_repo_doctor import checks_of, in_repo, named, with_pipeline_worktree
from tests.cli.public_content_repo import planning
from tests.factories import git, init_repo

CHECK = "unit worktrees"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The unit worktree root, set the way `ABK_WORKTREE_ROOT` sets it."""
    units = tmp_path / "units"
    monkeypatch.setattr(settings, "worktree_root", units)
    return units


def add_worktree(repo: Path, path: Path, branch: str = "spec/x/1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    return path


def listing(repo: Path) -> str:
    return git(repo, "worktree", "list", "--porcelain")


def code_repo(tmp_path: Path, folder: str, *keys: str) -> Path:
    """A planning repo apart from one code checkout `folder`, listed under each of `keys`."""
    code = init_repo(tmp_path / folder)
    git(code, "commit", "-q", "--allow-empty", "-m", "base")
    repos = {key: RepoConfig(path=code, slug=f"example/{key}", changelog=None) for key in keys}
    return planning(tmp_path / "plan", repos=repos)


def test_every_worktree_under_the_repos_folder_is_ok(tmp_path: Path, root: Path) -> None:
    config = in_repo(tmp_path / "app")
    add_worktree(config.parent, root / "app" / "spec_x_1")

    assert [c.status for c in named(checks_of(config), CHECK)] == ["ok"]


def test_a_worktree_under_another_folder_is_a_note_naming_the_path_and_the_move(
    tmp_path: Path, root: Path
) -> None:
    config = in_repo(tmp_path / "app")
    old = add_worktree(config.parent, root / "worktree" / "spec_x_1")

    [found] = named(checks_of(config), CHECK)

    assert found.status == "info"
    assert str(old) in found.detail
    assert "git worktree move" in found.detail + found.fix


def test_a_registered_worktree_whose_directory_is_gone_warns_and_nothing_changes(
    tmp_path: Path, root: Path
) -> None:
    config = in_repo(tmp_path / "app")
    shutil.rmtree(add_worktree(config.parent, root / "app" / "spec_x_1"))
    before = listing(config.parent)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "warn"
    assert "git worktree prune" in found.detail + found.fix
    assert listing(config.parent) == before


def test_a_worktree_outside_the_root_is_not_listed(tmp_path: Path, root: Path) -> None:
    config = in_repo(tmp_path / "app", publish="branch")
    pipeline = with_pipeline_worktree(config)

    found = named(checks_of(config), CHECK)

    assert [c.status for c in found] == ["ok"]
    assert str(pipeline) not in found[0].detail


def test_a_folder_that_differs_from_the_key_is_a_note(tmp_path: Path, root: Path) -> None:
    config = code_repo(tmp_path, "app-src", "app")
    old = add_worktree(tmp_path / "app-src", root / "app-src" / "spec_x_1")

    [found] = named(checks_of(config), CHECK)

    assert found.status == "info"
    assert str(old) in found.detail


def test_a_worktree_under_the_key_is_ok_whatever_the_checkout_folder(
    tmp_path: Path, root: Path
) -> None:
    config = code_repo(tmp_path, "app-src", "app")
    add_worktree(tmp_path / "app-src", root / "app" / "spec_x_1")

    assert [c.status for c in named(checks_of(config), CHECK)] == ["ok"]


def test_repos_sharing_a_checkout_list_its_worktree_once(tmp_path: Path, root: Path) -> None:
    config = code_repo(tmp_path, "shared", "app", "lib")
    old = add_worktree(tmp_path / "shared", root / "shared" / "spec_x_1")

    found = named(checks_of(config), CHECK)

    assert sum(str(old) in c.detail for c in found) == 1
