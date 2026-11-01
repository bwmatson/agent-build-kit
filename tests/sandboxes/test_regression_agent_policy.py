"""The regression agent's sandbox, run through the real launcher: a program and `git log` start in
a linked worktree of the unit's base, the change directory is writable, and the worktree is not
(spec: regression-agent). Skipped where the backend cannot be applied on this machine.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import sandboxes
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.check_runner import worktree_at
from agent_build_kit.pipeline.regression_agent import agent_sandbox
from tests.factories import commit, git, init_repo
from tests.runtimes.stand_in import StandInRuntime
from tests.sandboxes.landlock_support import require_working, run_confined


def test_git_log_starts_in_the_worktree_and_only_the_change_directory_is_writable(
    confined_installation: Installation, tmp_path: Path
) -> None:
    backend, _ = sandboxes.probe("auto")
    require_working(backend)
    installation = confined_installation
    repo = init_repo(installation.checkouts["app"])
    commit(repo, "widget.py", "def label():\n    return 'a'\n")
    base = git(repo, "rev-parse", "HEAD").strip()
    change = installation.changes_dir / "fix-test-x"
    change.mkdir(parents=True)

    with worktree_at(repo, base) as tree:
        policy = agent_sandbox(installation, "app", tree, change, StandInRuntime())
        assert policy is not None

        log = run_confined(backend, policy, ["git", "-C", str(tree), "log", "--format=%s"])
        wrote_tree = run_confined(backend, policy, ["sh", "-c", f"echo x > {tree}/new.txt"])
        wrote_change = run_confined(backend, policy, ["sh", "-c", f"echo x > {change}/new.txt"])

        assert log.returncode == 0, log.stderr
        assert "widget.py" in log.stdout
        assert wrote_tree.returncode != 0 and not (tree / "new.txt").exists()
        assert wrote_change.returncode == 0, wrote_change.stderr
        assert (change / "new.txt").is_file()
