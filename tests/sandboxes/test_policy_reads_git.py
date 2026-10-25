"""The policy for a step in a worktree reads what `git` opens to run there, and writes none of it
(spec: sandbox-git-reads)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.sandboxes.policy import BUILT_IN, policy_entries
from tests.factories import commit, git, init_repo
from tests.sandboxes.policy_support import BareProfile, BareRuntime, Scene, reads, writes


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (tmp_path / "home").mkdir()
    return Scene(tmp_path)


@pytest.fixture
def linked(scene: Scene) -> Scene:
    """The scene's worktree is a linked worktree of its main checkout."""
    init_repo(scene.main)
    commit(scene.main, "a.txt")
    git(scene.main, "worktree", "add", "-q", "-b", "unit", str(scene.worktree))
    return scene


def common(scene: Scene) -> Path:
    return scene.main / ".git"


def entry(scene: Scene) -> Path:
    """The common directory's entry for the linked worktree."""
    return common(scene) / "worktrees" / scene.worktree.name


def test_a_linked_worktree_reads_the_repository_configuration_and_its_own_entry(
    linked: Scene,
) -> None:
    policy = linked.policy()

    assert reads(policy, common(linked) / "config")
    assert reads(policy, common(linked) / "info" / "exclude")
    for name in ("HEAD", "gitdir", "commondir"):
        assert reads(policy, entry(linked) / name), name
    assert reads(policy, linked.worktree / ".git")


def test_the_persons_git_configuration_is_read_when_it_exists(linked: Scene) -> None:
    home = linked.tmp / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".gitconfig").write_text("[user]\n\tname = t\n")
    (home / ".config" / "git" / "ignore").write_text("*.swp\n")

    policy = linked.policy()

    assert reads(policy, home / ".gitconfig")
    assert reads(policy, home / ".config" / "git" / "ignore")


def test_the_credential_store_beside_the_configuration_is_not_read(linked: Scene) -> None:
    folder = linked.tmp / "home" / ".config" / "git"
    folder.mkdir(parents=True)
    (folder / "config").write_text("[user]\n\tname = t\n")
    (folder / "credentials").write_text("https://user:secret@host.example\n")

    policy = linked.policy()

    assert reads(policy, folder / "config")
    assert not reads(policy, folder / "credentials")


def test_the_xdg_configuration_folder_is_read_in_place_of_the_default(
    linked: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    xdg = linked.tmp / "xdg"
    (xdg / "git").mkdir(parents=True)
    (xdg / "git" / "config").write_text("[user]\n\tname = t\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    policy = linked.policy()

    assert reads(policy, xdg / "git" / "config")


def test_none_of_it_is_writable(linked: Scene) -> None:
    home = linked.tmp / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("*.swp\n")
    (home / ".gitconfig").write_text("[user]\n\tname = t\n")

    policy = linked.policy()

    kept = [
        common(linked) / "config",
        common(linked) / "info",
        home / ".gitconfig",
        home / ".config" / "git" / "ignore",
    ]
    for path in kept:
        assert reads(policy, path), path
        assert not writes(policy, path), path


def test_a_path_that_does_not_exist_adds_nothing(linked: Scene) -> None:
    home = linked.tmp / "home"
    assert not (home / ".gitconfig").exists()

    policy = linked.policy()

    assert reads(policy, common(linked) / "config"), "the control: what exists is read"
    assert not reads(policy, home / ".gitconfig")
    assert not reads(policy, home / ".config" / "git")
    assert all(path.exists() for path in policy.read)


def test_another_repository_under_the_same_parent_stays_unreadable(linked: Scene) -> None:
    other = init_repo(linked.tmp / "other")
    commit(other, "b.txt")

    policy = linked.policy()

    assert reads(policy, common(linked) / "config"), "the control: its own is read"
    assert not reads(policy, other / ".git" / "config")
    assert not reads(policy, other / "b.txt")
    assert not reads(policy, linked.main / "a.txt"), "the main checkout's files are not its own"
    assert not reads(policy, common(linked) / "hooks")


def test_a_step_in_the_main_checkout_reads_its_own_configuration(scene: Scene) -> None:
    init_repo(scene.main)
    commit(scene.main, "a.txt")
    scene.worktree = scene.main

    policy = scene.policy()

    assert reads(policy, scene.main / ".git" / "config")
    assert reads(policy, scene.main / ".git" / "info")


def test_the_entries_are_built_in_so_the_policy_display_shows_where_they_came_from(
    linked: Scene,
) -> None:
    installation = linked.installation()

    entries = policy_entries(
        installation, "app", linked.worktree, runtime=BareRuntime(), profile=BareProfile()
    )

    wanted = {
        (common(linked) / "config").resolve(),
        (common(linked) / "info").resolve(),
        entry(linked).resolve(),
        (linked.worktree / ".git").resolve(),
    }
    built_in = {
        Path(e.value).resolve() for e in entries if e.kind == "read" and e.source == BUILT_IN
    }
    assert wanted <= built_in
