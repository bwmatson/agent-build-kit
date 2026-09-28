"""Running the clean and red checks at the tests commit.

The checks have to run against the tree as it stood at the tests commit, not
the branch tip — the whole question is whether the tests failed *before* the
implementation existed. That means a throwaway worktree, which is also what
keeps the check from disturbing whatever the agent is doing in the real one.

Commands are injected here rather than hardcoded, so these tests never shell
out to pytest inside pytest.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.check_runner import CheckCache, CommandResult, run_at_commit
from tests.factories import git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "marker.txt").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    (work / "marker.txt").write_text("tests commit\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "test: covers it")
    (work / "marker.txt").write_text("tip\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "feat: implements it")
    return work


def first_commit(repo: Path) -> str:
    """The tests commit: one back from the tip, per the fixture above.

    Not named tests_* — pytest would collect it as a test case.
    """
    return git(repo, "rev-parse", "HEAD~1")


def test_commands_see_the_tree_as_it_was_at_that_commit(repo: Path) -> None:
    """The point of the whole exercise: the tip's implementation must not be
    present while the tests commit is being judged."""
    results = run_at_commit(repo, first_commit(repo), ["cat marker.txt"])

    assert results[0].stdout.strip() == "tests commit"


def test_the_real_worktree_is_left_alone(repo: Path) -> None:
    before = (repo / "marker.txt").read_text()

    run_at_commit(repo, first_commit(repo), ["echo hi"])

    assert (repo / "marker.txt").read_text() == before
    assert git(repo, "status", "--porcelain") == ""


def test_the_temporary_worktree_is_cleaned_up(repo: Path) -> None:
    run_at_commit(repo, first_commit(repo), ["echo hi"])

    assert "spec-check" not in git(repo, "worktree", "list")


def test_a_failing_command_is_reported_not_raised(repo: Path) -> None:
    """A non-zero exit is the normal case here — the red check expects it."""
    results = run_at_commit(repo, first_commit(repo), ["exit 3"])

    assert isinstance(results[0], CommandResult)
    assert results[0].exit_code == 3


def test_commands_run_in_order_and_all_are_reported(repo: Path) -> None:
    results = run_at_commit(repo, first_commit(repo), ["echo one", "echo two"])

    assert [r.stdout.strip() for r in results] == ["one", "two"]


def test_cleanup_happens_even_when_a_command_blows_up(repo: Path) -> None:
    """A leaked worktree would make the next run fail with 'already exists',
    turning one bad run into every run."""
    run_at_commit(repo, first_commit(repo), ["kill -9 $$"])

    assert "spec-check" not in git(repo, "worktree", "list")


def test_the_cache_is_keyed_by_content_not_by_sha(repo: Path, tmp_path: Path) -> None:
    """A restack rewrites every SHA without changing a single line. Keying on
    the SHA would re-run the checks on work already verified."""
    cache = CheckCache(tmp_path / "cache.json")
    sha = first_commit(repo)
    cache.record(repo, sha, ok=True)

    # Move main forward, then restack the branch onto it — exactly what
    # happens when a base PR merges. Every SHA on the branch changes; not a
    # line of its content does.
    git(repo, "checkout", "-q", "main")
    (repo / "unrelated.txt").write_text("moved on\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main moves on")
    git(repo, "checkout", "-q", "spec/change/1-unit")
    git(repo, "rebase", "-q", "main")
    rewritten = first_commit(repo)

    assert rewritten != sha
    assert cache.lookup(repo, rewritten) is True


def test_an_unknown_commit_is_a_cache_miss(repo: Path, tmp_path: Path) -> None:
    cache = CheckCache(tmp_path / "cache.json")

    assert cache.lookup(repo, first_commit(repo)) is None


def test_failures_are_cached_too(repo: Path, tmp_path: Path) -> None:
    """Otherwise a broken commit is re-checked on every push, and the slowest
    path is the one taken most often."""
    cache = CheckCache(tmp_path / "cache.json")
    cache.record(repo, first_commit(repo), ok=False)

    assert cache.lookup(repo, first_commit(repo)) is False


def test_the_cache_survives_a_restart(repo: Path, tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    CheckCache(path).record(repo, first_commit(repo), ok=True)

    assert CheckCache(path).lookup(repo, first_commit(repo)) is True


def test_a_corrupt_cache_is_a_miss_not_a_crash(repo: Path, tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("{not json")

    assert CheckCache(path).lookup(repo, first_commit(repo)) is None
