"""The task-group tag check.

`openspec/config.yaml`'s rules tell the model to tag each task group with the
repo it lands in and the test tier it needs, but rules are a prompt input, not
a check (docs/architecture.md). This is the check: it runs in CI on
the change's own PR, so a missing tag is caught in review rather than by a
failed run days later.
"""

import argparse
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.work_graph import (
    Need,
    TaskGroup,
    ValidationError,
    environment_setting_notes,
    group_needs,
    missing_test_folder_warnings,
    shared_test_file_warnings,
    shared_test_files,
    validate_tasks,
)
from tests.factories import commit_files, init_repo
from tests.project_workspace import app_with_projects

# tests/ mirrors src/, so the repo root is two levels up from this file.
REPO_ROOT = Path(__file__).resolve().parents[2]


WELL_FORMED = """# Tasks

## 1. [platform] [unit-test] Register the marker

- [ ] 1.1 Test: default selection deselects it.
- [ ] 1.2 Register it in pytest config.

## 2. [app] [e2e-test] Relay the event

- [ ] 2.1 Test: the consumer sees the event.
- [ ] 2.2 Publish it.
"""


# The fixtures below are about other rules, so they opt out of the
# acceptance group the way a change with nothing to exercise does; the
# acceptance tests at the end use parse_as_written.
OPT_OUT = "\nAcceptance: none — a fixture about another rule\n"


def parse_as_written(text: str, tmp_path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(text)
    return validate_tasks(tmp_path / "tasks.md")


def parse(text: str, tmp_path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    return parse_as_written(text + OPT_OUT, tmp_path)


def test_well_formed_tasks_parse_into_groups(tmp_path: Path) -> None:
    groups, errors = parse(WELL_FORMED, tmp_path)

    assert errors == []
    assert [(g.number, g.repo, g.tier) for g in groups] == [
        (1, "platform", "unit-test"),
        (2, "app", "e2e-test"),
    ]
    assert groups[0].title == "Register the marker"
    assert groups[0].task_count == 2


def test_missing_tags_are_reported_with_the_group_named(tmp_path: Path) -> None:
    _, errors = parse("# Tasks\n\n## 1. Register the marker\n\n- [ ] 1.1 Do it.\n", tmp_path)

    assert len(errors) == 1
    assert "1. Register the marker" in errors[0].message
    assert errors[0].line == 3


def test_a_tier_tag_alone_is_not_enough(tmp_path: Path) -> None:
    _, errors = parse("# Tasks\n\n## 1. [unit-test] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path)

    assert len(errors) == 1


@pytest.mark.parametrize("repo", ["App", "app-agent", "plat_form", ""])
def test_unknown_repos_are_rejected(repo: str, tmp_path: Path) -> None:
    """The repo tag routes the unit to a worktree, so a near-miss is a failure.

    A near-miss of `app` or `platform` would otherwise reach the runner and
    fail there, after the change had already been reviewed and merged.
    """
    _, errors = parse(
        f"# Tasks\n\n## 1. [{repo}] [unit-test] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path
    )

    assert len(errors) == 1
    assert "repo" in errors[0].message


@pytest.mark.parametrize("tier", ["tier3", "integration", "e2e", "2", ""])
def test_unknown_tiers_are_rejected(tier: str, tmp_path: Path) -> None:
    _, errors = parse(f"# Tasks\n\n## 1. [app] [{tier}] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path)

    assert len(errors) == 1
    assert "tier" in errors[0].message
    for tag in ("unit-test", "integration-test", "e2e-test"):
        assert tag in errors[0].message


def test_groups_must_be_numbered_from_one_in_order(tmp_path: Path) -> None:
    """Out-of-order numbering means the runner's unit order wouldn't match the
    author's intent, and the mismatch would be silent."""
    _, errors = parse(
        "# Tasks\n\n"
        "## 1. [app] [unit-test] First\n\n- [ ] 1.1 Do it.\n\n"
        "## 3. [app] [unit-test] Third\n\n- [ ] 3.1 Do it.\n",
        tmp_path,
    )

    assert len(errors) == 1
    assert "numbered" in errors[0].message


def test_an_empty_group_is_rejected(tmp_path: Path) -> None:
    _, errors = parse("# Tasks\n\n## 1. [app] [unit-test] Nothing here\n", tmp_path)

    assert len(errors) == 1
    assert "no tasks" in errors[0].message


def test_a_file_with_no_groups_is_rejected(tmp_path: Path) -> None:
    _, errors = parse("# Tasks\n\nNothing to do yet.\n", tmp_path)

    assert len(errors) == 1
    assert "no task groups" in errors[0].message


def test_all_bad_groups_are_reported_not_just_the_first(tmp_path: Path) -> None:
    """A CI run should show every tag to fix, not one per push."""
    _, errors = parse(
        "# Tasks\n\n"
        "## 1. Untagged\n\n- [ ] 1.1 Do it.\n\n"
        "## 2. [nope] [unit-test] Bad repo\n\n- [ ] 2.1 Do it.\n",
        tmp_path,
    )

    assert len(errors) == 2


def test_every_fixture_change_passes() -> None:
    """The changes shipped as fixtures are authored against these rules and
    have to satisfy them — the same check an installation runs over its own
    store with `abk tags --all`."""
    tasks_files = sorted(REPO_ROOT.glob("tests/fixtures/changes/**/tasks.md"))
    assert tasks_files, "no fixture changes found — the glob is wrong"

    problems = {
        str(path.relative_to(REPO_ROOT)): [str(e) for e in validate_tasks(path)[1]]
        for path in tasks_files
        if validate_tasks(path)[1]
    }

    assert problems == {}


CONTRACT_TASKS = """# Tasks

## 1. [platform] [unit-test] [contract] Add the new field

- [ ] 1.1 Test: the new field is accepted.
- [ ] 1.2 Add it alongside the old one.

## 2. [app] [unit-test] Consume the new field

- [ ] 2.1 Test: the consumer reads it.
- [ ] 2.2 Bump the pinned SHA and re-lock.

## 3. [platform] [unit-test] [narrow] Remove the old field

- [ ] 3.1 Test: the old field is gone.
- [ ] 3.2 Remove it.
"""


def test_a_contract_change_may_flag_itself(tmp_path: Path) -> None:
    """The flag is how a widening group says so, and the only reason to have it
    is that the narrowing group can then be required."""
    groups, errors = parse(CONTRACT_TASKS, tmp_path)

    assert errors == []
    assert [g.flag for g in groups] == ["contract", "", "narrow"]


def test_widening_without_narrowing_is_rejected(tmp_path: Path) -> None:
    """Without the final group the compatibility shim becomes the contract —
    which is exactly what nobody notices, so it is checked rather than trusted
    to a rule in config.yaml."""
    _, errors = parse(CONTRACT_TASKS.split("## 3.")[0], tmp_path)

    assert len(errors) == 1
    assert "narrow" in errors[0].message


def test_the_narrowing_group_has_to_come_last(tmp_path: Path) -> None:
    """A narrowing group with migration work after it removes the old shape
    while something still depends on it."""
    reordered = CONTRACT_TASKS.replace(
        "## 2. [app] [unit-test] Consume the new field",
        "## 2. [platform] [unit-test] [narrow] Remove the old field",
    ).replace(
        "## 3. [platform] [unit-test] [narrow] Remove the old field",
        "## 3. [app] [unit-test] Consume the new field",
    )

    _, errors = parse(reordered, tmp_path)

    assert len(errors) == 1
    assert "last" in errors[0].message


def test_a_change_touching_no_contract_needs_no_narrowing(tmp_path: Path) -> None:
    """Most changes widen nothing. The rule must not tax them."""
    groups, errors = parse(WELL_FORMED, tmp_path)

    assert errors == []
    assert [g.flag for g in groups] == ["", ""]


@pytest.mark.parametrize("flag", ["contracts", "narrowing", "unit-test", ""])
def test_an_unknown_flag_is_rejected(flag: str, tmp_path: Path) -> None:
    """A near-miss would read as no flag at all, so a widening group would
    silently stop requiring its narrowing group."""
    _, errors = parse(
        f"# Tasks\n\n## 1. [app] [unit-test] [{flag}] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path
    )

    assert len(errors) == 1
    assert "flag" in errors[0].message


def test_needs_lines_are_read_per_group(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "## 5. [platform] [unit-test] A\n- [ ] 5.1 x\n\n"
        "## 6. [platform] [e2e-test] B\n"
        "Needs: sample-change group 2 — e2e-test runs against the dev stack.\n"
        "Needs: other-change group 1\n- [ ] 6.1 y\n"
    )

    assert {
        group: [(need.change, need.group) for need in found]
        for group, found in group_needs(tasks).items()
    } == {6: [("sample-change", 2), ("other-change", 1)]}


def test_a_merged_qualifier_is_read_with_its_reason(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "## 3. [app] [unit-test] A\n"
        "Needs: sample-change group 4 merged — it is still reshaping what this wraps\n"
        "Needs: other-change group 1 — why\n- [ ] 3.1 x\n"
    )

    assert group_needs(tasks) == {
        3: [
            Need(
                change="sample-change",
                group=4,
                merged=True,
                reason="it is still reshaping what this wraps",
                line=2,
            ),
            Need(change="other-change", group=1, merged=False, reason="why", line=3),
        ]
    }


def test_merged_after_the_dash_is_part_of_the_reason(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "## 1. [app] [unit-test] A\nNeeds: sample-change group 2 — merged later\n- [ ] 1.1 x\n"
    )

    (need,) = group_needs(tasks)[1]
    assert need.merged is False
    assert need.reason == "merged later"


def test_a_merged_need_on_its_own_change_is_reported(tmp_path: Path) -> None:
    """Groups of one change are ordered already, so the qualifier says nothing."""
    change = tmp_path / "feature"
    change.mkdir()
    (change / "tasks.md").write_text(
        "# Tasks\n\n## 1. [app] [unit-test] A\n\n- [ ] 1.1 x\n\n"
        "## 2. [app] [unit-test] B\n\nNeeds: feature group 1 merged — why\n\n- [ ] 2.1 y\n"
        + OPT_OUT
    )

    _, errors = validate_tasks(change / "tasks.md")

    assert len(errors) == 1
    assert "merged" in errors[0].message


# --- the acceptance group -------------------------------------------------
#
# A change can pass every review and tier with live bugs that a scripted run
# of its tools, as a real client, finds in minutes. Each change therefore ends
# by driving its surface the way its consumer does (docs/architecture.md).

IMPLEMENTATION = """# Tasks

## 1. [platform] [unit-test] Add the tool

- [ ] 1.1 Test: the tool answers.
- [ ] 1.2 Add it.
"""

ACCEPTANCE = """
## 2. [platform] [e2e-test] [acceptance] Drive the tool as an agent does

- [ ] 2.1 Test: an MCP client clicks a field, types, and reads the value back.
"""


def test_a_change_ends_with_an_acceptance_group(tmp_path: Path) -> None:
    groups, errors = parse_as_written(IMPLEMENTATION + ACCEPTANCE, tmp_path)

    assert errors == []
    assert [g.flag for g in groups] == ["", "acceptance"]


def test_a_change_without_one_is_refused_and_told_how_to_opt_out(tmp_path: Path) -> None:
    _, errors = parse_as_written(IMPLEMENTATION, tmp_path)

    assert len(errors) == 1
    assert "[acceptance]" in errors[0].message
    assert "Acceptance: none" in errors[0].message


def test_opting_out_needs_a_reason(tmp_path: Path) -> None:
    with_reason, errors = parse_as_written(
        IMPLEMENTATION + "\nAcceptance: none — a refactor, nothing a consumer sees changes\n",
        tmp_path,
    )
    assert errors == []

    _, errors = parse_as_written(IMPLEMENTATION + "\nAcceptance: none\n", tmp_path)
    assert len(errors) == 1
    assert "reason" in errors[0].message


def test_the_acceptance_group_runs_on_the_stack(tmp_path: Path) -> None:
    _, errors = parse_as_written(
        IMPLEMENTATION + ACCEPTANCE.replace("e2e-test", "unit-test"), tmp_path
    )

    assert len(errors) == 1
    assert "e2e-test" in errors[0].message


def test_only_a_narrowing_group_may_follow_the_acceptance_group(tmp_path: Path) -> None:
    after = "\n## 3. [platform] [unit-test] More work\n\n- [ ] 3.1 Do it.\n"

    _, errors = parse_as_written(IMPLEMENTATION + ACCEPTANCE + after, tmp_path)

    assert len(errors) == 1
    assert "after every group" in errors[0].message


def test_a_widening_change_accepts_then_narrows(tmp_path: Path) -> None:
    text = (
        "# Tasks\n\n## 1. [platform] [unit-test] [contract] Add the field\n\n- [ ] 1.1 x\n"
        + ACCEPTANCE
        + "\n## 3. [platform] [unit-test] [narrow] Drop the old field\n\n- [ ] 3.1 y\n"
    )

    groups, errors = parse_as_written(text, tmp_path)

    assert errors == []
    assert [g.flag for g in groups] == ["contract", "acceptance", "narrow"]


# --- keeping a group separate ---------------------------------------------


def test_a_separate_line_marks_only_its_own_group(tmp_path: Path) -> None:
    groups, errors = parse(
        "## 1. [app] [unit-test] A\n"
        "Separate: reviewed and reverted on its own\n"
        "- [ ] 1.1 x\n\n"
        "## 2. [app] [unit-test] B\n- [ ] 2.1 y\n",
        tmp_path,
    )

    assert errors == []
    assert [g.separate for g in groups] == [True, False]


def test_a_separate_line_without_a_reason_is_rejected(tmp_path: Path) -> None:
    _, errors = parse("## 1. [app] [unit-test] A\nSeparate:\n- [ ] 1.1 x\n", tmp_path)

    assert len(errors) == 1
    assert "Separate" in errors[0].message
    assert errors[0].line == 2


# --- groups that do not wait for the ones before them ---------------------


def test_an_independent_line_marks_only_its_own_group(tmp_path: Path) -> None:
    groups, errors = parse(
        "## 1. [app] [unit-test] A\n- [ ] 1.1 x\n\n"
        "## 2. [platform] [unit-test] B\n"
        "Independent: only adds a receiver\n"
        "- [ ] 2.1 y\n",
        tmp_path,
    )

    assert errors == []
    assert [g.independent for g in groups] == [False, True]


def test_an_independent_line_without_a_reason_is_rejected(tmp_path: Path) -> None:
    _, errors = parse(
        "## 1. [app] [unit-test] A\n- [ ] 1.1 x\n\n"
        "## 2. [platform] [unit-test] B\nIndependent:\n- [ ] 2.1 y\n",
        tmp_path,
    )

    assert len(errors) == 1
    assert "Independent" in errors[0].message
    assert "reason" in errors[0].message
    assert errors[0].line == 5


def test_the_first_group_cannot_be_independent(tmp_path: Path) -> None:
    _, errors = parse(
        "## 1. [app] [unit-test] A\nIndependent: nothing before it\n- [ ] 1.1 x\n", tmp_path
    )

    assert len(errors) == 1
    assert "Independent" in errors[0].message
    assert "nothing to be independent of" in errors[0].message


@pytest.mark.parametrize("flag", ["contract", "narrow", "acceptance"])
def test_an_independent_group_cannot_carry_a_flag(flag: str, tmp_path: Path) -> None:
    tier = "e2e-test" if flag == "acceptance" else "unit-test"
    text = (
        "## 1. [app] [unit-test] A\n- [ ] 1.1 x\n\n"
        f"## 2. [platform] [{tier}] [{flag}] B\nIndependent: a reason\n- [ ] 2.1 y\n"
    )
    if flag == "contract":
        text += "\n## 3. [platform] [unit-test] [narrow] C\n- [ ] 3.1 z\n"

    _, errors = parse(text, tmp_path)

    assert [e for e in errors if "Independent" in e.message], errors


LAYOUT_TEST = "tests/test_project_root.py"


def tasks_naming(*bodies: str) -> str:
    """A tasks file whose group N has one task with the text `bodies[N - 1]`."""
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, body in enumerate(bodies, start=1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n- [ ] {number}.1 {body}\n\n"
    return text


def written(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "tasks.md"
    path.write_text(text)
    return path


LAYOUT_GROUPS = tasks_naming(
    f"Test: `{LAYOUT_TEST}` asserts the folder.",
    "Move the code.",
    f"Test: `{LAYOUT_TEST}` asserts the new folder.",
    *["Move more code."] * 10,
    f"Rewrite `{LAYOUT_TEST}` for the final layout.",
)


def test_a_test_file_named_by_several_groups_is_found_with_those_groups() -> None:
    assert shared_test_files(LAYOUT_GROUPS) == {LAYOUT_TEST: (1, 3, 14)}


def test_a_test_file_named_by_one_group_is_not_shared() -> None:
    assert shared_test_files(tasks_naming(f"Test: `{LAYOUT_TEST}`.", "Do it.")) == {}


def test_a_source_file_named_by_several_groups_is_not_a_shared_test_file() -> None:
    assert shared_test_files(tasks_naming("Edit `src/app.py`.", "Edit `src/app.py` again.")) == {}


def test_the_warning_names_the_file_and_the_groups_and_what_to_do(tmp_path: Path) -> None:
    warnings = shared_test_file_warnings(written(tmp_path, LAYOUT_GROUPS))

    assert len(warnings) == 1
    assert "warning" in warnings[0] and LAYOUT_TEST in warnings[0]
    assert "1, 3 and 14" in warnings[0]
    assert "share a unit" in warnings[0] and "leave the file passing" in warnings[0]


def test_a_file_named_by_one_group_gives_no_warning(tmp_path: Path) -> None:
    text = tasks_naming(f"Test: `{LAYOUT_TEST}`.", "Test: `tests/test_other.py`.")

    assert shared_test_file_warnings(written(tmp_path, text)) == []


def tags_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> tuple[int, list[str]]:
    inst = app_with_projects(tmp_path)
    written(inst.changes_dir / "feature", text)

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)

    return status, capsys.readouterr().out.splitlines()


def test_abk_tags_prints_the_shared_file_warning_and_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, lines = tags_output(tmp_path, capsys, LAYOUT_GROUPS)

    assert status == 0
    assert any(LAYOUT_TEST in line and "warning" in line for line in lines)


@pytest.mark.parametrize(
    "task",
    [
        "Add `[tool.uv.workspace]` to `pyproject.toml`.",
        "Add a `[project]` table to the root `pyproject.toml`.",
        "Edit `pytest.toml` to change the markers.",
        "Set `[tool.pytest.ini_options]` in `pyproject.toml`.",
    ],
)
def test_a_group_editing_a_workspace_or_test_setting_gets_a_note(
    task: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = tasks_naming("Edit `src/app.py`.", task)

    notes = environment_setting_notes(written(tmp_path / "plain", text))
    status, lines = tags_output(tmp_path / "installation", capsys, text)

    assert len(notes) == 1
    assert "group 2" in notes[0] and "info" in notes[0]
    assert "installation setting" in notes[0] and "Manual:" in notes[0]
    assert status == 0
    assert any("installation setting" in line for line in lines)


@pytest.mark.parametrize(
    "task",
    [
        "Set the `workspaces` field of `package.json` to `packages/*`.",
        "Edit `vitest.config.ts` to change the include globs.",
    ],
)
def test_a_group_editing_a_node_workspace_or_test_setting_gets_a_note(
    task: str, tmp_path: Path
) -> None:
    text = tasks_naming("Edit `src/app.ts`.", task)

    notes = environment_setting_notes(written(tmp_path, text), {"app": "node-npm"})

    assert len(notes) == 1
    assert "group 2" in notes[0] and "info" in notes[0]


def test_a_python_setting_gets_no_note_in_a_repo_on_the_node_profile(tmp_path: Path) -> None:
    text = tasks_naming("Edit `src/app.ts`.", "Add `[tool.uv.workspace]` to `pyproject.toml`.")

    assert environment_setting_notes(written(tmp_path, text), {"app": "node-npm"}) == []


def test_a_group_naming_only_source_and_test_files_gets_no_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = tasks_naming("Edit `src/app.py`.", "Test: `tests/test_app.py`.")

    status, lines = tags_output(tmp_path / "installation", capsys, text)

    assert environment_setting_notes(written(tmp_path / "plain", text)) == []
    assert status == 0
    assert not any("installation setting" in line for line in lines)


MISSING_ROOT = "packages/core/tests"
MISSING_TEST = f"{MISSING_ROOT}/store/test_units.py"


def groups_text(*groups: tuple[str, ...], needs: dict[int, str] | None = None) -> str:
    """A tasks file whose group N has the tasks `groups[N - 1]`, each task one line, and the
    `Needs:` line `needs[N]` when given."""
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, tasks in enumerate(groups, start=1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n"
        if needs and number in needs:
            text += f"Needs: {needs[number]}\n\n"
        for index, task in enumerate(tasks, start=1):
            text += f"- [ ] {number}.{index} {task}\n"
        text += "\n"
    return text


def folder_lookup(*present: str) -> Callable[[str, str], bool | None]:
    """A lookup of which test folders the default branch holds: `present` are held."""
    return lambda repo, root: root in present


def folder_warnings(
    tmp_path: Path,
    text: str,
    lookup: Callable[[str, str], bool | None] | None = None,
    *,
    others: Mapping[str, str] | None = None,
) -> list[str]:
    """The warnings of the change `feature`, whose tasks file is `text`, with the tasks files
    `others` written as the changes of those names."""
    changes = tmp_path / "changes"
    path = written(changes / "feature", text)
    for name, other in (others or {}).items():
        written(changes / name, other)
    return missing_test_folder_warnings(path, changes, lookup or folder_lookup())


def test_a_test_folder_the_branch_lacks_is_warned_of_once_with_the_fixes(tmp_path: Path) -> None:
    text = groups_text(
        ("Edit `src/app.py`.",),
        (f"Test: `{MISSING_TEST}` covers it.", f"Test: `{MISSING_ROOT}/test_other.py` too."),
    )

    warnings = folder_warnings(tmp_path, text)

    assert len(warnings) == 1
    assert "warning" in warnings[0] and "group 2" in warnings[0]
    assert "2.1" in warnings[0] and MISSING_TEST in warnings[0]
    assert "not on the default branch" in warnings[0]
    assert "no earlier group creates it" in warnings[0]
    assert "Needs:" in warnings[0] and "folder that exists" in warnings[0]


def test_two_tasks_of_a_group_naming_one_missing_folder_give_one_warning(tmp_path: Path) -> None:
    text = groups_text(
        (f"Test: `{MISSING_ROOT}/test_a.py`.", f"Test: `{MISSING_ROOT}/test_b.py`."),
    )

    assert len(folder_warnings(tmp_path, text)) == 1


def test_an_earlier_group_that_names_a_path_under_the_folder_silences_a_later_group(
    tmp_path: Path,
) -> None:
    text = groups_text((f"Test: `{MISSING_ROOT}/test_marker.py`.",), (f"Test: `{MISSING_TEST}`.",))

    warnings = folder_warnings(tmp_path, text)

    assert not any("group 2" in warning for warning in warnings)
    assert len(warnings) == 1 and "group 1" in warnings[0]


def test_a_task_that_creates_the_folder_by_name_silences_its_own_group(tmp_path: Path) -> None:
    text = groups_text(
        (f"Create the `{MISSING_ROOT}` folder.", f"Test: `{MISSING_TEST}`."),
    )

    assert folder_warnings(tmp_path, text) == []


@pytest.mark.parametrize(
    "continuation",
    [
        f"  Reads: `{MISSING_ROOT}/test_marker.py`",
        f"  Not changed: `{MISSING_ROOT}/test_marker.py`",
    ],
)
def test_a_reads_or_not_changed_line_under_a_task_does_not_create_the_folder(
    continuation: str, tmp_path: Path
) -> None:
    text = groups_text(
        (f"Edit `src/app.py`.\n{continuation}",),
        (f"Test: `{MISSING_TEST}`.",),
    )

    warnings = folder_warnings(tmp_path, text)

    assert len(warnings) == 1 and "group 2" in warnings[0]


def test_a_reads_task_does_not_create_the_folder(tmp_path: Path) -> None:
    text = groups_text(
        ("Edit `src/app.py`.", f"Reads: `{MISSING_ROOT}/test_marker.py`"),
        (f"Test: `{MISSING_TEST}`.",),
    )

    assert len(folder_warnings(tmp_path, text)) == 1


def test_a_later_group_naming_the_folder_does_not_create_it_for_an_earlier_one(
    tmp_path: Path,
) -> None:
    text = groups_text((f"Test: `{MISSING_TEST}`.",), (f"Test: `{MISSING_ROOT}/test_later.py`.",))

    warnings = folder_warnings(tmp_path, text)

    assert len(warnings) == 1 and "group 1" in warnings[0]


def test_a_group_of_a_needed_change_that_names_the_folder_silences_the_warning(
    tmp_path: Path,
) -> None:
    text = groups_text(
        ("Edit `src/app.py`.",),
        (f"Test: `{MISSING_TEST}`.",),
        needs={2: "other-change group 1"},
    )
    other = groups_text((f"Test: `{MISSING_ROOT}/test_marker.py`.",))

    assert folder_warnings(tmp_path, text, others={"other-change": other}) == []


def test_a_folder_created_further_along_the_needs_chain_silences_the_warning(
    tmp_path: Path,
) -> None:
    text = groups_text((f"Test: `{MISSING_TEST}`.",), needs={1: "other-change group 1"})
    other = groups_text(("Edit `src/app.py`.",), needs={1: "third-change group 1"})
    third = groups_text((f"Test: `{MISSING_ROOT}/test_marker.py`.",))

    assert (
        folder_warnings(tmp_path, text, others={"other-change": other, "third-change": third}) == []
    )


def test_a_needed_change_that_does_not_name_the_folder_leaves_the_warning(tmp_path: Path) -> None:
    text = groups_text((f"Test: `{MISSING_TEST}`.",), needs={1: "other-change group 1"})
    other = groups_text(("Test: `tests/test_elsewhere.py`.",))

    assert len(folder_warnings(tmp_path, text, others={"other-change": other})) == 1


@pytest.mark.parametrize(
    "task",
    [
        "Test: `packages/core/tests/test_new.py`.",
        "Test: `packages/core/tests/store/test_units.py`.",
        "Test: `packages/core/tests/markers/deep/test_registry.py`.",
    ],
)
def test_a_new_file_or_subfolder_under_a_folder_the_branch_has_gives_no_warning(
    task: str, tmp_path: Path
) -> None:
    lookup = folder_lookup(MISSING_ROOT)

    assert folder_warnings(tmp_path, groups_text((task,)), lookup) == []


@pytest.mark.parametrize(
    "task",
    ["Edit `src/app.py`.", "Edit `docs/cli.md`.", "Test: `src/app/test_inside.py`."],
)
def test_a_path_outside_a_test_folder_gives_no_warning(task: str, tmp_path: Path) -> None:
    assert folder_warnings(tmp_path, groups_text((task,))) == []


def test_a_node_shaped_test_folder_is_checked_like_a_tests_folder(tmp_path: Path) -> None:
    text = groups_text(("Test: `web/__tests__/panel.test.ts`.",))

    assert len(folder_warnings(tmp_path, text)) == 1
    assert folder_warnings(tmp_path, text, folder_lookup("web/__tests__")) == []


def test_a_lookup_that_cannot_tell_gives_no_warning(tmp_path: Path) -> None:
    text = groups_text((f"Test: `{MISSING_TEST}`.",))

    assert folder_warnings(tmp_path, text, lambda repo, root: None) == []


def git_checkout(tmp_path: Path, *tracked: str) -> Path:
    """The `app` checkout of `app_with_projects(tmp_path)` as a git repo on `main` holding
    `tracked` files."""
    checkout = init_repo(tmp_path / "checkouts" / "app")
    commit_files(checkout, "init", {"README.md": "", **{name: "" for name in tracked}})
    return checkout


def test_abk_tags_warns_of_a_folder_the_checkout_lacks_and_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git_checkout(tmp_path, "tests/.gitkeep")

    status, lines = tags_output(tmp_path, capsys, groups_text((f"Test: `{MISSING_TEST}`.",)))

    assert status == 0
    assert any(MISSING_TEST in line and "warning" in line for line in lines)


def test_abk_tags_is_quiet_about_a_folder_the_checkout_has_and_warns_of_one_it_lacks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git_checkout(tmp_path, f"{MISSING_ROOT}/.gitkeep")
    text = groups_text((f"Test: `{MISSING_TEST}`.", "Test: `web/__tests__/panel.test.ts`."))

    status, lines = tags_output(tmp_path, capsys, text)

    assert status == 0
    assert any("panel.test.ts" in line and "warning" in line for line in lines)
    assert not any(MISSING_TEST in line for line in lines)


@pytest.mark.parametrize("kind", ["missing", "not-a-repo"])
def test_abk_tags_goes_quiet_and_does_not_fail_when_the_checkout_becomes_unusable(
    kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = git_checkout(tmp_path, "tests/.gitkeep")
    text = groups_text((f"Test: `{MISSING_TEST}`.",))
    _, before = tags_output(tmp_path, capsys, text)
    shutil.rmtree(checkout / ".git" if kind == "not-a-repo" else checkout)

    status, lines = tags_output(tmp_path, capsys, text)

    assert any(MISSING_TEST in line and "warning" in line for line in before)
    assert status == 0
    assert not any(MISSING_TEST in line for line in lines)
