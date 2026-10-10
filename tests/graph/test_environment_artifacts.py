"""What an environment's `sync` builds into artifact folders is the pipeline's, not a
leftover (spec: pipeline-environment).

The same real worktree, commit step and `sync` child process as the lock-file tests, with a
repository that does not ignore the folder its `sync` fills. The unit is built in one tick and
asked for a rework in the next, so that the worktree check runs over what the first tick left.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from tests.factories import unit
from tests.graph.test_environment_lock_files import STRAY, built, committed, reworked

UNIT = unit().id
SHAPES = [pytest.param(".venv", id="python-shaped"), pytest.param("modules", id="node-shaped")]


@pytest.mark.parametrize("artifact", SHAPES)
def test_an_artifact_folder_the_sync_created_does_not_hold_the_rework(
    tmp_path: Path, artifact: str
) -> None:
    habitat, recorder = built(tmp_path, artifacts=(artifact,))
    assert (habitat.tree / artifact / "pkg" / "built.bin").exists(), "the sync filled it"

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get(UNIT).cause is not Cause.DIRTY_WORKTREE
    assert (habitat.tree / "rework.txt").exists(), "the rework step ran"
    assert (habitat.tree / artifact / "pkg" / "built.bin").exists(), "the folder is still there"
    assert not [name for name in committed(habitat) if name.startswith(f"{artifact}/")], (
        "and in no commit of the unit"
    )


def test_another_uncommitted_file_still_holds_the_unit_and_is_the_only_one_named(
    tmp_path: Path,
) -> None:
    habitat, recorder = built(tmp_path, artifacts=("modules",))
    (habitat.tree / STRAY).write_text("mine\n")
    asked = len(habitat.runtime.requests)

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(UNIT)
    assert stored.cause is Cause.DIRTY_WORKTREE
    words = f"{stored.note}\n{outcome.detail}"
    assert STRAY in words
    assert "modules" not in words, "the artifact is not a leftover"
    assert len(habitat.runtime.requests) == asked, "no agent was started over it"
    assert (habitat.tree / STRAY).read_text() == "mine\n"
    assert (habitat.tree / "modules" / "pkg" / "built.bin").exists()


def test_a_repository_with_no_artifacts_is_held_for_the_folder_as_before(tmp_path: Path) -> None:
    habitat, recorder = built(tmp_path)
    (habitat.tree / "modules" / "pkg").mkdir(parents=True)
    (habitat.tree / "modules" / "pkg" / "built.bin").write_text("built\n")

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.HELD
    assert recorder.store.get(UNIT).cause is Cause.DIRTY_WORKTREE
    assert "modules" in f"{recorder.store.get(UNIT).note}\n{outcome.detail}"
