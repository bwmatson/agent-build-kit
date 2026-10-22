"""python-uv applies its fixers through the repository's pre-commit hooks
(spec: fixers-run-before-commits)."""

from __future__ import annotations

from agent_build_kit import profiles
from agent_build_kit.profiles.base import AppliesFixers


def test_the_hooks_run_over_every_file_given() -> None:
    profile = profiles.get("python-uv")

    assert isinstance(profile, AppliesFixers)
    assert profile.fix_command(["src/a.py", "docs/x.md"]) == [
        "uv",
        "run",
        "pre-commit",
        "run",
        "--files",
        "src/a.py",
        "docs/x.md",
    ]
