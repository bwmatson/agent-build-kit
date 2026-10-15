"""The node-npm profile reads npm workspace members from the manifest
(spec: node-npm-workspaces)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.node_workspace import manifest, workspace


@pytest.fixture
def profile():
    return profiles.get("node-npm")


def test_a_glob_expands_to_the_directories_that_hold_a_manifest(profile, tmp_path: Path) -> None:
    manifest(tmp_path, "root", workspaces=["packages/*"])
    manifest(tmp_path / "packages" / "a", "a")
    manifest(tmp_path / "packages" / "b", "b")
    (tmp_path / "packages" / "notes").mkdir()

    assert sorted(profile.members(tmp_path)) == ["packages/a", "packages/b"]


def test_a_literal_path_is_a_member_when_it_holds_a_manifest(profile, tmp_path: Path) -> None:
    manifest(tmp_path, "root", workspaces=["./apps/web", "libs/missing"])
    manifest(tmp_path / "apps" / "web", "web")

    assert profile.members(tmp_path) == ["apps/web"]


def test_the_object_form_is_read_from_its_packages(profile, tmp_path: Path) -> None:
    manifest(tmp_path, "root", workspaces={"packages": ["libs/*"], "nohoist": ["**/x"]})
    manifest(tmp_path / "libs" / "a", "a")
    manifest(tmp_path / "apps" / "b", "b")

    assert profile.members(tmp_path) == ["libs/a"]


def test_a_single_package_has_no_members(profile, tmp_path: Path) -> None:
    manifest(tmp_path, "solo", version="1.0.0")
    manifest(tmp_path / "packages" / "a", "a")

    assert profile.members(tmp_path) == []


def test_a_path_belongs_to_the_deepest_member_holding_it(profile, tmp_path: Path) -> None:
    workspace(tmp_path, ["packages/a", "packages/a/examples/demo"])

    assert profile.member_of(tmp_path, "packages/a/src/x.ts") == "packages/a"
    assert profile.member_of(tmp_path, "packages/a/examples/demo/src/x.ts") == (
        "packages/a/examples/demo"
    )
    assert profile.member_of(tmp_path, "packages/a/examples/demo") == "packages/a/examples/demo"


def test_a_path_outside_every_member_has_none(profile, tmp_path: Path) -> None:
    workspace(tmp_path, ["packages/a"])

    assert profile.member_of(tmp_path, "package.json") is None
    assert profile.member_of(tmp_path, "packages/ab/x.ts") is None


def test_dependents_are_found_by_name_in_every_kind_of_dependency(profile, tmp_path: Path) -> None:
    workspace(tmp_path, ["packages/lib", "packages/a", "packages/b", "packages/c", "packages/d"])
    manifest(tmp_path / "packages" / "lib", "@scope/lib")
    manifest(tmp_path / "packages" / "a", "a", dependencies={"@scope/lib": "*"})
    manifest(tmp_path / "packages" / "b", "b", devDependencies={"@scope/lib": "^1"})
    manifest(tmp_path / "packages" / "c", "c", peerDependencies={"@scope/lib": ">=1"})
    manifest(tmp_path / "packages" / "d", "d", dependencies={"lib": "*", "other": "1"})

    found = profile.dependents(tmp_path, "packages/lib")

    assert sorted(found) == ["packages/a", "packages/b", "packages/c"]
