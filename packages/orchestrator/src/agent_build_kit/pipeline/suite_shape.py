"""The shape of a repository's tests: the five figures `abk tests report` prints."""

from __future__ import annotations

from datetime import date, datetime

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen


class ShapeReport(Frozen):
    """The five figures of one repository's tests.

    A figure whose files no supporting profile read is None, and `unsupported_profile` names
    the profile that refused. `left_out` names the projects whose files were not read, as
    `<path> (<profile>)`; `unreadable` counts the files that did not parse."""

    repo: str
    # 1. Unit-test files not named `test_<module>` for a source module, of all unit-test files.
    unplaced: int | None = None
    unit_test_files: int | None = None
    # 2. Test files added in the window that are not for a source module added in it, of all.
    new_files_not_for_new_module: int | None = None
    new_files: int | None = None
    # 3. Tests added, and existing tests modified, in the window's commits.
    added: int = 0
    modified: int = 0
    # 4. Tests sharing setup and action with a sibling, tests with one assertion, of all read.
    sharing: int | None = None
    single_assertion: int | None = None
    tests_read: int | None = None
    # 5. The suite at the tip, and the median minutes of the window's whole-suite runs.
    suite_tests: int | None = None
    suite_files: int | None = None
    median_minutes: float | None = None
    full_runs: int = 0
    unsupported_profile: str | None = None
    left_out: tuple[str, ...] = ()
    unreadable: int = 0


def definition(figure: int) -> str:
    """The sentence that defines figure 1 to 5, printed with it."""
    raise NotImplementedError


def shape_report(
    installation: Installation, name: str, *, since: date, now: datetime
) -> ShapeReport:
    """The figures of the repository `name`: its default branch's tests, the commits from
    `since` to `now`, and the installation's run ledger and unit store."""
    raise NotImplementedError
