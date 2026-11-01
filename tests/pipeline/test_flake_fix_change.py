"""One change, written by the regression agent, fixes a flaky test, and every unit that meets the
flake waits on it (spec: flaky-tests, regression-agent).

The planning repo is a folder under the test's temporary path; the agent is the stand-in every
test gets (`tests/regression_agent_fakes.py`), which writes a complete change. What the agent
writes is tested in `test_regression_agent_change.py`.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import file_lock as file_lock_module
from agent_build_kit.pipeline.flakes import Flake, flake_change_name
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.work_graph import group_needs
from tests.factories import stored_unit
from tests.regression_agent_fakes import waited_on as wait_on_fix

TEST = "tests/test_widget.py::test_renders_the_label"
OUTPUT = "FAILED tests/test_widget.py::test_renders_the_label - assert 'a' == 'b'\n"
TASKS = (
    "# Tasks\n\n## 1. [app] [unit-test] Do the work\n\n"
    "- [ ] 1.1 Test: it works\n- [ ] 1.2 Make it work\n"
)


def flaked(
    test: str = TEST,
    unit: str = "feature/1",
    *,
    output: str = OUTPUT,
    change: str = "",
    directory: str = "",
) -> Flake:
    return Flake(
        test=test,
        unit=unit,
        command="uv run pytest -n auto -q",
        output=output,
        at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
        change=change,
        directory=directory,
    )


def code_repo(inst: Installation) -> None:
    """The `app` checkout: the flaky test, which imports `app.widget`, and that module."""
    checkout = inst.checkouts["app"]
    (checkout / "tests").mkdir(parents=True)
    (checkout / "tests" / "test_widget.py").write_text(
        "from app.widget import label\n\n\ndef test_renders_the_label():\n    assert label()\n"
    )
    (checkout / "src" / "app").mkdir(parents=True)
    (checkout / "src" / "app" / "widget.py").write_text("def label():\n    return 'a'\n")


def change_with_unit(inst: Installation, change: str, unit_id: str) -> StoredUnit:
    """A change of one group, built by one unit of the `app` repo."""
    path = inst.changes_dir / change / "tasks.md"
    path.parent.mkdir(parents=True)
    path.write_text(TASKS)
    return stored_unit(unit_id, change=change, groups=(1,))


def changes(inst: Installation) -> set[str]:
    return {p.name for p in inst.changes_dir.iterdir() if p.is_dir() and p.name != "archive"}


def waits_on(inst: Installation, change: str) -> list[str]:
    """The changes a change's group 1 has `Needs:` lines on, each unqualified."""
    needs = group_needs(inst.changes_dir / change / "tasks.md").get(1, [])
    assert all(not need.merged and need.group == 1 for need in needs)
    return [need.change for need in needs]


# --- the change ----------------------------------------------------------------------


def test_the_change_is_named_from_the_tests_identifier() -> None:
    name = flake_change_name(TEST)

    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
    assert "test-renders-the-label" in name
    assert flake_change_name(TEST) == name, "the same test, the same name"
    assert flake_change_name("tests/test_widget.py::test_other") != name


def test_the_agent_writes_the_change_a_flake_waits_on(installation: Installation) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")

    name = str(wait_on_fix(installation, flaked(), unit))

    assert name == flake_change_name(TEST)
    root = installation.changes_dir / name
    assert {"proposal.md", "design.md", "tasks.md"} <= {p.name for p in root.iterdir()}


# --- who waits ---------------------------------------------------------------------


def test_the_unit_that_met_the_flake_gains_a_needs_line_on_the_change(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")

    name = wait_on_fix(installation, flaked(), unit)

    assert waits_on(installation, "feature") == [name]
    needs = group_needs(installation.changes_dir / "feature" / "tasks.md")[1]
    assert TEST in needs[0].reason, "the reason says which test"


def test_a_unit_met_twice_has_one_needs_line(installation: Installation) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")

    wait_on_fix(installation, flaked(), unit)
    wait_on_fix(installation, flaked(), unit)

    assert len(waits_on(installation, "feature")) == 1


def test_two_units_meeting_the_same_flake_write_one_change_and_two_needs_lines(
    installation: Installation,
) -> None:
    code_repo(installation)
    units = [
        change_with_unit(installation, "feature", "feature/1"),
        change_with_unit(installation, "other", "other/1"),
    ]
    meeting = threading.Barrier(len(units))
    named: list[str | None] = []

    def meet(unit: StoredUnit) -> None:
        meeting.wait()
        named.append(wait_on_fix(installation, flaked(unit=unit.id), unit))

    workers = [threading.Thread(target=meet, args=(unit,)) for unit in units]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    fix = flake_change_name(TEST)
    assert named == [fix, fix]
    assert changes(installation) == {"feature", "other", fix}, "one change, not two"
    assert waits_on(installation, "feature") == [fix]
    assert waits_on(installation, "other") == [fix]


def test_a_later_unit_gains_the_line_and_writes_nothing(installation: Installation) -> None:
    code_repo(installation)
    first = change_with_unit(installation, "feature", "feature/1")
    later = change_with_unit(installation, "other", "other/1")
    fix = str(wait_on_fix(installation, flaked(), first))
    written = (installation.changes_dir / fix / "proposal.md").read_text()

    assert wait_on_fix(installation, flaked(unit="other/1"), later) == fix

    assert changes(installation) == {"feature", "other", fix}
    assert waits_on(installation, "other") == [fix]
    assert (installation.changes_dir / fix / "proposal.md").read_text() == written


def test_another_flaky_test_is_another_change(installation: Installation) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    other = "tests/test_widget.py::test_something_else"

    first = wait_on_fix(installation, flaked(), unit)
    second = wait_on_fix(installation, flaked(other), unit)

    assert first != second
    assert sorted(waits_on(installation, "feature")) == sorted([str(first), str(second)])


def test_once_the_fix_is_merged_and_archived_a_flake_writes_a_successor(
    installation: Installation,
) -> None:
    code_repo(installation)
    first = change_with_unit(installation, "feature", "feature/1")
    later = change_with_unit(installation, "other", "other/1")
    fix = str(wait_on_fix(installation, flaked(), first))
    archive = installation.changes_dir / "archive"
    archive.mkdir()
    (installation.changes_dir / fix).rename(archive / f"2026-03-02-{fix}")

    successor = wait_on_fix(installation, flaked(unit="other/1"), later)

    assert successor and successor != fix
    assert "test-renders-the-label" in successor, "named from the same test"
    assert waits_on(installation, "other") == [successor]


def test_a_unit_still_waiting_when_the_successor_is_written_waits_on_it(
    installation: Installation,
) -> None:
    code_repo(installation)
    waiting = change_with_unit(installation, "feature", "feature/1")
    fix = str(wait_on_fix(installation, flaked(), waiting))
    archive = installation.changes_dir / "archive"
    archive.mkdir()
    (installation.changes_dir / fix).rename(archive / f"2026-03-02-{fix}")

    successor = wait_on_fix(installation, flaked(), waiting)

    assert successor and successor != fix
    assert successor in waits_on(installation, "feature")


def test_a_unit_of_the_fix_change_does_not_wait_on_itself(installation: Installation) -> None:
    code_repo(installation)
    first = change_with_unit(installation, "feature", "feature/1")
    fix = str(wait_on_fix(installation, flaked(), first))
    own = stored_unit(f"{fix}/1", change=fix, groups=(1,))
    before = (installation.changes_dir / fix / "tasks.md").read_text()

    assert wait_on_fix(installation, flaked(unit=own.id), own) is None

    assert (installation.changes_dir / fix / "tasks.md").read_text() == before
    assert changes(installation) == {"feature", fix}


def test_the_needs_line_links_the_unit_to_the_fix_changes_unit_through_the_existing_link(
    installation: Installation,
) -> None:
    code_repo(installation)
    waiting = change_with_unit(installation, "feature", "feature/1")
    fix = str(wait_on_fix(installation, flaked(), waiting))
    store = UnitStore(installation.root / "units.json")
    store.upsert([waiting, stored_unit(f"{fix}/1", change=fix, groups=(1,))])

    cli.link_needs(installation, store=store)

    stored = store.get("feature/1")
    assert stored.depends_on == (f"{fix}/1",)


def test_the_needs_line_is_added_under_the_lock_that_ticking_boxes_takes(
    installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    held: list[Path] = []
    real = file_lock_module.file_lock

    @contextmanager
    def spy(path: Path) -> Iterator[None]:
        with real(path):
            held.append(path)
            yield

    monkeypatch.setattr(file_lock_module, "file_lock", spy)

    wait_on_fix(installation, flaked(), unit)

    assert installation.local_dir / "locks" / "changes" / "feature" / "tasks.md.lock" in held
