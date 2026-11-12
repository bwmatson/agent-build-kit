"""`docs/trackers.md` and the turn-on runbook name only real commands, options and keys, give
the steps in order and state the rules (spec: tracker-rollout)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import build_parser
from agent_build_kit.trackers.config import AzureDevOpsTracker, GithubTracker, TrackerSection

ROOT = Path(__file__).resolve().parent.parent
TRACKERS = ROOT / "docs" / "trackers.md"
RUNBOOK = ROOT / "docs" / "runbooks" / "turn-on-a-tracker.md"
DOCUMENTS = (TRACKERS, RUNBOOK)
COMMAND = re.compile(r"abk tracker ([a-z][a-z-]*)")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
# What a provider block holds beside its connection settings.
BLOCK_COMMON = {"types", "states"}
PROVIDERS = {"azure_devops": AzureDevOpsTracker, "github": GithubTracker}
# The old flat keys the documents may still name, as old keys.
OLD_KEYS = {"story_type", "labels", "state_map"}


def text_of(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(ROOT)} is missing"
    return path.read_text()


def tracker_parsers() -> dict[str, argparse.ArgumentParser]:
    """The parser of each `abk tracker` subcommand, by name."""
    top = next(
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    found = next(
        action
        for action in top.choices["tracker"]._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return dict(found.choices)


def command_texts(text: str) -> list[str]:
    """Each command the document shows: the line naming `abk tracker`, with the lines a
    trailing backslash continues."""
    lines = text.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if "abk tracker" not in line:
            continue
        joined = line
        while joined.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            joined += " " + lines[i]
        found.append(joined)
    return found


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
    parsers = tracker_parsers()
    texts = command_texts(text_of(path))
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
    assert named >= set(tracker_parsers())
    assert "abk tracker link" in text_of(TRACKERS)
    assert "--epic" in text_of(TRACKERS)


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_every_configuration_key_a_document_shows_exists_in_the_models(path: Path) -> None:
    sections = tracker_sections(text_of(path))
    assert sections, f"{path.name} shows no tracker section"
    top = set(TrackerSection.model_fields) | set(PROVIDERS) | OLD_KEYS
    for section in sections:
        assert set(section) <= top, set(section) - top
        for kind, model in PROVIDERS.items():
            if kind not in section:
                continue
            allowed = (set(model.model_fields) - set(TrackerSection.model_fields)) | BLOCK_COMMON
            assert set(section[kind]) <= allowed | OLD_KEYS, set(section[kind]) - allowed


def test_the_trackers_document_shows_both_providers_and_the_new_keys() -> None:
    text = text_of(TRACKERS)
    kinds = {section.get("kind") for section in tracker_sections(text)}
    assert kinds >= {"azure_devops", "github"}
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


@pytest.mark.parametrize(
    "phrase",
    (
        "ownership",
        "never applied",
        "precedence",
        "turning it off",
    ),
)
def test_the_trackers_document_states_the_rules(phrase: str) -> None:
    assert phrase in " ".join(text_of(TRACKERS).lower().split()), phrase


def test_the_trackers_document_says_removals_are_never_applied() -> None:
    text = " ".join(text_of(TRACKERS).lower().split())
    assert re.search(r"removal\w* (is|are) never applied|never applies? (a )?removal", text)
