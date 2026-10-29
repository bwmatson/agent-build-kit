"""Which cache folders a step may write: the project's list over the repo's over the toolchain's
defaults, the overlay over the committed file, each as a `write` entry with its source
(spec: sandbox-caches)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.base import SandboxPaths, ToolchainProfile
from agent_build_kit.sandboxes.policy import policy_entries
from tests.sandboxes.policy_support import BareRuntime, Scene


class CacheProfile:
    """A toolchain whose defaults are `caches`."""

    def __init__(self, name: str, caches: tuple[str, ...]) -> None:
        self.name = name
        self.caches = caches

    def sandbox_paths(self, repo: Path) -> SandboxPaths:
        return SandboxPaths.model_validate({"caches": self.caches})


ONE = CacheProfile("caches-one", ("~/.cache/one",))
TWO = CacheProfile("caches-two", ("~/.cache/two-a", "~/.cache/two-b"))


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Scene]:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with (
        profiles.registered(cast(ToolchainProfile, ONE)),
        profiles.registered(cast(ToolchainProfile, TWO)),
    ):
        yield Scene(tmp_path)


def caches(
    scene: Scene,
    sandbox: dict[str, Any] | None = None,
    projects: list[dict[str, Any]] | None = None,
    local: dict[str, Any] | None = None,
) -> set[tuple[str, str]]:
    """The cache entries (value, source) of the policy; every write entry here is one."""
    installation = scene.installation(sandbox, projects, local)
    scene.worktree.mkdir(exist_ok=True)
    entries = policy_entries(
        installation, "app", scene.worktree, runtime=BareRuntime(), profile=ONE
    )
    return {(e.value, e.source) for e in entries if e.kind == "write"}


def test_a_repo_with_no_setting_gets_the_profiles_defaults(scene: Scene) -> None:
    assert caches(scene) == {("~/.cache/one", "default (caches-one)")}


def test_the_repos_list_replaces_the_profiles_defaults(scene: Scene) -> None:
    given = caches(scene, {"caches": ["~/.cache/mine"]})

    assert given == {("~/.cache/mine", "abk.yaml")}


def test_an_empty_list_grants_no_cache(scene: Scene) -> None:
    assert caches(scene, {"caches": []}) == set()


def test_a_projects_list_beats_the_repos(scene: Scene) -> None:
    projects = [{"path": "web", "profile": "caches-one", "sandbox": {"caches": ["~/.cache/web"]}}]

    given = caches(scene, {"caches": ["~/.cache/repo"]}, projects)

    assert given == {("~/.cache/web", "abk.yaml")}


def test_a_project_without_a_list_takes_the_repos(scene: Scene) -> None:
    projects = [
        {"path": "web", "profile": "caches-one", "sandbox": {"caches": ["~/.cache/web"]}},
        {"path": "api", "profile": "caches-two"},
    ]

    given = caches(scene, {"caches": ["~/.cache/repo"]}, projects)

    assert given == {("~/.cache/web", "abk.yaml"), ("~/.cache/repo", "abk.yaml")}


def test_projects_on_two_profiles_each_get_their_own_defaults(scene: Scene) -> None:
    projects = [
        {"path": "web", "profile": "caches-one"},
        {"path": "api", "profile": "caches-two"},
    ]

    given = caches(scene, projects=projects)

    assert given == {
        ("~/.cache/one", "default (caches-one)"),
        ("~/.cache/two-a", "default (caches-two)"),
        ("~/.cache/two-b", "default (caches-two)"),
    }


def test_the_repos_own_profile_counts_beside_its_projects_profiles(scene: Scene) -> None:
    projects = [{"path": "web", "profile": "caches-two"}]

    given = caches(scene, projects=projects)

    assert given == {
        ("~/.cache/one", "default (caches-one)"),
        ("~/.cache/two-a", "default (caches-two)"),
        ("~/.cache/two-b", "default (caches-two)"),
    }


def test_the_overlay_replaces_the_committed_list_at_the_same_level(scene: Scene) -> None:
    local = {"repos": {"app": {"sandbox": {"caches": ["~/.cache/local"]}}}}

    given = caches(scene, {"caches": ["~/.cache/committed"]}, local=local)

    assert given == {("~/.cache/local", "abk.local.yaml")}


def test_an_overlay_empty_list_replaces_the_committed_list(scene: Scene) -> None:
    local = {"repos": {"app": {"sandbox": {"caches": []}}}}

    assert caches(scene, {"caches": ["~/.cache/committed"]}, local=local) == set()


def test_a_project_overlay_list_replaces_the_projects_committed_list(scene: Scene) -> None:
    projects = [{"path": "web", "profile": "caches-one", "sandbox": {"caches": ["~/.cache/a"]}}]
    web = {"path": "web", "profile": "caches-one", "sandbox": {"caches": ["~/.cache/b"]}}
    local = {"repos": {"app": {"projects": [web]}}}

    given = caches(scene, projects=projects, local=local)

    # The repo sets no list, so its own profile's defaults count beside the project's list.
    assert given == {("~/.cache/b", "abk.local.yaml"), ("~/.cache/one", "default (caches-one)")}
