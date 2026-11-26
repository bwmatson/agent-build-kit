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
)
from tests.factories import git, init_repo
from tests.old_merge_rule import statements
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import ROOT, source_trees

LINE_ENTRIES = [entry for entry in ENTRIES if entry.check is None]
OFFENDING = [(entry, case) for entry in ENTRIES for case in entry.offends]
PASSING = [(entry, case) for entry in ENTRIES for case in entry.passes]
EXEMPT = [(entry, exemption) for entry in LINE_ENTRIES for exemption in entry.exemptions]
LISTED = [(entry, exemption) for entry, exemption in EXEMPT if exemption.stale]
BY_NAME = {entry.name: entry for entry in ENTRIES}
ARCHIVED = "openspec/changes/archive/2026-01-01-drop-key/proposal.md"
# Until the statement entries are folded, the old rule about who merges is read by its own matcher.
OLD_MERGE_RULE = Entry(
    name="old-merge-rule",
    reason="stands in for the statement entry, which a later group folds into the table",
    found=lambda line: bool(statements(line)),
    under=(),
    names=(),
    suffixes=frozenset({".md"}),
    specs=False,
    offends=(Case(path="docs/a.md", text="A person merges every pull request.\n"),),
)
DOCUMENT_GUARDS = [
    BY_NAME["removed-review-key-in-a-document"],
    OLD_MERGE_RULE,
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
@pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry.name)
def test_the_repository_holds_nothing_an_entry_forbids(entry: Entry, reading: Reading) -> None:
    assert reading.findings(entry) + reading.stale(entry) == [], f"{entry.name}: {entry.reason}"


@pytest.mark.parametrize(("entry", "case"), OFFENDING, ids=named(OFFENDING))
def test_an_entry_reports_its_offending_example(entry: Entry, case: Case, tmp_path: Path) -> None:
    build(tmp_path, case)

    found = Reading(tmp_path).findings(entry)

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
    build(tmp_path, case)

    assert Reading(tmp_path).findings(entry) == []


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

    for entry in ENTRIES:
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

    assert configuration_parses(many, list(ENTRIES), monkeypatch) == configuration_parses(
        few, list(ENTRIES), monkeypatch
    )


def test_the_configuration_is_parsed_once_for_every_line_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_checkout(tmp_path, config=True, files=10)

    assert configuration_parses(root, LINE_ENTRIES, monkeypatch) == 1
