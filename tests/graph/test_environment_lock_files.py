"""Lock files an environment's `sync` writes are the pipeline's, not leftovers
(spec: pipeline-environment).

A unit is built in a real git worktree with the real commit step, in a repository whose
`sync` is a real child process that writes the lock file named in its lock inputs, a
different one each time (`tests/environment_fakes.py`). Only the agent, the review and
tier 1 are stand-ins. The unit is built in one tick and asked for a rework in the next, as
a person's comment does, so that the worktree check runs over what the first tick left.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from tests.environment_fakes import FakeEnvironment, repo_config
from tests.factories import unit
from tests.graph.test_resume_over_leftovers import rework_event
from tests.graph_driver import fresh, tick
from tests.leftovers_driver import Habitat, Hands
from tests.runner_fakes import Recorder

UNIT = unit().id
MANIFEST = "manifest.toml"
LOCK = "deps.lock"
STRAY = "stray.txt"


def built(tmp_path: Path, **tracked: str) -> tuple[Habitat, Recorder]:
    """A unit built and waiting in review, the lock the sync last wrote still in its tree."""
    env = FakeEnvironment(tmp_path / "control", inputs=(MANIFEST,), locks=(LOCK,))
    env.writes_lock("rewritten ")
    habitat = Habitat(
        tmp_path,
        Hands(),
        tracked={MANIFEST: 'widget = "1"\n', **tracked},
        config=repo_config(tmp_path / "meta", env),
    )
    recorder = fresh(tmp_path)
    assert tick(tmp_path, recorder, **habitat.overrides()).status == RunStatus.OPEN
    assert (habitat.tree / LOCK).read_text().startswith("rewritten ")
    return habitat, recorder


def reworked(tmp_path: Path, habitat: Habitat, recorder: Recorder) -> RunOutcome:
    """The tick that delivers a person's rework comment, and the one that does the rework."""
    tick(tmp_path, recorder, event=rework_event(), **habitat.overrides())
    return tick(tmp_path, recorder, **habitat.overrides())


def committed(habitat: Habitat) -> list[str]:
    return git_out(habitat.tree, "ls-tree", "-r", "--name-only", "HEAD").split()


def test_an_untracked_lock_the_sync_created_does_not_hold_the_rework(tmp_path: Path) -> None:
    habitat, recorder = built(tmp_path)

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get(UNIT).cause is not Cause.DIRTY_WORKTREE
    assert (habitat.tree / "rework.txt").exists(), "the rework step ran"
    assert (habitat.tree / LOCK).exists(), "the lock is still in the worktree"
    assert LOCK not in committed(habitat), "and in no commit of the unit"


def test_a_tracked_lock_the_sync_rewrote_does_not_hold_the_rework(tmp_path: Path) -> None:
    habitat, recorder = built(tmp_path, **{LOCK: "as committed\n"})

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get(UNIT).cause is not Cause.DIRTY_WORKTREE
    assert (habitat.tree / "rework.txt").exists(), "the rework step ran"
    assert git_out(habitat.tree, "show", f"HEAD:{LOCK}") == "as committed", "no dependency changed"


def test_another_uncommitted_file_still_holds_the_unit_and_is_the_only_one_named(
    tmp_path: Path,
) -> None:
    habitat, recorder = built(tmp_path, **{LOCK: "as committed\n"})
    (habitat.tree / STRAY).write_text("mine\n")
    asked = len(habitat.runtime.requests)

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(UNIT)
    assert stored.cause is Cause.DIRTY_WORKTREE
    words = f"{stored.note}\n{outcome.detail}"
    assert STRAY in words
    assert LOCK not in words, "the lock is not a leftover"
    assert len(habitat.runtime.requests) == asked, "no agent was started over it"
    assert (habitat.tree / STRAY).read_text() == "mine\n"
    assert (habitat.tree / LOCK).read_text().startswith("rewritten "), "the rewrite was kept"
