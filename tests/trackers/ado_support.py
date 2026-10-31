"""Configurations of the process templates the Azure DevOps tracker tests run against."""

from __future__ import annotations

from typing import Any

from agent_build_kit.trackers.config import AzureDevOpsTracker

# Process -> the work item type of each level.
PROCESS_TYPES: dict[str, dict[str, str]] = {
    "basic": {"epic": "Epic", "change": "Issue", "group": "Task"},
    "scrum": {
        "epic": "Epic",
        "change": "Feature",
        "group": "Product Backlog Item",
        "task": "Task",
    },
    "agile": {"epic": "Epic", "change": "Feature", "group": "User Story", "task": "Task"},
}
AREA_PATH = "Some Project\\Team A"
ITERATION_PATH = "Some Project\\Sprint 1"


def section(process: str = "basic", **overrides: Any) -> AzureDevOpsTracker:
    """The configuration of a process; `overrides` set fields of the `azure_devops` block."""
    types = PROCESS_TYPES[process]
    made = AzureDevOpsTracker(
        kind="azure_devops",
        organization="example",
        project="Some Project",
        team="Team A",
        area_path=AREA_PATH,
        iteration_path=ITERATION_PATH,
        story_type=types["group"],
        levels=tuple(level for level in ("change", "group", "task") if level in types),
        epic="epic" in types,
        types=types,
    )
    return made.model_copy(update={"process": process, **overrides})
