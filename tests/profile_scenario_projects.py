"""The tiny fixture project per toolchain profile that the scenario suite runs over."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.profiles.base import ToolchainProfile


class Scenario(Frozen):
    """What differs between the fixture projects: their files, and the tests each case adds."""

    files: dict[str, str]
    passing_id: str  # a test of the project that passes, and reaches `changed_file`
    new_path: str
    new_id: str
    new_failing: str  # the new test's source when it fails by an assertion
    new_passing: str  # and when it passes
    changed_file: str
    changed_source: str  # `changed_file` after a one-file change that breaks `passing_id`


class Broken(Frozen):
    """A test that always fails, written beside the project's own files."""

    path: str
    test_id: str
    source: str


class Run(Frozen):
    output: str
    returncode: int


class ScenarioProject:
    """A fixture project in a folder, run through the profile's own commands."""

    name: str
    profile: ToolchainProfile
    scenario: Scenario
    broken: Broken
    root: Path
    seed: Path

    def __init__(self, name: str, root: Path) -> None:
        raise NotImplementedError

    def write(self, files: dict[str, str]) -> None:
        raise NotImplementedError

    def run(self, command: str | list[str]) -> Run:
        raise NotImplementedError

    def full_run(self) -> tuple[list[str], Run]:
        """The project's first full-suite command and its run."""
        raise NotImplementedError

    def counts(self, output: str) -> tuple[int, int]:
        raise NotImplementedError


def scenario_names() -> list[str]:
    """The profiles that have a fixture project."""
    raise NotImplementedError
