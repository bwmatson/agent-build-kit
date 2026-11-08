"""A git failure that is a lock file already existing is recognised from git's own text."""

from agent_build_kit.pipeline.git_output import lock_failure

# What git prints when it cannot take a lock, as git writes it.
LOCKED = """\
fatal: Unable to create '/work/repo/.git/worktrees/w/MERGE_RR.lock': File exists.

Another git process seems to be running in this repository, e.g.
an editor opened by 'git commit'. Please make sure all processes
are terminated then try again. If it still fails, a git process
may have crashed in this repository earlier:
remove the file manually to continue.
"""


def test_a_lock_that_exists_is_named_by_its_path() -> None:
    assert lock_failure(LOCKED) == "/work/repo/.git/worktrees/w/MERGE_RR.lock"


def test_a_ref_lock_is_named_too() -> None:
    text = "fatal: Unable to create '/r/.git/refs/heads/x.lock': File exists.\n"

    assert lock_failure(text) == "/r/.git/refs/heads/x.lock"


def test_another_failure_is_not_a_lock_failure() -> None:
    assert lock_failure("fatal: not a git repository (or any of the parent directories)") is None
    assert lock_failure("error: Unable to create '/r/x.txt': Permission denied") is None
