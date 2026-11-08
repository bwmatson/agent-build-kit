"""What an Azure DevOps project is made of, as the in-memory host answers for it: its work item
types and their states, its backlog levels, and the team and paths a configuration names."""

from __future__ import annotations

from agent_build_kit.model import Frozen


class ProjectShape(Frozen):
    """`types`: each work item type's states. `backlogs`: the types on each backlog level, top
    level first. `areas` and `iterations`: the classification nodes below the project's root.
    `work_item_access` is false for a credential without work item scope."""

    types: dict[str, tuple[str, ...]]
    backlogs: tuple[tuple[str, ...], ...]
    teams: tuple[str, ...] = ("Team A",)
    areas: tuple[str, ...] = ("Team A",)
    iterations: tuple[str, ...] = ("Sprint 1",)
    work_item_access: bool = True


BASIC_STATES = ("To Do", "Doing", "Done")
SCRUM_STATES = ("New", "Approved", "Committed", "Done", "Removed")

BASIC = ProjectShape(
    types={"Epic": BASIC_STATES, "Issue": BASIC_STATES, "Task": BASIC_STATES},
    backlogs=(("Epic",), ("Issue",), ("Task",)),
)
SCRUM = ProjectShape(
    types={
        name: SCRUM_STATES for name in ("Epic", "Feature", "Product Backlog Item", "Bug", "Task")
    },
    backlogs=(("Epic",), ("Feature",), ("Product Backlog Item", "Bug"), ("Task",)),
)
