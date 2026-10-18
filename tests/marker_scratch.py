"""The scratch installation the live tests that build the add-a-marker unit share: a remote, an app
pushed to it, and a planning repository holding the change, for one runtime."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field

from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from tests.factories import git, init_repo, scratch_app
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtime_scratch import RuntimeScratch

CHANGE = "add-marker"


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    planning: Path
    app: Path
    remote: Path
    state: Path
    env: dict[str, str] = Field(repr=False)
    host: FakeGitHub


def build_scratch(
    root: Path,
    host: FakeGitHub,
    runtime: RuntimeScratch,
    *,
    tasks: str,
    marker: str = "marked",
    extra_env: Mapping[str, str] | None = None,
) -> Scratch:
    """A remote (keeping its reflog, which says which push put a branch there), an app pushed to
    it and a planning repository holding the change that adds `marker()` returning `marker`,
    under `root`, with the environment `abk tick` runs in. `tasks` is the change's `tasks.md`."""
    remote = root / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    git(remote, "config", "core.logAllRefUpdates", "always")
    app = scratch_app(root / "app")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main")

    planning = init_repo(root / "planning")
    change = planning / "openspec" / "changes" / CHANGE
    (change / "specs" / "marker").mkdir(parents=True)
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    (change / "proposal.md").write_text(
        "## Why\n\nThe app needs a marker.\n\n## What Changes\n\n- Add `marker()`.\n\n"
        "## Impact\n\n- app: one module.\n"
    )
    (change / "specs" / "marker" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: A marker\nThe app SHALL expose `marker()`.\n\n"
        "#### Scenario: Reading it\n- **WHEN** `marker()` is called\n"
        f'- **THEN** it returns "{marker}"\n'
    )
    (change / "tasks.md").write_text(tasks)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"{runtime.runtimes_yaml}"
    )
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    env = {
        **process_env(host, root / "bin", root / "gh-calls.txt"),
        **runtime.env,
        "ABK_CONFIG": str(planning / "abk.yaml"),
        "ABK_WORKTREE_ROOT": str(root / "worktrees"),
        **(extra_env or {}),
    }
    return Scratch(
        planning=planning,
        app=app,
        remote=remote,
        state=Installation(config.load(planning / "abk.yaml"), planning).state_dir,
        env=env,
        host=host,
    )
