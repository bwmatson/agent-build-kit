"""An installation whose root is a pipeline worktree: the repository gives its name, its
worktree root, its environment file and the meaning of a repo path."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import installation as installation_module
from agent_build_kit.pipeline.planning_repo import repository_name
from agent_build_kit.pipeline.planning_sync import PlanningMode, planning_mode
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo
from tests.planning_worktree_support import in_repo, installation_at


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setattr(installation_module, "data_home", lambda: data)
    return data


def with_repos(root: Path, repos: dict[str, Path]):
    return make_installation(
        root,
        repos={
            name: {"path": str(path), "slug": f"example/{name}"} for name, path in repos.items()
        },
    )


def test_the_default_worktree_root_is_named_for_the_repository(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)
    plain = tmp_path / "meta"

    assert installation_at(setup.worktree, setup.working_copy).worktree_root == (
        data / "app" / "worktrees"
    )
    assert installation_at(plain, setup.working_copy).worktree_root == data / "meta" / "worktrees"


def test_a_configured_worktree_root_wins(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)
    configured = tmp_path / "trees"

    inst = installation_at(
        setup.worktree, setup.working_copy, planning=dict(worktree_root=str(configured))
    )

    assert inst.worktree_root == configured.resolve()
    assert inst.worktree_root != data / "app" / "worktrees"
    assert installation_at(setup.worktree, setup.working_copy).worktree_root == (
        data / "app" / "worktrees"
    )


def test_the_main_working_trees_env_file_is_used_when_the_worktree_has_none(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)
    (setup.working_copy / ".env").write_text("# local\n")

    inst = installation_at(setup.worktree, setup.working_copy)

    assert inst.env_file == setup.working_copy / ".env"
    assert not (setup.worktree / ".env").exists()
    # Its own wins once it has one, and neither file is written.
    (setup.worktree / ".env").write_text("# own\n")
    assert installation_at(setup.worktree, setup.working_copy).env_file == (setup.worktree / ".env")
    assert (setup.working_copy / ".env").read_text() == "# local\n"
    # A working copy and a separate root keep their own.
    plain = tmp_path / "meta"
    assert installation_at(plain, setup.working_copy).env_file == plain / ".env"
    assert installation_at(setup.working_copy, setup.working_copy).env_file == (
        setup.working_copy / ".env"
    )


def test_a_relative_repo_path_is_relative_to_the_root(tmp_path: Path, data: Path) -> None:
    setup = in_repo(tmp_path)
    plain = tmp_path / "meta"
    plain.mkdir()

    here = with_repos(setup.worktree, {"app": Path(".")})
    below = with_repos(plain, {"app": Path("checkouts/app")})

    assert here.checkouts["app"].resolve() == setup.worktree.resolve()
    assert planning_mode(here) == PlanningMode.PIPELINE_WORKTREE
    assert below.checkouts["app"].resolve() == (plain / "checkouts" / "app").resolve()


def test_an_absolute_path_naming_the_repository_is_the_root_only_in_the_pipeline_worktree(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)
    other = init_repo(tmp_path / "platform")

    inst = with_repos(setup.worktree, {"app": setup.working_copy, "platform": other})

    assert inst.checkouts["app"].resolve() == setup.worktree.resolve()
    assert inst.checkouts["platform"] == other
    # In a working copy the same path is left as written.
    copy = with_repos(setup.working_copy, {"app": setup.working_copy, "platform": other})
    assert copy.checkouts["app"] == setup.working_copy
    assert copy.checkouts["platform"] == other


def test_the_repository_is_named_for_its_main_working_tree(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)

    for root in (setup.working_copy, setup.worktree):
        found = repository_name(root)
        assert found.name == "app"
        assert found.reason == ""


def test_a_common_git_directory_not_named_dot_git_falls_back_to_the_root_name(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    store = tmp_path / "store.git"
    git(root, "init", "-q", "-b", "main", f"--separate-git-dir={store}")
    git(root, "config", "user.email", "t@t.t")
    git(root, "config", "user.name", "t")
    commit_files(root, "start", {"README.md": "x\n"})

    found = repository_name(root)

    assert found.name == "checkout"
    assert "store.git" in found.reason
