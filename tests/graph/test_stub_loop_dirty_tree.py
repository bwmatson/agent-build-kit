"""A unit stopped in the stub check loop leaves its tests uncommitted in the worktree; a requeue
takes them as its own and goes to the fix, unless a chat's changes are what is there
(spec: stub-check-loop)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.stack_runner import LEFTOVERS_NOTE, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from agent_build_kit.pipeline.workspaces import DirtyWorktree
from tests.attach_driver import leave_lease
from tests.graph.stub_loop_fakes import StubLoop, stubbed_build
from tests.graph.test_build_path import build, limited
from tests.graph_driver import fresh as fresh_store
from tests.runner_fakes import Killed

UNIT = "add-marker/1"
SAVED = "STUB-OUTPUT-0"
PATHS = ("tests/test_marker.py", "src/marker.py")


def dirty_overrides(recorder: StubLoop, tmp_path: Path) -> dict[str, Any]:
    """The overrides with a worktree that refuses a dirty tree unless allowed, as the real one."""
    tree = tmp_path / "tree"

    def worktree(unit: Any, base: str, allow_dirty: bool = False) -> Path:
        if not allow_dirty:
            raise DirtyWorktree("uncommitted changes", paths=PATHS)
        return tree

    return {**recorder.overrides(tmp_path), "worktree": worktree}


def clean_then_dirty(worktree: Callable[..., Path], recorder: StubLoop) -> Callable[..., Path]:
    """A worktree that is clean until the first fix has been killed, then dirty with its edits."""

    def chosen(unit: Any, base: str, allow_dirty: bool = False) -> Path:
        if not recorder.fix_prompts:
            return worktree(unit, base, allow_dirty=True)
        return worktree(unit, base, allow_dirty=allow_dirty)

    return chosen


def stopped(tmp_path: Path) -> StubLoop:
    stubbed_build()
    recorder = StubLoop(fresh_store(tmp_path).store, checks=[(False, SAVED), (True, "")])
    recorder.asked = 1
    recorder.store.set_feedback(UNIT, SAVED, source=FeedbackSource.STUB_CHECKS)
    return recorder


def test_a_requeue_over_the_loops_uncommitted_tests_goes_to_the_fix(tmp_path: Path) -> None:
    recorder = stopped(tmp_path)

    outcome = build(tmp_path, recorder, **dirty_overrides(recorder, tmp_path))

    assert outcome.status == "open", outcome
    assert recorder.events[0] == "claude:fix_stub"
    assert recorder.store.get(UNIT).cause != Cause.DIRTY_WORKTREE
    assert PATHS[0] in recorder.fix_prompts[0], "the fix is told of the uncommitted files"


def test_a_dirty_tree_that_is_a_chats_still_holds_the_unit(tmp_path: Path) -> None:
    recorder = stopped(tmp_path)
    leave_lease(lease_dir(tmp_path / "state"), UNIT, files=1)

    outcome = build(
        tmp_path,
        recorder,
        leases=Leases(lease_dir(tmp_path / "state")),
        **dirty_overrides(recorder, tmp_path),
    )

    assert outcome.status == RunStatus.HELD
    assert recorder.store.get(UNIT).cause == Cause("attached")
    assert "claude:fix_stub" not in recorder.events


def test_a_fix_killed_mid_agent_resumes_over_its_own_leftovers_and_is_told_of_them(
    tmp_path: Path,
) -> None:
    stubbed_build()
    limited(max_check_rounds=3)
    recorder = StubLoop(
        fresh_store(tmp_path).store, checks=[(False, SAVED), (True, "")], kill_in_fix=1
    )
    overrides = dirty_overrides(recorder, tmp_path)
    overrides["worktree"] = clean_then_dirty(overrides["worktree"], recorder)

    with pytest.raises(Killed):
        build(tmp_path, recorder, **overrides)
    outcome = build(tmp_path, recorder, **overrides)

    assert outcome.status == "open", outcome
    assert recorder.events.count("claude:fix_stub") == 2
    assert LEFTOVERS_NOTE[:20] in recorder.fix_prompts[-1]
    assert PATHS[0] in recorder.fix_prompts[-1]
