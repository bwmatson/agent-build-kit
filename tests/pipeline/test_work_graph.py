"""The task-group tag check.

`openspec/config.yaml`'s rules tell the model to tag each task group with the
repo it lands in and the test tier it needs, but rules are a prompt input, not
a check (docs/architecture.md). This is the check: it runs in CI on
the change's own PR, so a missing tag is caught in review rather than by a
failed run days later.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks

# tests/ mirrors src/, so the repo root is two levels up from this file.
REPO_ROOT = Path(__file__).resolve().parents[2]


WELL_FORMED = """# Tasks

## 1. [platform] [tier1] Register the marker

- [ ] 1.1 Test: default selection deselects it.
- [ ] 1.2 Register it in pytest config.

## 2. [app] [tier2] Relay the event

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
        (1, "platform", "tier1"),
        (2, "app", "tier2"),
    ]
    assert groups[0].title == "Register the marker"
    assert groups[0].task_count == 2


def test_missing_tags_are_reported_with_the_group_named(tmp_path: Path) -> None:
    _, errors = parse("# Tasks\n\n## 1. Register the marker\n\n- [ ] 1.1 Do it.\n", tmp_path)

    assert len(errors) == 1
    assert "1. Register the marker" in errors[0].message
    assert errors[0].line == 3


def test_a_tier_tag_alone_is_not_enough(tmp_path: Path) -> None:
    _, errors = parse("# Tasks\n\n## 1. [tier1] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path)

    assert len(errors) == 1


@pytest.mark.parametrize("repo", ["App", "app-agent", "plat_form", ""])
def test_unknown_repos_are_rejected(repo: str, tmp_path: Path) -> None:
    """The repo tag routes the unit to a worktree, so a near-miss is a failure.

    A near-miss of `app` or `platform` would otherwise reach the runner and
    fail there, after the change had already been reviewed and merged.
    """
    _, errors = parse(f"# Tasks\n\n## 1. [{repo}] [tier1] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path)

    assert len(errors) == 1
    assert "repo" in errors[0].message


@pytest.mark.parametrize("tier", ["tier3", "local_stack", "2", ""])
def test_unknown_tiers_are_rejected(tier: str, tmp_path: Path) -> None:
    _, errors = parse(f"# Tasks\n\n## 1. [app] [{tier}] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path)

    assert len(errors) == 1
    assert "tier" in errors[0].message


def test_groups_must_be_numbered_from_one_in_order(tmp_path: Path) -> None:
    """Out-of-order numbering means the runner's unit order wouldn't match the
    author's intent, and the mismatch would be silent."""
    _, errors = parse(
        "# Tasks\n\n"
        "## 1. [app] [tier1] First\n\n- [ ] 1.1 Do it.\n\n"
        "## 3. [app] [tier1] Third\n\n- [ ] 3.1 Do it.\n",
        tmp_path,
    )

    assert len(errors) == 1
    assert "numbered" in errors[0].message


def test_an_empty_group_is_rejected(tmp_path: Path) -> None:
    _, errors = parse("# Tasks\n\n## 1. [app] [tier1] Nothing here\n", tmp_path)

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
        "## 2. [nope] [tier1] Bad repo\n\n- [ ] 2.1 Do it.\n",
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

## 1. [platform] [tier1] [contract] Add the new field

- [ ] 1.1 Test: the new field is accepted.
- [ ] 1.2 Add it alongside the old one.

## 2. [app] [tier1] Consume the new field

- [ ] 2.1 Test: the consumer reads it.
- [ ] 2.2 Bump the pinned SHA and re-lock.

## 3. [platform] [tier1] [narrow] Remove the old field

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
        "## 2. [app] [tier1] Consume the new field",
        "## 2. [platform] [tier1] [narrow] Remove the old field",
    ).replace(
        "## 3. [platform] [tier1] [narrow] Remove the old field",
        "## 3. [app] [tier1] Consume the new field",
    )

    _, errors = parse(reordered, tmp_path)

    assert len(errors) == 1
    assert "last" in errors[0].message


def test_a_change_touching_no_contract_needs_no_narrowing(tmp_path: Path) -> None:
    """Most changes widen nothing. The rule must not tax them."""
    groups, errors = parse(WELL_FORMED, tmp_path)

    assert errors == []
    assert [g.flag for g in groups] == ["", ""]


@pytest.mark.parametrize("flag", ["contracts", "narrowing", "tier1", ""])
def test_an_unknown_flag_is_rejected(flag: str, tmp_path: Path) -> None:
    """A near-miss would read as no flag at all, so a widening group would
    silently stop requiring its narrowing group."""
    _, errors = parse(
        f"# Tasks\n\n## 1. [app] [tier1] [{flag}] Do it\n\n- [ ] 1.1 Do it.\n", tmp_path
    )

    assert len(errors) == 1
    assert "flag" in errors[0].message


def test_needs_lines_are_read_per_group(tmp_path: Path) -> None:
    from agent_build_kit.pipeline.work_graph import cross_change_needs

    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "## 5. [platform] [tier1] A\n- [ ] 5.1 x\n\n"
        "## 6. [platform] [tier2] B\n"
        "Needs: sample-change group 2 — tier 2 runs against the dev stack.\n"
        "Needs: other-change group 1\n- [ ] 6.1 y\n"
    )

    assert cross_change_needs(tasks) == {6: [("sample-change", 2), ("other-change", 1)]}


def test_a_merged_qualifier_is_read_with_its_reason(tmp_path: Path) -> None:
    from agent_build_kit.pipeline.work_graph import Need, group_needs

    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "## 3. [app] [tier1] A\n"
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
            ),
            Need(change="other-change", group=1, merged=False, reason="why"),
        ]
    }


def test_merged_after_the_dash_is_part_of_the_reason(tmp_path: Path) -> None:
    from agent_build_kit.pipeline.work_graph import group_needs

    tasks = tmp_path / "tasks.md"
    tasks.write_text(
        "## 1. [app] [tier1] A\nNeeds: sample-change group 2 — merged later\n- [ ] 1.1 x\n"
    )

    (need,) = group_needs(tasks)[1]
    assert need.merged is False
    assert need.reason == "merged later"


def test_a_merged_need_on_its_own_change_is_reported(tmp_path: Path) -> None:
    """Groups of one change are ordered already, so the qualifier says nothing."""
    change = tmp_path / "feature"
    change.mkdir()
    (change / "tasks.md").write_text(
        "# Tasks\n\n## 1. [app] [tier1] A\n\n- [ ] 1.1 x\n\n"
        "## 2. [app] [tier1] B\n\nNeeds: feature group 1 merged — why\n\n- [ ] 2.1 y\n" + OPT_OUT
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

## 1. [platform] [tier1] Add the tool

- [ ] 1.1 Test: the tool answers.
- [ ] 1.2 Add it.
"""

ACCEPTANCE = """
## 2. [platform] [tier2] [acceptance] Drive the tool as an agent does

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
    _, errors = parse_as_written(IMPLEMENTATION + ACCEPTANCE.replace("tier2", "tier1"), tmp_path)

    assert len(errors) == 1
    assert "tier2" in errors[0].message


def test_only_a_narrowing_group_may_follow_the_acceptance_group(tmp_path: Path) -> None:
    after = "\n## 3. [platform] [tier1] More work\n\n- [ ] 3.1 Do it.\n"

    _, errors = parse_as_written(IMPLEMENTATION + ACCEPTANCE + after, tmp_path)

    assert len(errors) == 1
    assert "after every group" in errors[0].message


def test_a_widening_change_accepts_then_narrows(tmp_path: Path) -> None:
    text = (
        "# Tasks\n\n## 1. [platform] [tier1] [contract] Add the field\n\n- [ ] 1.1 x\n"
        + ACCEPTANCE
        + "\n## 3. [platform] [tier1] [narrow] Drop the old field\n\n- [ ] 3.1 y\n"
    )

    groups, errors = parse_as_written(text, tmp_path)

    assert errors == []
    assert [g.flag for g in groups] == ["contract", "acceptance", "narrow"]


# --- keeping a group separate ---------------------------------------------


def test_a_separate_line_marks_only_its_own_group(tmp_path: Path) -> None:
    groups, errors = parse(
        "## 1. [app] [tier1] A\n"
        "Separate: reviewed and reverted on its own\n"
        "- [ ] 1.1 x\n\n"
        "## 2. [app] [tier1] B\n- [ ] 2.1 y\n",
        tmp_path,
    )

    assert errors == []
    assert [g.separate for g in groups] == [True, False]


def test_a_separate_line_without_a_reason_is_rejected(tmp_path: Path) -> None:
    _, errors = parse("## 1. [app] [tier1] A\nSeparate:\n- [ ] 1.1 x\n", tmp_path)

    assert len(errors) == 1
    assert "Separate" in errors[0].message
    assert errors[0].line == 2
