"""The policy reads, and does not write, the installation that runs the step: the interpreter's
prefix and base prefix, the folders of the interpreter and the `abk` entry point and, for a
checkout install, the package's source root (spec: sandbox-abk-exec)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import agent_build_kit
from agent_build_kit.sandboxes.policy import BUILT_IN, own_installation, policy_entries
from tests.sandboxes.policy_support import BareProfile, BareRuntime, Scene, reads, writes


class Process:
    """A process laid out in a temp folder: a venv, the interpreter it points to, the folder
    holding the `abk` entry point, and the package imported from a checkout."""

    def __init__(self, tmp: Path) -> None:
        self.prefix = tmp / "venv"
        self.base = tmp / "uv" / "python"
        self.entry = tmp / "tools" / "bin"
        self.checkout = tmp / "checkout" / "src"
        for folder in (self.prefix / "bin", self.base, self.entry, self.checkout):
            folder.mkdir(parents=True)
        (self.prefix / "bin" / "python").write_text("")
        (self.entry / "abk").write_text("")

    def install(self, monkeypatch: pytest.MonkeyPatch, *, package: Path | None = None) -> None:
        """Make this process the running one."""
        monkeypatch.setattr(sys, "prefix", str(self.prefix))
        monkeypatch.setattr(sys, "base_prefix", str(self.base))
        monkeypatch.setattr(sys, "executable", str(self.prefix / "bin" / "python"))
        monkeypatch.setattr(shutil, "which", lambda name, *a, **k: str(self.entry / name))
        file = package or self.checkout / "agent_build_kit" / "__init__.py"
        monkeypatch.setattr(agent_build_kit, "__file__", str(file))


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return Scene(tmp_path)


@pytest.fixture
def process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Process:
    found = Process(tmp_path / "process")
    found.install(monkeypatch)
    return found


def test_the_policy_reads_the_prefix_the_base_prefix_and_the_entry_point_folder(
    scene: Scene, process: Process
) -> None:
    policy = scene.policy()

    assert reads(policy, process.prefix / "bin" / "python")
    assert reads(policy, process.base)
    assert reads(policy, process.entry / "abk")


def test_a_checkout_install_adds_the_package_s_source_root(scene: Scene, process: Process) -> None:
    policy = scene.policy()

    assert reads(policy, process.checkout / "agent_build_kit" / "__init__.py")


def test_an_install_under_the_prefix_adds_no_source_root(
    scene: Scene, process: Process, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = process.prefix / "lib" / "site-packages"
    (site / "agent_build_kit").mkdir(parents=True)
    process.install(monkeypatch, package=site / "agent_build_kit" / "__init__.py")

    policy = scene.policy()

    assert site.resolve() not in policy.read
    assert process.checkout.resolve() not in policy.read
    assert reads(policy, site)


def test_none_of_it_is_writable(scene: Scene, process: Process) -> None:
    policy = scene.policy()

    assert reads(policy, process.prefix)
    for path in (process.prefix, process.base, process.entry, process.checkout):
        assert not writes(policy, path), path


def test_a_path_that_does_not_exist_adds_nothing(
    scene: Scene, process: Process, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gone = tmp_path / "gone"
    monkeypatch.setattr(sys, "base_prefix", str(gone / "base"))
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: str(gone / "bin" / name))
    package = gone / "src" / "agent_build_kit" / "__init__.py"
    monkeypatch.setattr(agent_build_kit, "__file__", str(package))

    policy = scene.policy()

    assert not any(Path(p).is_relative_to(gone.resolve()) for p in policy.read)
    assert reads(policy, process.prefix)


def test_the_set_is_what_the_process_runs_from_and_only_what_exists(
    process: Process,
) -> None:
    found = {path.resolve() for path in own_installation()}

    assert {process.prefix, process.base, process.entry, process.checkout} <= found
    assert all(path.exists() for path in found)


def test_it_is_a_built_in_entry_beside_the_others(scene: Scene, process: Process) -> None:
    installation = scene.installation()
    scene.worktree.mkdir(exist_ok=True)

    entries = policy_entries(
        installation, "app", scene.worktree, runtime=BareRuntime(), profile=BareProfile()
    )

    shown = {e.value for e in entries if e.kind == "read" and e.source == BUILT_IN}
    assert str(process.prefix) in shown


def test_the_planning_repo_s_other_folders_and_another_repository_stay_unreadable(
    scene: Scene, process: Process, tmp_path: Path
) -> None:
    other = tmp_path / "platform" / "src" / "a.py"
    other.parent.mkdir(parents=True)
    other.write_text("x = 1\n")
    scene.root.mkdir(parents=True, exist_ok=True)
    (scene.root / "README.md").write_text("text\n")

    policy = scene.policy(changes=())

    assert reads(policy, process.prefix)
    assert not reads(policy, other)
    assert not reads(policy, scene.root / "README.md")


def test_the_files_that_load_the_installation_are_read_one_by_one(
    scene: Scene, process: Process
) -> None:
    scene.root.mkdir(parents=True, exist_ok=True)
    (scene.root / ".env").write_text("ABK_X=1\n")
    (scene.root / "notes.md").write_text("text\n")

    policy = scene.policy(local={})

    for name in ("abk.yaml", "abk.local.yaml"):
        assert reads(policy, scene.root / name), name
        assert not writes(policy, scene.root / name), name
    assert not reads(policy, scene.root / ".env")
    assert not reads(policy, scene.root / "notes.md")
    assert scene.root.resolve() not in policy.read


def test_a_file_that_is_not_there_is_not_granted(scene: Scene, process: Process) -> None:
    policy = scene.policy()

    assert reads(policy, scene.root / "abk.yaml")
    assert (scene.root / "abk.local.yaml").resolve() not in policy.read
    assert (scene.root / ".env").resolve() not in policy.read
