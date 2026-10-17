"""What the lane's hand-back tests share: a unit in review told its base moved, whose move the
lane makes and whose run then meets a step that is not moved-base work.

The scene is `test_restack_lane_prepare`'s. `resolved_move` makes the move change the diff, so the
run goes on into a review of the result; without it the move is clean and the run goes from tier 1
to the push.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import git
from tests.graph.test_restack_lane_prepare import Scene, adapting
from tests.tick_driver import OTHER


def resolved_move(scene: Scene) -> None:
    """The move rewrites the diff (a conflict it resolved), and the run's port has nothing to do."""

    def resolving(tree: Path, branch: str, *, new_base: str, old_base: str, **_: Any) -> Moved:
        git(tree, "rebase", "-q", "--onto", new_base, old_base, branch)
        return Moved(sha=git(tree, "rev-parse", "HEAD"), resolved=("a.txt",))

    scene.graph.options["restack_onto"] = scene.restack(
        build_restack_onto(scene.graph.store, move=resolving)
    )
    adapting(scene)


def move_threads(scene: Scene) -> list[str]:
    """Wrap the scene's move so each call notes the name of the thread it ran on; the lane's
    workers are named `restack`."""
    names: list[str] = []
    moving = scene.graph.options["restack_onto"]

    def restack(**kwargs: Any) -> Any:
        names.append(threading.current_thread().name)
        return moving(**kwargs)

    scene.graph.options["restack_onto"] = restack
    return names


def handed_back_at(scene: Scene, step: Node) -> None:
    """The unit was given back to a build worker, its thread kept at `step`."""
    stored = scene.graph.store.get(OTHER)
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_HANDED_BACK)
    assert not stored.moved_base_run
    assert scene.graph.next(OTHER) == (step,)
