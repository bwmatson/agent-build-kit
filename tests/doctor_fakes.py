"""What the `abk doctor` tests share: a `run` that answers each command as a healthy host does,
and a planning repo over one fixture app.

They live here and not in a test file, and name no method `test_*`, because the pipeline takes
any such name for a test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_build_kit import skills
from agent_build_kit.config import EnvironmentConfig, RepoConfig, WorkspaceConfig, dump
from agent_build_kit.init.scaffold import render_openspec_config
from tests.factories import init_repo


def ok_run(argv, **kwargs):
    if argv[0] == "git":
        return subprocess.run(argv, **kwargs)
    if argv[0] == "npx":
        return subprocess.CompletedProcess(argv, 0, "1.0.0\n", "")
    if argv[0] == "gh":
        return subprocess.CompletedProcess(argv, 0, "tok\n", "")
    return subprocess.CompletedProcess(argv, 0, "", "")


def planning_with(tmp_path: Path, **repo_fields: Any) -> Path:
    """A planning repo whose `abk.yaml` names one repo, `app`, with `repo_fields` set on it."""
    root = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    (app / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n")
    (app / ".gitattributes").write_text("CHANGELOG.md merge=union\n")
    environment = EnvironmentConfig(sync=["env-sync"], check=["env-check"])
    config = WorkspaceConfig(
        environment=environment,
        repos={
            "app": RepoConfig(path=app, slug="example/app", environment=environment, **repo_fields)
        },
    )
    (root / "abk.yaml").write_text(dump(config))
    (root / "openspec").mkdir()
    (root / "openspec" / "config.yaml").write_text(render_openspec_config(config))
    skills.install(root / ".claude" / "skills")
    return root
