"""Which changes and archive entries a split moves, by their groups' repo and project tags."""

import pytest

from agent_build_kit.split.select import SplitUsageError, plan_split
from tests.split_sources import source_installation, write_change


def test_the_repo_selects_changes_whose_groups_are_all_its_own(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "a", ["app", "app"])
    write_change(source, "b", ["lib"])
    write_change(source, "c", ["app", "lib"])

    plan = plan_split(source, "app")

    assert plan.changes_moved == ("a",)
    assert plan.changes_staying == ("b",)
    assert [mixed.name for mixed in plan.changes_mixed] == ["c"]


def test_a_project_counts_only_its_own_groups(tmp_path):
    source = source_installation(tmp_path, app=["web"])
    write_change(source, "in-web", ["app/web"])
    write_change(source, "in-root", ["app"])

    plan = plan_split(source, "app", project="web", allow_mixed="source")

    assert plan.changes_moved == ("in-web",)
    assert [mixed.name for mixed in plan.changes_mixed] == ["in-root"]


def test_an_undeclared_project_is_refused_naming_the_declared_ones(tmp_path):
    source = source_installation(tmp_path, app=["web"])

    with pytest.raises(SplitUsageError) as refused:
        plan_split(source, "app", project="mobile")

    message = str(refused.value)
    assert "mobile" in message
    assert "app" in message
    assert "web" in message


def test_an_archive_entry_is_classified_by_its_own_tasks(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "old", ["app"], archived="2026-01-02")
    write_change(source, "other", ["lib"], archived="2026-01-03")
    write_change(source, "bare", [], archived="2026-01-04", tasks=False)

    plan = plan_split(source, "app")

    assert plan.archive_moved == ("2026-01-02-old",)
    assert plan.archive_staying == ("2026-01-03-other",)
    assert plan.archive_unclassified == ("2026-01-04-bare",)


def test_a_heading_with_no_repo_tag_is_unreadable_and_neither_moved_nor_staying(tmp_path):
    source = source_installation(tmp_path)
    untagged = "# Tasks\n\n## 1. No tag here\n\n- [ ] 1.1 Test: x\n"
    write_change(source, "broken", ["app"]).joinpath("tasks.md").write_text(untagged)
    write_change(source, "broken-old", ["app"], archived="2026-01-02").joinpath(
        "tasks.md"
    ).write_text(untagged)

    plan = plan_split(source, "app")

    assert [(item.name, item.line) for item in plan.changes_unreadable] == [("broken", 3)]
    assert [item.name for item in plan.archive_unreadable] == ["2026-01-02-broken-old"]
    assert "broken" not in plan.changes_moved + plan.changes_staying
    assert "2026-01-02-broken-old" not in plan.archive_moved + plan.archive_staying
