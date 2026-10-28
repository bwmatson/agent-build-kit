"""A level's parent follows from the levels in use and from the manual epic."""

from __future__ import annotations

from itertools import combinations

import pytest

from agent_build_kit.trackers.config import section_for
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure

ORDER = ("change", "group", "task")
SUBSETS = [list(subset) for size in (1, 2, 3) for subset in combinations(ORDER, size)]
TYPES = {"epic": "Epic", "change": "Feature", "group": "Product Backlog Item", "task": "Task"}


def parents(levels: list[str], epic: bool) -> dict[str, str | None]:
    configure(
        app={
            "kind": "azure_devops",
            "levels": levels,
            "epic": epic,
            "azure_devops": {**AZURE_BLOCK, "types": TYPES},
        }
    )
    section = section_for("app")
    assert section is not None
    return {level: section.parent_level(level) for level in levels}


def expected(levels: list[str], epic: bool) -> dict[str, str | None]:
    """The previous level in use, and for the first the epic when one is set."""
    return {
        level: levels[index - 1] if index else ("epic" if epic else None)
        for index, level in enumerate(levels)
    }


@pytest.mark.parametrize("levels", SUBSETS)
def test_a_level_hangs_under_the_previous_level_in_use(levels: list[str]) -> None:
    assert parents(levels, epic=False) == expected(levels, epic=False)


@pytest.mark.parametrize("levels", SUBSETS)
def test_the_first_level_hangs_under_the_epic_when_one_is_set(levels: list[str]) -> None:
    found = parents(levels, epic=True)

    assert found == expected(levels, epic=True)
    assert found[levels[0]] == "epic"


def test_a_skipped_level_attaches_to_the_nearest_one_above() -> None:
    assert parents(["change", "task"], epic=False) == {"change": None, "task": "change"}


def test_the_single_level_change_has_no_group_items() -> None:
    block = {**AZURE_BLOCK, "types": TYPES}
    configure(app={"kind": "azure_devops", "levels": ["change"], "azure_devops": block})
    section = section_for("app")

    assert section is not None
    assert section.levels == ("change",)
    assert "group" not in section.level_types
    assert section.parent_level("change") is None
