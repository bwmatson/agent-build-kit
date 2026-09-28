"""Ticking a unit's tasks off — by the pipeline, when the unit is done."""

from pathlib import Path

from agent_build_kit.pipeline.task_progress import mark_groups

TASKS = """\
## 1. [platform] [tier1] First
- [x] 1.1 Test: one
- [ ] 1.2 Do one

## 2. [platform] [tier1] Second
- [ ] 2.1 Test: two, which mentions 1.2 in passing
- [ ] 2.10 Do two
- [ ] 12.1 Not group 1 or 2
"""


def test_a_unit_s_groups_are_ticked_and_nothing_else(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(TASKS)

    mark_groups(tasks, (2,), done=True)

    text = tasks.read_text()
    assert "- [x] 2.1 Test: two" in text
    assert "- [x] 2.10 Do two" in text
    assert "- [ ] 1.2 Do one" in text
    assert "- [ ] 12.1 Not group" in text, "2 is not a prefix match for 12"


def test_a_failed_unit_s_groups_are_unticked(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(TASKS)

    mark_groups(tasks, (1,), done=False)

    assert "- [ ] 1.1 Test: one" in tasks.read_text()


def test_the_text_of_a_task_is_never_changed(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(TASKS)

    mark_groups(tasks, (1, 2), done=True)
    mark_groups(tasks, (1, 2), done=False)

    assert tasks.read_text() == TASKS.replace("- [x] 1.1", "- [ ] 1.1")
