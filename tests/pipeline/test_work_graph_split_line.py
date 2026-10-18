"""A group's `Split:` line: read case-insensitively, `rest` when absent, checked against what
the group's own repo declares (spec: e2e-split-declaration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks
from tests.split_workspace import group, line_of, splits_workspace, tasks_text


def read(tmp_path: Path, text: str) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(text)
    return validate_tasks(tmp_path / "tasks.md")


@pytest.mark.parametrize("line", ["Split: acp", "split: acp", "SPLIT: acp"])
def test_a_declared_split_is_the_groups_split_whatever_the_keys_case(
    tmp_path: Path, line: str
) -> None:
    splits_workspace(tmp_path / "planning")

    groups, errors = read(tmp_path, tasks_text(group(1, line)))

    assert errors == []
    assert [g.split for g in groups] == ["acp"]


def test_a_group_with_no_line_or_with_rest_is_in_rest_beside_one_in_a_declared_split(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning")

    groups, errors = read(
        tmp_path, tasks_text(group(1), group(2, "Split: rest"), group(3, "Split: acp"))
    )

    assert errors == []
    assert [g.split for g in groups] == ["rest", "rest", "acp"]


@pytest.mark.parametrize("name", ["Acp", "acp-x", "a.cp"])
def test_a_name_outside_lowercase_letters_digits_and_underscores_is_refused_naming_the_rule(
    tmp_path: Path, name: str
) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1, f"Split: {name}"))

    _, errors = read(tmp_path, text)

    (error,) = errors
    assert error.line == line_of(text, f"Split: {name}")
    assert "lowercase letters, digits and underscores" in error.message


def test_a_name_the_repo_does_not_declare_is_refused_at_its_line_naming_the_repo_and_splits(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1, "Split: gpu"))

    _, errors = read(tmp_path, text)

    (error,) = errors
    assert error.line == line_of(text, "Split: gpu")
    for wanted in ("gpu", "app", "claude_code", "acp", "rest"):
        assert wanted in error.message


def test_a_repo_with_no_splits_refuses_every_name_but_rest_and_says_it_declares_none(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning", top={})
    text = tasks_text(group(1, "Split: acp"), group(2, "Split: rest"), group(3), group(4, repo="x"))

    groups, errors = read(tmp_path, text)

    # A group with no line gives the errors it always gave: the unknown repo, and nothing of splits.
    assert [e.line for e in errors] == [
        line_of(text, "Split: acp"),
        line_of(text, "## 4. [x] [e2e-test] Group 4"),
    ]
    assert "app" in errors[0].message
    assert "declares no" in errors[0].message
    assert "split" not in errors[1].message.lower()
    assert [(g.number, g.split) for g in groups if g.number in (2, 3)] == [(2, "rest"), (3, "rest")]


def test_a_repos_own_map_replaces_the_top_level_one(tmp_path: Path) -> None:
    splits_workspace(tmp_path / "planning", own={"app": {"gpu": {"marker": "runtime_gpu"}}})
    text = tasks_text(group(1, "Split: gpu"), group(2, "Split: acp"))

    groups, errors = read(tmp_path, text)

    (error,) = errors
    assert error.line == line_of(text, "Split: acp")
    assert "gpu" in error.message
    assert "claude_code" not in error.message
    assert [(g.number, g.split) for g in groups if g.number == 1] == [(1, "gpu")]


def test_a_groups_split_is_the_declaration_of_its_own_repo(tmp_path: Path) -> None:
    splits_workspace(tmp_path / "planning", own={"platform": {"gpu": {"marker": "runtime_gpu"}}})
    text = tasks_text(
        group(1, "Split: acp"),
        group(2, "Split: gpu", repo="platform"),
        group(3, "Split: gpu"),
        group(4, "Split: acp", repo="platform"),
    )

    groups, errors = read(tmp_path, text)

    refused = {error.line for error in errors}
    assert refused == {line_of(text, "Split: gpu", 2), line_of(text, "Split: acp", 2)}
    assert [(g.number, g.split) for g in groups if g.number in (1, 2)] == [(1, "acp"), (2, "gpu")]


def test_a_unit_test_group_with_a_split_line_is_refused_saying_it_has_no_tier_2(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1, "Split: acp", kind="unit-test"))

    _, errors = read(tmp_path, text)

    (error,) = errors
    assert error.line == line_of(text, "Split: acp")
    assert "unit-test group has no tier 2" in error.message


def test_a_split_line_above_the_first_group_is_refused_as_belonging_to_no_group(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1), before="Split: acp\n\n")

    _, errors = read(tmp_path, text)

    (error,) = errors
    assert error.line == line_of(text, "Split: acp")
    assert "belongs to no group" in error.message


def test_a_split_line_in_a_group_whose_heading_cannot_be_read_is_reported_with_its_reason(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1, "Split: acp").replace("[e2e-test]", "[nonsense]"))

    _, errors = read(tmp_path, text)

    stray = [e for e in errors if e.line == line_of(text, "Split: acp")]
    (error,) = stray
    assert "`Split:`" in error.message
    assert "heading" in error.message
