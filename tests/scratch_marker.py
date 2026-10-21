"""The `add-marker` scratch installation the live tests that build one unit share: a planning
repo with one change, a code repo with a bare remote, and a fake host.

The runtime comes from `tests.runtime_scratch`; what is asked of the unit, and where its
worktrees live (`planning.worktree_root` in `abk.yaml`, so a ticking process and a server in the
test process resolve the same ones), is written here once.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Iterator
from pathlib import Path

from pydantic import Field

from agent_build_kit import config
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from tests.factories import git, init_repo, scratch_app
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtime_scratch import RuntimeScratch

CHANGE = "add-marker"
BRANCH = f"spec/{CHANGE}/1"
UNIT_ID = f"{CHANGE}/1"

TASKS = """# Tasks

## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"marked"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof
"""


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    planning: Path
    app: Path
    remote: Path
    state: Path
    host: FakeGitHub
    env: dict[str, str] = Field(repr=False)
    command: list[str]
    runtime: str

    @property
    def installation(self) -> Installation:
        return Installation(config.load(self.planning / "abk.yaml"), self.planning)


def serving_host() -> Iterator[FakeGitHub]:
    """The fake host, numbering its first pull request 7, for a module-scoped fixture to
    yield from."""
    with FakeGitHub(first_number=7) as server:
        yield server
        # Checked for every test of the module: a route the fake does not serve
        # fails here, naming it, even when no test looked.
        missed = server.unrouted()
        assert missed == [], f"the forge called routes the fake host does not serve: {missed}"


def build_scratch(tmp_path: Path, host: FakeGitHub, runtime: RuntimeScratch) -> Scratch:
    """The scratch installation under `tmp_path`, planning the `add-marker` change for `runtime`."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    app = scratch_app(tmp_path / "app")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main")

    planning = init_repo(tmp_path / "planning")
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
        '- **THEN** it returns "marked"\n'
    )
    (change / "tasks.md").write_text(TASKS)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"planning:\n  worktree_root: {tmp_path / 'worktrees'}\n"
        f"{runtime.runtimes_yaml}"
    )
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    env = {
        **process_env(host, tmp_path / "bin", tmp_path / "gh-calls.txt"),
        **runtime.env,
        "ABK_CONFIG": str(planning / "abk.yaml"),
    }
    return Scratch(
        planning=planning,
        app=app,
        remote=remote,
        state=Installation(config.load(planning / "abk.yaml"), planning).state_dir,
        host=host,
        env=env,
        command=runtime.command,
        runtime=runtime.runtime,
    )


def thread_next(state: Path) -> tuple[Node, ...] | None:
    """Where the unit's thread stands in the checkpoint store under `state`: the nodes still
    to run, or None when there is no thread."""

    async def look() -> tuple[Node, ...] | None:
        async with open_checkpointer(unit_graphs_path(state)) as saver:
            position = await thread_position(saver, UNIT_ID)
            return None if position.state is None else position.next

    return asyncio.run(look())


def run_log(state: Path) -> str:
    """The unit's run logs under `state`, oldest first."""
    logs = sorted((state / "unit-logs").glob(f"{CHANGE}-01-*.log"))
    return "\n".join(path.read_text() for path in logs)
