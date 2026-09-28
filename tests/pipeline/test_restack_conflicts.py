"""Resolving a restack conflict with the intent of both sides in hand.

A conflict during a restack is not a random merge conflict. Both sides are
known work: the unit that just merged, and the unit being moved onto it. Each
has a change, a title and acceptance criteria saying what it was trying to do.
That is far more context than a human usually has when resolving, so the
resolver is given it.

What must stay true regardless:

- **A resolution that keeps conflict markers is not a resolution.**
- **Neither side's intent may be dropped** to make the conflict go away —
  deleting the incoming change is the easiest "fix" and the worst one.
- **Failure leaves no rebase in progress**, or every later command in that
  worktree breaks.
- **The tests still have to pass afterwards.** Resolution produces a
  candidate, not a verdict; the runner re-verifies.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack import (
    ConflictContext,
    RestackConflict,
    move_branch_onto,
)
from tests.factories import git, init_repo


def commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"write {name}")


@pytest.fixture
def conflicting(tmp_path: Path) -> Path:
    """main and spec/c/2 both change markers.py, in different ways."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "markers.py", "markers = []\n")

    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    commit(repo, "markers.py", 'markers = ["local_stack"]\n')

    git(repo, "checkout", "-q", "main")
    commit(repo, "markers.py", 'markers = ["integration"]\n')
    return repo


def context() -> ConflictContext:
    return ConflictContext(
        moving_unit="add-marker/2",
        moving_intent="Register the local_stack marker in app",
        onto_unit="add-integration/1",
        onto_intent="Register the integration marker in app",
    )


def test_without_a_resolver_a_conflict_still_stops(conflicting: Path) -> None:
    """The resolver is opt-in: nothing changes for callers that don't pass one."""
    with pytest.raises(RestackConflict):
        move_branch_onto(conflicting, "spec/c/2", new_base="main", old_base="spec/c/1")


def test_the_resolver_is_told_what_both_sides_were_doing(conflicting: Path) -> None:
    """The point of resolving here rather than by hand: both intents are
    known, so the resolution can keep both rather than pick one."""
    seen: dict = {}

    def resolver(prompt: str, *, cwd: Path) -> None:
        seen["prompt"] = prompt
        (cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')

    move_branch_onto(
        conflicting,
        "spec/c/2",
        new_base="main",
        old_base="spec/c/1",
        resolve=resolver,
        context=context(),
    )

    assert "local_stack marker in app" in seen["prompt"]
    assert "integration marker in app" in seen["prompt"]
    assert "markers.py" in seen["prompt"]


def test_a_good_resolution_completes_the_move_keeping_both_changes(conflicting: Path) -> None:
    def resolver(prompt: str, *, cwd: Path) -> None:
        (cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')

    move_branch_onto(
        conflicting,
        "spec/c/2",
        new_base="main",
        old_base="spec/c/1",
        resolve=resolver,
        context=context(),
    )

    git(conflicting, "checkout", "-q", "spec/c/2")
    resolved = (conflicting / "markers.py").read_text()
    assert "local_stack" in resolved
    assert "integration" in resolved
    assert not (conflicting / ".git" / "rebase-merge").exists()


def test_leftover_conflict_markers_are_refused(conflicting: Path) -> None:
    """The commonest bad resolution: staging the conflict itself."""

    def lazy(prompt: str, *, cwd: Path) -> None:
        pass  # leaves the <<<<<<< markers in place

    with pytest.raises(RestackConflict, match="conflict markers"):
        move_branch_onto(
            conflicting,
            "spec/c/2",
            new_base="main",
            old_base="spec/c/1",
            resolve=lazy,
            context=context(),
        )


def test_dropping_the_moving_units_own_change_is_refused(conflicting: Path) -> None:
    """Taking the base's side wholesale makes the conflict disappear and the
    unit pointless. That is the easiest wrong answer, so it is checked."""

    def takes_theirs(prompt: str, *, cwd: Path) -> None:
        (cwd / "markers.py").write_text('markers = ["integration"]\n')

    with pytest.raises(RestackConflict, match="dropped"):
        move_branch_onto(
            conflicting,
            "spec/c/2",
            new_base="main",
            old_base="spec/c/1",
            resolve=takes_theirs,
            context=context(),
            must_keep=["local_stack"],
        )


def test_a_failed_resolution_leaves_no_rebase_in_progress(conflicting: Path) -> None:
    def lazy(prompt: str, *, cwd: Path) -> None:
        pass

    with pytest.raises(RestackConflict):
        move_branch_onto(
            conflicting,
            "spec/c/2",
            new_base="main",
            old_base="spec/c/1",
            resolve=lazy,
            context=context(),
        )

    assert not (conflicting / ".git" / "rebase-merge").exists()
    assert git(conflicting, "status", "--porcelain") == ""


def test_a_resolver_that_raises_is_not_retried_forever(conflicting: Path) -> None:
    """An unattended run that loops on a failing resolver burns the usage
    window with nothing to show."""
    attempts = {"n": 0}

    def broken(prompt: str, *, cwd: Path) -> None:
        attempts["n"] += 1
        raise RuntimeError("model unavailable")

    with pytest.raises(RestackConflict):
        move_branch_onto(
            conflicting,
            "spec/c/2",
            new_base="main",
            old_base="spec/c/1",
            resolve=broken,
            context=context(),
        )

    assert attempts["n"] == 1


def test_the_prompt_says_resolution_is_not_a_licence_to_rewrite(conflicting: Path) -> None:
    """Resolving is not the moment to improve the code: anything beyond the
    conflict is unreviewed work smuggled into a rebase."""
    seen: dict = {}

    def resolver(prompt: str, *, cwd: Path) -> None:
        seen["prompt"] = prompt
        (cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')

    move_branch_onto(
        conflicting,
        "spec/c/2",
        new_base="main",
        old_base="spec/c/1",
        resolve=resolver,
        context=context(),
    )

    assert "only the conflict" in seen["prompt"].lower()


def test_the_guard_is_derived_when_the_caller_gives_none(conflicting: Path) -> None:
    """The caller shouldn't have to know which string proves the unit's change
    survived — it is in the branch's own diff."""

    def takes_theirs(prompt: str, *, cwd: Path) -> None:
        (cwd / "markers.py").write_text('markers = ["integration"]\n')

    with pytest.raises(RestackConflict, match="dropped"):
        move_branch_onto(
            conflicting,
            "spec/c/2",
            new_base="main",
            old_base="spec/c/1",
            resolve=takes_theirs,
            context=context(),
        )


def test_a_genuine_resolution_still_passes_the_derived_guard(conflicting: Path) -> None:
    """The guard must not be so strict that keeping both sides is refused."""

    def keeps_both(prompt: str, *, cwd: Path) -> None:
        (cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')

    move_branch_onto(
        conflicting,
        "spec/c/2",
        new_base="main",
        old_base="spec/c/1",
        resolve=keeps_both,
        context=context(),
    )

    git(conflicting, "checkout", "-q", "spec/c/2")
    assert "local_stack" in (conflicting / "markers.py").read_text()
