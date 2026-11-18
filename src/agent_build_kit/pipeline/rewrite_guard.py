"""The guard after a step that holds a rewrite request: the unit's base must be unchanged.

At the start of such a step the head the branch is on is recorded. After it, the base must still
be an ancestor of the head, every commit above the base must carry the unit trailer, and none may
be a merge commit. A branch that fails is put back at the recorded head and the step is returned
to the agent with the reason, as a failed check is.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredRewriteRequest, UnitStore


class GuardCheck(StrEnum):
    """The check a rewrite failed."""

    BASE = "base"
    TRAILER = "trailer"
    MERGE = "merge"


class GuardVerdict(Frozen):
    """Whether the branch passed, and when it did not, the check, the reason naming the commits
    or the base, and that the branch was put back."""

    ok: bool
    check: GuardCheck | None = None
    reason: str = ""


class GuardedStep(Frozen):
    """How a guarded step ended: `ok` when the guard passed, how many times the step was
    returned to the agent, and the last verdict."""

    ok: bool
    returned: int
    verdict: GuardVerdict


def guard_rewrite(
    tree: Path,
    *,
    request: StoredRewriteRequest | None,
    base: str,
    started_at: str,
    unit_id: str,
) -> GuardVerdict:
    """Check the branch checked out in `tree` after a step that started at `started_at` with
    `request`; `base` is where the unit's own commits begin. A step with no request is not
    checked. A failure moves the branch back to `started_at`."""
    raise NotImplementedError


def run_guarded_step(
    tree: Path,
    *,
    request: StoredRewriteRequest | None,
    base: str,
    unit_id: str,
    store: UnitStore,
    agent: Callable[[str], None],
    returns: int | None,
) -> GuardedStep:
    """Run `agent` in the step: first with an empty reason, then with the guard's reason each
    time the guard fails, up to `returns` times (None: no limit). The stored request is cleared
    when the step ends, passed or failed."""
    raise NotImplementedError
