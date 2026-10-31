"""The tracker section's levels, provider blocks and the setting for pull request links."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.trackers.config import TrackerConfigError, TrackerSection, section_for
from tests.trackers.tracker_section_support import (
    AZURE_BLOCK,
    BASIC,
    GITHUB_BLOCK,
    TOKEN_SHAPED,
    configure,
)

ALL_TYPES = {"epic": "Epic", "change": "Feature", "group": "Product Backlog Item", "task": "Task"}


def accepted(raw: dict[str, Any]) -> TrackerSection:
    configure(app=raw)
    section = section_for("app")
    assert section is not None
    return section


def refused(raw: dict[str, Any]) -> str:
    """The message of the refusal; the unmodified Basic section is valid, so a refusal is
    owed to the one change a test makes to it."""
    assert accepted(BASIC).levels == ("change", "group")
    configure(app=raw)
    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")
    return str(raised.value)


def basic_with(**changes: Any) -> dict[str, Any]:
    return {**BASIC, **changes}


def basic_block(**changes: Any) -> dict[str, Any]:
    return basic_with(azure_devops={**AZURE_BLOCK, **changes})


@pytest.mark.parametrize(
    "levels",
    [
        ["change"],
        ["group"],
        ["task"],
        ["change", "group"],
        ["change", "task"],
        ["group", "task"],
        ["change", "group", "task"],
    ],
)
def test_levels_accepts_any_non_empty_ordered_subset(levels: list[str]) -> None:
    section = accepted(basic_block(types=ALL_TYPES) | {"levels": levels, "epic": False})

    assert section.levels == tuple(levels)


@pytest.mark.parametrize(
    ("levels", "entry"),
    [
        (["change", "change"], "change"),
        (["change", "story"], "story"),
        (["group", "change"], "change"),
        (["task", "group"], "group"),
    ],
)
def test_a_repeated_unknown_or_misordered_level_is_refused_naming_the_entry(
    levels: list[str], entry: str
) -> None:
    message = refused(basic_block(types=ALL_TYPES) | {"levels": levels})

    assert "app" in message and "levels" in message and entry in message


def test_an_empty_levels_list_is_refused_saying_one_is_required() -> None:
    message = refused(basic_with(levels=[]))

    assert "levels" in message and "at least one" in message


def test_a_basic_section_maps_change_to_issue_and_group_to_task() -> None:
    section = accepted(BASIC)

    assert section.levels == ("change", "group")
    assert section.epic is True
    assert section.level_types["change"] == "Issue"
    assert section.level_types["group"] == "Task"
    assert "task" not in section.level_types


def test_a_github_section_with_a_block_is_valid() -> None:
    section = accepted(
        {"kind": "github", "token_env": "TRACKER_TOKEN", "levels": ["change", "group", "task"]}
        | {"github": GITHUB_BLOCK}
    )

    assert section.level_types == GITHUB_BLOCK["types"]


def test_another_providers_block_is_refused_naming_it() -> None:
    message = refused(basic_with(github=GITHUB_BLOCK))

    assert "github" in message and "app" in message


def test_a_level_with_no_type_is_refused_naming_the_level_and_types() -> None:
    message = refused(basic_block(types={"epic": "Epic", "change": "Issue"}))

    assert "group" in message and "types" in message


def test_the_epic_with_no_type_is_refused_naming_epic_and_types() -> None:
    message = refused(basic_block(types={"change": "Issue", "group": "Task"}))

    assert "epic" in message and "types" in message


def test_an_unknown_key_is_refused_naming_it() -> None:
    assert "colour" in refused(basic_with(colour="red"))
    assert "colour" in refused(basic_block(colour="red"))


def test_a_credential_shaped_token_env_is_refused_without_echoing_it() -> None:
    message = refused(basic_with(token_env=TOKEN_SHAPED))

    assert "token_env" in message
    assert TOKEN_SHAPED not in message


@pytest.mark.parametrize("setting", ["lowest", "all", ["change"], ["change", "group"]])
def test_pr_links_accepts_lowest_all_and_a_list(setting: str | list[str]) -> None:
    section = accepted(basic_with(pr_links=setting))

    assert section.pr_links == (tuple(setting) if isinstance(setting, list) else setting)


def test_pr_links_defaults_to_lowest() -> None:
    assert accepted(BASIC).pr_links == "lowest"


def test_pr_links_naming_a_level_not_in_use_is_refused_naming_it() -> None:
    message = refused(basic_with(pr_links=["task"]))

    assert "pr_links" in message and "task" in message
