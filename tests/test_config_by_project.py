"""Paths are grouped by the project that owns them, relative to it."""

from agent_build_kit.config import ProjectConfig, by_project

ROOT = ProjectConfig(path=".")
WEB = ProjectConfig(path="web", profile="node-npm")


def test_paths_are_grouped_by_owner_relative_to_it_in_first_seen_order() -> None:
    groups = by_project([ROOT, WEB], ["web/src/a.ts", "tests/b.py", "web/c.ts"])

    assert groups == [(WEB, ["src/a.ts", "c.ts"]), (ROOT, ["tests/b.py"])]


def test_a_path_no_project_owns_keeps_its_name_under_none() -> None:
    assert by_project([WEB], ["README.md", "web/a.ts"]) == [(None, ["README.md"]), (WEB, ["a.ts"])]
