"""The node-npm profile names the folders of its Node toolchain to read, beside the npm cache
and the registry, and the policy lists the ones that exist on the machine (spec:
sandbox-profile-paths)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.base import SandboxPaths
from agent_build_kit.sandboxes.base import SandboxPathsProfile
from agent_build_kit.sandboxes.policy import build_policy, policy_entries
from tests.sandboxes.policy_support import BareRuntime, Scene, reads

# The home shorthand, held apart so no line reads as a path under a home directory.
HOME_MARK = "~"
MANAGER_FOLDERS = (".volta", ".nvm", ".local/share/fnm")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def node_npm_paths(repo: Path) -> SandboxPaths:
    profile = profiles.get("node-npm")
    assert isinstance(profile, SandboxPathsProfile)
    found = profile.sandbox_paths(repo)
    assert isinstance(found, SandboxPaths)
    return found


def test_node_npm_reads_the_folders_of_the_node_version_managers(tmp_path: Path) -> None:
    found = node_npm_paths(tmp_path)

    assert {f"{HOME_MARK}/{folder}" for folder in MANAGER_FOLDERS} <= set(found.read)


def test_the_policy_lists_the_manager_folders_that_exist(tmp_path: Path, home: Path) -> None:
    scene = Scene(tmp_path)
    (home / ".volta").mkdir(parents=True)
    node = profiles.get("node-npm")
    installation = scene.installation()
    scene.worktree.mkdir()

    entries = policy_entries(
        installation, "app", scene.worktree, runtime=BareRuntime(), profile=node
    )
    policy = build_policy(installation, "app", scene.worktree, runtime=BareRuntime(), profile=node)

    defaults = {e.value for e in entries if e.kind == "read" and e.source == "default (node-npm)"}
    assert f"{HOME_MARK}/.volta" in defaults
    assert reads(policy, home / ".volta")
    assert not reads(policy, home / ".nvm")
    assert not reads(policy, home / ".local" / "share" / "fnm")


def test_the_policy_lists_a_persons_read_folder_beside_the_profiles(
    tmp_path: Path, home: Path
) -> None:
    scene = Scene(tmp_path)
    (home / ".nvm").mkdir(parents=True)
    own = tmp_path / "toolbox"
    own.mkdir()
    node = profiles.get("node-npm")
    local = {"repos": {"app": {"sandbox": {"read": [str(own)]}}}}
    installation = scene.installation(local=local)
    scene.worktree.mkdir()

    policy = build_policy(installation, "app", scene.worktree, runtime=BareRuntime(), profile=node)

    assert reads(policy, home / ".nvm")
    assert reads(policy, own)
