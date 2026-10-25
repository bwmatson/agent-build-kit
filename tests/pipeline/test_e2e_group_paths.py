"""The classifier that says which of the paths a task line names are product code (spec:
e2e-group-scope); the reader of those paths is tested in test_group_paths.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.e2e_scope import is_product_path, unscoped_task_paths


def repo(tmp_path: Path, **fields) -> RepoConfig:
    return RepoConfig(
        path=tmp_path,
        projects=[ProjectConfig(path="."), ProjectConfig(path="web", profile="node-npm")],
        **fields,
    )


@pytest.mark.parametrize(
    ("path", "product"),
    [
        ("src/client/retry.py", True),
        ("tests/e2e/test_route.py", False),
        ("tests/e2e/conftest.py", False),
        ("docs/cli.md", False),
        ("README.md", False),
        ("CHANGELOG.md", False),
        ("scripts/seed-stack.sh", True),
        ("web/src/app.test.ts", False),
        ("web/src/app.ts", True),
        ("web/tests/test_x.py", True),
    ],
)
def test_a_path_is_judged_by_the_profile_of_its_project_and_the_docs_and_changelog(
    tmp_path: Path, path: str, product: bool
) -> None:
    assert is_product_path(path, repo(tmp_path)) is product


def test_the_changelog_is_the_repos_setting(tmp_path: Path) -> None:
    assert not is_product_path("NEWS.rst.in", repo(tmp_path, changelog="NEWS.rst.in"))
    assert is_product_path("CHANGELOG.rst.in", repo(tmp_path, changelog="NEWS.rst.in"))
    assert is_product_path("changes/log.in", repo(tmp_path, changelog=None))


def test_declared_support_is_allowed_and_a_trailing_slash_covers_a_directory(
    tmp_path: Path,
) -> None:
    support = ("scripts/seed-stack.sh", "compose.e2e.yml", "tools/")

    assert not is_product_path("scripts/seed-stack.sh", repo(tmp_path), support)
    assert not is_product_path("compose.e2e.yml", repo(tmp_path), support)
    assert not is_product_path("tools/deep/helper.sh", repo(tmp_path), support)
    assert is_product_path("scripts/other.sh", repo(tmp_path), support)
    assert is_product_path("toolsmith/x.sh", repo(tmp_path), support)


def test_a_script_is_allowed_on_a_line_that_also_names_a_test_path(tmp_path: Path) -> None:
    named = ["tests/e2e/test_route.py", "scripts/seed-stack.sh"]

    assert unscoped_task_paths(named, repo(tmp_path)) == []
    assert unscoped_task_paths(["scripts/seed-stack.sh"], repo(tmp_path)) == [
        "scripts/seed-stack.sh"
    ]


def test_only_a_scripts_path_gets_that_allowance_and_the_rest_come_back_in_order(
    tmp_path: Path,
) -> None:
    named = ["src/client/retry.py", "tests/e2e/test_route.py", "scripts/seed.sh", "src/b.py"]

    assert unscoped_task_paths(named, repo(tmp_path)) == ["src/client/retry.py", "src/b.py"]
