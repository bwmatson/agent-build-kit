"""A change tagged for the repo and another is mixed: kept or moved whole by a named side."""

import pytest

from agent_build_kit.split.select import RefusalKind, SplitUsageError, plan_split
from tests.split_sources import source_installation, write_change


def source_with_a_mixed_change(tmp_path):
    source = source_installation(tmp_path, app=["web"])
    write_change(source, "moves", ["app"])
    write_change(source, "mixed", ["app/web", "lib"])
    write_change(source, "mixed", ["app", "lib"], archived="2026-01-02")
    return source


def test_a_mixed_change_is_listed_with_each_groups_repo_and_project(tmp_path):
    plan = plan_split(source_with_a_mixed_change(tmp_path), "app", allow_mixed="source")

    (mixed,) = plan.changes_mixed
    assert mixed.name == "mixed"
    assert [(group.number, group.repo, group.project) for group in mixed.groups] == [
        (1, "app", "web"),
        (2, "lib", "."),
    ]


def test_with_no_side_the_plan_refuses_and_names_the_change(tmp_path):
    plan = plan_split(source_with_a_mixed_change(tmp_path), "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.MIXED
    assert "mixed" in refusal.line
    assert "lib" in refusal.line


def test_source_keeps_every_mixed_change_and_its_archive_entries(tmp_path):
    plan = plan_split(source_with_a_mixed_change(tmp_path), "app", allow_mixed="source")

    assert plan.changes_moved == ("moves",)
    assert plan.archive_moved == ()
    assert [mixed.name for mixed in plan.archive_mixed] == ["2026-01-02-mixed"]
    assert plan.refusals == ()


def test_destination_moves_mixed_changes_whole_with_their_archive_entries(tmp_path):
    source = source_with_a_mixed_change(tmp_path)

    plan = plan_split(source, "app", allow_mixed="destination", destination_repos={"app", "lib"})

    assert plan.changes_moved == ("mixed", "moves")
    assert plan.archive_moved == ("2026-01-02-mixed",)
    assert plan.refusals == ()


def test_destination_is_refused_naming_the_repo_and_change_the_destination_lacks(tmp_path):
    source = source_with_a_mixed_change(tmp_path)

    plan = plan_split(source, "app", allow_mixed="destination", destination_repos={"app"})

    refusals = [refusal for refusal in plan.refusals if "lib" in refusal.line]
    assert {refusal.kind for refusal in plan.refusals} == {RefusalKind.DESTINATION_LACKS_REPO}
    assert refusals
    assert all("mixed" in refusal.line for refusal in refusals)
    assert "mixed" not in plan.changes_moved


def test_both_is_a_usage_error_naming_the_two_sides(tmp_path):
    source = source_with_a_mixed_change(tmp_path)

    with pytest.raises(SplitUsageError, match="source.*destination"):
        plan_split(source, "app", allow_mixed="both")


def test_a_mixed_archive_entry_with_no_active_change_is_refused_without_a_side(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "x", ["app", "lib"], archived="2026-01-02")

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.MIXED
    assert "2026-01-02-x" in refusal.line
    assert "lib" in refusal.line
