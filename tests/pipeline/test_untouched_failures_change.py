"""One change, written by the regression agent, fixes a pre-existing failing test, and what would
be written is previewed first (spec: e2e-failures, regression-agent).

The agent is the stand-in every test gets (`tests/regression_agent_fakes.py`).
"""

from __future__ import annotations

import re
import threading

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_name, flake_change_name
from agent_build_kit.pipeline.regression_agent import FixKind
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.untouched_failures import Exists, Write, preview
from tests.pipeline.test_flake_fix_change import (
    change_with_unit,
    changes,
    code_repo,
    flaked,
)
from tests.regression_agent_fakes import waited_on
from tests.untouched_failure_fakes import TEST, failing

OTHER = "tests/far/test_two.py::test_two"


def ensured(inst: Installation, unit: StoredUnit, test: str = TEST) -> str:
    """The change that fixes `test` for a failure of it on the base, written if there is none."""
    entry = failing(test, unit=unit.id)
    found = flaked(test, unit=unit.id, output=entry.line).model_copy(update={"failing": True})
    return str(waited_on(inst, found, unit, kind=FixKind.PRE_EXISTING, wait=False))


def test_the_change_is_named_from_the_id_with_the_fix_test_prefix(
    installation: Installation,
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")

    name = ensured(installation, unit)

    assert name == fix_change_name(TEST, "fix-test")
    assert re.fullmatch(r"fix-test-[a-z0-9-]+", name)
    assert "test-one" in name
    assert fix_change_name(TEST, "fix-test") == flake_change_name(TEST)


def test_a_long_id_is_capped_with_a_hash_of_the_whole() -> None:
    long = "tests/far/test_" + "very_long_name_" * 10 + "x.py::test_one"
    other = long[:-1] + "y"

    first = fix_change_name(long, "fix-test")
    second = fix_change_name(other, "fix-test")

    assert first.startswith("fix-test-") and len(first) <= 70
    assert first != second, "the hash tells the cut ones apart"
    assert re.search(r"-[0-9a-f]{8}$", first)


def test_an_open_flake_fix_of_the_same_test_is_the_change_found(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    flake_fix = str(waited_on(installation, flaked(TEST), unit))

    assert ensured(installation, unit) == flake_fix


# --- the preview --------------------------------------------------------------------


def test_the_preview_reads_the_directory_and_writes_nothing(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    name = fix_change_name(TEST, "fix-test")

    assert preview(installation, TEST) == Write(name=name)
    assert changes(installation) == {"feature"}
    ensured(installation, unit)
    assert preview(installation, TEST) == Exists(change=name)


def test_two_ids_are_written_independently(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    first = ensured(installation, unit)

    second = ensured(installation, unit, OTHER)

    assert second != first
    assert preview(installation, TEST) == Exists(change=first)
    assert preview(installation, OTHER) == Exists(change=second)


def test_an_open_change_is_found_and_nothing_is_written(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    name = ensured(installation, unit)
    written = (installation.changes_dir / name / "proposal.md").read_text()

    assert ensured(installation, unit) == name

    assert changes(installation) == {"feature", name}
    assert (installation.changes_dir / name / "proposal.md").read_text() == written


def test_two_calls_in_one_tick_write_one_change(installation: Installation) -> None:
    units = [
        change_with_unit(installation, "feature", "feature/1"),
        change_with_unit(installation, "other", "other/1"),
    ]
    meeting = threading.Barrier(len(units))
    named: list[str] = []

    def meet(unit: StoredUnit) -> None:
        meeting.wait()
        named.append(ensured(installation, unit))

    workers = [threading.Thread(target=meet, args=(unit,)) for unit in units]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(named) == 2 and named[0] == named[1]
    assert changes(installation) == {"feature", "other", named[0]}, "one change, not two"


# --- a successor --------------------------------------------------------------------


def archive(inst: Installation, name: str) -> None:
    folder = inst.changes_dir / "archive"
    folder.mkdir(exist_ok=True)
    (inst.changes_dir / name).rename(folder / f"2026-03-02-{name}")


def test_a_failure_after_an_archived_fix_gets_the_next_name(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    first = ensured(installation, unit)
    archive(installation, first)

    successor = ensured(installation, unit)

    assert successor != first
    assert "test-one" in successor, "named from the same test"
    assert preview(installation, TEST) == Exists(change=successor)
