"""A pure move of a task keeps its item; an ambiguous one is a conflict (spec: tracker-mapping)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.task_progress import text_hash
from agent_build_kit.pipeline.tracker_file import (
    Reconciled,
    TaskEntry,
    TrackerFile,
    reconcile_moves,
)
from agent_build_kit.pipeline.work_graph import read_tasks


def recorded(lines: dict[str, str]) -> TrackerFile:
    """A tracker file whose item for each key is `item-<key>`, hashed from the given first line."""
    return TrackerFile(
        kind="local",
        target="board",
        tasks={
            key: TaskEntry(id=f"item-{key}", text_hash=text_hash(line))
            for key, line in lines.items()
        },
    )


def reconcile(tmp_path: Path, tracker: TrackerFile, body: str) -> Reconciled:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(f"# Tasks\n\n## 2. [app] [unit-test] Second\n\n{body}")
    return reconcile_moves(tracker, read_tasks(tasks, "feature"))


def test_a_renumbered_task_keeps_its_item_id(tmp_path: Path) -> None:
    tracker = recorded({"feature:2.1": "Do two"})

    result = reconcile(tmp_path, tracker, "- [ ] 2.2 Do two\n")

    assert result.moved == {"feature:2.1": "feature:2.2"}
    assert set(result.tracker.tasks) == {"feature:2.2"}
    assert result.tracker.tasks["feature:2.2"].id == "item-feature:2.1"
    assert (result.created, result.removed, result.conflicts) == ((), (), ())


def test_two_tasks_swapping_places_each_keep_their_item(tmp_path: Path) -> None:
    tracker = recorded({"feature:2.1": "Do two", "feature:2.2": "Do three"})

    result = reconcile(tmp_path, tracker, "- [ ] 2.1 Do three\n- [ ] 2.2 Do two\n")

    assert result.tracker.tasks["feature:2.1"].id == "item-feature:2.2"
    assert result.tracker.tasks["feature:2.2"].id == "item-feature:2.1"
    assert (result.created, result.removed, result.conflicts) == ((), (), ())


def test_a_hash_matching_two_tasks_moves_nothing_and_is_a_conflict(tmp_path: Path) -> None:
    tracker = recorded({"feature:2.1": "Do two"})

    result = reconcile(tmp_path, tracker, "- [ ] 2.2 Do two\n- [ ] 2.3 Do two\n")

    assert result.moved == {}
    assert result.tracker == tracker
    assert len(result.conflicts) == 1
    assert "feature:2.1" in result.conflicts[0]
