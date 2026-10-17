"""The e2e-test command asks pytest for every duration worth reading, and only the python
profile knows the flags (spec: e2e-time-is-recorded-per-test)."""

from pathlib import Path

from agent_build_kit.profiles.python_uv import PROFILE
from tests.ecosystem_names import SOURCE_ROOT

FLAGS = ("--durations=0", "--durations-min=1.0")


def _workspace(root: Path) -> None:
    (root / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    for member in ("svc-a", "svc-b"):
        (root / member / "tests").mkdir(parents=True)
        (root / member / "pyproject.toml").write_text(f'[project]\nname = "{member}"\n')


def test_a_repo_without_members_asks_for_every_duration(tmp_path: Path) -> None:
    (command,) = PROFILE.e2e_commands(tmp_path, marker="local_stack")

    for flag in FLAGS:
        assert flag in command


def test_every_member_asks_for_every_duration(tmp_path: Path) -> None:
    _workspace(tmp_path)

    commands = PROFILE.e2e_commands(tmp_path, marker="local_stack")

    assert len(commands) == 2
    for command in commands:
        for flag in FLAGS:
            assert flag in command


def test_the_flag_is_named_in_the_python_profile_and_nowhere_else() -> None:
    named = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*.py")
        if "--durations" in path.read_text()
    }

    assert named
    assert all(name.startswith("profiles/") for name in named), named
