"""A recording of an external tool goes stale when the tool's major version moves on.

Each fixture under `tests/fixtures/external/` names the version it was recorded
from. When the installed tool is a major version ahead, the recording no longer
shows what the tool does, and this fails with the command that re-records it.
"""

import re
import shutil
import subprocess
from pathlib import Path

import acp
import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "external"

PYTEST_HEADER = re.compile(r"<!-- tool: pytest (\d+)\.")
CLAUDE_HEADER = re.compile(r"# tool: claude_code_version (\d+)\.")
GIT_HEADER = re.compile(r"# tool: git version (\d+)\.")
ACP_README = re.compile(r"ACP protocol version (\d+)")


def recorded_majors(folder: str, pattern: re.Pattern[str], suffix: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted((FIXTURES / folder).glob(f"*{suffix}")):
        match = pattern.match(path.read_text())
        assert match, f"{path.name} has no tool version in its header"
        found[path.name] = int(match.group(1))
    assert found, f"no fixtures under {folder}"
    return found


def installed_major(command: list[str], pattern: str) -> int | None:
    if shutil.which(command[0]) is None:
        return None
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    match = re.search(pattern, done.stdout + done.stderr)
    return int(match.group(1)) if match else None


def assert_not_behind(folder: str, recorded: dict[str, int], installed: int, rerecord: str) -> None:
    behind = {name: major for name, major in recorded.items() if major < installed}
    assert not behind, (
        f"{folder} fixtures {sorted(behind)} were recorded from major version "
        f"{sorted(set(behind.values()))}, the installed tool is {installed}; "
        f"re-record with: {rerecord}"
    )


def test_the_pytest_recordings_are_not_a_major_version_behind() -> None:
    recorded = recorded_majors("pytest", PYTEST_HEADER, ".xml")

    assert_not_behind(
        "pytest",
        recorded,
        int(pytest.__version__.split(".")[0]),
        "uv run python tests/fixtures/external/record_pytest.py",
    )


def test_every_claude_recording_names_the_cli_version_it_came_from() -> None:
    """Whether the installed CLI is a major version ahead is not checked here: the
    suite refuses to start `claude`, even for `--version`."""
    assert recorded_majors("claude", CLAUDE_HEADER, ".txt")


def test_the_git_recordings_are_not_a_major_version_behind() -> None:
    installed = installed_major(["git", "--version"], r"git version (\d+)\.")
    if installed is None:
        pytest.skip("git is not installed here")

    assert_not_behind(
        "git",
        recorded_majors("git", GIT_HEADER, ".txt"),
        installed,
        "uv run python tests/fixtures/external/record_git.py",
    )


def test_the_acp_recordings_name_the_installed_protocol_version() -> None:
    match = ACP_README.search((FIXTURES / "acp" / "README.md").read_text())
    assert match, "the acp README does not name the ACP protocol version"

    assert_not_behind(
        "acp",
        {"README.md": int(match.group(1))},
        acp.PROTOCOL_VERSION,
        "drive an agent through a denied, an allowed and a failing tool call (see the README)",
    )
