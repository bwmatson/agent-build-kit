"""An npm workspace member names the root `package-lock.json`; one above the checkout is ignored."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.init.environment import detect_environment
from tests.factories import init_repo
from tests.node_workspace import touch, workspace


def named_locks(folder: Path) -> list[Path]:
    found = detect_environment(folder, framework=False, profile="node-npm")
    assert found is not None
    return [(folder / name).resolve() for name in found.inputs.lock]


def test_a_member_names_the_root_lock_in_its_inputs(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    workspace(root, ["packages/web"])
    touch(root, "package-lock.json")

    assert named_locks(root / "packages" / "web") == [(root / "package-lock.json").resolve()]


def test_a_project_the_workspace_does_not_list_takes_no_lock(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    workspace(root, ["packages/web"])
    workspace(root / "tools" / "other", [])
    touch(root, "package-lock.json")

    assert named_locks(root / "tools" / "other") == []


def test_a_lock_above_the_git_root_is_not_named(tmp_path: Path) -> None:
    workspace(tmp_path, ["repo/app"])
    touch(tmp_path, "package-lock.json")
    init_repo(tmp_path / "repo")

    assert named_locks(tmp_path / "repo" / "app") == []
