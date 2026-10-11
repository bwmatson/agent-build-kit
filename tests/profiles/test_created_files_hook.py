"""What the built-in toolchain profiles say their own commands create."""

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.profiles.python_uv import LOCK


def test_the_python_profile_names_its_lock_file(tmp_path: Path) -> None:
    assert profiles.get("python-uv").created_files(tmp_path) == [LOCK]  # type: ignore[attr-defined]


def test_the_node_profile_names_none(tmp_path: Path) -> None:
    assert profiles.get("node-npm").created_files(tmp_path) == []  # type: ignore[attr-defined]
