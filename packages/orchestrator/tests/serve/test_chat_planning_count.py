"""The planning changes the chat records on a free session's lease are the planning paths only in
an in-repo installation, and committing them releases only what the commit took (spec:
planning-state-paths). Real git; the chat is driven at the step the end of a turn calls.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.attach import commit_planning
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.serve.chat import Chat
from tests.attach_driver import unit_worktree
from tests.factories import git, stored_unit
from tests.planning_paths_support import (
    CHANGE,
    EDITED_TASKS,
    OUTSIDE,
    SOURCE,
    edit_change_and_source,
    in_repo_planning,
    separate_planning,
)

UNIT = stored_unit("feature/1", change="feature", branch="spec/feature/1")


def held_by_a_free_session(inst: Installation) -> tuple[Chat, Leases]:
    """A chat over `inst` whose tab `t1` holds the unit's worktree with one changed file in it,
    and no session of the unit's own recorded, so the session is a free one."""
    UnitStore(inst.state_dir / "units.json").upsert([UNIT])
    git(inst.root, "add", "-A")  # the store is tracked: recording the unit is not a change
    git(inst.root, "commit", "-qm", "units")
    (unit_worktree(inst, UNIT) / "scratch.txt").write_text("mine\n")
    leases = Leases(lease_dir(inst.local_dir))
    assert leases.take(UNIT.id, "tab:t1", checkouts=("worktree",), session="free", head="abc")
    return Chat(inst, units=lambda: [UNIT], recorded_session=lambda unit_id: None), leases


def test_a_source_file_in_an_in_repo_tree_is_not_a_planning_change(tmp_path: Path) -> None:
    inst, _ = in_repo_planning(tmp_path)
    chat, leases = held_by_a_free_session(inst)
    edit_change_and_source(inst.root)

    chat.note_changes(UNIT, "t1")

    held = leases.attachment(UNIT.id)
    assert held is not None
    assert set(held.checkouts) == {"worktree", "planning"}
    assert held.changed == 2, "the unit's file and the change; not the two source files"


def test_a_tree_with_only_a_source_file_adds_no_planning_checkout(tmp_path: Path) -> None:
    inst, _ = in_repo_planning(tmp_path)
    chat, leases = held_by_a_free_session(inst)
    (inst.root / SOURCE).write_text("edited\n")

    chat.note_changes(UNIT, "t1")

    held = leases.attachment(UNIT.id)
    assert held is not None
    assert held.checkouts == ("worktree",)
    assert held.changed == 1


def test_the_commit_releases_the_planning_checkout_and_keeps_the_unit_files(
    tmp_path: Path,
) -> None:
    inst, _ = in_repo_planning(tmp_path)
    chat, leases = held_by_a_free_session(inst)
    edit_change_and_source(inst.root)
    chat.note_changes(UNIT, "t1")

    commit_planning(inst, UNIT, "Plan it")

    assert (inst.root / SOURCE).read_text() == "edited\n"
    assert SOURCE in git(inst.root, "status", "--porcelain"), "the source file was not taken"
    held = leases.attachment(UNIT.id)
    assert held is not None
    assert held.checkouts == ("worktree",), "only the planning checkout was taken"
    assert held.changed == 1, "the source files left in the planning root are not counted"
    chat.note_changes(UNIT, "t1")
    again = leases.attachment(UNIT.id)
    assert again is not None and again.changed == 1 and again.checkouts == ("worktree",)


def test_a_separate_root_counts_every_file_a_free_session_left(tmp_path: Path) -> None:
    inst = separate_planning(tmp_path)
    chat, leases = held_by_a_free_session(inst)
    (inst.root / CHANGE).write_text(EDITED_TASKS)
    (inst.root / OUTSIDE).parent.mkdir()
    (inst.root / OUTSIDE).write_text("notes\n")

    chat.note_changes(UNIT, "t1")

    held = leases.attachment(UNIT.id)
    assert held is not None
    assert set(held.checkouts) == {"worktree", "planning"}
    assert held.changed == 3, "the unit's file, the change and the file outside the planning paths"
