"""The old flat tracker keys still read, as the three levels they always meant."""

from __future__ import annotations

import pytest

from agent_build_kit.trackers.config import TrackerConfigError, section_for
from tests.trackers.tracker_section_support import (
    AZURE,
    AZURE_BLOCK,
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
