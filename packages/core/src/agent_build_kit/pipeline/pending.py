"""What is not built yet: a project whose directory is absent from the checkout being checked.

A project is registered in `abk.yaml` before the unit that creates it has run, so its
directory exists in no checkout until that unit's own commits add it. It is pending only
while the directory is absent, so the unit that creates it is checked in full.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ProjectConfig


def pending_projects(root: Path, projects: list[ProjectConfig] | None) -> list[ProjectConfig]:
    """The projects whose directory does not exist under `root`, in the order declared."""
    return [project for project in projects or [] if not (root / project.path).is_dir()]


def describe(project: ProjectConfig) -> str:
    """One line naming a pending project and the path that is missing."""
    return f"project {project.path} is pending: {project.path} does not exist in this checkout"
