"""What real pytest collects for the command tier 2 builds for a member.

The command's `uv run --directory <member> --package ... --isolated` head only
chooses the directory and the environment, so it is replaced by the current
interpreter started in that directory: pytest then sees what it sees under uv.
"""

import subprocess
import sys
from pathlib import Path

from agent_build_kit.profiles.python_uv import PROFILE

MARKED_TEST = "import pytest\n\n\n@pytest.mark.local_stack\ndef test_live() -> None:\n    pass\n"
DECOY = 'raise SystemExit("optional package missing")\n'


def _member(root: Path, *, testpaths: bool, decoy: str) -> Path:
    """A one-member workspace, its marker registered, with a decoy that exits
    on import at the path `decoy` names inside the member."""
    (root / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a"]\n')
    member = root / "svc-a"
    (member / "tests").mkdir(parents=True)
    narrowing = 'testpaths = ["tests"]\n' if testpaths else ""
    (member / "pyproject.toml").write_text(
        '[project]\nname = "svc-a"\n\n[tool.pytest.ini_options]\n'
        f'markers = ["local_stack: needs the live stack"]\n{narrowing}'
    )
    (member / "tests" / "test_live.py").write_text(MARKED_TEST)
    (member / decoy).write_text(DECOY)
    return member


def _run_tier_two(root: Path) -> subprocess.CompletedProcess:
    (command,) = PROFILE.tier2_commands(root, marker="local_stack")
    directory = root / command[command.index("--directory") + 1]
    pytest_args = command[command.index("pytest") + 1 :]
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *pytest_args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_members_testpaths_keep_a_decoy_outside_them_uncollected(tmp_path: Path) -> None:
    _member(tmp_path, testpaths=True, decoy="smoke_test.py")

    result = _run_tier_two(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "1 passed" in result.stdout
    assert "smoke_test" not in result.stdout


def test_a_member_without_testpaths_collects_from_its_own_directory(tmp_path: Path) -> None:
    _member(tmp_path, testpaths=False, decoy="tests/test_smoke.py")

    result = _run_tier_two(tmp_path)

    assert result.returncode != 0
    assert "test_smoke" in result.stdout
