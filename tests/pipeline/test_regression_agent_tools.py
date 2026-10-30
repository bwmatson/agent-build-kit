"""The tools the regression agent runs under (spec: regression-agent).

The agent is a stand-in runtime; the history it may read is a real git repository, and the
base checkout it works in is a detached worktree of it, read through the sandbox policy the
request carries.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.check_runner import worktree_at
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import FixKind, run_regression_agent
from agent_build_kit.runtimes import AgentRequest
from tests.conftest import make_installation
from tests.factories import commit, git, init_repo, stored_unit
from tests.pipeline.test_regression_agent_change import failure, run
from tests.regression_agent_fakes import BASE, TEST, Attempts, openspec_checking
from tests.sandboxes.policy_support import reads, writes

READ_TOOLS = ("Read", "Grep", "Glob")
HISTORY_TOOLS = ("Bash(git log*)", "Bash(git show*)", "Bash(git blame*)", "Bash(git diff*)")
REFUSED = (
    "git bisect",
    "git checkout",
    "git switch",
    "git reset",
    "git commit",
    "Bash(gh",
    "gh ",
)


def request_of(installation: Installation, tmp_path: Path) -> AgentRequest:
    agent = Attempts(installation, next_fix_name(installation, TEST), {})
    run(installation, tmp_path, agent.runtime)
    return agent.runtime.request


def app_repo(path: Path, **fields: object) -> dict[str, dict[str, object]]:
    return {"app": {"path": str(path), "slug": "example/app", **fields}}


def test_the_request_carries_the_read_tools_and_the_history_commands(
    installation: Installation, tmp_path: Path
) -> None:
    tools = request_of(installation, tmp_path).allowed_tools

    for tool in (*READ_TOOLS, *HISTORY_TOOLS):
        assert tool in tools


def test_a_python_repo_gets_its_test_commands_and_no_tool_for_changing_dependencies(
    installation: Installation, tmp_path: Path
) -> None:
    tools = request_of(installation, tmp_path).allowed_tools

    assert "Bash(uv run pytest -q*)" in tools and "Bash(uv run pytest -q *)" in tools
    for other in ("uv add", "uv remove", "uv lock", "uv sync", "pre-commit"):
        assert other not in tools


def test_a_node_shaped_repo_gets_its_test_commands_and_not_every_npm_command(
    tmp_path: Path,
) -> None:
    node = make_installation(
        tmp_path / "node", repos=app_repo(tmp_path / "node" / "app", profile="node-npm")
    )

    tools = request_of(node, tmp_path).allowed_tools

    assert "Bash(npx vitest run*)" in tools and "Bash(npx vitest run *)" in tools
    for other in ("npm *", "npx *"):
        assert other not in tools
    for tool in (*READ_TOOLS, *HISTORY_TOOLS):
        assert tool in tools


def test_a_repo_that_overrides_its_agent_commands_gets_the_override_to_run_a_test(
    tmp_path: Path,
) -> None:
    commands = [
        {"purpose": "test", "command": "make test"},
        {"purpose": "test", "command": "make test {path}", "scope": "file"},
        {"purpose": "lint", "command": "make lint"},
    ]
    custom = make_installation(
        tmp_path / "custom", repos=app_repo(tmp_path / "custom" / "app", agent_commands=commands)
    )

    tools = request_of(custom, tmp_path).allowed_tools

    assert "Bash(make test*)" in tools and "Bash(make test *)" in tools
    assert "make lint" not in tools, "only the commands that run a test"
    assert "uv run" not in tools, "the toolchain's own commands are not the repo's"


@pytest.mark.parametrize("command", REFUSED)
def test_the_request_carries_no_command_that_moves_the_base_or_reaches_the_forge(
    installation: Installation, tmp_path: Path, command: str
) -> None:
    request = request_of(installation, tmp_path)

    assert request.allowed_tools, "the agent is given a list, not everything"
    assert command not in request.allowed_tools


def test_the_sandbox_reads_what_git_log_and_blame_open_in_a_linked_worktree_and_writes_none(
    installation: Installation, tmp_path: Path
) -> None:
    repo = init_repo(tmp_path / "history")
    commit(repo, "widget.py", "def label():\n    return 'a'\n")
    base = commit(repo, "widget.py", "def label():\n    return 'b'\n").strip()
    agent = Attempts(installation, next_fix_name(installation, TEST), {})

    with worktree_at(repo, base) as tree:
        run_regression_agent(
            installation,
            failure(),
            stored_unit("feature/1", change="feature", groups=(1,)),
            kind=FixKind.REGRESSION,
            base=BASE,
            runtime=agent.runtime,
            cwd=tree,
            run_openspec=openspec_checking(installation),
        )
        policy = agent.runtime.request.policy
        assert policy is not None and policy.sandbox is not None
        sandbox = policy.sandbox
        entry = repo / ".git" / "worktrees" / tree.name
        opened = [
            tree / ".git",
            repo / ".git" / "objects",
            repo / ".git" / "refs" / "heads",
            repo / ".git" / "HEAD",
            repo / ".git" / "config",
            entry / "HEAD",
            entry / "commondir",
        ]
        found = git(tree, "log", "-S", "return 'b'", "--format=%s")
        blamed = git(tree, "blame", "-L2,2", "widget.py")

        assert reads(sandbox, tree)
        for path in opened:
            assert reads(sandbox, path), path
            assert not writes(sandbox, path), path
        assert not writes(sandbox, tree), "the base checkout is read-only"
        assert sandbox.hosts == ()
    assert found == "write widget.py"
    assert "return 'b'" in blamed


def test_a_write_outside_the_change_directory_is_refused_in_the_base_checkout(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    request = request_of(installation, tmp_path)
    assert request.policy is not None
    base = tmp_path / "base-checkout"
    base.mkdir(parents=True, exist_ok=True)
    init_repo(installation.root)

    def answer(target: Path) -> dict | None:
        return decide(
            {"tool_name": "Write", "cwd": str(base), "tool_input": {"file_path": str(target)}},
            planning_repo=request.planning_repo,
            planning_change_dir=request.planning_change_dir,
            specs=request.policy.specs_dir if request.policy else None,
            no_commit=True,
        )

    assert "Bash(git log*)" in request.allowed_tools
    assert answer(installation.changes_dir / name / "tasks.md") is None
    assert answer(base / "tests" / "test_widget.py") is not None
    assert answer(installation.changes_dir / "other" / "tasks.md") is not None


def test_the_sandbox_has_no_network_host(installation: Installation, tmp_path: Path) -> None:
    request = request_of(installation, tmp_path)

    assert request.allowed_tools
    assert request.policy is not None and request.policy.sandbox is not None
    assert request.policy.sandbox.hosts == ()
