"""The node-npm profile names the files its own commands create (spec: node-npm-red-and-stubs)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.profiles.base import CreatedFiles


def listed(tmp_path: Path) -> list[str]:
    profile = profiles.get("node-npm")
    assert isinstance(profile, CreatedFiles)
    return [name.rstrip("/") for name in profile.created_files(tmp_path)]


def test_the_type_check_build_info_is_named(tmp_path: Path) -> None:
    assert any(name.endswith(".tsbuildinfo") for name in listed(tmp_path)), listed(tmp_path)


def test_the_vite_cache_directory_is_named(tmp_path: Path) -> None:
    names = listed(tmp_path)
    assert any(name.endswith("node_modules/.vite") for name in names), names


def test_the_vitest_cache_directory_is_named(tmp_path: Path) -> None:
    names = listed(tmp_path)
    assert any(name.endswith("node_modules/.vitest") for name in names), names
