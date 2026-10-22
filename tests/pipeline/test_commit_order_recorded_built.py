"""An empty commit marked `Already-built: yes` is recognised by `recorded_built`, and the push
gate and a restack take a branch holding an empty marked pair (spec:
built-group-recorded-as-empty-pair). Real git; the gate's toolchain commands are scripted.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_order import check_structure, group_progress, recorded_built
from agent_build_kit.pipeline.restack import move_branch_onto
from tests.factories import git
from tests.stub_gate_support import (
    ModeProfile,
    commit_feat,
    commit_tests,
    judged,
    plan,
    repo,  # noqa: F401  (the fixture)
)

MARKED = "{subject}\n\nUnit: feature/1\nAlready-built: yes\n"


def empty(work: Path, subject: str, *, marked: bool = True) -> str:
    message = MARKED.format(subject=subject) if marked else subject
    git(work, "commit", "-q", "--allow-empty", "-m", message)
    return git(work, "rev-parse", "HEAD")


def real_pair(work: Path) -> None:
    commit_tests(work, "G3", "g3")
    commit_feat(work, "G3", "g3")


def test_the_empty_marked_commit_is_recorded_built(repo: Path) -> None:  # noqa: F811
    assert recorded_built(repo, empty(repo, "test: G4"))


def test_an_empty_commit_with_no_trailer_is_not(repo: Path) -> None:  # noqa: F811
    assert not recorded_built(repo, empty(repo, "test: G4", marked=False))


def test_a_marked_commit_with_a_changed_file_is_not(repo: Path) -> None:  # noqa: F811
    (repo / "src.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", MARKED.format(subject="feat: G4"))

    assert not recorded_built(repo, git(repo, "rev-parse", "HEAD"))


def test_the_structure_accepts_an_empty_marked_pair_after_a_real_one(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    empty(repo, "test: G4")
    empty(repo, "feat: G4")

    assert check_structure(repo, "main", paired=True) == []


def test_the_structure_refuses_a_branch_of_only_empty_commits(repo: Path) -> None:  # noqa: F811
    empty(repo, "test: G4")
    empty(repo, "feat: G4")

    assert check_structure(repo, "main", paired=True) == ["the branch changes no tests and no code"]


def test_an_empty_marked_tests_commit_with_no_implementation_is_a_missing_pair(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    empty(repo, "test: G4")

    problems = check_structure(repo, "main", paired=True)

    assert problems == ["`test: G4` is not directly followed by `feat: G4` (next: nothing)"]


def test_the_gate_accepts_the_pair_and_runs_nothing_for_the_empty_tests_commit(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    empty(repo, "test: G4")
    empty(repo, "feat: G4")
    profile = ModeProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan(("G3", False), ("G4", False)))

    assert problems == []
    assert profile.cleans == [True], "only the real tests commit is run"
    assert profile.reads == [True], "one red reading, for the real tests commit only"


def test_a_test_only_group_s_empty_marked_tests_commit_needs_no_implementation(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    empty(repo, "test: Drive")
    profile = ModeProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan(("G3", False), ("Drive", True)))

    assert problems == []
    assert profile.cleans == [True]
    assert profile.reads == [True]


def test_a_restack_keeps_the_empty_pair_with_its_subjects_and_trailers(
    repo: Path,  # noqa: F811
) -> None:
    old_base = git(repo, "rev-parse", "main")
    real_pair(repo)
    empty(repo, "test: G4")
    empty(repo, "feat: G4")
    branch = git(repo, "branch", "--show-current")
    git(repo, "checkout", "-q", "main")
    (repo / "unrelated.txt").write_text("moved on\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main moves on")

    move_branch_onto(repo, branch, new_base="main", old_base=old_base)

    git(repo, "checkout", "-q", branch)
    subjects = git(repo, "log", "--reverse", "--format=%s", "main..HEAD").splitlines()
    assert subjects == ["test: G3", "feat: G3", "test: G4", "feat: G4"]
    for sha in git(repo, "rev-list", "HEAD~2..HEAD").split():
        assert recorded_built(repo, sha)
        assert "Unit: feature/1" in git(repo, "log", "-1", "--format=%B", sha)
    assert group_progress(subjects, ["G3", "G4"]).done == 2


def test_the_structure_accepts_an_empty_marked_tests_commit_before_a_real_feat(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    empty(repo, "test: G4")
    commit_feat(repo, "G4", "g4")

    assert check_structure(repo, "main", paired=True) == []


def test_the_structure_accepts_a_real_tests_commit_before_an_empty_marked_feat(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    commit_tests(repo, "G4", "g4")
    empty(repo, "feat: G4")

    assert check_structure(repo, "main", paired=True) == []


def test_the_gate_runs_nothing_for_an_empty_tests_commit_before_a_real_feat(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    empty(repo, "test: G4")
    commit_feat(repo, "G4", "g4")
    profile = ModeProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan(("G3", False), ("G4", False)))

    assert problems == []
    assert profile.cleans == [True], "only the real tests commit is run"


def test_the_gate_checks_the_real_tests_commit_before_an_empty_feat(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    commit_tests(repo, "G4", "g4")
    empty(repo, "feat: G4")
    profile = ModeProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan(("G3", False), ("G4", False)))

    assert problems == []
    assert profile.cleans == [True, True]


def restacked_subjects(repo: Path) -> list[str]:  # noqa: F811
    """The subjects of the branch after a restack onto a base that moved on."""
    old_base = git(repo, "rev-parse", "main")
    branch = git(repo, "branch", "--show-current")
    git(repo, "checkout", "-q", "main")
    (repo / "unrelated.txt").write_text("moved on\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main moves on")

    move_branch_onto(repo, branch, new_base="main", old_base=old_base)

    git(repo, "checkout", "-q", branch)
    return git(repo, "log", "--reverse", "--format=%s", "main..HEAD").splitlines()


def test_a_restack_keeps_an_empty_tests_commit_before_a_real_feat(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    empty(repo, "test: G4")
    commit_feat(repo, "G4", "g4")

    subjects = restacked_subjects(repo)

    assert subjects == ["test: G3", "feat: G3", "test: G4", "feat: G4"]
    assert recorded_built(repo, git(repo, "rev-parse", "HEAD~1"))
    assert "Unit: feature/1" in git(repo, "log", "-1", "--format=%B", "HEAD~1")
    assert group_progress(subjects, ["G3", "G4"]).done == 2


def test_a_restack_keeps_a_real_tests_commit_before_an_empty_feat(
    repo: Path,  # noqa: F811
) -> None:
    real_pair(repo)
    commit_tests(repo, "G4", "g4")
    empty(repo, "feat: G4")

    subjects = restacked_subjects(repo)

    assert subjects == ["test: G3", "feat: G3", "test: G4", "feat: G4"]
    assert recorded_built(repo, git(repo, "rev-parse", "HEAD"))
    assert "Unit: feature/1" in git(repo, "log", "-1", "--format=%B", "HEAD")
    assert group_progress(subjects, ["G3", "G4"]).done == 2
