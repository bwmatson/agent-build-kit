"""The e2e-test command asks pytest for a short failure summary, and only the python
profile knows the flags."""

from pathlib import Path

from agent_build_kit.profiles.python_uv import PROFILE
from tests.ecosystem_names import SOURCE_ROOT

# `-vv` keeps a summary message whole (below it pytest cuts it to the terminal width).
FLAGS = ("-vv", "-rfE", "--tb=short")
# Named only here and in the profile: `-vv` also spells a git listing option elsewhere.
NAMED_ONLY_IN_PROFILE = ("-rfE", "--tb=short")


def _workspace(root: Path) -> None:
    (root / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    for member in ("svc-a", "svc-b"):
        (root / member / "tests").mkdir(parents=True)
        (root / member / "pyproject.toml").write_text(f'[project]\nname = "{member}"\n')


def test_a_repo_without_members_asks_for_the_short_summary(tmp_path: Path) -> None:
    (command,) = PROFILE.e2e_commands(tmp_path, marker="local_stack")

    for flag in FLAGS:
        assert flag in command
    assert "-v" not in command


def test_every_member_asks_for_the_short_summary(tmp_path: Path) -> None:
    _workspace(tmp_path)

    commands = PROFILE.e2e_commands(tmp_path, marker="local_stack")

    assert len(commands) == 2
    for command in commands:
        for flag in FLAGS:
            assert flag in command
        assert "-v" not in command


def test_the_flags_are_named_in_the_python_profile_and_nowhere_else() -> None:
    named = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*.py")
        if any(flag in path.read_text() for flag in NAMED_ONLY_IN_PROFILE)
    }

    assert named
    assert all(name.startswith("profiles/") for name in named), named
