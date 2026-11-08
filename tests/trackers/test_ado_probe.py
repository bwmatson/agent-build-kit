"""The doctor probe reads the project's types, states and backlog levels and says in one line each
what is right and what is wrong with the configuration, without printing the credential."""

from __future__ import annotations

import pytest

from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.base import ProbeLine
from tests.forges.conftest import PAT
from tests.trackers.ado_project import BASIC, BASIC_STATES, SCRUM, ProjectShape
from tests.trackers.ado_support import PROCESS_TYPES, section, tracker_on
from tests.trackers.ado_work_item_host import WorkItemHost

pytestmark = pytest.mark.usefixtures("rest_env")

CHECKS = ("access", "type", "state", "nesting", "epic", "team", "path")


def probe(project: ProjectShape, process: str = "basic", **overrides: object) -> list[ProbeLine]:
    return tracker_on(WorkItemHost(project=project), process, **overrides).probe()


def failures(lines: list[ProbeLine]) -> list[str]:
    return [line.text for line in lines if not line.ok]


def reports(lines: list[ProbeLine], word: str) -> bool:
    return any(line.ok and word in line.text.lower() for line in lines)


def test_a_good_basic_project_reports_each_check() -> None:
    lines = probe(BASIC)

    assert failures(lines) == []
    assert any("sync@example.com" in line.text for line in lines)
    assert [word for word in CHECKS if not reports(lines, word)] == []
    assert len(lines) >= len(CHECKS) + 1, "the identity and each check are lines of their own"


def test_a_good_scrum_project_with_three_levels_reports_each_check() -> None:
    lines = probe(SCRUM, "scrum")

    assert failures(lines) == []
    assert [word for word in CHECKS if not reports(lines, word)] == []
    assert not any("Bug" in line.text for line in lines), "a type the configuration does not use"


def test_a_missing_type_names_the_level() -> None:
    types = {**PROCESS_TYPES["basic"], "group": "User Story"}

    [text] = failures(probe(BASIC, types=types))

    assert "group" in text
    assert "User Story" in text


def test_the_backlog_levels_are_ordered_by_rank_not_by_their_place_in_the_list() -> None:
    task_first = BASIC.model_copy(update={"backlogs_bottom_first": True})

    assert failures(probe(task_first)) == []


def test_a_type_on_no_backlog_level_is_named() -> None:
    no_task_level = BASIC.model_copy(update={"backlogs": (("Epic",), ("Issue",))})

    [text] = failures(probe(no_task_level))

    assert "nesting" in text
    assert "Task" in text
    assert "no backlog level" in text


def test_a_process_with_no_state_map_names_the_type_and_the_kit_state() -> None:
    cmmi = section("basic").model_copy(update={"process": "cmmi"})

    texts = failures(AzureDevOpsWorkItems(cmmi, http=WorkItemHost(project=BASIC)).probe())

    assert texts, "cmmi has no default states to fall back on"
    assert all("states" in text and "`states`" in text for text in texts)
    assert any("Issue" in text and "new" in text for text in texts)


def test_a_mapped_state_the_type_lacks_names_both() -> None:
    [text] = failures(
        probe(
            BASIC,
            levels=("change",),
            epic=False,
            types={"change": "Issue"},
            state_map={"done": "Closed"},
        )
    )

    assert "Closed" in text
    assert "Issue" in text


def test_a_nesting_the_backlog_levels_disallow_is_reported_specifically() -> None:
    same_level = ProjectShape(types=BASIC.types, backlogs=(("Epic",), ("Issue", "Task")))

    [text] = failures(probe(same_level))

    assert "nesting" in text.lower()
    assert "not allowed" in text


@pytest.mark.parametrize(
    "backlogs",
    [(("Issue",), ("Task",)), (("Issue",), ("Epic",), ("Task",))],
    ids=["no-epic-type", "epic-below-the-first-level"],
)
def test_an_epic_type_that_does_not_exist_above_the_first_level_is_refused(
    backlogs: tuple[tuple[str, ...], ...],
) -> None:
    on_a_level = {name for level in backlogs for name in level}
    types = {name: states for name, states in BASIC.types.items() if name in on_a_level}

    [text] = failures(probe(ProjectShape(types=types, backlogs=backlogs)))

    assert "Epic" in text
    assert "above the first level" in text


def test_a_credential_without_work_item_scope_is_explained_and_not_printed() -> None:
    lines = probe(BASIC.model_copy(update={"work_item_access": False}))

    [text] = failures(lines)
    assert "work item" in text.lower()
    assert "access" in text.lower()
    assert not any(PAT in line.text for line in lines)


def test_a_state_list_is_read_from_the_project_not_assumed() -> None:
    renamed = BASIC.model_copy(
        update={"types": {**BASIC.types, "Issue": (*BASIC_STATES[:2], "Finished")}}
    )

    [text] = failures(probe(renamed))

    assert "Done" in text
    assert "Issue" in text
