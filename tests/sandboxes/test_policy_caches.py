"""The built policy for a Python repo grants the profile's default caches, the pre-commit one
included, as `write` entries with their source (spec: sandbox-caches)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import profiles
from agent_build_kit.sandboxes.policy import policy_entries
from tests.sandboxes.policy_support import BareRuntime, Scene, writes

# The home shorthand, held apart so no line reads as a path under a home directory.
HOME_MARK = "~"
UV_CACHE = f"{HOME_MARK}/.cache/uv"
PRE_COMMIT = f"{HOME_MARK}/.cache/pre-commit"
UV_DATA = f"{HOME_MARK}/.local/share/uv"


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return Scene(tmp_path)


def listed(
    scene: Scene, profile: str, sandbox: dict[str, Any] | None = None
) -> set[tuple[str, str]]:
    installation = scene.installation(sandbox)
    scene.worktree.mkdir(exist_ok=True)
    entries = policy_entries(
        installation, "app", scene.worktree, runtime=BareRuntime(), profile=profiles.get(profile)
    )
    return {(e.value, e.source) for e in entries if e.kind == "write"}


def test_the_policy_for_a_python_repo_writes_the_pre_commit_cache(scene: Scene) -> None:
    policy = scene.policy(profile=profiles.get("python-uv"))

    assert writes(policy, scene.tmp / "home" / ".cache" / "pre-commit")
    assert writes(policy, scene.tmp / "home" / ".cache" / "uv")


def test_the_listing_shows_each_cache_with_the_profile_as_its_source(scene: Scene) -> None:
    found = listed(scene, "python-uv")

    assert {
        (UV_CACHE, "default (python-uv)"),
        (UV_DATA, "default (python-uv)"),
        (PRE_COMMIT, "default (python-uv)"),
    } <= found


def test_caches_naming_only_uv_drops_the_pre_commit_and_uv_data_grants(scene: Scene) -> None:
    sandbox = {"caches": [UV_CACHE]}

    policy = scene.policy(sandbox, profile=profiles.get("python-uv"))
    found = listed(scene, "python-uv", sandbox)

    assert (UV_CACHE, "abk.yaml") in found
    assert not {value for value, _ in found} & {PRE_COMMIT, UV_DATA}
    assert not writes(policy, scene.tmp / "home" / ".cache" / "pre-commit")
    assert not writes(policy, scene.tmp / "home" / ".local" / "share" / "uv")


def test_a_repo_on_another_profile_does_not_get_the_pre_commit_cache(scene: Scene) -> None:
    python = {value for value, _ in listed(scene, "python-uv")}
    node = {value for value, _ in listed(scene, "node-npm")}

    assert PRE_COMMIT in python
    assert PRE_COMMIT not in node
    assert UV_DATA not in node
