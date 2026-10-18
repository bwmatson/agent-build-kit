"""The documents and skills say how the kit's tests are tagged and split and how a split is held.

The commands are spelled as the command group is, `abk e2e-test`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
SKILL_NAMES = ("abk-config", "abk-authoring", "abk-pipeline")
COMMANDS = ("hold", "release", "status")


def squashed(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def section(path: Path, heading: str) -> str:
    """The text of the first heading of `path` that matches `heading`, up to the next heading
    of the same or a higher level; "" when there is none."""
    text = path.read_text(encoding="utf-8")
    found = re.search(rf"^(#+) [^\n]*{heading}[^\n]*$", text, re.M | re.I)
    if not found:
        return ""
    rest = text[found.end() :]
    end = re.search(rf"^#{{1,{len(found.group(1))}}} ", rest, re.M)
    return " ".join((rest[: end.start()] if end else rest).split())


def command_entry(command: str) -> str:
    text = squashed(DOCS / "cli.md")
    start = text.index(f"### `abk e2e-test {command}")
    return text[start : text.index("### ", start + 4)]


@pytest.mark.parametrize("command", COMMANDS)
def test_the_command_document_has_an_entry_for_each_command(command: str) -> None:
    assert command_entry(command).strip()


@pytest.mark.parametrize("command", ["hold", "release"])
def test_the_command_document_gives_the_refusals_of_a_command_that_writes(command: str) -> None:
    assert re.search(r"refus", command_entry(command), re.I)


def test_the_command_document_says_a_deadline_argument_is_unknown() -> None:
    assert re.search(r"--until", command_entry("hold"))


def test_the_runtimes_document_names_the_kits_drift_test_and_its_table_of_reasons() -> None:
    text = squashed(DOCS / "agent-runtimes.md")

    assert re.search(r"drift test", text, re.I)
    assert re.search(r"table of reasons", text, re.I)


def test_the_runtimes_document_describes_parking_and_scheduled_changes_per_split() -> None:
    text = section(DOCS / "agent-runtimes.md", "splits")

    assert re.search(r"park", text, re.I)
    assert re.search(r"scheduled", text, re.I)


def test_the_runtimes_document_has_a_section_on_holding_a_split() -> None:
    held = section(DOCS / "agent-runtimes.md", r"hold(ing)? a split")

    assert held
    for command in COMMANDS:
        assert f"abk e2e-test {command}" in held
    assert re.search(r"no deadline", held)
    assert re.search(r"configuration[^.]*wins", held)


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_each_skill_names_the_hold_release_and_status_commands(skill: str) -> None:
    text = squashed(SKILLS / skill / "SKILL.md")

    assert [c for c in COMMANDS if f"abk e2e-test {c}" not in text] == []
