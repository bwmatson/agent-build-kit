"""This repo is a framework and never names an installation, and holds nothing else it forbids.

`tests/exclusions.py` is the table: what is forbidden, where it is looked for, what is exempt and
why. One integration test runs every entry over this checkout through one shared read; the unit
tests run each entry's own examples over a temporary tree.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

from tests.exclusions import ENTRIES, Case, Entry, Exemption, Reading, build
from tests.factories import git, init_repo
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import ROOT

LINE_ENTRIES = [entry for entry in ENTRIES if entry.check is None]
OFFENDING = [(entry, case) for entry in ENTRIES for case in entry.offends]
PASSING = [(entry, case) for entry in ENTRIES for case in entry.passes]
EXEMPT = [(entry, exemption) for entry in LINE_ENTRIES for exemption in entry.exemptions]


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
    assert reading.findings(entry) == [], f"{entry.name}: {entry.reason}"


@pytest.mark.parametrize(("entry", "case"), OFFENDING, ids=named(OFFENDING))
def test_an_entry_reports_its_offending_example(entry: Entry, case: Case, tmp_path: Path) -> None:
    build(tmp_path, case)

    found = Reading(tmp_path).findings(entry)

    assert found, entry.name
    if case.line is not None:
        assert any(line.startswith(f"{case.path}:{case.line}:") for line in found)
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

    found = {entry.name: reading.findings(entry) for entry in ENTRIES}

    skill = "src/agent_build_kit/skills/x/SKILL.md"
    assert [line.split(":")[0] for line in found["home-path"]] == ["docs/guide.md", skill]
    assert [line.split(":")[0] for line in found["shipped-text-names-a-tilde-path"]] == [skill]
    assert root / skill in reads
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
