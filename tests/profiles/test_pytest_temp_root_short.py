"""A unit-test run's temp folder has a short path whatever its unit's id, and says which unit it
belongs to (spec: unit-test-temp-root-short-paths).

A fix unit's id carries the name of the test it fixes, 80 characters with its group. In the
unit-test step's folder that made a `tmp_path` of 227 characters: Claude's project folder for a
worktree under it (its path flattened into one name) was then 256 characters against a limit
of 255, and a progress line clipped at 160 characters kept the absolute path of the worktree.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.installation import Installation, data_home
from agent_build_kit.pipeline import spans
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation

VARIABLE = "PYTEST_DEBUG_TEMPROOT"
LONG_UNIT = "fix-test-tests-pipeline-test-branch-lock-identity-py-test-ps-10a14e69/1"
RUN = "63611807"
DEFAULT_HOME = Path("/home/benmatson/.local/share/ai-accelerators-meta-agent")


def folder_of(installation: Installation, unit: str = LONG_UNIT, run: str = RUN) -> Path:
    profile = profiles.get("python-uv")
    assert isinstance(profile, PythonUvProfile)
    return Path(profile.test_environment(installation, unit, run)[VARIABLE])


def test_the_default_root_is_a_sibling_of_the_planning_home(installation: Installation) -> None:
    home = installation.planning_home

    assert installation.pytest_temp_root == home.parent / "tmp"
    assert home.parent.parent == data_home()


def test_a_configured_planning_home_holds_the_root_under_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    configured = make_installation(tmp_path / "root", planning={"home": str(home)})

    assert configured.pytest_temp_root == home / "tmp"


def test_the_run_folder_is_named_by_the_run_token_whatever_the_unit(
    installation: Installation,
) -> None:
    folder = folder_of(installation)

    assert folder == installation.pytest_temp_root / RUN
    assert "lock-identity" not in str(folder)


def test_the_path_below_the_data_home_does_not_grow_with_the_units_id(
    installation: Installation,
) -> None:
    short = folder_of(installation, "a/1", "11111111")
    long = folder_of(installation, LONG_UNIT, "22222222")

    assert len(str(long)) == len(str(short))


def test_a_run_folder_leaves_room_for_the_longest_names_the_tests_make_under_it(
    installation: Installation,
) -> None:
    """Under the default data home, for a 9-character user name and the 11th worker, a
    `tmp_path` is at most 144 characters (the progress line needs that) and the name Claude
    makes of a worktree under it is under 255 (a file name needs that)."""
    below_data_home = folder_of(installation).relative_to(data_home()).parts[1:]
    folder = DEFAULT_HOME.joinpath(*below_data_home)
    tmp_path = folder / "pytest-of-benmatson" / "pytest-0" / "popen-gw10" / ("t" * 31)
    worktree = tmp_path / "worktrees" / "app" / "spec_feature_2"

    assert len(str(tmp_path)) <= 144
    assert len(str(worktree)) < 255


def test_the_run_file_names_the_unit_the_run_and_the_process(installation: Installation) -> None:
    token = spans.current_unit.set(("add-marker/1", "add-marker", "n1", 1))
    try:
        folder = folder_of(installation, "add-marker/1")
    finally:
        spans.current_unit.reset(token)

    record = json.loads((folder / "run.json").read_text())

    assert record["unit"] == "add-marker/1"
    assert record["run"] == RUN
    assert record["tick"] == spans.PROCESS_TICK
    assert isinstance(record["pid"], int)
    assert record["started"]
