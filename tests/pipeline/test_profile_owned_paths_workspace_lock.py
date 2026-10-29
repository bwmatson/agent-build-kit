"""A workspace member's build leaves the workspace root's lock alone, even when the root is not a
registered project: the pipeline owns it (spec: path-discovery)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.environment import Ownership, owned_paths
from tests.factories import init_repo
from tests.profiles.test_python_uv_workspace_lock import project, workspace_root


def test_the_root_lock_of_a_member_project_is_owned_as_created(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    workspace_root(repo / "py", "a")
    project(repo / "py" / "a", "a")
    config = RepoConfig(
        path=repo,
        slug="example/app",
        profile="python-uv",
        projects=[ProjectConfig(path="py/a", profile="python-uv")],
    )

    assert owned_paths(config, repo)["py/uv.lock"] == Ownership.CREATED
