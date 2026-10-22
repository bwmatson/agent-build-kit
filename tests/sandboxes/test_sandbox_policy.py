"""The sandbox policy: assembled from every place that grants, resolved, and fenced."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.config import ConfigError
from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.sandboxes.policy import PolicyRefused, build_policy

# The home shorthand, held apart so no line reads as a path under a home directory.
HOME_MARK = "~"


class StandInRuntime:
    def __init__(self, write: list[str]) -> None:
        self.write = write

    def sandbox_paths(self) -> dict[str, list[str]]:
        return {"write": self.write}


class StandInProfile:
    """A profile with the optional member."""

    def __init__(self, write: list[str]) -> None:
        self.write = write

    def sandbox_paths(self, repo: Path) -> dict[str, list[str]]:
        return {"write": self.write}


class BareProfile:
    """A profile without it."""


class BareRuntime:
    pass


class Scene:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "plan"
        self.main = tmp_path / "main"
        self.worktree = tmp_path / "wt"

    def repos(self, sandbox: dict[str, Any] | None = None, projects: list | None = None) -> dict:
        return {
            "app": {
                "path": str(self.main),
                "slug": "example/app",
                "sandbox": sandbox or {},
                "projects": projects or [],
            }
        }

    def installation(
        self,
        sandbox: dict[str, Any] | None = None,
        projects: list | None = None,
        local: dict[str, Any] | None = None,
    ) -> Installation:
        """The installation a real load gives: abk.yaml and abk.local.yaml written to disk."""
        self.root.mkdir(exist_ok=True)
        (self.root / "abk.yaml").write_text(
            yaml.safe_dump({"repos": self.repos(sandbox, projects)})
        )
        overlay = self.root / "abk.local.yaml"
        overlay.unlink(missing_ok=True)
        if local is not None:
            overlay.write_text(yaml.safe_dump(local))
        return load_installation(self.root / "abk.yaml")

    def policy(
        self,
        sandbox: dict[str, Any] | None = None,
        *,
        projects: list | None = None,
        runtime: object = BareRuntime(),
        profile: object = BareProfile(),
        local: dict[str, Any] | None = None,
    ):
        installation = self.installation(sandbox, projects, local)
        self.worktree.mkdir(exist_ok=True)
        return build_policy(installation, "app", self.worktree, runtime=runtime, profile=profile)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return Scene(tmp_path)


def test_the_lists_are_taken_in_order_and_without_duplicates(scene: Scene) -> None:
    a, b, c, d, e = (str(scene.tmp / name) for name in "abcde")
    policy = scene.policy(
        {"write": [c, a], "hosts": ["h-repo", "h-both"]},
        projects=[{"path": "web", "sandbox": {"write": [d], "hosts": ["h-project", "h-both"]}}],
        runtime=StandInRuntime([a]),
        profile=StandInProfile([b]),
        local={"repos": {"app": {"sandbox": {"write": [e, a], "hosts": ["h-local"]}}}},
    )

    ours = [Path(p) for p in (a, b, c, d, e)]
    assert [p for p in policy.write if p in ours] == ours
    assert list(policy.write).count(Path(a)) == 1
    named = {"h-repo", "h-both", "h-project", "h-local"}
    assert [h for h in policy.hosts if h in named] == ["h-repo", "h-both", "h-project", "h-local"]


def test_the_policy_is_frozen_and_carries_the_lists_and_required(scene: Scene) -> None:
    policy = scene.policy({"hosts": ["pypi.org"]})

    assert "pypi.org" in policy.hosts
    assert isinstance(policy.write, tuple)
    assert isinstance(policy.read, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        policy.hosts = ()  # type: ignore[misc]


def test_required_comes_from_the_repos_configuration(scene: Scene) -> None:
    assert scene.policy({"required": "none"}).required is Coverage.NONE
    assert scene.policy({"required": "process"}).required is Coverage.PROCESS


def test_the_committed_file_is_kept_when_the_local_file_sets_the_same_keys(scene: Scene) -> None:
    """The loaded configuration has the overlay's list in place of the committed one; the policy
    still takes the committed entries first, then the local ones, once each."""
    a, e, shared = (str(scene.tmp / name) for name in ("a", "e", "shared"))
    policy = scene.policy(
        {"write": [a, shared], "hosts": ["h-committed", "h-both"]},
        local={
            "repos": {"app": {"sandbox": {"write": [e, shared], "hosts": ["h-both", "h-local"]}}}
        },
    )

    named_paths = [scene.tmp / name for name in ("a", "shared", "e")]
    assert [p for p in policy.write if p in named_paths] == named_paths
    named = {"h-committed", "h-both", "h-local"}
    assert [h for h in policy.hosts if h in named] == ["h-committed", "h-both", "h-local"]


def test_a_local_list_that_is_not_a_list_is_refused(scene: Scene) -> None:
    with pytest.raises(ConfigError):
        scene.policy(local={"repos": {"app": {"sandbox": {"write": "some/path"}}}})


def test_a_local_key_the_schema_does_not_know_is_refused(scene: Scene) -> None:
    with pytest.raises(ConfigError):
        scene.policy(local={"repos": {"app": {"sandbox": {"writes": ["x"]}}}})


def test_a_profile_and_a_runtime_without_the_member_add_nothing(scene: Scene) -> None:
    bare = scene.policy()
    with_member = scene.policy(
        runtime=StandInRuntime([str(scene.tmp / "r")]),
        profile=StandInProfile([str(scene.tmp / "p")]),
    )

    assert set(with_member.write) - set(bare.write) == {scene.tmp / "r", scene.tmp / "p"}


def test_read_lists_are_assembled_like_write_lists(scene: Scene) -> None:
    policy = scene.policy(
        {"read": [str(scene.tmp / "r1")]},
        local={"repos": {"app": {"sandbox": {"read": [str(scene.tmp / "r2")]}}}},
    )

    ours = [p for p in policy.read if p.parent == scene.tmp]
    assert ours == [scene.tmp / "r1", scene.tmp / "r2"]


def test_a_path_that_is_a_symlink_resolves_to_its_target(scene: Scene) -> None:
    target = scene.tmp / "target"
    target.mkdir()
    link = scene.tmp / "link"
    link.symlink_to(target)

    assert target in scene.policy({"write": [str(link)]}).write


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (f"{HOME_MARK}/cache", "home/cache"),
        ("out", "wt/out"),
        ("../shared", "shared"),
        ("{tmp}//doubled///dir", "doubled/dir"),
        ("{tmp}/a/../b", "b"),
    ],
)
def test_a_path_resolves_to_one_absolute_path(scene: Scene, given: str, expected: str) -> None:
    """A relative path is relative to the unit's worktree."""
    policy = scene.policy({"write": [given.format(tmp=scene.tmp)]})

    assert (scene.tmp / expected) in policy.write
    assert all(p.is_absolute() and ".." not in p.parts for p in policy.write)


@pytest.mark.parametrize(
    "grant",
    [
        "{root}/abk.yaml",
        "{root}/abk.local.yaml",
        "{root}/openspec",
        "{root}/openspec/changes",
        "{root}/openspec/specs/x",
        "{root}",
        "{parent}",
    ],
    ids=[
        "abk.yaml",
        "abk.local.yaml",
        "specs",
        "inside specs",
        "deep inside specs",
        "planning root",
        "a parent of it",
    ],
)
def test_a_grant_of_what_a_person_owns_is_refused_with_the_reason(scene: Scene, grant: str) -> None:
    given = grant.format(root=scene.root, parent=scene.root.parent)

    with pytest.raises(PolicyRefused) as caught:
        scene.policy({"write": [given]})

    assert given in str(caught.value)
    assert "planning" in str(caught.value)


def test_a_refused_grant_in_the_local_file_is_refused_too(scene: Scene) -> None:
    with pytest.raises(PolicyRefused):
        scene.policy(
            local={"repos": {"app": {"sandbox": {"write": [str(scene.root / "abk.yaml")]}}}}
        )


def test_a_linked_worktree_gets_the_git_parts_a_commit_needs_and_never_hooks_or_config(
    scene: Scene,
) -> None:
    git = scene.main / ".git"
    for part in ("objects", "refs", "logs", "hooks", "worktrees/wt1"):
        (git / part).mkdir(parents=True)
    for part in ("packed-refs", "HEAD", "FETCH_HEAD", "config"):
        (git / part).write_text("")
    (git / "worktrees/wt1/commondir").write_text("../..\n")
    scene.worktree.mkdir()
    (scene.worktree / ".git").write_text(f"gitdir: {git}/worktrees/wt1\n")

    write = set(scene.policy().write)

    for part in ("objects", "refs", "logs", "worktrees/wt1", "packed-refs", "HEAD", "FETCH_HEAD"):
        assert git / part in write
    assert not {git, git / "hooks", git / "config"} & write
