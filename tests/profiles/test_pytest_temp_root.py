"""The Python profile's test environment points pytest's temp root at a folder of the
installation's `runs/tmp/pytest` named for the unit and the run (spec:
test-temp-folders-clean-up)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.installation import Installation
from agent_build_kit.profiles.python_uv import PythonUvProfile

VARIABLE = "PYTEST_DEBUG_TEMPROOT"


def environment(installation: Installation, unit: str = "add-marker/1", run: str = "run1"):
    profile = profiles.get("python-uv")
    assert isinstance(profile, PythonUvProfile)
    return profile.test_environment(installation, unit, run)


def test_the_environment_names_a_folder_under_the_pytest_temp_root(
    installation: Installation,
) -> None:
    found = environment(installation)

    folder = Path(found[VARIABLE])
    assert folder.parent == installation.state_dir / "tmp" / "pytest"


def test_the_folder_is_named_for_the_unit_and_the_run(installation: Installation) -> None:
    folder = Path(environment(installation, "add-marker/1", "run7")[VARIABLE])

    assert "add-marker" in folder.name
    assert "run7" in folder.name


def test_the_folder_exists_before_the_run(installation: Installation) -> None:
    folder = Path(environment(installation)[VARIABLE])

    assert folder.is_dir()


def test_two_runs_get_two_folders(installation: Installation) -> None:
    first = environment(installation, run="run1")[VARIABLE]
    second = environment(installation, run="run2")[VARIABLE]

    assert first != second


def test_the_environment_sets_nothing_else(installation: Installation) -> None:
    assert set(environment(installation)) == {VARIABLE}
