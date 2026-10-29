"""The Python profile's default caches are the uv folders and the pre-commit cache, carried as
`caches` of its `sandbox_paths` (spec: sandbox-caches)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.profiles.base import SandboxPaths
from agent_build_kit.sandboxes.base import SandboxPathsProfile

# The home shorthand, held apart so no line reads as a path under a home directory.
HOME_MARK = "~"


def python_uv_paths(repo: Path) -> SandboxPaths:
    profile = profiles.get("python-uv")
    assert isinstance(profile, SandboxPathsProfile)
    found = profile.sandbox_paths(repo)
    assert isinstance(found, SandboxPaths)
    return found


def test_python_uv_carries_the_uv_and_pre_commit_folders_as_caches(tmp_path: Path) -> None:
    found = python_uv_paths(tmp_path)

    assert set(found.caches) == {
        f"{HOME_MARK}/.cache/uv",
        f"{HOME_MARK}/.local/share/uv",
        f"{HOME_MARK}/.cache/pre-commit",
    }


def test_python_uv_grants_its_caches_through_caches_alone(tmp_path: Path) -> None:
    found = python_uv_paths(tmp_path)

    assert not set(found.caches) & set(found.write)
    assert set(found.hosts) == {"pypi.org", "files.pythonhosted.org"}
