"""A uv workspace member's lock is the root's: named in its environment inputs, and left alone
by a unit's commit; a project the workspace does not list, or a lock above the checkout, is not."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.init.environment import detect_environment
from agent_build_kit.profiles.base import CreatedFiles
from tests.factories import init_repo

PYPROJECT = '[project]\nname = "{name}"\nversion = "0"\n'
WORKSPACE = "\n[tool.uv.workspace]\nmembers = [{members}]\n"


def project(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pyproject.toml").write_text(PYPROJECT.format(name=name))
    return folder


def workspace_root(folder: Path, *members: str) -> Path:
    listed = ", ".join(f'"{member}"' for member in members)
    project(folder, "root")
    (folder / "pyproject.toml").write_text(
        PYPROJECT.format(name="root") + WORKSPACE.format(members=listed)
    )
    (folder / "uv.lock").write_text("version = 1\n")
    return folder


def named_locks(folder: Path) -> list[Path]:
    found = detect_environment(folder, framework=False, profile="python-uv")
    assert found is not None
    return [(folder / name).resolve() for name in found.inputs.lock]


def test_a_member_names_the_root_lock_in_its_inputs(tmp_path: Path) -> None:
    root = workspace_root(init_repo(tmp_path / "repo"), "member-a")
    member = project(root / "member-a", "member-a")

    assert named_locks(member) == [(root / "uv.lock").resolve()]


def test_a_project_the_workspace_does_not_list_takes_no_lock(tmp_path: Path) -> None:
    root = workspace_root(init_repo(tmp_path / "repo"), "member-a")
    other = project(root / "other-project", "other-project")

    assert named_locks(other) == []


def test_a_project_with_its_own_lock_names_only_that_one(tmp_path: Path) -> None:
    root = workspace_root(init_repo(tmp_path / "repo"), "member-a")
    member = project(root / "member-a", "member-a")
    (member / "uv.lock").write_text("version = 1\n")

    assert named_locks(member) == [(member / "uv.lock").resolve()]


def test_a_lock_above_the_git_root_is_not_named(tmp_path: Path) -> None:
    workspace_root(tmp_path, "repo/app")
    repo = init_repo(tmp_path / "repo")
    app = project(repo / "app", "app")

    assert named_locks(app) == []


def test_the_files_left_by_a_build_of_a_member_include_the_root_lock(tmp_path: Path) -> None:
    root = workspace_root(init_repo(tmp_path / "repo"), "member-a")
    member = project(root / "member-a", "member-a")
    profile = profiles.get("python-uv")
    assert isinstance(profile, CreatedFiles)

    left = [(member / name).resolve() for name in profile.created_files(member)]

    assert (root / "uv.lock").resolve() in left
