"""A group whose heading names no project is resolved from the paths it names, a manual tag is
used as written, `[repo/<root>]` keeps the root, the group carries how it was decided, and the
resolution is part of the plan digest (spec: project-resolution)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.work_graph import (
    TaskGroup,
    ValidationError,
    resolved_project,
    validate_tasks,
)
from tests.project_workspace import OPT_OUT, app_with_projects

PROJECTS = ("web", "services", "services/api")


def tasks_of(heading: str, body: str) -> str:
    return f"# Tasks\n\n{OPT_OUT}\n## 1. {heading}\n\n{body}"


def read(
    tmp_path: Path, heading: str, body: str, *projects: str
) -> tuple[list[TaskGroup], list[ValidationError]]:
    app_with_projects(tmp_path / "planning", *projects)
    (tmp_path / "tasks.md").write_text(tasks_of(heading, body))
    return validate_tasks(tmp_path / "tasks.md")


def resolve(tmp_path: Path, body: str, *projects: str) -> tuple[str, str]:
    groups, errors = read(tmp_path, "[app] [unit-test] Group", body, *projects)
    assert errors == []
    return resolved_project(groups[0], projects)


def test_every_path_inside_one_declared_project_resolves_to_it(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Test: `web/tests/test_app.py`.\n- [ ] 1.2 Edit `web/src/app.ts`.\n"

    groups, errors = read(tmp_path, "[app] [unit-test] Group", body, "web")

    assert errors == []
    assert [(g.repo, g.project, g.source) for g in groups] == [("app", "web", "resolved")]


def test_a_path_outside_every_project_keeps_the_group_in_the_root(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `web/src/app.ts` and `CHANGELOG.md`.\n"

    assert resolve(tmp_path, body, "web") == (".", "root")


def test_paths_under_two_projects_keep_the_group_in_the_root(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `web/src/app.ts` and `services/api/src/route.py`.\n"

    assert resolve(tmp_path, body, *PROJECTS) == (".", "root")


def test_paths_under_nested_projects_keep_the_group_in_the_root(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `services/api/src/route.py` and `services/shared.py`.\n"

    assert resolve(tmp_path, body, *PROJECTS) == (".", "root")


def test_a_group_naming_no_path_stays_in_the_root(tmp_path: Path) -> None:
    assert resolve(tmp_path, "- [ ] 1.1 Test: it.\n", "web") == (".", "root")


def test_a_repo_declaring_no_project_keeps_every_group_in_the_root(tmp_path: Path) -> None:
    assert resolve(tmp_path, "- [ ] 1.1 Edit `web/src/app.ts`.\n") == (".", "root")


def test_a_path_relative_to_a_project_does_not_resolve(tmp_path: Path) -> None:
    assert resolve(tmp_path, "- [ ] 1.1 Edit `src/app.ts` in web.\n", "web") == (".", "root")


def test_a_paths_line_decides_over_the_task_lines(tmp_path: Path) -> None:
    body = "Paths: `web/**`\n\n- [ ] 1.1 Edit `services/api/src/route.py` and `README.md`.\n"

    groups, errors = read(tmp_path, "[app] [unit-test] Group", body, *PROJECTS)

    assert errors == []
    assert [(g.project, g.source) for g in groups] == [("web", "resolved")]


def test_a_manual_project_tag_is_used_as_written_whatever_the_paths(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `web/src/app.ts`.\n"

    groups, errors = read(tmp_path, "[app/services] [unit-test] Group", body, *PROJECTS)

    assert errors == []
    assert [(g.project, g.source) for g in groups] == [("services", "explicit")]
    assert resolved_project(groups[0], PROJECTS) == ("services", "explicit")


def test_the_root_spelling_keeps_a_group_in_the_root_as_an_explicit_choice(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `web/src/app.ts`.\n"

    groups, errors = read(tmp_path, "[app/<root>] [unit-test] Group", body, "web")

    assert errors == []
    assert [(g.project, g.source) for g in groups] == [(".", "explicit")]
    assert resolved_project(groups[0], ("web",)) == (".", "explicit")


def test_paths_and_reads_lines_parse_into_the_group(tmp_path: Path) -> None:
    body = (
        "Paths: `web/src/**`, `web/tests/test_app.py`\n"
        "Reads: `services/api/src/route.py`\n"
        "\n- [ ] 1.1 Test: it.\n"
    )

    groups, errors = read(tmp_path, "[app] [unit-test] Group", body, *PROJECTS)

    assert errors == []
    assert groups[0].paths == ("web/src/**", "web/tests/test_app.py")
    assert groups[0].reads == ("services/api/src/route.py",)


def test_moving_a_declared_project_moves_the_plan_digest_of_a_change_that_resolves_to_it(
    tmp_path: Path,
) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(tasks_of("[app] [unit-test] Group", "- [ ] 1.1 Edit `web/src/app.ts`.\n"))

    app_with_projects(tmp_path / "planning-before")
    before = cli.plan_digest(tasks)
    app_with_projects(tmp_path / "planning-after", "web")
    after = cli.plan_digest(tasks)

    assert before != after
