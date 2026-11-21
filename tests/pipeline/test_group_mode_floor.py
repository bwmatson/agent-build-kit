"""The floor build mode of a task group, read from its tier and the paths its tasks name."""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.group_paths import named_paths
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


def test_a_tests_line_names_no_path_even_when_its_reason_quotes_one(tmp_path: Path) -> None:
    group = unit_group(
        "- [ ] 1.1 Describe the mode in `docs/cli.md`.\n\n"
        "Tests: required — it guards `src/app/main.py` reading the mode\n",
        tmp_path,
    )

    assert named_paths(group, []) == ["docs/cli.md"]
    assert group.mode is GroupMode.TESTS_AND_CODE


MODE_LINE = "Mode: refactor — moves and renames only"
SOURCE_TASK = "- [ ] 1.1 Move `src/app/old.py` to `src/app/new.py` and fix `tests/test_old.py`.\n"


def declared(heading: str, body: str, folder: Path) -> tuple[list[TaskGroup], list, str]:
    folder.mkdir(parents=True, exist_ok=True)
    text = f"# Tasks\n\n{OPT_OUT}\n## {heading}\n\n{body}"
    (folder / "tasks.md").write_text(text)
    groups, errors = validate_tasks(folder / "tasks.md")
    return groups, errors, text


def test_a_group_that_declares_a_reorganization_is_read_with_that_mode_and_reason(
    tmp_path: Path,
) -> None:
    groups, errors, _ = declared(
        "1. [app] [unit-test] Move it", f"{MODE_LINE}\n\n{SOURCE_TASK}", tmp_path
    )

    assert errors == []
    assert groups[0].declared_mode is GroupMode.REFACTOR
    assert groups[0].declared_reason == "moves and renames only"


@pytest.mark.parametrize(
    ("heading", "line", "tasks", "why"),
    [
        ("1. [app] [unit-test] Move it", "Mode: refactor", SOURCE_TASK, "reason"),
        ("1. [app] [unit-test] Move it", "Mode: refactor —", SOURCE_TASK, "reason"),
        (
            "1. [app] [unit-test] Move it",
            "Mode: tests_only — nothing else",
            SOURCE_TASK,
            "refactor",
        ),
        ("1. [app] [e2e-test] Move it", MODE_LINE, SOURCE_TASK, "e2e-test"),
        (
            "1. [app] [unit-test] Move it",
            MODE_LINE,
            "- [ ] 1.1 Edit `docs/cli.md` and `CHANGELOG.md`.\n",
            "no_code",
        ),
        (
            "1. [app] [unit-test] Move it",
            MODE_LINE,
            "- [ ] 1.1 Edit `tests/test_old.py`.\n",
            "tests_only",
        ),
        (
            "1. [app] [unit-test] Move it",
            MODE_LINE,
            SOURCE_TASK + "- [ ] 1.2 Test: the new path is read.\n",
            "Test:",
        ),
        (
            "1. [app] [unit-test] Move it",
            MODE_LINE,
            SOURCE_TASK + "- [ ] 1.2 Tests: the new path is read.\n",
            "Test:",
        ),
        ("1. [app] [unit-test] Move it", "Mode:", SOURCE_TASK, "refactor"),
        ("1. [app] [unit-test] Move it", "Mode: — moves only", SOURCE_TASK, "refactor"),
        ("1. [app] [unit-test] Move it", "Mode: no-code — docs", SOURCE_TASK, "refactor"),
        (
            "1. [app] [unit-test] Move it",
            f"{MODE_LINE}\nTests: required — the move is risky",
            SOURCE_TASK,
            "Tests:",
        ),
        (
            "1. [app] [unit-test] Move it",
            MODE_LINE,
            SOURCE_TASK + "- [ ] 1.2 Add a new test file `tests/test_new.py`.\n",
            "new test file",
        ),
    ],
    ids=[
        "no reason",
        "empty reason",
        "other value",
        "e2e group",
        "no_code floor",
        "tests_only floor",
        "Test: task",
        "Tests: task",
        "no value",
        "no value before a reason",
        "hyphenated value",
        "Tests: required",
        "new test file",
    ],
)
def test_a_declared_reorganization_the_group_cannot_be_is_an_error_naming_the_line(
    heading: str, line: str, tasks: str, why: str, tmp_path: Path
) -> None:
    _, errors, text = declared(heading, f"{line}\n\n{tasks}", tmp_path)

    at = text.splitlines().index(line.splitlines()[0]) + 1
    assert [e.message for e in errors if e.line == at and why in e.message] != []


def test_a_group_that_names_source_files_and_existing_test_files_may_declare_it(
    tmp_path: Path,
) -> None:
    groups, errors, _ = declared(
        "1. [app] [unit-test] Move it",
        f"{MODE_LINE}\n\n{SOURCE_TASK}- [ ] 1.2 Update `tests/test_other.py` for the new path.\n",
        tmp_path,
    )

    assert errors == []
    assert groups[0].declared_mode is GroupMode.REFACTOR
