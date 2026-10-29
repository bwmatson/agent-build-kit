"""A toolchain profile names the folders and hosts its tools need under the sandbox, and the
policy assembly takes them for the repo's profile and for each project's (spec:
sandbox-profile-paths)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit import profiles
from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.profiles.base import SandboxPaths
from agent_build_kit.sandboxes.policy import build_policy, policy_entries

# The home shorthand, held apart so no line reads as a path under a home directory.
HOME_MARK = "~"


class Silent:
    """A stand-in profile that does not declare `sandbox_paths`."""


def paths_of(name: str, worktree: Path) -> SandboxPaths:
    profile = profiles.get(name)
    assert hasattr(profile, "sandbox_paths"), f"{name} declares no sandbox_paths"
    return profile.sandbox_paths(worktree)


def installation(
    tmp_path: Path, *, projects: list[dict[str, Any]] | None = None
) -> tuple[Installation, Path]:
    """A planning repo over a python-uv repo `app`, and a worktree for a step in it."""
    root = tmp_path / "plan"
    root.mkdir()
    repo = {
        "path": str(tmp_path / "main"),
        "slug": "example/app",
        "profile": "python-uv",
        "projects": projects or [],
    }
    (root / "abk.yaml").write_text(yaml.safe_dump({"repos": {"app": repo}}))
    worktree = tmp_path / "wt"
    worktree.mkdir()
    return load_installation(root / "abk.yaml"), worktree


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_the_value_is_frozen(tmp_path: Path) -> None:
    found = paths_of("python-uv", tmp_path)

    assert isinstance(found, SandboxPaths)
    with pytest.raises(ValidationError, match="frozen"):
        found.hosts = ()  # type: ignore[misc]


def test_python_uv_names_the_uv_folders_and_the_two_index_hosts(tmp_path: Path) -> None:
    found = paths_of("python-uv", tmp_path)

    assert set(found.caches) >= {f"{HOME_MARK}/.cache/uv", f"{HOME_MARK}/.local/share/uv"}
    assert set(found.hosts) == {"pypi.org", "files.pythonhosted.org"}


def test_node_npm_names_the_npm_cache_and_the_registry(tmp_path: Path) -> None:
    found = paths_of("node-npm", tmp_path)

    assert f"{HOME_MARK}/.npm" in found.write
    assert found.hosts == ("registry.npmjs.org",)


def test_a_profile_without_the_member_adds_nothing(tmp_path: Path, home: Path) -> None:
    """The policy still assembles, and the profile that has no member is the source of nothing."""
    plan, worktree = installation(tmp_path)
    bare = Silent()

    entries = policy_entries(plan, "app", worktree, runtime=bare, profile=bare)
    policy = build_policy(plan, "app", worktree, runtime=bare, profile=bare)

    assert "Silent" not in {e.source for e in entries}
    assert worktree.resolve() in policy.write


def test_the_policy_lists_a_profiles_entries_with_the_profile_as_their_source(
    tmp_path: Path, home: Path
) -> None:
    plan, worktree = installation(tmp_path)
    uv = profiles.get("python-uv")

    entries = policy_entries(plan, "app", worktree, runtime=Silent(), profile=uv)
    policy = build_policy(plan, "app", worktree, runtime=Silent(), profile=uv)

    from_profile = {(e.kind, e.value) for e in entries if e.source == "python-uv"}
    cache_entries = {(e.kind, e.value) for e in entries if e.source == "default (python-uv)"}
    assert ("write", f"{HOME_MARK}/.cache/uv") in cache_entries
    assert ("hosts", "pypi.org") in from_profile
    assert (home / ".cache" / "uv").resolve() in policy.write
    assert {"pypi.org", "files.pythonhosted.org"} <= set(policy.hosts)


def test_a_repo_with_projects_of_different_profiles_gets_both_sets(
    tmp_path: Path, home: Path
) -> None:
    plan, worktree = installation(tmp_path, projects=[{"path": "web", "profile": "node-npm"}])
    uv = profiles.get("python-uv")

    entries = policy_entries(plan, "app", worktree, runtime=Silent(), profile=uv)
    policy = build_policy(plan, "app", worktree, runtime=Silent(), profile=uv)

    assert {"python-uv", "node-npm"} <= {e.source for e in entries}
    assert (home / ".cache" / "uv").resolve() in policy.write
    assert (home / ".npm").resolve() in policy.write
    assert {"pypi.org", "registry.npmjs.org"} <= set(policy.hosts)
