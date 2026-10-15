"""A unit the pipeline landed itself is recorded merged through the path a person's merge takes.

Only the cause differs: `auto_landed` says the pipeline did it, and everything
that follows a merge (the restack, the retarget, the cleanup, the release of a
child held for depth) is the same as when a person merged.
"""

from pathlib import Path

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED
from tests.factories import stored_unit as unit


def deep_store(path: Path) -> UnitStore:
    """c/2 on c/1, c/3 on c/2, and c/4 on both c/1 and c/3: merging c/1 leaves c/4 too deep."""
    store = UnitStore(path)
    store.upsert(
        [
            unit("c/1"),
            unit("c/2", depends_on=("c/1",)),
            unit("c/3", depends_on=("c/2",)),
            unit("c/4", depends_on=("c/1", "c/3")),
        ]
    )
    for n in (1, 2, 3, 4):
        store.set_state(f"c/{n}", IN_REVIEW, pr=n, branch=f"spec/c/{n}")
    return store


def land(store: UnitStore, pr: int, cause: Cause | None) -> dict:
    """Record the merge of `pr` and return everything it did, as one comparable value."""
    restacked: list[tuple[str, str, str]] = []
    removed: list[str] = []
    deleted: list[str] = []
    retargeted: list[tuple[str, str]] = []
    handled = events.on_merged(
        pr,
        repo="app",
        store=store,
        restack=lambda **k: restacked.append((k["branch"], k["old_base"], k["new_base"])),
        remove_worktree=lambda repo, branch: removed.append(branch),
        delete_branch=lambda repo, branch: deleted.append(branch),
        retarget=lambda u, base: retargeted.append((u.id, base)),
        rebase_cap=2,
        log=lambda m: None,
        cause=cause or Cause.MERGED,
    )
    return dict(
        handled=handled,
        restacked=restacked,
        removed=removed,
        deleted=deleted,
        retargeted=retargeted,
        states={u.id: u.state for u in store.all()},
    )


def test_the_unit_is_recorded_merged_with_the_cause_auto_landed(tmp_path: Path) -> None:
    store = deep_store(tmp_path / "units.json")

    land(store, 1, Cause.AUTO_LANDED)

    stored = store.get("c/1")
    assert stored.state == MERGED
    assert stored.cause == Cause.AUTO_LANDED
    assert stored.history[-1]["cause"] == "auto_landed"


def test_children_and_cleanup_are_as_a_person_s_merge_leaves_them(tmp_path: Path) -> None:
    by_person = land(deep_store(tmp_path / "person.json"), 1, None)
    by_pipeline = land(deep_store(tmp_path / "pipeline.json"), 1, Cause.AUTO_LANDED)

    assert by_pipeline == by_person
    assert by_pipeline["restacked"] == [("spec/c/2", "spec/c/1", "main")]
    assert by_pipeline["retargeted"] == [("c/4", "spec/c/3")]
    assert by_pipeline["removed"] == ["spec/c/1"]
    assert by_pipeline["deleted"] == [], "c/4, held for depth, still builds on its branch"


def test_a_landing_removes_the_worktree_and_branch_once_nothing_builds_on_it(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path / "units.json")
    store.set_state("c/2", MERGED)
    store.set_state("c/4", MERGED)

    landed = land(store, 3, Cause.AUTO_LANDED)

    assert landed["removed"] == ["spec/c/3"]
    assert landed["deleted"] == ["spec/c/3"]
    assert store.get("c/3").cause == Cause.AUTO_LANDED


def test_a_child_held_for_depth_is_released_when_a_landing_brings_it_within_the_cap(
    tmp_path: Path,
) -> None:
    by_person = deep_store(tmp_path / "person.json")
    by_pipeline = deep_store(tmp_path / "pipeline.json")
    land(by_person, 1, None)
    land(by_pipeline, 1, Cause.AUTO_LANDED)
    assert by_pipeline.get("c/4").state == HELD

    released_by_person = land(by_person, 2, None)
    released = land(by_pipeline, 2, Cause.AUTO_LANDED)

    assert by_pipeline.get("c/4").state == IN_REVIEW
    assert by_pipeline.get("c/2").cause == Cause.AUTO_LANDED
    assert ("spec/c/4", "spec/c/1", "spec/c/3") in released["restacked"]
    assert released == released_by_person
