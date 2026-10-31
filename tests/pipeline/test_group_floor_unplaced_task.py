"""A group is tests-only or no-code only when each of its tasks is placed: a test task, a check,
or one that names a path. A prose task that changes code and names no file makes the group code
(spec: group-floor-reads-every-task).

The floor used to read the paths of the whole group together, so a test task that named a test
file beside an implementation task that named nothing looked like a group that "names only test
files", and the build wrote its tests and no implementation."""

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import group_paths
from agent_build_kit.pipeline.work_graph import GroupMode
from tests.factories import planning
from tests.pipeline.test_group_mode_floor import read, unit_group

TEST_TASK = "- [ ] 1.1 Test: `tests/pipeline/test_x.py` covers it.\n"


def test_a_test_task_beside_an_implementation_task_that_names_no_file_is_code(
    tmp_path: Path,
) -> None:
    group = unit_group(
        TEST_TASK + "- [ ] 1.2 Add the level-aware parenting to the tracker. Verify: 1.1 passes.\n",
        tmp_path,
    )

    assert group.mode is GroupMode.TESTS_AND_CODE
    assert group.test_only is False


def test_a_group_whose_every_task_names_test_files_stays_tests_only(tmp_path: Path) -> None:
    group = unit_group(
        "- [ ] 1.1 Fix `tests/test_a.py`.\n- [ ] 1.2 Fix `tests/test_b.py`.\n", tmp_path
    )

    assert group.mode is GroupMode.TESTS_ONLY


@pytest.mark.parametrize(
    "check",
    [
        "Confirm the node ids are unchanged apart from their paths",
        "Check that the suite passes",
        "Verify the repeat run passes",
        "Read the output and note what ran",
        "Run the repeat check on the changed tests",
    ],
)
def test_a_check_that_names_no_path_does_not_make_a_test_only_group_code(
    check: str, tmp_path: Path
) -> None:
    group = unit_group(f"- [ ] 1.1 Fix `tests/test_a.py`.\n- [ ] 1.2 {check}.\n", tmp_path)

    assert group.mode is GroupMode.TESTS_ONLY


def test_a_test_task_that_names_no_path_does_not_make_the_group_code(tmp_path: Path) -> None:
    group = unit_group(
        "- [ ] 1.1 Fix `tests/test_a.py`.\n- [ ] 1.2 Test: the repeat run passes.\n", tmp_path
    )

    assert group.mode is GroupMode.TESTS_ONLY


def test_a_command_that_names_its_paths_counts_as_naming_them(tmp_path: Path) -> None:
    group = unit_group(
        "- [ ] 1.1 Fix `tests/test_a.py`.\n- [ ] 1.2 `git mv tests/test_b.py tests/c/test_b.py`\n",
        tmp_path,
    )

    assert group.mode is GroupMode.TESTS_ONLY


def test_a_documents_group_with_an_implementation_task_that_names_no_file_is_not_no_code(
    tmp_path: Path,
) -> None:
    group = unit_group(
        "- [ ] 1.1 Describe it in `docs/cli.md`.\n- [ ] 1.2 Wire the step into the tick.\n",
        tmp_path,
    )

    assert group.mode is GroupMode.TESTS_AND_CODE


def test_a_documents_group_whose_every_task_names_a_document_may_still_be_no_code(
    tmp_path: Path,
) -> None:
    group = unit_group(
        "- [ ] 1.1 Describe it in `docs/cli.md`.\n- [ ] 1.2 Add a bullet to `CHANGELOG.md`.\n",
        tmp_path,
    )

    assert group.mode is GroupMode.NO_CODE


def test_an_e2e_group_stays_tests_only_beside_a_task_that_names_no_path(tmp_path: Path) -> None:
    group = read(
        "1. [app] [e2e-test] Drive it",
        "- [ ] 1.1 Test: `tests/e2e/test_a.py` drives it.\n- [ ] 1.2 Wire it up.\n",
        tmp_path,
    )

    assert group.mode is GroupMode.TESTS_ONLY


def test_a_paths_line_still_decides_what_the_group_names(tmp_path: Path) -> None:
    group = unit_group(
        "Paths: `tests/test_foo.py`\n\n" + TEST_TASK + "- [ ] 1.2 Make it faster.\n", tmp_path
    )

    assert group.mode is GroupMode.TESTS_ONLY


def test_tests_required_still_raises_the_floor(tmp_path: Path) -> None:
    group = unit_group(
        "Tests: required — the helper is read by a tool\n\n"
        "- [ ] 1.1 Fix `tests/test_a.py`.\n- [ ] 1.2 Fix `tests/test_b.py`.\n",
        tmp_path,
    )

    assert group.mode is GroupMode.TESTS_AND_CODE


def test_names_unplaced_work_is_true_for_a_task_that_changes_code_and_names_no_file(
    tmp_path: Path,
) -> None:
    group = unit_group(TEST_TASK + "- [ ] 1.2 Add the parenting to the tracker.\n", tmp_path)

    assert group_paths.names_unplaced_work(group, []) is True


def test_names_unplaced_work_is_false_when_every_task_is_placed(tmp_path: Path) -> None:
    group = unit_group(TEST_TASK + "- [ ] 1.2 Fix `tests/test_b.py`.\n", tmp_path)

    assert group_paths.names_unplaced_work(group, []) is False


def test_abk_tags_prints_tests_and_code_for_a_group_with_an_unplaced_task(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    inst = planning(tmp_path)
    folder = inst.changes_dir / "feature"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(
        "# Tasks\n\nAcceptance: none — a fixture about the floor\n\n"
        "## 1. [app] [unit-test] Add it\n\n" + TEST_TASK + "- [ ] 1.2 Add the parenting.\n"
    )

    code = cli.cmd_tags(argparse.Namespace(all=False, change="feature"), inst)

    assert code == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if x.strip().startswith("1."))
    assert GroupMode.TESTS_AND_CODE.value in line
