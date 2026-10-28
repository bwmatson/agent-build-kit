"""A split by project counts a group by the project it resolved to, not by its heading's tag."""

from agent_build_kit.split.select import plan_split
from tests.project_workspace import tasks_editing
from tests.split_sources import source_installation, write_change


def test_a_group_resolved_to_the_project_moves_with_it(tmp_path):
    source = source_installation(tmp_path, app=["web"])
    write_change(source, "resolved", ["app"]).joinpath("tasks.md").write_text(
        tasks_editing(("[app] [unit-test] Group 1", "web/src/a.ts"))
    )
    write_change(source, "in-root", ["app"]).joinpath("tasks.md").write_text(
        tasks_editing(("[app] [unit-test] Group 1", "CHANGELOG.md"))
    )

    plan = plan_split(source, "app", project="web", allow_mixed="source")

    assert plan.changes_moved == ("resolved",)
    assert [mixed.name for mixed in plan.changes_mixed] == ["in-root"]
