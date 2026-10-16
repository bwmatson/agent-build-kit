"""`commit_planning` in an in-repo installation commits only the planning paths and leaves a
source file in progress modified and unstaged; in a separate planning repository it commits every
file as before (spec: planning-state-paths). Real git throughout; the OpenSpec command is a
script that records its runs, and `abk tags` is real over the change's task file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.attach import NothingToCommit, commit_planning
from tests.factories import git, stored_unit
from tests.planning_paths_support import (
    CHANGE,
    EDITED_TASKS,
    NEW_SOURCE,
    OUTSIDE,
    SOURCE,
    edit_change_and_source,
    gate_runs,
    in_repo_planning,
    separate_planning,
)

UNIT = stored_unit("feature/1", change="feature")


def committed(root: Path) -> list[str]:
    return sorted(git(root, "show", "--name-only", "--format=", "HEAD").split())


def test_the_commit_holds_the_change_not_the_source_file_and_the_gate_ran(tmp_path: Path) -> None:
    inst, _ = in_repo_planning(tmp_path)
    edit_change_and_source(inst.root)
    before = gate_runs(tmp_path)

    commit_planning(inst, UNIT, "Plan it")

    assert gate_runs(tmp_path) == before + 1
    assert committed(inst.root) == [CHANGE]
    assert git(inst.root, "diff", "--cached", "--name-only") == ""
    assert sorted(git(inst.root, "status", "--porcelain").split()) == sorted(
        ["M", SOURCE, "??", NEW_SOURCE]
    )
    assert (inst.root / SOURCE).read_text() == "edited\n"


def test_only_a_source_file_modified_is_nothing_to_commit_and_no_commit_is_made(
    tmp_path: Path,
) -> None:
    inst, _ = in_repo_planning(tmp_path)
    (inst.root / SOURCE).write_text("edited\n")
    before = git(inst.root, "rev-parse", "HEAD")

    with pytest.raises(NothingToCommit):
        commit_planning(inst, UNIT, "Plan it")

    assert git(inst.root, "rev-parse", "HEAD") == before
    assert git(inst.root, "status", "--porcelain").split() == ["M", SOURCE]


def test_a_separate_planning_repository_commits_every_file(tmp_path: Path) -> None:
    inst = separate_planning(tmp_path)
    (inst.root / CHANGE).write_text(EDITED_TASKS)
    (inst.root / OUTSIDE).parent.mkdir()
    (inst.root / OUTSIDE).write_text("notes\n")

    commit_planning(inst, UNIT, "Plan it")

    assert committed(inst.root) == sorted([CHANGE, OUTSIDE])
    assert git(inst.root, "status", "--porcelain") == ""
