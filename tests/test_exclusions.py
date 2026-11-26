"""This repo is a framework and never names an installation, and holds nothing else it forbids.

`tests/exclusions.py` is the table: what is forbidden, where it is looked for, what is exempt and
why. One integration test runs every entry over this checkout through one shared read; the unit
tests run each entry's own examples over a temporary tree.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from tests.exclusions import (
    ALLOWLIST,
    E2E_CLASSES,
    E2E_MODULES,
    ENTRIES,
    OWN_TOOLING,
    Case,
    Entry,
    Exemption,
    Reading,
    build,
    text_findings,
)
from tests.factories import git, init_repo
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import ROOT, source_trees

FILE_ENTRIES = [entry for entry in ENTRIES if entry.texts is None]
TEXT_ENTRIES = [entry for entry in ENTRIES if entry.texts is not None]
LINE_ENTRIES = [entry for entry in FILE_ENTRIES if entry.check is None]
OFFENDING = [(entry, case) for entry in ENTRIES for case in entry.offends]
PASSING = [(entry, case) for entry in ENTRIES for case in entry.passes]
EXEMPT = [(entry, exemption) for entry in LINE_ENTRIES for exemption in entry.exemptions]
LISTED = [(entry, exemption) for entry, exemption in EXEMPT if exemption.stale]
BY_NAME = {entry.name: entry for entry in ENTRIES}
ARCHIVED = "openspec/changes/archive/2026-01-01-drop-key/proposal.md"
DOCUMENT_GUARDS = [
    BY_NAME["removed-review-key-in-a-document"],
    BY_NAME["old-merge-rule-in-a-markdown-file"],
    BY_NAME["old-live-test-module-name"],
]


def named(pairs: list[tuple[Entry, Case]] | list[tuple[Entry, Exemption]]) -> list[str]:
    """One test id for each example of the table, numbered so that two on one path differ."""
    return [
        f"{entry.name}:{example.path}:{number}" for number, (entry, example) in enumerate(pairs)
    ]


@pytest.fixture(scope="module")
def reading() -> Reading:
    """The files the entries read, listed and read once for every entry of the module."""
    return Reading(ROOT)


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
@pytest.mark.parametrize("entry", FILE_ENTRIES, ids=lambda entry: entry.name)
def test_the_repository_holds_nothing_an_entry_forbids(entry: Entry, reading: Reading) -> None:
    assert reading.findings(entry) + reading.stale(entry) == [], f"{entry.name}: {entry.reason}"


@pytest.mark.parametrize("entry", TEXT_ENTRIES, ids=lambda entry: entry.name)
def test_the_product_returns_no_text_an_entry_forbids(entry: Entry) -> None:
    assert entry.texts is not None
    assert text_findings(entry, entry.texts()) == [], f"{entry.name}: {entry.reason}"


def found_in(entry: Entry, case: Case, root: Path) -> list[str]:
    """What the entry finds in the example: in the text it holds for a text entry, in the tree the
    example is written into for any other."""
    if entry.texts is not None:
        return text_findings(entry, {case.path: case.text})
    build(root, case)
    return Reading(root).findings(entry)


@pytest.mark.parametrize(("entry", "case"), OFFENDING, ids=named(OFFENDING))
def test_an_entry_reports_its_offending_example(entry: Entry, case: Case, tmp_path: Path) -> None:
    found = found_in(entry, case, tmp_path)

    assert found, entry.name
    if case.line is not None:
        on_lines = [line for line in found if re.match(rf"{re.escape(case.path)}:\d+:", line)]
        assert len(on_lines) == 1
        assert on_lines[0].startswith(f"{case.path}:{case.line}:")
    for text in case.in_report:
        assert any(text in line for line in found)
    for text in case.not_in_report:
        assert not any(text in line for line in found)


@pytest.mark.parametrize(("entry", "case"), PASSING, ids=named(PASSING))
def test_an_entry_passes_its_allowed_example(entry: Entry, case: Case, tmp_path: Path) -> None:
    assert found_in(entry, case, tmp_path) == []


@pytest.mark.parametrize(("entry", "exemption"), EXEMPT, ids=named(EXEMPT))
def test_an_entry_passes_what_its_exemption_covers(
    entry: Entry, exemption: Exemption, tmp_path: Path
) -> None:
    build(tmp_path, Case(path=exemption.path, text=entry.offends[0].text))
    reading = Reading(tmp_path)

    assert tmp_path / exemption.path in reading.files(entry)
    assert reading.findings(entry) == []


@pytest.mark.parametrize(("entry", "exemption"), LISTED, ids=named(LISTED))
def test_a_listing_that_covers_a_hit_is_not_stale(
    entry: Entry, exemption: Exemption, tmp_path: Path
) -> None:
    build(tmp_path, Case(path=exemption.path, text=entry.offends[0].text))

    assert not [line for line in Reading(tmp_path).stale(entry) if exemption.path in line]


@pytest.mark.parametrize("present", [True, False], ids=["a file with no name left", "no file"])
@pytest.mark.parametrize(("entry", "exemption"), LISTED, ids=named(LISTED))
def test_a_listing_that_covers_no_hit_is_reported_as_stale(
    entry: Entry, exemption: Exemption, present: bool, tmp_path: Path
) -> None:
    if present:
        build(tmp_path, Case(path=exemption.path, text="x = 1\n"))

    assert [line for line in Reading(tmp_path).stale(entry) if exemption.path in line]


def test_the_ecosystem_allowlist_only_shrinks() -> None:
    assert set(ALLOWLIST) <= {"cli/doctor.py", "tracks/runner.py"}


def test_the_ecosystem_own_tooling_list_is_fixed_and_each_listing_has_a_reason() -> None:
    assert set(OWN_TOOLING) <= {
        "openspec.py",
        "serve/server.py",
        "settings.py",
        "config.py",
        "timers.py",
    }
    assert all(reason.strip() for reason in [*ALLOWLIST.values(), *OWN_TOOLING.values()])


@pytest.mark.parametrize(
    "relative",
    [*E2E_MODULES, *(module for module, _ in E2E_CLASSES)],
)
def test_each_module_the_e2e_entry_reads_exists_in_a_source_tree(relative: str) -> None:
    assert any((tree / relative).is_file() for tree in source_trees()), relative


@pytest.mark.parametrize("entry", DOCUMENT_GUARDS, ids=lambda entry: entry.name)
def test_a_document_guard_skips_an_archived_change_and_still_reads_docs(
    entry: Entry, tmp_path: Path
) -> None:
    text = entry.offends[0].text
    build(tmp_path, Case(path=ARCHIVED, text=text))
    build(tmp_path, Case(path="docs/a.md", text=text))

    found = Reading(tmp_path).findings(entry)

    assert [line.split(":")[0] for line in found] == ["docs/a.md"]


def a_checkout(root: Path, *, config: bool = False, files: int = 6) -> Path:
    init_repo(root)
    if config:
        (root / "abk.yaml").write_text("planning:\n  specs_dir: openspec/specs\n")
    for number in range(files):
        build(root, Case(path=f"src/module_{number}.py", text=f"x = {number}\n"))
    build(root, Case(path="docs/guide.md", text="see /home/someone/work for the checkout\n"))
    build(root, Case(path="src/agent_build_kit/skills/x/SKILL.md", text="in ~/work\n"))
    build(root, Case(path="openspec/specs/x/spec.md", text="path: ~/work/app\n"))
    git(root, "add", "-A")
    git(root, "commit", "-qm", "files")
    return root


def test_every_entry_shares_one_read_of_each_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_checkout(tmp_path)
    reads: Counter[Path] = Counter()
    real = Path.read_text

    def counting(self: Path, *args, **kwargs):
        if root in self.parents and self.name != "abk.yaml":
            reads[self] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    reading = Reading(root)

    for entry in FILE_ENTRIES:
        reading.findings(entry)

    assert root / "src/agent_build_kit/skills/x/SKILL.md" in reads
    assert set(reads.values()) == {1}


def configuration_parses(root: Path, entries: list[Entry], monkeypatch: pytest.MonkeyPatch) -> int:
    parses = 0
    real = yaml.safe_load

    def counting(stream):
        nonlocal parses
        parses += 1
        return real(stream)

    monkeypatch.setattr(yaml, "safe_load", counting)
    reading = Reading(root)
    for entry in entries:
        assert isinstance(reading.findings(entry), list)
    return parses


def test_the_configuration_is_parsed_no_more_often_for_more_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    few = a_checkout(tmp_path / "few", config=True, files=2)
    many = a_checkout(tmp_path / "many", config=True, files=40)

    assert configuration_parses(many, FILE_ENTRIES, monkeypatch) == configuration_parses(
        few, FILE_ENTRIES, monkeypatch
    )


def test_the_configuration_is_parsed_once_for_every_line_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_checkout(tmp_path, config=True, files=10)

    assert configuration_parses(root, LINE_ENTRIES, monkeypatch) == 1
