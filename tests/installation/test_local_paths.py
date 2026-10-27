"""The locks, leases, e2e-test lock and environment lock are in the local directory and none in
the state directory (spec: planning-local-directory)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import unit_graphs_path
from tests.planning_worktree_support import in_repo, installation_at


def test_every_machine_local_file_is_under_the_local_directory_and_none_under_the_state(
    tmp_path: Path, data: Path
) -> None:
    setup = in_repo(tmp_path)
    inst = installation_at(setup.working_copy, setup.working_copy)
    assert inst.local_dir != inst.state_dir

    paths = (inst.locks_dir, inst.leases_dir, inst.e2e_lock, inst.environment_lock)

    for path in paths:
        assert path.is_relative_to(inst.local_dir), path
        assert not path.is_relative_to(inst.state_dir), path
    assert unit_graphs_path(inst.local_dir) == inst.local_dir / "unit-graphs.sqlite"


@pytest.mark.parametrize("name", ["locks_dir", "leases_dir"])
def test_the_directories_are_named_for_what_they_hold(
    tmp_path: Path, data: Path, name: str
) -> None:
    setup = in_repo(tmp_path)
    inst = installation_at(setup.working_copy, setup.working_copy)

    assert getattr(inst, name) == inst.local_dir / name.removesuffix("_dir")
