"""A reported product defect gets one `[unit-test]` change that reproduces it and then fixes
it, written without a model, shared by every unit that meets it (spec: e2e-group-scope)."""

from __future__ import annotations

import argparse
import re
import threading
from datetime import datetime

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.product_defect import product_defect_record
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.work_graph import old_test_kind_warnings, validate_tasks
from tests.pipeline.test_flake_fix_change import changes, waits_on
from tests.pipeline.test_untouched_failures_change import archive
from tests.product_defect_fakes import (
    FIX,
    PREFIX,
    PRODUCT,
    REPRODUCTION,
    SKETCH,
    TEST,
    defect,
    met_by,
    reporter,
)


def filed(log: list[str]) -> list[str]:
    return [line for line in log if line.startswith(("would write:", "wrote:", "exists:"))]


def test_a_report_writes_a_change_whose_one_unit_test_group_reproduces_then_fixes(
    installation: Installation,
) -> None:
    unit = met_by(installation, "feature", "feature/10", priority=2)
    hook, _ = reporter(installation, unit)

    name = hook(unit, defect())

    assert name == FIX == "fix-product-defect-tests-e2e-test-route-py-test-stream"
    root = installation.changes_dir / name
    proposal = (root / "proposal.md").read_text()
    assert TEST in proposal and REPRODUCTION in proposal and PRODUCT in proposal
    assert "feature/10" in proposal, "the unit that met it"
    assert (root / "design.md").read_text().strip()
    tasks = root / "tasks.md"
    groups, errors = validate_tasks(tasks, repos=tuple(installation.repos))
    assert errors == []
    [group] = groups
    assert (group.number, group.repo, group.tier, group.priority) == (1, "app", "unit-test", 2)
    assert "reproduce" in group.title.lower() and TEST in group.title
    assert old_test_kind_warnings(tasks) == []
    text = tasks.read_text()
    assert "Priority: 2" in text
    assert re.search(r"^Acceptance: none — .+", text, re.MULTILINE)
    first, second = re.findall(r"^- \[ \] 1\.\d+ (.*)$", text, re.MULTILINE)[:2]
    assert first.startswith("Test:"), "the reproduction comes first"
    assert not second.startswith("Test:")
    assert REPRODUCTION in text and SKETCH.splitlines()[0] in text
    assert PRODUCT in text, "named as where the builder believes the fault is"
    assert cli.cmd_tags(argparse.Namespace(all=False, change=name), installation) == 0


def test_the_spec_adds_one_requirement_that_the_test_passes_against_the_fixed_product(
    installation: Installation,
) -> None:
    unit = met_by(installation, "feature", "feature/10")
    hook, _ = reporter(installation, unit)

    name = hook(unit, defect())

    delta = next((installation.changes_dir / str(name) / "specs").rglob("spec.md")).read_text()
    assert "## ADDED Requirements" in delta
    assert TEST in delta and "SHALL" in delta and "#### Scenario:" in delta


def test_the_log_says_would_write_then_wrote_and_the_record_gains_an_entry(
    installation: Installation,
) -> None:
    log: list[str] = []
    unit = met_by(installation, "feature", "feature/10")
    hook, _ = reporter(installation, unit, log=log)

    hook(unit, defect())

    assert filed(log) == [f"would write: {FIX}", f"wrote: {FIX}"]
    [entry] = product_defect_record(installation).entries()
    assert (entry.test, entry.unit, entry.change) == (TEST, "feature/10", FIX)
    assert entry.files == [PRODUCT] and entry.reproduction == REPRODUCTION
    assert isinstance(entry.at, datetime)


def test_the_unit_that_met_the_defect_gets_a_needs_line_on_the_change(
    installation: Installation,
) -> None:
    unit = met_by(installation, "feature", "feature/10")
    hook, _ = reporter(installation, unit)

    name = hook(unit, defect())

    assert waits_on(installation, "feature") == [name]
    needs = (installation.changes_dir / "feature" / "tasks.md").read_text()
    assert f"Needs: {name} group 1 — product defect found by {TEST}" in needs


# --- one change for one defect ------------------------------------------------------


def test_a_second_report_for_the_same_test_writes_nothing_and_gives_its_unit_a_needs_line(
    installation: Installation,
) -> None:
    log: list[str] = []
    first = met_by(installation, "feature", "feature/10")
    second = met_by(installation, "other", "other/1", priority=1)
    hook, _ = reporter(installation, first, second, log=log)
    name = hook(first, defect())
    written = (installation.changes_dir / str(name) / "proposal.md").read_text()
    log.clear()

    again = hook(second, defect(reproduction="the same, seen from the other unit"))

    assert again == name
    assert filed(log) == [f"exists: {name}"]
    assert changes(installation) == {"feature", "other", str(name)}
    assert (installation.changes_dir / str(name) / "proposal.md").read_text() == written
    assert waits_on(installation, "other") == [name]
    assert [entry.unit for entry in product_defect_record(installation).entries()] == [
        "feature/10",
        "other/1",
    ]


def test_a_report_after_the_change_was_merged_and_archived_writes_a_numbered_successor(
    installation: Installation,
) -> None:
    unit = met_by(installation, "feature", "feature/10")
    hook, _ = reporter(installation, unit)
    first = str(hook(unit, defect()))
    added = next((installation.changes_dir / first / "specs").rglob("spec.md")).read_text()
    archive(installation, first)
    log: list[str] = []
    hook, _ = reporter(installation, unit, log=log)

    successor = str(hook(unit, defect()))

    assert successor != first and successor.startswith(first)
    assert filed(log)[0] == f"would write: {successor}"
    assert first in (installation.changes_dir / successor / "proposal.md").read_text()
    delta = next((installation.changes_dir / successor / "specs").rglob("spec.md")).read_text()
    header = next(line for line in added.splitlines() if line.startswith("### Requirement:"))
    assert "## ADDED Requirements" not in delta
    assert "## MODIFIED Requirements" in delta and header in delta


def test_a_name_over_the_limit_is_cut_and_ends_in_a_hash_of_the_whole_id(
    installation: Installation,
) -> None:
    long = "tests/e2e/test_" + "very_long_name_" * 10 + "x.py::test_stream"
    unit = met_by(installation, "feature", "feature/10")
    hook, _ = reporter(installation, unit)

    name = str(hook(unit, defect(test=long)))

    assert name == fix_change_name(long, PREFIX)
    assert name.startswith(f"{PREFIX}-") and len(name) <= 70
    assert re.search(r"-[0-9a-f]{8}$", name)
    assert (installation.changes_dir / name / "tasks.md").is_file()


def test_a_unit_of_the_fix_change_itself_is_given_no_needs_line(
    installation: Installation,
) -> None:
    first = met_by(installation, "feature", "feature/10")
    hook, store = reporter(installation, first)
    name = str(hook(first, defect()))
    own = StoredUnit.model_validate(
        {**first.model_dump(), "id": f"{name}/1", "change": name, "groups": (1,)}
    )
    store.upsert([first, own])

    answer = hook(own, defect())

    assert answer is None
    assert waits_on(installation, name) == []


def test_two_reports_at_once_write_one_change(installation: Installation) -> None:
    units = [
        met_by(installation, "feature", "feature/1"),
        met_by(installation, "other", "other/1"),
    ]
    hook, _ = reporter(installation, *units)
    meeting = threading.Barrier(len(units))
    named: list[str | None] = []

    def meet(unit: StoredUnit) -> None:
        meeting.wait()
        named.append(hook(unit, defect()))

    workers = [threading.Thread(target=meet, args=(unit,)) for unit in units]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert named == [FIX, FIX]
    assert changes(installation) == {"feature", "other", FIX}, "one change, not two"
