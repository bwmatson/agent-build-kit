"""The runner ticks and records follow-ups in the tracking copy, never in the pipeline worktree."""

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import UnitRunner, unit_follow_ups
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Member
from tests.factories import git, stored_unit
from tests.planning_worktree_support import InRepo, in_repo, installation_at
from tests.progress_support import copy_file, ticked
from tests.runner_fakes import Recorder, make_runner

OWN, OTHER = "add-marker", "sample-change"
CARRIED = Member(change=OTHER, groups=(7, 8))


def tasks_text(groups: tuple[int, ...]) -> str:
    return "".join(
        f"## {g}. [app] [unit-test] G{g}\n- [ ] {g}.1 Test: a\n- [ ] {g}.2 Do a\n" for g in groups
    )


def joined(uid: str = f"{OWN}/1") -> StoredUnit:
    return stored_unit(uid, groups=(2,), joined=(CARRIED,))


def worktree_with_changes(tmp_path: Path) -> tuple[InRepo, Installation, UnitRunner]:
    """A pipeline worktree holding both changes' tasks files, its installation, and a runner over
    it; the state directory is outside the worktree."""
    setup = in_repo(
        tmp_path,
        files={
            f"openspec/changes/{OWN}/tasks.md": tasks_text((1, 2, 3)),
            f"openspec/changes/{OTHER}/tasks.md": tasks_text((6, 7, 8, 9)),
        },
    )
    inst = installation_at(
        setup.worktree, setup.working_copy, planning=dict(state_dir=str(tmp_path / "state"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([joined(), stored_unit(f"{OWN}/2", groups=(3,))])
    runner = make_runner(store, Recorder(store), tmp_path, planning_repo=setup.worktree)
    return setup, inst, runner


def status(setup: InRepo) -> str:
    return git(setup.worktree, "status", "--porcelain", "--untracked-files=all")


def test_mark_tasks_for_a_joined_unit_ticks_each_member_changes_own_copy(tmp_path: Path) -> None:
    setup, inst, runner = worktree_with_changes(tmp_path)

    runner.mark_tasks(joined(), done=True)

    assert ticked(copy_file(inst, OWN)) == {2}
    assert ticked(copy_file(inst, OTHER)) == {7, 8}
    assert status(setup) == ""

    runner.mark_tasks(joined(), done=False)

    assert ticked(copy_file(inst, OWN)) == set()
    assert ticked(copy_file(inst, OTHER)) == set()
    assert status(setup) == ""


def test_follow_ups_are_recorded_in_the_copy_and_none_appears_in_the_repository(
    tmp_path: Path,
) -> None:
    setup, inst, runner = worktree_with_changes(tmp_path)

    runner.record_follow_ups(joined(), ["rename the helper", "document the flag"])

    recorded = copy_file(inst, OWN, "follow-ups.md").read_text()
    assert "- rename the helper\n- document the flag\n" in recorded
    assert list((setup.worktree / "openspec" / "changes").rglob("follow-ups.md")) == []
    assert status(setup) == ""


def test_a_second_record_of_the_same_unit_replaces_its_block(tmp_path: Path) -> None:
    _, inst, runner = worktree_with_changes(tmp_path)
    other = stored_unit(f"{OWN}/2", groups=(3,))

    runner.record_follow_ups(joined(), ["first point"])
    runner.record_follow_ups(other, ["another unit's point"])
    runner.record_follow_ups(joined(), ["second point"])

    recorded = copy_file(inst, OWN, "follow-ups.md").read_text()
    assert "second point" in recorded and "first point" not in recorded
    assert recorded.count(f"## From `{OWN}/1`") == 1
    assert "another unit's point" in recorded


def test_the_readers_return_what_the_copy_holds(tmp_path: Path) -> None:
    setup, inst, runner = worktree_with_changes(tmp_path)
    runner.record_follow_ups(joined(), ["rename the helper"])

    assert copy_file(inst, OWN, "follow-ups.md").exists()
    assert "rename the helper" in runner.follow_ups_note(joined())
    assert runner.follow_ups_for(joined()) == ["rename the helper"]
    assert unit_follow_ups(setup.worktree, OWN, joined().id) == ("rename the helper",)


def test_a_repository_follow_ups_file_is_read_when_there_is_no_copy_and_seeds_the_copy(
    tmp_path: Path,
) -> None:
    setup, inst, runner = worktree_with_changes(tmp_path)
    written = setup.worktree / "openspec" / "changes" / OWN / "follow-ups.md"
    text = f"## From `{OWN}/2`\n\n- written by a person\n\n"
    written.write_text(text)
    earlier = stored_unit(f"{OWN}/2", groups=(3,))

    assert not copy_file(inst, OWN, "follow-ups.md").exists()
    assert "written by a person" in runner.follow_ups_note(joined())
    assert runner.follow_ups_for(earlier) == ["written by a person"]
    assert unit_follow_ups(setup.worktree, OWN, earlier.id) == ("written by a person",)

    runner.record_follow_ups(joined(), ["rename the helper"])

    kept = copy_file(inst, OWN, "follow-ups.md").read_text()
    assert "written by a person" in kept and "rename the helper" in kept
    assert written.read_text() == text, "the repository file is not written"


def test_the_copy_wins_over_a_repository_follow_ups_file(tmp_path: Path) -> None:
    setup, inst, runner = worktree_with_changes(tmp_path)
    written = setup.worktree / "openspec" / "changes" / OWN / "follow-ups.md"
    written.write_text(f"## From `{OWN}/1`\n\n- written by a person\n\n")
    copy = copy_file(inst, OWN, "follow-ups.md")
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(f"## From `{OWN}/1`\n\n- recorded by the pipeline\n\n")

    assert runner.follow_ups_for(joined()) == ["recorded by the pipeline"]
    assert "written by a person" not in runner.follow_ups_note(joined())


def test_the_worktree_is_clean_after_ticks_and_follow_ups_together(tmp_path: Path) -> None:
    setup, _, runner = worktree_with_changes(tmp_path)

    runner.mark_tasks(joined(), done=True)
    runner.record_follow_ups(joined(), ["a point"])
    runner.mark_tasks(joined(), done=False)
    runner.record_follow_ups(joined(), ["a point, reworded"])

    assert status(setup) == ""
