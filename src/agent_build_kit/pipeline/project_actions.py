"""Applying a change's `Project:` lines to the planning repo's abk.yaml (spec: project-lines).

An `add`, and the new half of a `replace`, is applied when the change is planned. A `remove`, and
the old half of a `replace`, is applied once the unit that carries the group is settling or merged,
and waits while an unfinished unit is stored in that project. Each application is recorded in a
ledger in the state folder, keyed by change, group and a hash of the line.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import ProjectLine


class ActionReport(Frozen):
    """What one run of the step did, as lines a person can read."""

    # Applied now, or found already applied and recorded.
    applied: tuple[str, ...] = ()
    # A `remove` held while an unfinished unit is stored in the project.
    waiting: tuple[str, ...] = ()
    # An edit that could not be made, to be retried on the next tick.
    failed: tuple[str, ...] = ()


def action_key(change: str, group: int, line: ProjectLine) -> str:
    """The ledger key of one line: its change, its group and a hash of the line's text."""
    raise NotImplementedError


def apply_project_actions(
    inst: Installation,
    units: Sequence[StoredUnit],
    *,
    planning: Sequence[str] = (),
    publish: Callable[[str, int], None] | None = None,
    log: Callable[[str], None] = print,
) -> ActionReport:
    """Apply what is due: the adds of the changes in `planning`, and the removes of every change
    whose carrying unit (joined groups included) is settling or merged. `publish(change, group)`
    commits abk.yaml after an application. A failure is logged and reported, never raised."""
    raise NotImplementedError


def status_lines(inst: Installation, units: Sequence[StoredUnit]) -> list[str]:
    """The lines `abk status` shows: a `remove` waiting for a project to empty, and an edit that
    failed."""
    raise NotImplementedError


def failed_lines(inst: Installation) -> list[str]:
    """The edits whose last try failed, for `abk doctor`."""
    raise NotImplementedError


def commit_project_file(
    inst: Installation, change: str, group: int, *, log: Callable[[str], None] = print
) -> bool:
    """Commit abk.yaml alone to the planning repo, with a message naming the change and group.
    True when a commit was made; a refused commit is logged and returns False."""
    raise NotImplementedError
