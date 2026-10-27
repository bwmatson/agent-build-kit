"""Over a real pipeline worktree, no lock file reaches a change's directory: ticks, follow-ups,
`Needs:` lines and `abk tags --fix` all lock under the local directory (spec: change-locks)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import change_lock
from agent_build_kit.pipeline.flakes import add_needs
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.tags_fix_support import OLD_E2E_TAG, OLD_UNIT_TEST_TAG, tasks_text
from tests.factories import git, stored_unit
from tests.planning_worktree_support import InRepo, in_repo, installation_at
from tests.progress_support import copy_file, tick, ticked
from tests.runner_fakes import Recorder, make_runner

CHANGE = "add-marker"
JOIN = 10


@pytest.fixture(autouse=True)
def data_home(data: Path) -> Path:
    return data


def scene(tmp_path: Path) -> tuple[InRepo, Installation]:
    """A pipeline worktree holding a change tagged in the old spellings, its `abk.yaml`, and the
    installation over it."""
    probe = installation_at(tmp_path / "probe", tmp_path / "probe", planning=dict())
    setup = in_repo(
        tmp_path,
        files={
            f"openspec/changes/{CHANGE}/tasks.md": tasks_text(
                OLD_UNIT_TEST_TAG, OLD_E2E_TAG
            ).decode(),
            "abk.yaml": dump(probe.config),
        },
    )
    inst = installation_at(
        setup.worktree, setup.working_copy, planning=dict(state_dir=str(tmp_path / "state"))
    )
    (setup.worktree / "abk.yaml").write_text(dump(inst.config))
    return setup, inst


def locks_under(root: Path) -> list[Path]:
    return sorted(root.rglob("*.lock"))


def test_no_lock_is_made_in_the_changes_directory_and_every_one_is_local(tmp_path: Path) -> None:
    setup, inst = scene(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    unit = stored_unit(f"{CHANGE}/1", groups=(1,))
    store.upsert([unit])
    runner = make_runner(store, Recorder(store), tmp_path, planning_repo=setup.worktree)

    tick(inst, CHANGE, (1,), done=True)
    runner.record_follow_ups(unit, ["rename the helper"])
    add_needs(inst, CHANGE, 2, "other-fix", "a reason")
    code = main(["--config", str(setup.worktree / "abk.yaml"), "tags", "--fix", CHANGE])

    assert code == 0
    assert locks_under(inst.changes_dir) == []
    assert ".lock" not in git(setup.worktree, "status", "--porcelain", "--ignored")
    local = inst.planning_home / "local" / "locks" / "changes" / CHANGE
    assert {p.name for p in local.glob("*.lock")} == {
        "progress.lock",
        "tasks.md.lock",
        "follow-ups.md.lock",
    }


def test_the_tick_of_the_copy_does_not_deadlock_with_a_holder_of_tasks_md(tmp_path: Path) -> None:
    _, inst = scene(tmp_path)
    holding = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with change_lock(inst, CHANGE, "tasks.md"):
            holding.set()
            release.wait(JOIN)

    one = threading.Thread(target=holder)
    one.start()
    assert holding.wait(JOIN)
    ticking = threading.Thread(target=tick, args=(inst, CHANGE, (1,)), kwargs=dict(done=True))
    ticking.start()
    release.set()
    one.join(JOIN)
    ticking.join(JOIN)

    assert not ticking.is_alive()
    assert ticked(copy_file(inst, CHANGE)) == {1}
