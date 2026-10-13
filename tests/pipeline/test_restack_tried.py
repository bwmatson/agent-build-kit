"""What the restack's steps tried reaches the port: the move records each failed check on the
`RestackConflict`, and `build_restack_onto` hands it on in `Restacked.tried` (spec:
restack-adapt, the port is told which steps were tried and what their checks said).

Real git and the real mover; the resolver is a stand-in for the agent that leaves the
conflict markers in place on both calls.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from agent_build_kit.pipeline.restack import RestackConflict, resolved_move
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import unit
from tests.pipeline.test_restack_onto_before_push import BASE, BRANCH, Repos, stack


def leaves_markers(prompt: str, *, cwd: Path, follow_up: str = "") -> None:
    """Does nothing: the conflict markers stay, so both steps fail their check."""


def test_the_port_is_told_both_failed_steps_and_what_their_checks_said(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=True)
    move = partial(resolved_move, resolve=leaves_markers)

    restacked = build_restack_onto(store, move=move)(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit()
    )

    assert restacked is not None and restacked.conflict
    steps = restacked.tried.splitlines()
    assert len(steps) == 2
    assert steps[0].startswith("step 1") and "conflict markers" in steps[0]
    assert steps[1].startswith("step 2") and "conflict markers" in steps[1]


def test_the_restacked_result_carries_what_the_raised_conflict_carries(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=True)
    raised: list[RestackConflict] = []

    def recording(*args, **kwargs):
        try:
            return resolved_move(*args, resolve=leaves_markers, **kwargs)
        except RestackConflict as error:
            raised.append(error)
            raise

    restacked = build_restack_onto(store, move=recording)(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit()
    )

    assert restacked is not None
    assert len(raised) == 1 and raised[0].tried
    assert restacked.tried == raised[0].tried


def test_a_resolver_that_fails_after_a_failed_step_still_tells_the_port_the_first(
    tmp_path: Path,
) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=True)
    calls: list[str] = []

    def crashes_on_the_second(prompt: str, *, cwd: Path, follow_up: str = "") -> None:
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("the agent crashed")

    restacked = build_restack_onto(
        store, move=partial(resolved_move, resolve=crashes_on_the_second)
    )(tree=repos.tree, branch=BRANCH, base=BASE, unit=unit())

    assert restacked is not None and restacked.conflict
    assert restacked.tried.startswith("step 1") and "conflict markers" in restacked.tried
    assert "step 2" not in restacked.tried


def test_a_move_that_needs_no_resolution_has_nothing_tried(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=False)

    restacked = build_restack_onto(store, move=partial(resolved_move, resolve=leaves_markers))(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit()
    )

    assert restacked is not None and restacked.tried == ""
