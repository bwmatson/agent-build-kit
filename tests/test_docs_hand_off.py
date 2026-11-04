"""`docs/hand-off.md` names only real commands, options and fields, and states the order
(spec: external-work)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from agent_build_kit.cli import build_parser
from agent_build_kit.cli.external_cmd import ITEM_ALIASES, ITEM_KEYS
from agent_build_kit.pipeline.external_file import Hold

DOCS = Path(__file__).resolve().parent.parent / "docs"
HAND_OFF = (DOCS / "hand-off.md").read_text() if (DOCS / "hand-off.md").is_file() else ""
COMMAND = re.compile(r"abk external ([a-z][a-z-]*)")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*")


def external_parsers() -> dict[str, argparse.ArgumentParser]:
    """The parser of each `abk external` subcommand, by name."""
    top = next(
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    external = top.choices["external"]
    found = next(
        action for action in external._actions if isinstance(action, argparse._SubParsersAction)
    )
    return dict(found.choices)


def command_texts(text: str) -> list[str]:
    """Each command the document shows: the line naming `abk external`, with the lines a
    trailing backslash continues."""
    lines = text.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if "abk external" not in line:
            continue
        joined = line
        while joined.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            joined += " " + lines[i]
        found.append(joined)
    return found


def steps(text: str) -> list[str]:
    """The numbered steps of the document, each with its continuation lines."""
    out: list[str] = []
    for line in text.splitlines():
        if re.match(r"\s*\d+\.\s", line):
            out.append(line)
        elif out and line.startswith((" ", "\t")) and line.strip():
            out[-1] += " " + line.strip()
    return out


def test_the_document_exists_and_names_the_four_commands() -> None:
    assert HAND_OFF, "docs/hand-off.md is missing"
    named = {match[1] for match in COMMAND.finditer(HAND_OFF)}
    assert named >= {"hand-off", "list", "done", "release"}


def test_every_command_and_option_the_document_names_exists() -> None:
    parsers = external_parsers()
    assert set(parsers) == {"hand-off", "list", "done", "release"}
    assert HAND_OFF, "docs/hand-off.md is missing"
    for text in command_texts(HAND_OFF):
        match = COMMAND.search(text)
        assert match and match[1] in parsers, text
        known = {
            option for action in parsers[match[1]]._actions for option in action.option_strings
        }
        for option in OPTION.findall(text.split(match[0], 1)[1]):
            assert option in known, f"{option} is not an option of `abk external {match[1]}`"


def test_every_field_the_document_shows_exists_in_the_hold_model() -> None:
    assert HAND_OFF, "docs/hand-off.md is missing"
    blocks = re.findall(r"```ya?ml\n(.*?)```", HAND_OFF, flags=re.DOTALL)
    assert blocks, "the document shows no external.yaml"
    for block in blocks:
        for hold in yaml.safe_load(block)["holds"]:
            assert set(hold) <= set(Hold.model_fields), set(hold) - set(Hold.model_fields)
            assert set(hold.get("items", {})) <= ITEM_KEYS


def test_the_hold_is_the_permanent_path_without_a_tracker() -> None:
    text = " ".join(HAND_OFF.lower().split())

    assert "interim" not in text
    assert "permanent" in text
    assert "no tracker" in text


def test_the_hold_is_recorded_before_the_spec_is_written_and_the_merge_after_the_work() -> None:
    listed = steps(HAND_OFF)
    hand_off = next(i for i, step in enumerate(listed) if "abk external hand-off" in step)
    spec = next(
        i for i, step in enumerate(listed) if "spec" in step.lower() and "hand-off" not in step
    )
    done = next(i for i, step in enumerate(listed) if "abk external done" in step)
    merged = next(
        i
        for i, step in enumerate(listed)
        if "merged" in step.lower() and "abk external done" not in step
    )

    assert hand_off < spec
    assert merged < done


def test_the_conventions_for_hand_made_board_items_are_given() -> None:
    text = HAND_OFF.lower()

    assert "<!-- abk:" in HAND_OFF
    for word in ("feature", "story", "task", "unassigned", "handoff", "--item"):
        assert word in text, word
    assert "copy" in text
    assert "group" in text


def test_the_commands_are_documented_in_the_cli_reference() -> None:
    reference = (DOCS / "cli.md").read_text()

    for name in ("hand-off", "list", "done", "release"):
        assert f"abk external {name}" in reference, name


ACCEPTED_KEYS = {*ITEM_KEYS, *ITEM_ALIASES}
SKILL = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "agent_build_kit"
    / "skills"
    / "abk-config"
    / "SKILL.md"
).read_text()
CONFIGURATION = (DOCS / "configuration.md").read_text()


def test_the_document_names_the_four_item_keys_and_no_other() -> None:
    assert ITEM_KEYS == ("change", "group", "tasks", "epic")
    named = set(re.findall(r"--item (\w+)=", HAND_OFF))
    named |= set(re.findall(r"^\s+(\w+): ", HAND_OFF.split("## The file")[1], flags=re.M))
    for key in ITEM_KEYS:
        assert f"`{key}`" in HAND_OFF or f"{key}:" in HAND_OFF, key
    assert {"change", "group", "tasks", "epic"} <= named | set(ITEM_KEYS)
    assert (named & {"feature", "story"}) == set(), "the document uses the names of the levels"


def test_every_key_the_document_passes_to_item_is_accepted() -> None:
    for key in re.findall(r"--item (\w+)=", HAND_OFF):
        assert key in ACCEPTED_KEYS, key


def test_the_board_items_made_by_hand_are_named_by_level() -> None:
    text = " ".join(HAND_OFF.split())

    assert "levels" in text
    assert "Feature per change" not in text
    assert "Story per unit" not in text


def test_the_configuration_shows_the_levels_epic_pr_links_and_provider_block() -> None:
    for word in ("levels:", "epic:", "pr_links:", "types:", "states:"):
        assert word in CONFIGURATION, word
    assert "story_type" in CONFIGURATION and "state_map" in CONFIGURATION
    assert "alias" in CONFIGURATION.lower() or "still work" in CONFIGURATION.lower()


def test_the_config_skill_says_the_same() -> None:
    for word in ("levels:", "epic: true", "pr_links", "story_type", "state_map"):
        assert word in SKILL, word
    assert "still work" in SKILL
