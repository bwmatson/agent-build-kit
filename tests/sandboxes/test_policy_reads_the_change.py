"""The policy for a unit of change `c` reads that change and the capability specs, and nothing
else of the planning repo (spec: sandbox-spec-reads)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.sandboxes import SandboxPolicy
from agent_build_kit.sandboxes.policy import PolicyRefused
from tests.sandboxes.policy_support import Scene


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return Scene(tmp_path)


def reads(policy: SandboxPolicy, path: Path) -> bool:
    """Whether the read list covers `path`, as a backend that enforces it would decide."""
    return any(path.resolve().is_relative_to(folder) for folder in policy.read)


def lay_out_specs(scene: Scene) -> Path:
    """The planning repo's specs folder with two changes and a capability; returns the folder."""
    specs = scene.root / "openspec"
    for change in ("feature", "other"):
        (specs / "changes" / change / "specs" / "cap").mkdir(parents=True)
        for name in ("tasks.md", "proposal.md", "design.md", "specs/cap/spec.md"):
            (specs / "changes" / change / name).write_text("text\n")
    (specs / "specs" / "cap").mkdir(parents=True)
    (specs / "specs" / "cap" / "spec.md").write_text("text\n")
    return specs


def test_the_unit_s_change_and_the_capability_specs_are_read(scene: Scene) -> None:
    scene.installation()
    specs = lay_out_specs(scene)

    policy = scene.policy(change="feature")

    for name in ("tasks.md", "proposal.md", "design.md", "specs/cap/spec.md"):
        assert reads(policy, specs / "changes" / "feature" / name), name
    assert reads(policy, specs / "specs" / "cap" / "spec.md")
    assert not any(Path(p).is_relative_to(specs.resolve()) for p in policy.write)


def test_nothing_else_of_the_planning_repo_is_read(scene: Scene) -> None:
    scene.installation()
    specs = lay_out_specs(scene)

    policy = scene.policy(change="feature", local={})

    assert reads(policy, specs / "changes" / "feature" / "tasks.md")
    assert not reads(policy, specs / "changes" / "other" / "tasks.md")
    assert not reads(policy, scene.root / "abk.yaml")
    assert not reads(policy, scene.root / "abk.local.yaml")
    assert not reads(policy, scene.root / "README.md")


def test_a_step_with_no_change_adds_nothing(scene: Scene) -> None:
    scene.installation()
    specs = lay_out_specs(scene)

    with_change = scene.policy(change="feature")
    without = scene.policy()

    assert reads(with_change, specs / "changes" / "feature" / "tasks.md")
    assert not reads(without, specs / "changes" / "feature" / "tasks.md")
    assert not reads(without, specs / "specs" / "cap" / "spec.md")


def test_a_write_grant_inside_the_specs_folder_is_still_refused(scene: Scene) -> None:
    scene.installation()
    specs = lay_out_specs(scene)
    assert reads(scene.policy(change="feature"), specs / "changes" / "feature" / "tasks.md")

    with pytest.raises(PolicyRefused, match="owns"):
        scene.policy(
            {"write": [str(specs / "changes" / "feature")]},
            change="feature",
        )
