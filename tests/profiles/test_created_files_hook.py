"""What the built-in toolchain profiles say their own commands create."""

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.profiles.base import CreatedFiles
from agent_build_kit.profiles.python_uv import LOCK


def test_the_python_profile_names_its_lock_file(tmp_path: Path) -> None:
    profile = profiles.get("python-uv")
    assert isinstance(profile, CreatedFiles)
    assert profile.created_files(tmp_path) == [LOCK]
