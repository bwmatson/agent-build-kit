"""A group that names only test files or test-support modules is `tests_only`: it edits test
code, which has no failing test to be written before it (spec: group-build-modes)."""

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.group_paths import allows_tests_only
from agent_build_kit.pipeline.work_graph import GroupMode
from tests.factories import planning
from tests.pipeline.test_group_mode_floor import read, unit_group


@pytest.mark.parametrize(
    "task",
    [
        "- [ ] 1.1 Fix `tests/test_foo.py`.\n",
        "- [ ] 1.1 Fix `tests/test_foo.py` and `tests/helpers.py`.\n",
        "- [ ] 1.1 Fix `tests/pipeline/test_foo.py::test_a_case`.\n",
        "- [ ] 1.1 Fix `tests/test_foo.py` and describe it in `docs/cli.md`.\n",
        "- [ ] 1.1 Fix `tests/test_foo.py` and add a bullet to `CHANGELOG.md`.\n",
    ],
)
def test_a_group_that_names_only_test_paths_is_tests_only(task: str, tmp_path: Path) -> None:
    group = unit_group(task, tmp_path)

    assert group.mode is GroupMode.TESTS_ONLY
    assert group.test_only is True


@pytest.mark.parametrize(
    "task",
    [
        "- [ ] 1.1 Fix `tests/test_foo.py` and `src/pkg/foo.py`.\n",
        "- [ ] 1.1 Fix `tests/helpers.py` and edit `pyproject.toml`.\n",
        "- [ ] 1.1 Fix `tests/test_foo.py`.\n- [ ] 1.2 Edit `web/src/App.tsx`.\n",
    ],
)
def test_a_test_path_with_a_source_file_keeps_the_code_floor(task: str, tmp_path: Path) -> None:
    group = unit_group(task, tmp_path)

    assert group.mode is GroupMode.TESTS_AND_CODE
    assert group.test_only is False


def test_a_group_that_names_no_path_keeps_the_code_floor(tmp_path: Path) -> None:
    assert unit_group("- [ ] 1.1 Make the tests faster.\n", tmp_path).mode is (
        GroupMode.TESTS_AND_CODE
    )


def test_tests_required_raises_a_test_only_group_to_the_code_floor(tmp_path: Path) -> None:
    group = unit_group(
        "- [ ] 1.1 Fix `tests/test_foo.py`.\n\nTests: required — the helper is read by a tool\n",
        tmp_path,
    )

    assert group.mode is GroupMode.TESTS_AND_CODE
    assert group.test_only is False


def test_an_e2e_group_stays_tests_only_beside_a_source_path(tmp_path: Path) -> None:
    group = read("1. [app] [e2e-test] Drive it", "- [ ] 1.1 Edit `src/app/main.py`.\n", tmp_path)

    assert group.mode is GroupMode.TESTS_ONLY


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["tests/test_foo.py"], True),
        (["tests/helpers.py", "tests/test_foo.py"], True),
        (["tests/test_foo.py", "docs/cli.md"], True),
        (["docs/cli.md"], False),
        ([], False),
        (["tests/test_foo.py", "src/pkg/foo.py"], False),
        (["tests/test_foo.py", "pyproject.toml"], False),
        (["tests/test_foo.py", "CHANGELOG.md"], True),
        (["tests/conftest.py"], True),
        (["web/src/__tests__/a.tsx"], True),
        (["web/src/App.test.tsx"], True),
        (["web/src/App.spec.ts"], True),
        (["src/app/tests/x.py"], True),
        (["src/app/testing/x.py"], False),
        (["src/app/testing/mock_server.py"], False),
        (["src/app/test/x.py"], False),
        (["tests/test_foo.py", "src/app/testing/x.py"], False),
    ],
)
def test_allows_tests_only_reads_the_labels_of_the_paths(paths: list[str], expected: bool) -> None:
    assert allows_tests_only(paths) is expected


def test_abk_tags_prints_the_tests_only_mode(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    inst = planning(tmp_path)
    folder = inst.changes_dir / "feature"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(
        "# Tasks\n\nAcceptance: none — a fixture about test paths\n\n"
        "## 1. [app] [unit-test] Fix it\n\n- [ ] 1.1 Fix `tests/test_foo.py`.\n"
    )

    code = cli.cmd_tags(argparse.Namespace(all=False, change="feature"), inst)

    assert code == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if x.strip().startswith("1."))
    assert GroupMode.TESTS_ONLY.value in line


@pytest.mark.parametrize(
    "task",
    [
        "- [ ] 1.1 Fix `src/app/testing/mock_server.py`.\n",
        "- [ ] 1.1 Fix `src/app/test/x.py`.\n",
    ],
)
def test_a_product_module_in_a_testing_folder_keeps_the_code_floor(
    task: str, tmp_path: Path
) -> None:
    assert unit_group(task, tmp_path).mode is GroupMode.TESTS_AND_CODE


@pytest.mark.parametrize(
    "task",
    [
        "- [ ] 1.1 Edit `tests/test_a.py` and `*.py`.\n",
        "- [ ] 1.1 Edit `tests/test_a.py` and `**/*.py`.\n",
    ],
)
def test_a_glob_with_no_folder_may_change_any_source_file(task: str, tmp_path: Path) -> None:
    assert unit_group(task, tmp_path).mode is GroupMode.TESTS_AND_CODE


def test_a_glob_under_tests_is_test_code(tmp_path: Path) -> None:
    group = unit_group("- [ ] 1.1 Edit `tests/pipeline/**`.\n", tmp_path)

    assert group.mode is GroupMode.TESTS_ONLY


def test_a_paths_line_of_test_paths_is_tests_only(tmp_path: Path) -> None:
    group = unit_group(
        "Paths: `tests/test_foo.py`, `tests/helpers.py`\n\n- [ ] 1.1 Make it faster.\n", tmp_path
    )

    assert group.mode is GroupMode.TESTS_ONLY


def test_a_paths_line_with_a_source_path_keeps_the_code_floor(tmp_path: Path) -> None:
    group = unit_group(
        "Paths: `tests/test_foo.py`, `src/pkg/foo.py`\n\n- [ ] 1.1 Make it faster.\n", tmp_path
    )

    assert group.mode is GroupMode.TESTS_AND_CODE


def test_an_e2e_group_stays_tests_only_when_tests_are_required(tmp_path: Path) -> None:
    group = read(
        "1. [app] [e2e-test] Drive it",
        "- [ ] 1.1 Edit `src/app/main.py`.\n\nTests: required — it is read at start\n",
        tmp_path,
    )

    assert group.mode is GroupMode.TESTS_ONLY
