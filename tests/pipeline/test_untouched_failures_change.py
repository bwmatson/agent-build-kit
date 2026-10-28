"""One change fixes a pre-existing failing test, previewed before it is written
(spec: e2e-failures)."""

from __future__ import annotations

import argparse
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import untouched_failures
from agent_build_kit.pipeline.flakes import fix_change_name, flake_change_name, wait_on_fix
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.untouched_failures import (
    Exists,
    Write,
    ensure_fix,
    preexisting_record,
    preview,
)
from agent_build_kit.pipeline.work_graph import old_test_kind_warnings, validate_tasks
from tests.pipeline.test_flake_fix_change import change_with_unit, changes, code_repo, flaked
from tests.untouched_failure_fakes import TEST, failing

OTHER = "tests/far/test_two.py::test_two"


def ensured(inst: Installation, unit: StoredUnit, test: str = TEST) -> tuple[str, list[str]]:
    said: list[str] = []
    return ensure_fix(inst, failing(test, unit=unit.id), unit, say=said.append), said


def archive(inst: Installation, name: str) -> None:
    folder = inst.changes_dir / "archive"
    folder.mkdir(exist_ok=True)
    (inst.changes_dir / name).rename(folder / f"2026-03-02-{name}")


def test_the_change_is_named_from_the_id_with_the_fix_test_prefix(
    installation: Installation,
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")

    name, _ = ensured(installation, unit)

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


def test_the_change_has_a_proposal_a_design_stub_and_one_e2e_group_tests_first(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    preexisting_record(installation).append(failing(unit="older/1"))

    name, _ = ensured(installation, unit)

    root = installation.changes_dir / name
    proposal = (root / "proposal.md").read_text()
    assert TEST in proposal
    assert "assert 1 == 2" in proposal, "its first failure line"
    assert "base" in proposal.lower()
    assert "older/1" in proposal, "the units that met it, from the record"
    design = (root / "design.md").read_text().lower()
    assert "test" in design and "code" in design and "environment" in design
    tasks = root / "tasks.md"
    groups, errors = validate_tasks(tasks, repos=tuple(installation.repos))
    assert errors == []
    assert [(g.number, g.repo, g.tier) for g in groups] == [(1, "app", "e2e-test")]
    assert old_test_kind_warnings(tasks) == []
    text = tasks.read_text()
    assert "Priority: 1" in text
    assert re.search(r"^Acceptance: none — .+", text, re.MULTILINE)
    first, second = re.findall(r"^- \[ \] 1\.\d+ (.*)$", text, re.MULTILINE)[:2]
    assert first.startswith("Test:"), "tests first"
    assert not second.startswith("Test:")
    assert TEST in text


def test_the_written_change_passes_abk_tags(installation: Installation) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    name, _ = ensured(installation, unit)

    assert cli.cmd_tags(argparse.Namespace(all=False, change=name), installation) == 0


def test_the_spec_states_the_test_passes_on_the_base(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    name, _ = ensured(installation, unit)

    delta = next((installation.changes_dir / name / "specs").rglob("spec.md")).read_text()

    assert "## ADDED Requirements" in delta
    assert TEST in delta and "SHALL" in delta and "#### Scenario:" in delta


def test_an_open_flake_fix_of_the_same_test_is_the_change_found(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    flake_fix = str(wait_on_fix(installation, flaked(TEST), unit))

    name, said = ensured(installation, unit)

    assert name == flake_fix
    assert said == [f"exists: {name}"]


# --- the preview --------------------------------------------------------------------


def test_the_ensure_step_says_would_write_before_it_writes(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    seen: list[tuple[str, bool]] = []
    name = fix_change_name(TEST, "fix-test")

    def say(line: str) -> None:
        seen.append((line, (installation.changes_dir / name).exists()))

    ensure_fix(installation, failing(unit=unit.id), unit, say=say)

    assert seen == [(f"would write: {name}", False), (f"wrote: {name}", True)]


def test_an_open_change_is_reported_as_existing_and_nothing_is_written(
    installation: Installation,
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    name, _ = ensured(installation, unit)
    written = (installation.changes_dir / name / "proposal.md").read_text()

    again, said = ensured(installation, unit)

    assert again == name
    assert said == [f"exists: {name}"]
    assert changes(installation) == {"feature", name}
    assert (installation.changes_dir / name / "proposal.md").read_text() == written


def test_the_preview_reads_the_directory_and_writes_nothing(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    name = fix_change_name(TEST, "fix-test")

    assert preview(installation, TEST) == Write(name=name)
    assert changes(installation) == {"feature"}
    ensured(installation, unit)
    assert preview(installation, TEST) == Exists(change=name)


def test_two_ids_are_previewed_and_written_independently(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    first, _ = ensured(installation, unit)

    second, said = ensured(installation, unit, OTHER)

    assert second != first
    assert said[0].startswith("would write: ")
    assert preview(installation, TEST) == Exists(change=first)
    assert preview(installation, OTHER) == Exists(change=second)


def test_two_calls_in_one_tick_write_one_change(installation: Installation) -> None:
    units = [
        change_with_unit(installation, "feature", "feature/1"),
        change_with_unit(installation, "other", "other/1"),
    ]
    meeting = threading.Barrier(len(units))
    named: list[str] = []

    def meet(unit: StoredUnit) -> None:
        meeting.wait()
        named.append(ensured(installation, unit)[0])

    workers = [threading.Thread(target=meet, args=(unit,)) for unit in units]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(named) == 2 and named[0] == named[1]
    assert changes(installation) == {"feature", "other", named[0]}, "one change, not two"


def test_the_step_takes_the_preexisting_lock(
    installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    held: list[Path] = []
    real = untouched_failures.file_lock

    @contextmanager
    def spy(path: Path) -> Iterator[None]:
        with real(path):
            held.append(path)
            yield

    monkeypatch.setattr(untouched_failures, "file_lock", spy)

    ensured(installation, unit)

    assert installation.state_dir / "preexisting.lock" in held


# --- a successor --------------------------------------------------------------------


def test_a_successor_names_the_earlier_attempt_and_restates_the_spec_once_it_is_archived(
    installation: Installation,
) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    first, _ = ensured(installation, unit)
    added = next((installation.changes_dir / first / "specs").rglob("spec.md")).read_text()
    archive(installation, first)

    successor, said = ensured(installation, unit)

    assert successor != first
    assert "test-one" in successor, "named from the same test"
    assert said[0] == f"would write: {successor}"
    assert first in (installation.changes_dir / successor / "proposal.md").read_text()
    delta = next((installation.changes_dir / successor / "specs").rglob("spec.md")).read_text()
    header = next(line for line in added.splitlines() if line.startswith("### Requirement:"))
    assert "## ADDED Requirements" not in delta
    assert "## MODIFIED Requirements" in delta and header in delta
    assert preview(installation, TEST) == Exists(change=successor)


def test_no_successor_is_written_while_the_first_is_open(installation: Installation) -> None:
    unit = change_with_unit(installation, "feature", "feature/1")
    first, _ = ensured(installation, unit)

    again, _ = ensured(installation, unit)

    assert again == first
    assert changes(installation) == {"feature", first}
