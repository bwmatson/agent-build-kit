"""The regression agent's sandbox, run through the real launcher: a program and `git log` start in
a linked worktree of the unit's base and the change directory is writable (spec:
regression-agent). A worktree is writable only where a runtime's grant covers it, as the Claude
runtime's grant of the temp folder covers the one `worktree_at` makes there, and the repo's own
checkout never is. Skipped where the backend cannot be applied on this machine.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import sandboxes
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.check_runner import worktree_at
from agent_build_kit.pipeline.regression_agent import agent_sandbox
from tests.factories import commit, git, init_repo
from tests.runtimes.stand_in import GrantsFolder, StandInRuntime
from tests.sandboxes.landlock_support import require_working, run_confined


def repo_with_a_commit(installation: Installation) -> tuple[Path, str]:
    repo = init_repo(installation.checkouts["app"])
    commit(repo, "widget.py", "def label():\n    return 'a'\n")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def test_git_log_starts_in_the_worktree_and_only_the_change_directory_is_writable(
    confined_installation: Installation, tmp_path: Path
) -> None:
    backend, _ = sandboxes.probe("auto")
    require_working(backend)
    installation = confined_installation
    repo, base = repo_with_a_commit(installation)
    change = installation.changes_dir / "fix-test-x"
    change.mkdir(parents=True)

    with worktree_at(repo, base) as tree:
        # A runtime that grants nothing covering the worktree, which `worktree_at` made in the
        # temp folder.
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


def test_a_worktree_in_a_granted_folder_is_writable_and_the_repos_checkout_is_not(
    confined_installation: Installation, tmp_path: Path
) -> None:
    backend, _ = sandboxes.probe("auto")
    require_working(backend)
    installation = confined_installation
    repo, base = repo_with_a_commit(installation)
    granted = tmp_path / "granted"
    granted.mkdir()
    tree = granted / "tree"
    git(repo, "worktree", "add", "--detach", "-q", str(tree), base)
    change = installation.changes_dir / "fix-test-x"
    change.mkdir(parents=True)
    runtime = GrantsFolder(granted)

    in_grant = agent_sandbox(installation, "app", tree, change, runtime)
    own = agent_sandbox(installation, "app", repo, change, runtime)
    assert in_grant is not None and own is not None

    wrote_worktree = run_confined(backend, in_grant, ["sh", "-c", f"echo x > {tree}/new.txt"])
    wrote_checkout = run_confined(backend, own, ["sh", "-c", f"echo x > {repo}/new.txt"])

    assert wrote_worktree.returncode == 0, wrote_worktree.stderr
    assert wrote_checkout.returncode != 0 and not (repo / "new.txt").exists()
