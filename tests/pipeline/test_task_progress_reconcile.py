"""The copy of a change's `tasks.md` is the repository text with ticks looked up by number."""

import os
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.task_progress import reconcile
from tests.progress_support import (
    copy_file,
    planning,
    repository_file,
    write_copy,
    write_repository,
)

CHANGE = "add-marker"

TWO_GROUPS = """\
## 1. [app] [unit-test] Alpha
- [ ] 1.1 Test: a
- [ ] 1.2 Do a

## 2. [app] [unit-test] Beta
- [ ] 2.1 Test: b
- [ ] 2.2 Do b
"""
FIRST_DONE = TWO_GROUPS.replace("- [ ] 1.", "- [x] 1.")
BOTH_DONE = TWO_GROUPS.replace("- [ ]", "- [x]")
GAMMA = "\n## 3. [app] [unit-test] Gamma\n- [ ] 3.1 Test: c\n"


def reconciled(tmp_path: Path, repository: str, copy: str) -> tuple[Installation, str]:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, repository)
    write_copy(inst, CHANGE, copy)
    reconcile(inst, CHANGE)
    return inst, copy_file(inst, CHANGE).read_text()


def test_a_group_added_is_appended_unticked(tmp_path: Path) -> None:
    _, text = reconciled(tmp_path, TWO_GROUPS + GAMMA, BOTH_DONE)

    assert text == BOTH_DONE + GAMMA


def test_a_group_removed_is_dropped_and_the_others_keep_their_ticks(tmp_path: Path) -> None:
    repository = "## 2." + TWO_GROUPS.split("\n## 2.")[1]
    copy = FIRST_DONE.replace("- [ ] 2.1", "- [x] 2.1")

    _, text = reconciled(tmp_path, repository, copy)

    assert "Alpha" not in text and "1.1" not in text
    assert "- [x] 2.1 Test: b" in text
    assert "- [ ] 2.2 Do b" in text


def test_a_task_added_to_a_fully_ticked_group_is_ticked(tmp_path: Path) -> None:
    repository = TWO_GROUPS.replace("- [ ] 1.2 Do a\n", "- [ ] 1.2 Do a\n- [ ] 1.3 Also a\n")

    _, text = reconciled(tmp_path, repository, FIRST_DONE)

    assert "- [x] 1.3 Also a" in text
    assert "- [ ] 2.1 Test: b" in text


def test_a_task_added_to_a_partly_ticked_group_is_not(tmp_path: Path) -> None:
    partly = TWO_GROUPS.replace("- [ ] 1.1", "- [x] 1.1")
    repository = TWO_GROUPS.replace("- [ ] 1.2 Do a\n", "- [ ] 1.2 Do a\n- [ ] 1.3 Also a\n")

    _, text = reconciled(tmp_path, repository, partly)

    assert "- [ ] 1.3 Also a" in text
    assert "- [x] 1.1 Test: a" in text


def test_edited_headings_and_a_new_needs_line_show_with_ticks_on_the_same_numbers(
    tmp_path: Path,
) -> None:
    repository = TWO_GROUPS.replace(
        "## 1. [app] [unit-test] Alpha\n",
        "## 1. [app] [unit-test] Alpha, reworded\n\nNeeds: other-change group 1 merged\n\n",
    ).replace("- [ ] 2.2 Do b", "- [ ] 2.2 Do b, in other words")

    _, text = reconciled(tmp_path, repository, FIRST_DONE)

    assert text == repository.replace("- [ ] 1.", "- [x] 1.")


def test_a_renumbered_group_moves_its_ticks_with_the_number(tmp_path: Path) -> None:
    swapped = (
        "## 1. [app] [unit-test] Beta\n- [ ] 1.1 Test: b\n- [ ] 1.2 Do b\n\n"
        "## 2. [app] [unit-test] Alpha\n- [ ] 2.1 Test: a\n- [ ] 2.2 Do a\n"
    )

    _, text = reconciled(tmp_path, swapped, FIRST_DONE)

    assert text == swapped.replace("- [ ] 1.", "- [x] 1.")


def test_a_deleted_repository_file_leaves_the_copy_as_it_is(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_copy(inst, CHANGE, FIRST_DONE)

    reconcile(inst, CHANGE)

    assert copy_file(inst, CHANGE).read_text() == FIRST_DONE


def test_an_unreadable_repository_file_leaves_the_copy_as_it_is(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    repository_file(inst, CHANGE).mkdir(parents=True)
    write_copy(inst, CHANGE, FIRST_DONE)

    reconcile(inst, CHANGE)

    assert copy_file(inst, CHANGE).read_text() == FIRST_DONE


def test_no_repository_file_and_no_copy_creates_none(tmp_path: Path) -> None:
    inst = planning(tmp_path)

    reconcile(inst, CHANGE)

    assert not copy_file(inst, CHANGE).exists()


def test_a_second_reconcile_with_no_edit_does_not_rewrite_the_file(tmp_path: Path) -> None:
    inst, before = reconciled(tmp_path, TWO_GROUPS + GAMMA, FIRST_DONE)
    path = copy_file(inst, CHANGE)
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))

    reconcile(inst, CHANGE)

    assert path.read_text() == before
    assert path.stat().st_mtime_ns == 1_000_000_000
