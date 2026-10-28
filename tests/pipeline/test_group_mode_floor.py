"""The floor build mode of a task group, read from its tier and the paths its tasks name."""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.work_graph import GroupMode, TaskGroup, validate_tasks

OPT_OUT = "Acceptance: none — a fixture about the mode of a group\n"


def read(heading: str, tasks: str, folder: Path) -> TaskGroup:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tasks.md").write_text(f"# Tasks\n\n{OPT_OUT}\n## {heading}\n\n{tasks}")
    groups, errors = validate_tasks(folder / "tasks.md")
    assert errors == []
    return groups[0]


def unit_group(tasks: str, folder: Path) -> TaskGroup:
    return read("1. [app] [unit-test] Cover it", tasks, folder)


@pytest.mark.parametrize(
    "heading",
    [
        "1. [app] [e2e-test] Drive it",
        "1. [app] [e2e-test] [acceptance] Drive it",
        "1. [app] [e2e-test] [narrow] Drive it",
    ],
)
def test_an_e2e_group_is_tests_only_whatever_its_text(heading: str, tmp_path: Path) -> None:
    group = read(heading, "- [ ] 1.1 Test: `docs/cli.md` is described.\n", tmp_path)

    assert group.mode is GroupMode.TESTS_ONLY
    assert group.test_only is True


@pytest.mark.parametrize(
    "task",
    [
        "- [ ] 1.1 Edit `src/app/main.py` to read the setting.\n",
        "- [ ] 1.1 Test: `tests/test_main.py` covers it.\n",
        "- [ ] 1.1 Edit `web/src/App.tsx`.\n",
    ],
)
def test_a_group_that_names_a_code_path_has_the_code_floor(task: str, tmp_path: Path) -> None:
    group = unit_group(task, tmp_path)

    assert group.mode is GroupMode.TESTS_AND_CODE
    assert group.test_only is False


def test_a_group_that_names_no_path_has_the_code_floor(tmp_path: Path) -> None:
    group = unit_group("- [ ] 1.1 Make the thing faster.\n", tmp_path)

    assert group.mode is GroupMode.TESTS_AND_CODE


@pytest.mark.parametrize(
    "task",
    [
        "- [ ] 1.1 Describe the mode in `docs/cli.md`.\n",
        "- [ ] 1.1 Add a bullet to `CHANGELOG.md`.\n",
        "- [ ] 1.1 Set the limit in `pyproject.toml`.\n",
        "- [ ] 1.1 Edit `config/settings.yml` and `config/other.yaml`.\n",
        "- [ ] 1.1 Edit `package.json`, `setup.cfg` and `tox.ini`.\n",
        "- [ ] 1.1 Edit `pyproject.toml` and `CHANGELOG.md`.\n",
    ],
)
def test_a_group_that_names_only_documents_or_configuration_may_be_no_code(
    task: str, tmp_path: Path
) -> None:
    group = unit_group(task, tmp_path)

    assert group.mode is GroupMode.NO_CODE
    assert group.test_only is False


def test_a_group_that_names_a_code_path_and_a_document_has_the_code_floor(
    tmp_path: Path,
) -> None:
    group = unit_group(
        "- [ ] 1.1 Edit `src/app/main.py`.\n- [ ] 1.2 Describe it in `docs/cli.md`.\n", tmp_path
    )

    assert group.mode is GroupMode.TESTS_AND_CODE


def test_a_group_that_names_configuration_and_a_code_path_has_the_code_floor(
    tmp_path: Path,
) -> None:
    group = unit_group("- [ ] 1.1 Edit `pyproject.toml` and `src/app/main.py`.\n", tmp_path)

    assert group.mode is GroupMode.TESTS_AND_CODE


def test_test_only_is_true_exactly_for_the_tests_only_mode(tmp_path: Path) -> None:
    e2e = read("1. [app] [e2e-test] Drive it", "- [ ] 1.1 Test: it.\n", tmp_path / "e2e")
    docs = unit_group("- [ ] 1.1 Edit `docs/cli.md`.\n", tmp_path / "docs")
    code = unit_group("- [ ] 1.1 Edit `src/app/main.py`.\n", tmp_path / "code")

    assert [g.mode for g in (e2e, docs, code)] == [
        GroupMode.TESTS_ONLY,
        GroupMode.NO_CODE,
        GroupMode.TESTS_AND_CODE,
    ]
    assert [g.test_only for g in (e2e, docs, code)] == [True, False, False]
