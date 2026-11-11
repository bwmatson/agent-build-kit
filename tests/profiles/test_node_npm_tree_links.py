"""The node-npm profile prepares a check worktree's `node_modules`
(spec: red-check-workspace-links)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.node_workspace import manifest, touch, workspace

MEMBERS = ["packages/shared", "packages/lib"]


@pytest.fixture
def profile():
    return profiles.get("node-npm")


def _tree(root: Path, project: str = ".") -> Path:
    """A workspace of two members, `@aa/shared` and `lib`, under `project` of `root`."""
    base = root / project
    workspace(base, MEMBERS)
    manifest(base / "packages" / "shared", "@aa/shared")
    manifest(base / "packages" / "lib", "lib")
    touch(base, "packages/shared/index.js", "packages/lib/index.js")
    return base


def _install(base: Path) -> None:
    """The installed `node_modules` of `_tree`: a plain package and a link for each member."""
    modules = base / "node_modules"
    touch(modules, "vitest/package.json")
    (modules / "@aa").mkdir(parents=True)
    (modules / "@aa" / "shared").symlink_to("../../packages/shared")
    (modules / "lib").symlink_to("../packages/lib")


@pytest.fixture
def trees(tmp_path: Path) -> tuple[Path, Path]:
    """An installed checkout and a worktree of the same shape whose members differ."""
    checkout = _tree(tmp_path / "checkout")
    _install(checkout)
    worktree = _tree(tmp_path / "worktree")
    touch(worktree, "packages/shared/changed.js")
    return checkout, worktree


def test_a_workspace_member_resolves_to_the_worktrees_own_folder(profile, trees) -> None:
    checkout, worktree = trees

    profile.prepare_worktree(checkout, worktree)

    modules = worktree / "node_modules"
    assert (modules / "@aa" / "shared").resolve() == (worktree / "packages" / "shared").resolve()
    assert (modules / "lib").resolve() == (worktree / "packages" / "lib").resolve()
    assert (modules / "@aa" / "shared" / "changed.js").is_file()


def test_another_package_resolves_to_the_installs_entry(profile, trees) -> None:
    checkout, worktree = trees

    profile.prepare_worktree(checkout, worktree)

    assert (worktree / "node_modules" / "vitest").resolve() == (
        checkout / "node_modules" / "vitest"
    ).resolve()


def test_a_checkout_without_an_install_gives_no_node_modules(profile, tmp_path: Path) -> None:
    checkout = _tree(tmp_path / "checkout")
    worktree = _tree(tmp_path / "worktree")

    profile.prepare_worktree(checkout, worktree)

    assert not (worktree / "node_modules").exists()


def test_a_member_the_worktree_lacks_is_skipped_and_the_others_are_linked(profile, trees) -> None:
    checkout, worktree = trees
    (worktree / "packages" / "lib" / "package.json").unlink()
    (worktree / "packages" / "lib" / "index.js").unlink()
    (worktree / "packages" / "lib").rmdir()

    profile.prepare_worktree(checkout, worktree)

    modules = worktree / "node_modules"
    assert not (modules / "lib").is_symlink()
    assert not (modules / "lib").exists()
    assert (modules / "@aa" / "shared").resolve() == (worktree / "packages" / "shared").resolve()


def test_preparing_twice_gives_the_same_result(profile, trees) -> None:
    checkout, worktree = trees

    profile.prepare_worktree(checkout, worktree)
    profile.prepare_worktree(checkout, worktree)

    modules = worktree / "node_modules"
    assert (modules / "@aa" / "shared").resolve() == (worktree / "packages" / "shared").resolve()
    assert (modules / "lib").resolve() == (worktree / "packages" / "lib").resolve()
    assert (modules / "vitest").resolve() == (checkout / "node_modules" / "vitest").resolve()


def test_a_project_folder_below_the_root_gets_its_node_modules_there(
    profile, tmp_path: Path
) -> None:
    project = "agent-assessment/web"
    checkout = tmp_path / "checkout"
    worktree = tmp_path / "worktree"
    _install(_tree(checkout, project))
    _tree(worktree, project)

    profile.prepare_worktree(checkout, worktree, project=project)

    modules = worktree / project / "node_modules"
    assert (modules / "@aa" / "shared").resolve() == (
        worktree / project / "packages" / "shared"
    ).resolve()
    assert (modules / "vitest").resolve() == (
        checkout / project / "node_modules" / "vitest"
    ).resolve()
    assert not (worktree / "node_modules").exists()
