"""The old flat tracker keys still read, as the three levels they always meant."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_build_kit.trackers.config import AzureDevOpsTracker, TrackerConfigError, section_for
from tests.trackers.tracker_section_support import (
    AZURE,
    AZURE_BLOCK,
    BASIC,
    GITHUB,
    GITHUB_BLOCK,
    LABELS,
    configure,
)

THREE = ("change", "group", "task")


def test_an_old_azure_devops_section_expands_to_three_levels_with_the_old_types() -> None:
    configure(app=AZURE)

    section = section_for("app")

    assert section is not None
    assert section.levels == THREE
    assert section.level_types == {"change": "Feature", "group": "User Story", "task": "Task"}


def test_an_old_github_section_expands_using_its_labels() -> None:
    configure(app=GITHUB)

    section = section_for("app")

    assert section is not None
    assert section.levels == THREE
    assert section.level_types == {
        "change": LABELS["feature"],
        "group": LABELS["story"],
        "task": LABELS["task"],
    }


def test_a_flat_state_map_is_kept_as_the_fallback() -> None:
    states = {"new": "To Do", "active": "Doing", "done": "Done"}
    configure(app={**AZURE, "state_map": states})

    section = section_for("app")

    assert section is not None and section.levels == THREE
    assert section.state_map == states


def test_the_old_shape_still_names_a_missing_field_and_an_empty_label() -> None:
    configure(app=AZURE)
    section = section_for("app")
    assert section is not None and section.levels == THREE

    configure(app={key: value for key, value in AZURE.items() if key != "project"})
    with pytest.raises(TrackerConfigError) as missing:
        section_for("app")
    configure(app={**GITHUB, "labels": {**LABELS, "story": ""}})
    with pytest.raises(TrackerConfigError) as empty:
        section_for("app")

    assert all(word in str(missing.value) for word in ("app", "azure_devops", "project"))
    assert all(word in str(empty.value) for word in ("labels", "story"))


@pytest.mark.parametrize(
    ("old", "block", "block_name", "old_key"),
    [
        (AZURE, AZURE_BLOCK, "azure_devops", "story_type"),
        (GITHUB, GITHUB_BLOCK, "github", "labels"),
    ],
)
def test_a_section_mixing_old_keys_and_a_provider_block_is_refused_naming_both(
    old: dict[str, object], block: dict[str, object], block_name: str, old_key: str
) -> None:
    configure(app=AZURE)
    section = section_for("app")
    assert section is not None and section.levels == THREE

    configure(app={**old, block_name: block})
    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert old_key in str(raised.value) and block_name in str(raised.value)


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ({**AZURE, "types": ["Feature"]}, "types"),
        ({**AZURE, "types": None}, "types"),
        ({**GITHUB, "labels": ["a", "b"]}, "labels"),
        ({**GITHUB, "types": ["a"]}, "types"),
    ],
)
def test_a_non_mapping_in_the_old_shape_is_a_tracker_error_naming_the_key(
    raw: dict[str, object], key: str
) -> None:
    configure(app=raw)

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert all(word in str(raised.value) for word in ("app", str(raw["kind"]), key))


def warned(caplog: pytest.LogCaptureFixture, raw: dict[str, Any]) -> list[str]:
    configure(app=raw)
    with caplog.at_level(logging.WARNING):
        section_for("app")
        section_for("app")
    return [record.getMessage() for record in caplog.records]


def test_an_old_azure_devops_section_warns_once_per_key_naming_the_new_place(
    caplog: pytest.LogCaptureFixture,
) -> None:
    messages = warned(caplog, {**AZURE, "state_map": {"new": "To Do"}})

    assert [m for m in messages if "'story_type'" in m and "azure_devops.types.group" in m]
    assert [m for m in messages if "'state_map'" in m and "azure_devops.states" in m]
    assert [m for m in messages if "'organization'" in m and "azure_devops.organization" in m]
    assert len(messages) == len(set(messages))


def test_an_old_github_section_warns_naming_the_new_place(
    caplog: pytest.LogCaptureFixture,
) -> None:
    messages = warned(caplog, GITHUB)

    assert [m for m in messages if "'labels'" in m and "github.types" in m]
    assert len(messages) == len(set(messages))


def test_a_new_shape_section_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    assert warned(caplog, BASIC) == []
    assert section_for("app") is not None


@pytest.mark.parametrize(
    ("block_name", "block", "flat"),
    [
        ("azure_devops", AZURE_BLOCK, {"state_map": {"new": "To Do"}}),
        ("azure_devops", AZURE_BLOCK, {"types": {"change": "Issue"}}),
        ("github", GITHUB_BLOCK, {"state_map": {"new": "open"}}),
    ],
)
def test_a_flat_state_map_or_types_beside_a_block_is_refused_naming_both(
    block_name: str, block: dict[str, object], flat: dict[str, object]
) -> None:
    valid = {"kind": block_name, "levels": ["change", "group"], block_name: block}
    configure(app=valid)
    assert section_for("app") is not None

    configure(app={**valid, **flat})
    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert next(iter(flat)) in str(raised.value) and block_name in str(raised.value)


@pytest.mark.parametrize(
    ("block_name", "block", "key"),
    [
        ("azure_devops", {**AZURE_BLOCK, "kind": "github"}, "kind"),
        ("azure_devops", {**AZURE_BLOCK, "story_type": "User Story"}, "story_type"),
        ("azure_devops", {**AZURE_BLOCK, "state_map": {"new": "To Do"}}, "state_map"),
        ("azure_devops", {**AZURE_BLOCK, "levels": ["change"]}, "levels"),
        ("github", {**GITHUB_BLOCK, "labels": LABELS}, "labels"),
    ],
)
def test_a_key_that_is_not_a_block_key_is_refused_naming_it_and_the_block(
    block_name: str, block: dict[str, object], key: str
) -> None:
    configure(app={"kind": block_name, "levels": ["change", "group"], block_name: block})

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert key in str(raised.value) and block_name in str(raised.value)


def test_a_story_type_shared_with_the_task_level_is_refused_naming_the_levels() -> None:
    configure(app={**AZURE, "story_type": "Task"})

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert "task" in str(raised.value) and "types" in str(raised.value)


def test_story_type_is_the_group_type_when_types_names_none_even_when_built_directly() -> None:
    section = AzureDevOpsTracker(
        kind="azure_devops",
        organization="example-org",
        project="Example Project",
        team="Example Team",
        area_path="Example Project\\Area",
        iteration_path="Example Project\\Iteration 1",
        story_type="User Story",
        levels=("change", "group"),
        types={"change": "Issue"},
    )

    assert section.level_types == {"change": "Issue", "group": "User Story"}
