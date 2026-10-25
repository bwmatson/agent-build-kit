"""The paths a task group names: one reader for project resolution and the e2e product-path
warning (spec: project-resolution)."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.pipeline.work_graph import TaskGroup


def line_paths(line: str) -> list[str]:
    """The repo paths a task line names in backticks: tokens with a `/` or a file extension,
    without a trailing `:<line>`, `::<test id>` or `/`; URLs, flags, assignments, globs and
    symbols are skipped."""
    raise NotImplementedError


def named_paths(group: TaskGroup, projects: Sequence[str]) -> list[str]:
    """The paths `group` names as changes: its `Paths:` line when it has one, else the paths of
    its lines that are changes, with globs by their literal prefix and unticked words anchored
    on a declared project's path (`projects`, as a heading writes them)."""
    raise NotImplementedError
