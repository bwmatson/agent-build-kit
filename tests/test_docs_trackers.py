"""`docs/trackers.md` and the turn-on runbook name only real commands, options and keys, give
the steps in order and state the rules (spec: tracker-rollout)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agent_build_kit.trackers.config import TrackerConfigError, section_for
from tests.docs_commands import OPTION, command_texts, subcommand_parsers
from tests.trackers.tracker_section_support import configure

ROOT = Path(__file__).resolve().parent.parent
TRACKERS = ROOT / "docs" / "trackers.md"
RUNBOOK = ROOT / "docs" / "runbooks" / "turn-on-a-tracker.md"
DOCUMENTS = (TRACKERS, RUNBOOK)
COMMAND = re.compile(r"abk tracker ([a-z][a-z-]*)")
PROVIDERS = ("azure_devops", "github")


def text_of(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(ROOT)} is missing"
    return path.read_text()


def flat(path: Path) -> str:
    """The document lower-cased with its whitespace collapsed, so a phrase can wrap lines."""
    return " ".join(text_of(path).lower().split())


def tracker_sections(text: str) -> list[dict]:
    """Each `tracker:` mapping the document shows in a yaml block."""
    sections: list[dict] = []
    for block in re.findall(r"```ya?ml\n(.*?)```", text, flags=re.DOTALL):
        loaded = yaml.safe_load(block)
        while isinstance(loaded, dict) and "tracker" not in loaded:
            loaded = next((v for v in loaded.values() if isinstance(v, dict)), None)
        if isinstance(loaded, dict) and isinstance(loaded["tracker"], dict):
            sections.append(loaded["tracker"])
    return sections


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_every_tracker_command_and_option_a_document_names_exists(path: Path) -> None:
    parsers = subcommand_parsers("tracker")
    texts = command_texts(text_of(path), "abk tracker")
    assert texts, f"{path.name} shows no `abk tracker` command"
    for text in texts:
        match = COMMAND.search(text)
        assert match and match[1] in parsers, text
        known = {
            option for action in parsers[match[1]]._actions for option in action.option_strings
        }
        for option in OPTION.findall(text.split(match[0], 1)[1]):
            assert option in known, f"{option} is not an option of `abk tracker {match[1]}`"


def test_the_documents_name_every_tracker_command_and_the_link_epic_option() -> None:
    named = {match[1] for path in DOCUMENTS for match in COMMAND.finditer(text_of(path))}
    assert named >= set(subcommand_parsers("tracker"))
    assert "abk tracker link" in text_of(TRACKERS)
    assert "--epic" in text_of(TRACKERS)


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_every_tracker_section_a_document_shows_loads_through_the_validator(path: Path) -> None:
    sections = tracker_sections(text_of(path))
    assert sections, f"{path.name} shows no tracker section"
    for section in sections:
        configure(app=section)
        try:
            loaded = section_for("app")
        except TrackerConfigError as error:
            pytest.fail(f"{path.name} shows a section the loader refuses: {error}")
        assert loaded is not None


def test_the_trackers_document_shows_both_providers_and_the_new_keys() -> None:
    text = text_of(TRACKERS)
    kinds = {section.get("kind") for section in tracker_sections(text)}
    assert kinds >= set(PROVIDERS)
    for word in ("levels", "epic", "pr_links", "azure_devops:", "github:"):
        assert word in text, word


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_the_documents_name_no_story_type_setting_except_as_an_old_key(path: Path) -> None:
    text = text_of(path)
    for section in tracker_sections(text):
        assert "story_type" not in section
        for kind in PROVIDERS:
            assert "story_type" not in section.get(kind, {})
    for line in text.splitlines():
        if "story_type" in line:
            assert re.search(r"\b(old|legacy|still read|replaced|deprecated)\b", line, re.I), line


def test_the_runbook_names_the_four_steps_in_order() -> None:
    text = text_of(RUNBOOK)
    positions = [
        text.find("tracker:"),
        text.find("abk doctor"),
        text.find("abk tracker sync --dry-run"),
        text.lower().find("tick"),
    ]
    assert all(position >= 0 for position in positions), positions
    assert positions == sorted(positions), positions


@pytest.mark.parametrize("phrase", ("ownership", "turning it on and off"))
def test_the_trackers_document_states_the_ownership_and_on_off_sections(phrase: str) -> None:
    assert phrase in flat(TRACKERS), phrase


def test_the_trackers_document_says_removals_are_never_applied() -> None:
    assert re.search(r"removal\w* (is|are) never applied", flat(TRACKERS))


def test_the_trackers_document_says_a_board_text_edit_reaches_tasks_md() -> None:
    assert re.search(
        r"(edited|changed) only on the board.{0,120}(rewritten|written) into `?tasks\.md",
        flat(TRACKERS),
    )


def test_the_trackers_document_says_an_edit_on_both_sides_is_a_conflict() -> None:
    assert re.search(r"edited on both sides.{0,80}conflict", flat(TRACKERS))
