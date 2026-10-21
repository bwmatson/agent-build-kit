"""The push gate's result cache keeps a test-only commit's result apart from an ordinary one's
(spec: a-test-only-group-commits-no-pair).

A result recorded with no red run says nothing about a judgement with one, and the reverse; a
test-only commit's own result is still found by content after a restack.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.check_runner import CheckCache
from tests.factories import git
from tests.stub_gate_support import (
    ModeProfile,
    commit_feat,
    commit_tests,
    judged,
    plan,
    repo,  # noqa: F401  (the fixture)
    restack_onto_moved_main,
)

DRIVE = "def test_drive(): assert False\n"


def drive_as_a_pair(work: Path) -> None:
    """The patch of the Drive tests commit, as the commit of an ordinary group's pair."""
    commit_tests(work, "Drive", "drive", DRIVE)
    commit_feat(work, "Drive", "drive")


def drive_alone(work: Path) -> None:
    """The same patch on a branch of its own, as a test-only group's lone commit."""
    git(work, "checkout", "-q", "main")
    git(work, "checkout", "-q", "-b", "spec/change/2-unit")
    commit_tests(work, "Drive", "drive", DRIVE)


def test_a_result_cached_with_no_red_run_is_not_reused_for_an_ordinary_tests_commit(
    repo: Path,  # noqa: F811 — fixture
    tmp_path: Path,
) -> None:
    cache = CheckCache(tmp_path / "cache.json")
    drive_alone(repo)
    assert (
        judged(repo, ModeProfile(), cache=cache, stubbed=True, groups=plan(("Drive", True))) == []
    )
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "spec/change/1-unit")
    drive_as_a_pair(repo)
    ordinary = ModeProfile()

    judged(repo, ordinary, cache=cache, stubbed=True, groups=plan(("Drive", False)))

    assert ordinary.reads == [True], "the red run was made: nothing was found for this mode"
    assert ordinary.cleans == [True]


def test_a_result_cached_by_an_ordinary_run_is_not_reused_for_a_test_only_commit(
    repo: Path,  # noqa: F811 — fixture
    tmp_path: Path,
) -> None:
    cache = CheckCache(tmp_path / "cache.json")
    drive_as_a_pair(repo)
    assert (
        judged(repo, ModeProfile(), cache=cache, stubbed=True, groups=plan(("Drive", False))) == []
    )
    drive_alone(repo)
    failing_types = ModeProfile(bad_types="tests/test_drive.py")

    problems = judged(repo, failing_types, cache=cache, stubbed=True, groups=plan(("Drive", True)))

    assert problems, "the checks ran again for the test-only commit"
    assert failing_types.cleans == [True]


def test_a_result_cached_for_a_test_only_commit_is_reused_after_a_restack(
    repo: Path,  # noqa: F811 — fixture
    tmp_path: Path,
) -> None:
    cache = CheckCache(tmp_path / "cache.json")
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_tests(repo, "Drive", "drive", DRIVE)
    groups = plan(("A", False), ("Drive", True))
    assert judged(repo, ModeProfile(), cache=cache, stubbed=True, groups=groups) == []
    restack_onto_moved_main(repo)
    next_run = ModeProfile(bad_types="tests/test_drive.py")

    assert judged(repo, next_run, cache=cache, stubbed=True, groups=groups) == []

    assert next_run.cleans == [], "nothing was run: both commits were found by content"
